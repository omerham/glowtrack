# Glowtrack

Syncs two Govee floor lamps (H6076) to whatever is playing on this Mac - Spotify,
Apple Music, YouTube Music or any other site/app, Tidal, Amazon Music, Deezer and so on.
Colours come from the album art. Everything stays on your Wi-Fi, and it
works with a free Spotify account.

![The Glowtrack dashboard](docs/screenshot.png)

> Unofficial hobby project. Not affiliated with or endorsed by Govee or Spotify.

## Requirements

- A Mac running macOS 13 or later, playing music in any app or browser tab
  (the Spotify desktop app works with a free account).
- One or two **Govee H6076 floor lamps** (other Govee lamps with LAN control may work
  but are untested), on the same Wi-Fi as the Mac.
- **LAN Control turned on** for each lamp: Govee Home app → the lamp → Settings → LAN Control.
- `/usr/bin/python3` (ships with the Xcode command-line tools) and Pillow
  (`/usr/bin/python3 -m pip install --user Pillow`).
- Xcode command-line tools (`xcode-select --install`): to build the menu-bar app, and so
  the server can build its small Now Playing helper the first time it runs.

## Install

```
git clone <this repo> ~/GoveeSpotifySync
cd ~/GoveeSpotifySync
mac/build.sh
cp -R build/Glowtrack.app /Applications/
```

The app expects the server at `~/GoveeSpotifySync/server/app.py`; to keep the
code elsewhere, change `GoveeServerPath` in `mac/Info.plist` before building.
You can also run just the server: `/usr/bin/python3 server/app.py`.
Lamps are found automatically; if they aren't, use the dashboard's lamp settings.
The first launch asks for permission to control Spotify and to use the local network.

## Using it

- **Glowtrack** (in Applications) lives in the menu bar (lightbulb icon).
  From there: open the dashboard, switch mode, brightness, play/pause, next track,
  *Open at Login*, restart the lighting server, quit.
- Dashboard: <http://127.0.0.1:8765> on this Mac. Phones/iPads on the same Wi-Fi can use it too
  after a one-time pairing (see *Privacy and security*). Set `GOVEE_LOCAL_ONLY=1` to allow this Mac only.
  To use another port, change `GoveeServerPort` in `mac/Info.plist` (or `GOVEE_PORT` when running the server by hand).
- Logs: `~/Library/Logs/GoveeSpotifySync.log`. Settings: `~/.govee_spotify_config.json`.

### Modes
| Mode | Motion |
|---|---|
| Spotify Solid | still – one album colour on both lamps |
| Ambient Wave | moving – both lamps flow through the album colours together |
| Two-Lamp Split | still – a different album colour on each lamp |
| 7-Zone Fade | moving – album colours flow up the 7 zones of each lamp |

Fine-tuning (colour cycle speed, song fade, vibrancy, pulse depth, tempo, dark
colour boost, lamp preview quality) is in the dashboard's Settings.

## Privacy and security

- Lamp control and the dashboard stay on your network. There is no account and no analytics.
- To find tempo and lyrics, the current song and artist names are sent to Deezer,
  songbpm.com and lrclib.net. Album art is fetched from Spotify's own image servers.
- **Pairing:** this Mac can always use the dashboard. Phones and tablets on your Wi-Fi must be
  paired once: open **Settings → Phone & tablet access** on the Mac and open that link on the
  device. Anyone with the link can control your lamps and Spotify, so keep it private. To pair
  nothing and keep it Mac-only, set `GOVEE_LOCAL_ONLY=1`; to skip pairing and let anyone on
  the network in (not recommended), set `GOVEE_OPEN_LAN=1`.
  Debug commands (`/api/debug_record`, `/api/lamp_test`) always require a request from this Mac.

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md). MIT licensed, see [LICENSE](LICENSE).

## Project layout

```
server/            Python lighting server (no installs needed beyond Pillow)
  app.py           entry point; restarts itself when any .py file changes
  config.py        settings, constants, saved config
  colors.py        album-art palette extraction, LED calibration, blending
  spotify.py       reads/controls the Spotify app via AppleScript
  players.py       picks Spotify or macOS Now Playing; routes the playback buttons
  nowplaying/      mr.m: small helper that reads/controls macOS Now Playing
  tempo.py         song tempo lookup (Deezer, songbpm.com)
  lamps.py         Govee LAN protocol (discovery, status, UDP packets)
  devices.py       other lights: WiZ, LIFX, WLED (experimental)
  engine.py        app state + lighting engine (the only code that talks to lamps)
  web.py           dashboard web server
  web/             dashboard: index.html, app.js, app.css, tailwind.css (pre-built)
mac/               menu-bar app (Swift): main.swift, Info.plist, build.sh
tools/             build_tailwind.py – rebuilds web/tailwind.css
tests/             engine tests (no lamps or Spotify needed)
archive/           old versions, kept for reference (not used)
```

## Developing

- Edit anything in `server/` – the server reloads itself (only if the code compiles).
  Dashboard files in `server/web/` are read fresh on every page load.
- Added new Tailwind classes to the page? Rebuild the styles:
  `/usr/bin/python3 tools/build_tailwind.py`, then open <http://127.0.0.1:8798>.
- Tests: `/usr/bin/python3 -m unittest discover tests`
- Rebuild the menu-bar app: `mac/build.sh`, then copy `build/Glowtrack.app`
  to Applications.

## Other lights (experimental)

Besides your Govee lamps, Glowtrack can drive **WiZ**, **LIFX** and **WLED** lights over your local
network. Open **Settings → Other lights**, press *Scan* (WiZ and LIFX are found automatically;
for a WLED strip type its IP address), and choose whether each light follows the left or right lamp.
Single-colour lights show the average of that lamp's colours; a WLED strip spreads the lamp's 7 zones
along its length (turn on WLED's realtime/UDP listening, which is the default).

These drivers (`server/devices.py`) were written from the products' published protocols and are
checked against fake devices in the tests, but **have not been tried on real hardware yet**. If you
try one, please report whether it worked. Other Govee models that report their model name are
driven with a single colour, since only the H6076's zone packets are known.

## Which players work

- **Spotify** is read directly (cover link, volume, shuffle, repeat all work).
- **Everything else** (Apple Music, browsers, Tidal, Amazon Music, Deezer, ...) is read from
  macOS's own *Now Playing* info, the same thing Control Centre shows. If the song appears
  there, Glowtrack can light to it. The helper (`server/nowplaying/mr.m`) is built into
  `~/Library/Caches/Glowtrack` on first run.
- If Spotify is playing it wins; otherwise whatever Now Playing reports. Play/pause, next,
  previous and seeking go to the player in use. Shuffle/repeat only work for Spotify, and
  the volume slider changes the Mac's output volume for other players.
- Needs the song to have artwork in Now Playing for album colours; otherwise the lamps keep the
  current colours. Lyrics need a title and artist.
- Now Playing is a private macOS interface (reached through Apple's own `perl`), so a future macOS
  update could break non-Spotify support.

## How song changes are detected

Spotify and Apple Music announce every song change and play/pause to the system. The menu-bar
app forwards that announcement to the server (`/api/spotify_changed`), which reads
the new song straight away. A slow background poll (every 4 s, or 1.8 s if the
announcements aren't arriving) is kept as a safety net, and is the only way other players are noticed (1.8 s).
