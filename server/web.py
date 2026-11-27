"""Local web server: serves the dashboard and handles its commands."""
import gzip
import hmac
import json
import math
import os
import queue
import socket
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

from colors import extract_spotify_palette
from lyrics import get_lyrics
from config import ALLOW_LAN, OPEN_LAN, SERVER_PORT, clamp, get_pair_token
from engine import PREVIEW_MODES
from players import (next_track, play_pause, prev_track, seek,
                     set_repeat, set_shuffle, set_volume)

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
STATE = None   # set by app.py
COOKIE_NAME = "glowtrack"
_PAIR_TOKEN = None


def pair_token():
    global _PAIR_TOKEN
    if _PAIR_TOKEN is None:
        _PAIR_TOKEN = get_pair_token()
    return _PAIR_TOKEN


def lan_ip():
    """This Mac's address on the Wi-Fi (for the pairing link)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))     # no packet is sent; just picks the right interface
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


PAIR_PAGE = (b"<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
             b"<body style='font-family:-apple-system,sans-serif;background:#0b0e13;color:#e6e9ef;padding:32px;max-width:520px;margin:auto'>"
             b"<h2>Glowtrack</h2><p>This device isn't paired yet.</p>"
             b"<p>On the Mac running Glowtrack, open <b>Settings &rarr; Phone &amp; tablet access</b> "
             b"and open the link shown there on this device.</p>")
SHUTDOWN_EXIT_CODE = 64   # "stopped on purpose" - the menu-bar app quits instead of restarting


class BadRequest(Exception):
    pass


def _num(body, key, default):
    try:
        v = float(body.get(key, default))
    except (TypeError, ValueError):
        raise BadRequest(f"'{key}' must be a number")
    if not math.isfinite(v):
        raise BadRequest(f"'{key}' must be a number")
    return v


ALLOWED_HOSTS = {f"127.0.0.1:{SERVER_PORT}", f"localhost:{SERVER_PORT}"}

# The only files the server will hand out (nothing else on disk is reachable)
STATIC_FILES = {
    "/index.html": "text/html; charset=utf-8",
    "/app.js": "application/javascript; charset=utf-8",
    "/app.css": "text/css; charset=utf-8",
    "/themes.css": "text/css; charset=utf-8",
    "/themes.js": "application/javascript; charset=utf-8",
    "/tailwind.css": "text/css; charset=utf-8",
    "/manifest.webmanifest": "application/manifest+json",
    "/icon-180.png": "image/png",
    "/icon-512.png": "image/png",
    "/icon-192.png": "image/png",
    "/icon-maskable-512.png": "image/png",
    "/favicon-32.png": "image/png",
    "/favicon.ico": "image/x-icon",
    "/favicon.svg": "image/svg+xml",
    "/fonts.css": "text/css; charset=utf-8",
}
# the dashboard's fonts, stored in web/fonts so the page never asks another website for them
_FONT_DIR = os.path.join(WEB_DIR, "fonts")
if os.path.isdir(_FONT_DIR):
    for _name in os.listdir(_FONT_DIR):
        if _name.endswith(".woff2"):
            STATIC_FILES["/fonts/" + _name] = "font/woff2"


_STATIC_CACHE = {}
_COMPRESSIBLE = ("text/", "application/javascript", "application/manifest+json", "image/svg+xml", "image/x-icon")


def _static_entry(path):
    """(version, bytes, gzip bytes or None, etag) for a dashboard file, re-read only when the file changed."""
    full = os.path.join(WEB_DIR, path.lstrip("/"))
    st = os.stat(full)
    version = (st.st_mtime_ns, st.st_size)
    entry = _STATIC_CACHE.get(path)
    if entry is None or entry[0] != version:
        with open(full, "rb") as f:
            raw = f.read()
        gz = gzip.compress(raw, 6, mtime=0) if len(raw) > 600 and STATIC_FILES[path].startswith(_COMPRESSIBLE) else None
        entry = (version, raw, gz, '"%x-%x"' % version)
        _STATIC_CACHE[path] = entry
    return entry


class GoveeHttpHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    # --- helpers -----------------------------------------------------------
    def _send(self, code, payload, ctype="application/json"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_static(self, path):
        """A dashboard file. It is checked against the file on disk on every request (so an edit shows on the
        next reload), but sent only when it changed (ETag, answered with 304 otherwise) and compressed
        when the browser accepts it. Saves phones and tablets re-downloading about 300 KB on every visit."""
        try:
            entry = _static_entry(path)
        except OSError:
            self._send(404, {"error": "not found"})
            return
        ctype, raw, gz, etag = STATIC_FILES[path], entry[1], entry[2], entry[3]
        self.send_response(304 if self.headers.get("If-None-Match") == etag else 200)
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")           # keep it, but ask each time whether it changed
        self.send_header("Vary", "Accept-Encoding")
        if self.headers.get("If-None-Match") == etag:
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = raw
        if gz is not None and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            body = gz
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        """Blocks DNS-rebinding (a random website pretending to be this Mac).
        Real devices reach us by IP address, localhost or the Mac's .local name;
        a rebinding attack has to use some other domain name, so it's refused."""
        host = (self.headers.get("Host") or "")
        if host in ALLOWED_HOSTS:
            return True
        if not ALLOW_LAN:
            return False
        name = host.rsplit(":", 1)[0].strip("[]").lower() if host.count(":") <= 1 or host.startswith("[") else host.lower()
        if name in ("localhost",) or name.endswith(".local") or name.endswith(".ts.net"):
            return True
        try:
            socket.inet_pton(socket.AF_INET6 if ":" in name else socket.AF_INET, name)
            return True       # a plain IP address
        except OSError:
            return False

    def _is_local_client(self):
        """True when the request comes from this Mac itself (not another device on the Wi-Fi)."""
        return self.client_address[0] in ("127.0.0.1", "::1", "::ffff:127.0.0.1")

    def _paired(self):
        """This Mac itself is always trusted. Other devices need the pairing cookie."""
        if OPEN_LAN or self._is_local_client():
            return True
        try:
            cookie = SimpleCookie(self.headers.get("Cookie") or "")
            got = cookie[COOKIE_NAME].value if COOKIE_NAME in cookie else ""
        except Exception:
            return False
        return hmac.compare_digest(got.encode("utf-8"), pair_token().encode("utf-8"))

    def _pairing_redirect(self):
        """A device opening the pairing link gets its cookie and is sent to the dashboard."""
        query = parse_qs(urlsplit(self.path).query)
        given = (query.get("token") or [""])[0]
        if given and hmac.compare_digest(given.encode("utf-8"), pair_token().encode("utf-8")):
            self.send_response(302)
            self.send_header("Set-Cookie", f"{COOKIE_NAME}={pair_token()}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Strict")
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True
        return False

    def _command_ok(self):
        """Commands must come from our own page. Browsers won't let another
        website add this custom header without our permission (which we never give),
        so a page you visit can't control your lamps or Spotify."""
        if self.headers.get("X-Govee-App") != "1":
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in ("null",) and origin.split("://", 1)[-1] != self.headers.get("Host"):
            return False
        return True

    # --- GET ---------------------------------------------------------------
    def do_HEAD(self):
        if not self._host_ok():
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self._host_ok():
            self._send(403, {"error": "forbidden"})
            return
        if not self._paired():
            if not self._pairing_redirect():
                self._send(401, PAIR_PAGE, "text/html; charset=utf-8")
            return
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            path = "/index.html"
        if path in STATIC_FILES:
            self._send_static(path)
        elif path == "/api/lyrics":
            # Lyrics for whatever is playing now (looked up once per song)
            if STATE.is_ad:
                self._send(200, {"status": "none", "synced": [], "plain": [], "track": ""})
            else:
                track, artist = STATE.current_track, STATE.current_artist
                res = dict(get_lyrics(track, artist, STATE.current_dur))
                res["track"] = track
                self._send(200, res)
        elif path == "/api/pairing":
            if self._is_local_client():
                self._send(200, {"url": f"http://{lan_ip()}:{SERVER_PORT}/?token={pair_token()}", "open": OPEN_LAN})
            else:
                self._send(403, {"error": "forbidden"})
        elif path == "/api/art":
            data = STATE.current_art_bytes
            if data:
                ctype = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
                self._send(200, data, ctype)
            else:
                self._send(404, {"error": "no cover"})
        elif path == "/api/state":
            self._send(200, STATE.to_dict())
        elif path == "/api/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.close_connection = True
            sub_q = queue.Queue(maxsize=50)
            STATE.add_subscriber(sub_q)
            try:
                self.wfile.write(f"retry: 1500\ndata: {json.dumps(STATE.to_dict())}\n\n".encode("utf-8"))
                self.wfile.flush()
                while STATE.is_running:
                    try:
                        msgs = [sub_q.get(timeout=15.0)]
                        while not sub_q.empty():
                            msgs.append(sub_q.get_nowait())
                        # If the page fell behind, only send the newest of each kind
                        latest_state = next((m for m in reversed(msgs) if m.startswith("data:")), None)
                        latest_frame = next((m for m in reversed(msgs) if m.startswith("event: frame")), None)
                        out = (latest_state or "") + (latest_frame or "")
                        self.wfile.write(out.encode("utf-8"))
                    except queue.Empty:
                        self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                STATE.remove_subscriber(sub_q)
        else:
            self._send(404, {"error": "not found"})

    # --- POST --------------------------------------------------------------
    def do_POST(self):
        if not self._host_ok() or not self._command_ok() or not self._paired():
            self._send(403, {"error": "forbidden"})
            return
        try:
            content_len = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            content_len = 0
        if content_len > 64 * 1024:
            self._send(413, {"error": "too large"})
            return
        raw = self.rfile.read(content_len).decode("utf-8", errors="ignore") if content_len > 0 else ""
        try:
            body = json.loads(raw) if raw else {}
            if not isinstance(body, dict):
                body = {}
        except ValueError:
            body = {}

        try:
            result = self._handle_post(self.path.split("?", 1)[0], body)
        except BadRequest as e:
            self._send(400, {"error": str(e)})
            return
        except Exception as e:
            print(f"[!] Error handling {self.path}: {e}")
            self._send(500, {"error": "internal error"})
            return
        if result is None:
            self._send(404, {"error": "not found"})
        else:
            self._send(200, result)

    def _handle_post(self, path, body):
        S = STATE
        ok = {"status": "ok"}

        if path == "/api/connect":
            threading.Thread(target=S.connect_and_start, daemon=True).start()
            return {"status": "connected"}

        if path == "/api/release":
            if not self._is_local_client():
                raise BadRequest("this command only works from this Mac")
            S.release_lamps()                    # the menu-bar app calls this just before it quits
            return ok

        if path == "/api/shutdown":
            # Stop the server (e.g. from a phone). Exit code SHUTDOWN_EXIT_CODE tells
            # the menu-bar app this was on purpose, so it quits instead of restarting.
            lamps_off = bool(body.get("lamps_off", False))
            def _stop():
                time.sleep(0.4)            # let this response reach the phone first
                if lamps_off:
                    S.set_power(False)
                    time.sleep(0.3)
                else:
                    S.release_lamps()            # leave them on, but under the Govee app's control again
                print("[*] Shut down from the dashboard")
                os._exit(SHUTDOWN_EXIT_CODE)
            threading.Thread(target=_stop, daemon=True).start()
            return {"status": "shutting down"}

        if path == "/api/spotify_changed":
            # The menu-bar app forwards Spotify's own "song/play state changed"
            # notification here, so changes show up instantly instead of on the next poll.
            S.spotify_nudge()
            return ok

        if path == "/api/preset":
            p = body.get("preset")
            if p == "solid":
                S.spatial_mode, S.motion_mode = "unified", "static"
            elif p == "wave":
                S.spatial_mode, S.motion_mode = "unified", "flow"
            elif p == "duo":
                S.spatial_mode, S.motion_mode = "duo", "static"
            elif p == "segmented":
                S.spatial_mode, S.motion_mode = "segmented", "flow"
            else:
                raise BadRequest("unknown preset")
            S.locked_swatch_index = None
            S.save_config()
            S.apply_lighting(1.0)
            return ok

        if path == "/api/swap_lr":
            S.swap_lr()
            return ok
        if path == "/api/invert_tb":
            S.invert_tb()
            return ok

        if path == "/api/flow_speed":
            S.flow_speed = clamp(_num(body, "speed", 5.0), 2.5, 20.0)
            S.save_config()
            S.broadcast()
            return ok

        if path == "/api/trans_speed":
            S.trans_speed = clamp(_num(body, "speed", 3.0), 1.0, 8.0)
            S.save_config()
            S.broadcast()
            return ok

        if path == "/api/vibrancy":
            S.vibrancy = clamp(_num(body, "value", 1.15), 0.7, 1.8)
            S.save_config()
            if S.current_art_bytes:
                raw_pal, lamp_pal = extract_spotify_palette(S.current_art_bytes, max_colors=5, vibrancy_mult=S.vibrancy,
                                                            white_accent=S.white_accent)
                if S.locked_swatch_index is not None and S.locked_swatch_index >= len(lamp_pal):
                    S.locked_swatch_index = None
                S.current_raw_palette = list(raw_pal)
                S.current_lamp_palette = list(lamp_pal)
                S.apply_lighting(0.6)    # gentle fade instead of a jump
            else:
                S.broadcast()
            return ok

        if path == "/api/pulse":
            S.music_pulse_enabled = bool(body.get("enabled", False))
            S.save_config()
            S.request_update(0)
            S.broadcast()
            return ok

        if path == "/api/dynamic_intensity":
            S.dynamic_intensity_enabled = bool(body.get("enabled", False))
            if not S.dynamic_intensity_enabled:
                S.current_intensity = 1.0
                S.current_section = "Normal"
            S.save_config()
            S.request_update(0)
            S.broadcast()
            return ok

        if path == "/api/bpm":
            S.set_manual_bpm(_num(body, "bpm", 120.0), tap=bool(body.get("tap", False)))
            return ok

        if path == "/api/bpm_auto":
            S.set_auto_bpm()
            return ok

        if path == "/api/dark_boost":
            S.dark_boost = clamp(_num(body, "value", 0.65), 0.0, 1.0)
            S.save_config()
            S.request_update(0.4)
            S.broadcast()
            return ok

        if path == "/api/white_accent":
            S.white_accent = bool(body.get("enabled", True))
            S.save_config()
            if S.current_art_bytes:      # re-pick this song's colours straight away
                raw_pal, lamp_pal = extract_spotify_palette(S.current_art_bytes, max_colors=5, vibrancy_mult=S.vibrancy,
                                                            white_accent=S.white_accent)
                S.locked_swatch_index = None
                S.set_new_track_palette(raw_pal, lamp_pal)
            S.broadcast()
            return ok

        if path == "/api/fs_motion":
            S.fs_motion = int(clamp(_num(body, "value", 1), 0, 5))
            S.save_config()
            S.broadcast()
            return ok

        if path == "/api/preview_mode":
            mode = body.get("mode")
            if mode not in PREVIEW_MODES:
                raise BadRequest("unknown preview mode")
            S.preview_mode = mode
            S.save_config()
            S.broadcast()
            return ok

        if path == "/api/pulse_depth":
            S.pulse_depth = clamp(_num(body, "depth", 0.60), 0.1, 0.9)
            S.save_config()
            S.broadcast()
            return ok

        if path == "/api/brightness":
            S.set_brightness(_num(body, "value", 100))
            return ok

        if path == "/api/power":
            S.set_power(bool(body.get("on", True)))
            return ok

        if path == "/api/rescan":
            def _scan():
                S.govee.discover_lamps()
                S.broadcast()
            threading.Thread(target=_scan, daemon=True).start()
            return ok

        if path == "/api/swatch":
            idx = body.get("index")
            if idx is None or idx == -1:
                S.locked_swatch_index = None
            else:
                try:
                    idx = int(idx)
                except (TypeError, ValueError):
                    raise BadRequest("index must be a number")
                if not (0 <= idx < len(S.current_lamp_palette)):
                    raise BadRequest("no such swatch")
                S.locked_swatch_index = idx
            S.apply_lighting(1.2)
            return ok

        if path == "/api/lamps/assign":
            side, ip = body.get("side"), body.get("ip")
            if side in ("left", "right") and ip:
                S.assign_lamp_side(side, str(ip))
            else:
                if body.get("left_ip"):
                    S.assign_lamp_side("left", str(body["left_ip"]))
                if body.get("right_ip"):
                    S.assign_lamp_side("right", str(body["right_ip"]))
            return ok

        if path in ("/api/debug_record", "/api/lamp_test") and not self._is_local_client():
            raise BadRequest("this command only works from this Mac")

        if path == "/api/debug_record":
            # Debug: log everything sent to the lamps for N seconds to ~/.govee_record.json
            secs = clamp(_num(body, "secs", 30), 1, 120)
            def _rec():
                S.govee.record = []
                time.sleep(secs)
                rows, S.govee.record = S.govee.record, None
                with open(os.path.expanduser("~/.govee_record.json"), "w") as f:
                    json.dump(rows, f)
            threading.Thread(target=_rec, daemon=True).start()
            return ok

        if path == "/api/lamp_test":
            import lamp_test
            lamp_test.run(S)
            return ok

        if path == "/api/attention":
            # Claude Code hooks: on when Claude needs you, off when you reply
            S.set_attention(bool(body.get("on", True)))
            return ok

        if path == "/api/flash":
            # Attention signal, e.g. red x3 (used by a Claude Code hook: "I'm done, need input")
            hexcol = str(body.get("color", "#FF0000")).lstrip("#")
            try:
                rgb = tuple(int(hexcol[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                raise BadRequest("color must be like #FF0000")
            times = int(clamp(_num(body, "times", 3), 1, 10))
            S.flash(rgb, times)
            return ok

        if path == "/api/updates/check":
            threading.Thread(target=lambda: S.check_for_update(force=True), daemon=True).start()
            return ok

        if path == "/api/updates/auto":
            S.set_check_updates(bool(body.get("enabled", True)))
            return ok

        if path == "/api/devices/add":
            try:
                S.add_device(body.get("kind"), body.get("ip"), body.get("side", "left"), body.get("name", ""))
            except ValueError as e:
                raise BadRequest(str(e))
            return ok

        if path == "/api/devices/update":
            try:
                S.update_device(str(body.get("ip", "")), body.get("name"), body.get("side"))
            except ValueError as e:
                raise BadRequest(str(e))
            return ok

        if path == "/api/devices/remove":
            S.remove_device(str(body.get("ip", "")))
            return ok

        if path == "/api/devices/scan":
            threading.Thread(target=S.scan_devices, daemon=True).start()
            return ok

        if path == "/api/lamps/identify":
            ip = body.get("ip")
            side = body.get("side")
            if not ip and side:
                ip = S.govee.left_ip if side == "left" else S.govee.right_ip
            if ip and ip in S.govee.all_ips:
                S.identify(ip)
            return ok

        if path == "/api/playback/playpause":
            S.is_playing = not S.is_playing
            S.pos_sample_time = time.time()
            S.broadcast()
            def _pp():
                play_pause()
                time.sleep(0.15)
                S.poll_spotify_step()
            threading.Thread(target=_pp, daemon=True).start()
            return ok

        if path in ("/api/playback/next", "/api/playback/prev"):
            fn = next_track if path.endswith("next") else prev_track
            def _skip():
                fn()
                time.sleep(0.25)
                S.poll_spotify_step()
            threading.Thread(target=_skip, daemon=True).start()
            return ok

        if path == "/api/playback/volume":
            vol = int(clamp(_num(body, "value", 50), 0, 100))
            S.set_playback_extra("volume", vol)
            threading.Thread(target=set_volume, args=(vol,), daemon=True).start()
            return ok

        if path == "/api/playback/shuffle":
            on = bool(body.get("on", True))
            S.set_playback_extra("shuffle", on)
            threading.Thread(target=set_shuffle, args=(on,), daemon=True).start()
            return ok

        if path == "/api/playback/repeat":
            on = bool(body.get("on", True))
            S.set_playback_extra("repeat", on)
            threading.Thread(target=set_repeat, args=(on,), daemon=True).start()
            return ok

        if path == "/api/playback/seek":
            pos = max(0.0, _num(body, "pos", 0.0))
            if S.current_dur:
                pos = min(pos, S.current_dur)
            S.current_pos = pos
            S.pos_sample_time = time.time()
            S.broadcast()
            threading.Thread(target=seek, args=(pos,), daemon=True).start()
            return ok

        return None
