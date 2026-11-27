// Glowtrack - menu-bar app.
//
// - Lives in the menu bar (no Dock icon unless the dashboard window is open).
// - Starts the Python lighting server (server/app.py) and restarts it if it stops.
// - Listens for Spotify's own "playback changed" announcement and tells the
//   server instantly, so song changes don't wait for the next poll.
// - Opens the dashboard in a window only when you ask for it.
//
// Build: mac/build.sh

import AppKit
import ServiceManagement
import WebKit

// Port comes from Info.plist (GoveeServerPort); the server is started with the same one.
let serverPort = (Bundle.main.object(forInfoDictionaryKey: "GoveeServerPort") as? Int) ?? 8765
let serverURL = URL(string: "http://127.0.0.1:\(serverPort)")!

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate, NSWindowDelegate, WKNavigationDelegate {
    private var statusItem: NSStatusItem!
    private let menu = NSMenu()
    private var server: Process?
    private var quitting = false
    private var state: [String: Any] = [:]
    private var window: NSWindow?
    private var webView: WKWebView?
    private var brightnessSlider: NSSlider?
    private var refreshTimer: Timer?

    // MARK: - Launch

    func applicationDidFinishLaunching(_ note: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        if let button = statusItem.button {
            let image = NSImage(systemSymbolName: "lightbulb.fill", accessibilityDescription: "Glowtrack")
            image?.isTemplate = true
            button.image = image
            button.toolTip = "Glowtrack"
        }
        menu.delegate = self
        statusItem.menu = menu
        rebuildMenu()

        startServerIfNeeded()

        // Spotify announces every song change / play / pause system-wide.
        DistributedNotificationCenter.default().addObserver(
            self, selector: #selector(spotifyChanged(_:)),
            name: NSNotification.Name("com.spotify.client.PlaybackStateChanged"),
            object: nil, suspensionBehavior: .deliverImmediately)
        // Apple Music announces changes the same way
        DistributedNotificationCenter.default().addObserver(
            self, selector: #selector(spotifyChanged(_:)),
            name: NSNotification.Name("com.apple.Music.playerInfo"),
            object: nil, suspensionBehavior: .deliverImmediately)

        refreshTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            self?.refreshState()
        }
        refreshState()

        if !launchedAtLogin() {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { self.openDashboard() }
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        openDashboard()   // double-clicking the app again opens the dashboard
        return false
    }

    func applicationWillTerminate(_ note: Notification) {
        quitting = true
        server?.terminate()
    }

    private func launchedAtLogin() -> Bool {
        guard let event = NSAppleEventManager.shared().currentAppleEvent else { return false }
        return event.eventID == kAEOpenApplication &&
            event.paramDescriptor(forKeyword: keyAEPropData)?.enumCodeValue == keyAELaunchedAsLogInItem
    }

    // MARK: - Python server

    private var serverScript: String {
        // A downloaded app carries its own copy of the server
        if let res = Bundle.main.resourcePath {
            let bundled = res + "/server/app.py"
            if FileManager.default.fileExists(atPath: bundled) { return bundled }
        }
        let configured = Bundle.main.object(forInfoDictionaryKey: "GoveeServerPath") as? String
            ?? "~/GoveeSpotifySync/server/app.py"
        return (configured as NSString).expandingTildeInPath
    }

    private func startServerIfNeeded() {
        // Reuse a server that's already running (e.g. started from Terminal)
        var req = URLRequest(url: serverURL.appendingPathComponent("api/state"))
        req.timeoutInterval = 1.5
        URLSession.shared.dataTask(with: req) { [weak self] _, response, _ in
            let running = (response as? HTTPURLResponse)?.statusCode == 200
            DispatchQueue.main.async { if !running { self?.launchServer() } }
        }.resume()
    }

    private func launchServer() {
        guard !quitting else { return }
        let script = serverScript
        guard FileManager.default.fileExists(atPath: script) else {
            alert("Server not found", "Expected the lighting server at:\n\(script)")
            return
        }
        let logURL = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/GoveeSpotifySync.log")
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        let log = try? FileHandle(forWritingTo: logURL)
        _ = try? log?.seekToEnd()   // keep earlier output, so a crash and restart doesn't erase the evidence

        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        p.arguments = ["-u", script]
        var env = ["GOVEE_PORT": String(serverPort)]
        if let theme = Bundle.main.object(forInfoDictionaryKey: "GoveeDefaultTheme") as? String { env["GOVEE_DEFAULT_THEME"] = theme }
        if let res = Bundle.main.resourcePath, FileManager.default.fileExists(atPath: res + "/vendor") {
            env["PYTHONPATH"] = res + "/vendor"        // Pillow, bundled so nothing needs installing
            env["PYTHONDONTWRITEBYTECODE"] = "1"       // leave the signed app untouched
        }
        p.environment = ProcessInfo.processInfo.environment.merging(env) { _, new in new }
        p.currentDirectoryURL = URL(fileURLWithPath: (script as NSString).deletingLastPathComponent)
        p.standardOutput = log
        p.standardError = log
        p.terminationHandler = { [weak self] proc in
            // Shut down from the dashboard (e.g. on a phone): quit the whole app
            if proc.terminationStatus == 64 {
                DispatchQueue.main.async {
                    self?.quitting = true
                    NSApp.terminate(nil)
                }
                return
            }
            // Otherwise keep the lights running: restart the server if it stops unexpectedly
            DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                guard let self = self, !self.quitting else { return }
                self.server = nil
                self.startServerIfNeeded()
            }
        }
        do {
            try p.run()
            server = p
        } catch {
            alert("Couldn't start the lighting server", error.localizedDescription)
        }
    }

    @objc private func restartServer() {
        if let p = server {
            p.terminate()   // terminationHandler starts a fresh one
        } else {
            post("api/connect")   // nothing of ours to restart; just poke the running one
        }
    }

    // MARK: - Spotify

    @objc private func spotifyChanged(_ note: Notification) {
        post("api/spotify_changed")
        // Update the menu header straight from Spotify's announcement
        if let info = note.userInfo {
            if let name = info["Name"] as? String { state["track"] = name }
            if let artist = info["Artist"] as? String { state["artist"] = artist }
            if let playing = info["Player State"] as? String { state["is_playing"] = (playing == "Playing") }
            updateMenuTitles()
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { self.refreshState() }
    }

    // MARK: - Talking to the server

    private func post(_ path: String, _ body: [String: Any] = [:]) {
        var req = URLRequest(url: serverURL.appendingPathComponent(path))
        req.httpMethod = "POST"
        req.setValue("1", forHTTPHeaderField: "X-Govee-App")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        req.timeoutInterval = 3
        URLSession.shared.dataTask(with: req) { [weak self] _, _, _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self?.refreshState() }
        }.resume()
    }

    private func refreshState() {
        var req = URLRequest(url: serverURL.appendingPathComponent("api/state"))
        req.timeoutInterval = 2
        URLSession.shared.dataTask(with: req) { [weak self] data, _, _ in
            guard let data = data,
                  let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
            DispatchQueue.main.async {
                self?.state = obj
                self?.updateMenuTitles()
            }
        }.resume()
    }

    // MARK: - Menu

    private enum Tag: Int { case track = 1, lamps, power, solid, wave, duo, seg, playPause, login }

    private func item(_ title: String, _ action: Selector?, key: String = "", tag: Tag? = nil) -> NSMenuItem {
        let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
        i.target = self
        if let tag = tag { i.tag = tag.rawValue }
        return i
    }

    private func rebuildMenu() {
        menu.removeAllItems()
        let track = item("Waiting for Spotify…", nil, tag: .track)
        track.isEnabled = false
        menu.addItem(track)
        let lamps = item("Checking lamps…", nil, tag: .lamps)
        lamps.isEnabled = false
        menu.addItem(lamps)
        menu.addItem(.separator())

        menu.addItem(item("Open Dashboard", #selector(openDashboard), key: "o"))
        menu.addItem(.separator())

        menu.addItem(item("Turn Lamps Off", #selector(togglePower), tag: .power))
        menu.addItem(item("Solid", #selector(setPreset(_:)), tag: .solid))
        menu.addItem(item("Colour Fade", #selector(setPreset(_:)), tag: .wave))
        menu.addItem(item("Two-Lamp Split", #selector(setPreset(_:)), tag: .duo))
        menu.addItem(item("7-Zone Fade", #selector(setPreset(_:)), tag: .seg))

        // Brightness slider inside the menu
        let sliderItem = NSMenuItem()
        let container = NSView(frame: NSRect(x: 0, y: 0, width: 220, height: 30))
        let icon = NSImageView(frame: NSRect(x: 16, y: 7, width: 16, height: 16))
        icon.image = NSImage(systemSymbolName: "sun.max", accessibilityDescription: "Brightness")
        icon.contentTintColor = .secondaryLabelColor
        let slider = NSSlider(value: 100, minValue: 1, maxValue: 100, target: self, action: #selector(brightnessChanged(_:)))
        slider.frame = NSRect(x: 38, y: 5, width: 166, height: 20)
        slider.isContinuous = false
        container.addSubview(icon)
        container.addSubview(slider)
        sliderItem.view = container
        brightnessSlider = slider
        menu.addItem(sliderItem)
        menu.addItem(.separator())

        menu.addItem(item("Play / Pause", #selector(playPause), tag: .playPause))
        menu.addItem(item("Next Track", #selector(nextTrack)))
        menu.addItem(.separator())

        menu.addItem(item("Open at Login", #selector(toggleLogin), tag: .login))
        menu.addItem(item("Restart Lighting Server", #selector(restartServer)))
        menu.addItem(item("Quit Glowtrack", #selector(quit), key: "q"))
        updateMenuTitles()
    }

    func menuWillOpen(_ menu: NSMenu) {
        refreshState()
        updateMenuTitles()
    }

    private func updateMenuTitles() {
        let track = (state["track"] as? String) ?? "Waiting for Spotify…"
        let artist = (state["artist"] as? String) ?? ""
        menu.item(withTag: Tag.track.rawValue)?.title = artist.isEmpty ? track : "\(track) — \(artist)"

        let online = (state["online_count"] as? Int) ?? 0
        let total = (state["configured_count"] as? Int) ?? 2
        menu.item(withTag: Tag.lamps.rawValue)?.title = state.isEmpty
            ? "Lighting server starting…"
            : (online > 0 ? "\(online) of \(total) lamps online" : "Lamps not responding")

        let on = (state["is_powered_on"] as? Bool) ?? true
        menu.item(withTag: Tag.power.rawValue)?.title = on ? "Turn Lamps Off" : "Turn Lamps On"

        let spatial = state["spatial_mode"] as? String ?? ""
        let motion = state["motion_mode"] as? String ?? ""
        let current: Tag? = spatial == "segmented" ? .seg : spatial == "duo" ? .duo
            : (spatial == "unified" ? (motion == "flow" ? .wave : .solid) : nil)
        for t in [Tag.solid, .wave, .duo, .seg] {
            menu.item(withTag: t.rawValue)?.state = (t == current) ? .on : .off
        }

        let playing = (state["is_playing"] as? Bool) ?? false
        menu.item(withTag: Tag.playPause.rawValue)?.title = playing ? "Pause" : "Play"

        if let b = state["brightness"] as? Double, let slider = brightnessSlider {
            slider.doubleValue = b
        }
        menu.item(withTag: Tag.login.rawValue)?.state = SMAppService.mainApp.status == .enabled ? .on : .off
    }

    // MARK: - Menu actions

    @objc private func togglePower() {
        let on = (state["is_powered_on"] as? Bool) ?? true
        post("api/power", ["on": !on])
    }

    @objc private func setPreset(_ sender: NSMenuItem) {
        let preset: String
        switch Tag(rawValue: sender.tag) {
        case .solid: preset = "solid"
        case .wave: preset = "wave"
        case .duo: preset = "duo"
        default: preset = "segmented"
        }
        post("api/preset", ["preset": preset])
    }

    @objc private func brightnessChanged(_ sender: NSSlider) {
        post("api/brightness", ["value": Int(sender.doubleValue)])
    }

    @objc private func playPause() { post("api/playback/playpause") }
    @objc private func nextTrack() { post("api/playback/next") }

    @objc private func toggleLogin() {
        do {
            if SMAppService.mainApp.status == .enabled {
                try SMAppService.mainApp.unregister()
            } else {
                try SMAppService.mainApp.register()
            }
        } catch {
            alert("Couldn't change Open at Login",
                  "\(error.localizedDescription)\n\nYou can also add the app in System Settings → General → Login Items.")
        }
        updateMenuTitles()
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }

    // MARK: - Dashboard window

    @objc func openDashboard() {
        if window == nil {
            let screen = NSScreen.main?.visibleFrame ?? NSRect(x: 0, y: 0, width: 1280, height: 800)
            // Start at 85% of the screen it opens on; the page scales itself to fit
            let size = NSSize(width: screen.width * 0.85, height: screen.height * 0.85)
            let frame = NSRect(x: screen.midX - size.width / 2, y: screen.midY - size.height / 2,
                               width: size.width, height: size.height)
            let w = NSWindow(contentRect: frame,
                             styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
                             backing: .buffered, defer: false)
            w.title = "Glowtrack"
            w.titlebarAppearsTransparent = true
            w.backgroundColor = NSColor(red: 0.035, green: 0.043, blue: 0.055, alpha: 1)
            w.minSize = NSSize(width: 640, height: 440)
            w.isReleasedWhenClosed = false
            w.delegate = self
            w.setFrameAutosaveName("GoveeDashboard")

            let config = WKWebViewConfiguration()
            config.preferences.isElementFullscreenEnabled = true   // the page's Full Screen button
            let web = WKWebView(frame: w.contentView!.bounds, configuration: config)
            web.autoresizingMask = [.width, .height]
            web.navigationDelegate = self
            web.setValue(false, forKey: "drawsBackground")
            w.contentView?.addSubview(web)

            // The page fills the whole window (even under the title bar), so add an
            // invisible strip along the top that you can grab to move the window.
            // Double-click it to zoom, like a normal title bar.
            let bounds = w.contentView!.bounds
            let strip = DragStrip(frame: NSRect(x: 0, y: bounds.height - 30, width: bounds.width, height: 30))
            strip.autoresizingMask = [.width, .minYMargin]
            w.contentView?.addSubview(strip)
            web.load(URLRequest(url: URL(string: "http://127.0.0.1:\(serverPort)/?app=mac")!))
            webView = web
            window = w
        }
        NSApp.setActivationPolicy(.regular)   // show in Dock / Cmd-Tab while open
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowWillClose(_ notification: Notification) {
        // Free the web page completely while closed (saves CPU and memory)
        webView?.stopLoading()
        webView?.removeFromSuperview()
        webView = nil
        window = nil
        NSApp.setActivationPolicy(.accessory)
    }

    // The server may still be starting when the window opens - keep retrying.
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) { [weak self] in
            guard let self = self, self.webView === webView else { return }
            webView.load(URLRequest(url: URL(string: "http://127.0.0.1:\(serverPort)/?app=mac")!))
        }
    }

    // MARK: - Helpers

    private func alert(_ title: String, _ text: String) {
        let a = NSAlert()
        a.messageText = title
        a.informativeText = text
        a.runModal()
    }
}

/// Invisible area at the top of the dashboard window that moves the window when dragged.
final class DragStrip: NSView {
    override var mouseDownCanMoveWindow: Bool { true }
    override func mouseDown(with event: NSEvent) {
        if event.clickCount == 2 {
            window?.performZoom(nil)
        } else {
            window?.performDrag(with: event)
        }
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
