#!/usr/bin/env python3
"""
Glowtrack - syncs two Govee floor lamps (H6076) to the song playing
in the Spotify app on this Mac. 100% local Wi-Fi, works with free Spotify.

Run:  /usr/bin/python3 app.py      (the menu-bar app starts this for you)

Files:
  config.py   settings, constants, saved config
  colors.py   album-art palette extraction, LED calibration, blending
  spotify.py  reads/controls the Spotify app via AppleScript
  tempo.py    song tempo lookup + song-position energy curve
  lamps.py    Govee LAN protocol (discovery, status, UDP colour packets)
  engine.py   app state + the lighting engine (only code that talks to lamps)
  web.py      local web server for the dashboard
  web/        the dashboard page (index.html, app.js, app.css, tailwind.css)
"""
import glob
import os
import py_compile
import sys
import threading
import time
from http.server import ThreadingHTTPServer

import web
from config import ALLOW_LAN, BIND_HOST, SERVER_PORT
from engine import AppState

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))


def _code_mtimes():
    return {f: os.path.getmtime(f) for f in glob.glob(os.path.join(SERVER_DIR, "*.py"))}


def watch_for_code_changes():
    """Restarts the server when any .py file changes, so the app never runs old
    code. Only restarts if every file still compiles. (Dashboard files in web/
    are read fresh on each request and don't need a restart.)"""
    last = _code_mtimes()
    while True:
        time.sleep(2.0)
        try:
            now = _code_mtimes()
        except OSError:
            continue
        if now == last:
            continue
        time.sleep(1.5)   # let the editor finish writing
        try:
            if _code_mtimes() != now:
                continue
            for f in now:
                py_compile.compile(f, doraise=True)
        except py_compile.PyCompileError as e:
            print(f"[!] Code changed but has an error, not reloading: {e.msg}")
            last = now
            continue
        except OSError:
            continue
        print("[*] Code changed - restarting with the new version...")
        sys.stdout.flush()
        me = os.path.abspath(__file__)
        os.execv(sys.executable, [sys.executable, me] + sys.argv[1:])


def run_server():
    try:
        server = ThreadingHTTPServer((BIND_HOST, SERVER_PORT), web.GoveeHttpHandler)
    except OSError as e:
        print(f"[!] Port {SERVER_PORT} is already in use - is another copy running? ({e})")
        sys.exit(1)
    server.daemon_threads = True
    server.serve_forever()


def exit_when_orphaned():
    """If the menu-bar app that started us goes away, quit too. A server left
    running on its own loses macOS's Local Network permission ("No route to
    host"), so the lamps show offline, and it blocks the app's fresh server."""
    if os.getppid() == 1:
        return   # started on purpose without a parent (e.g. by launchd)
    while True:
        time.sleep(5)
        if os.getppid() == 1:
            print("[*] The app that started the server has gone - stopping")
            os._exit(0)


def main():
    where = "this Mac + same Wi-Fi" if ALLOW_LAN else "this Mac only"
    print(f"[*] Glowtrack on http://127.0.0.1:{SERVER_PORT} ({where})")
    sys.stdout.flush()

    state = AppState()
    web.STATE = state

    state.govee.start_listener()
    threading.Thread(target=state.govee.status_loop, daemon=True).start()
    threading.Thread(target=state.govee.discover_lamps, daemon=True).start()
    state.govee.set_brightness(state.brightness)

    threading.Thread(target=state.spotify_sync_loop, daemon=True).start()
    threading.Thread(target=state.engine_loop, daemon=True).start()
    threading.Thread(target=watch_for_code_changes, daemon=True).start()
    threading.Thread(target=exit_when_orphaned, daemon=True).start()

    try:
        run_server()
    except KeyboardInterrupt:
        state.is_running = False


if __name__ == "__main__":
    main()
