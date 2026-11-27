"""What's playing, from any app.

Spotify and Apple Music are controlled directly through AppleScript (play/pause, skip,
seek, volume, shuffle and repeat all work). Everything else - YouTube Music in a browser,
Tidal, Amazon Music, Deezer, ... - comes from macOS's own "Now Playing" info, which
can play/pause, skip and seek, but has no shuffle/repeat we can reach; the volume
slider then changes the Mac's output volume.

All of them give the same answer shape, so the rest of the app doesn't care which one it is.
Playback buttons go to whichever player is in use."""
import base64
import json
import os
import subprocess
import sys
import time

import spotify

SYSTEM_SOURCE = "system"
MUSIC_SOURCE = "music"
MUSIC_BUNDLE = "com.apple.Music"
_SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nowplaying")
_SRC = os.path.join(_SRC_DIR, "mr.m")
_LIB_DIR = os.path.expanduser("~/Library/Caches/Glowtrack")
_LIB = os.path.join(_LIB_DIR, "libmr.dylib")

_PERL = ("use DynaLoader; $l = DynaLoader::dl_load_file($ARGV[0], 0) or exit 2; "
         "$s = DynaLoader::dl_find_symbol($l, $ARGV[1]) or exit 3; "
         "$r = DynaLoader::dl_install_xsub('main::f', $s); &$r;")

_active = "spotify"      # "spotify", "music" (Apple Music) or "system" (anything else)
_album = ""              # album of the current system-player song (for lyrics)
_helper_state = None     # None = not tried, True = ready, False = unavailable
_warned = False
_sysvol_read_at = 0.0
_bundle = ""             # bundle id of the app Now Playing reported
_sample_t = 0.0         # when the song position returned by get_track_info() was read


def active_source():
    return _active


_NAMES = {"com.apple.Music": "Apple Music", "com.google.Chrome": "Chrome", "com.apple.Safari": "Safari",
          "org.mozilla.firefox": "Firefox", "company.thebrowser.Browser": "Arc", "com.microsoft.edgemac": "Edge",
          "com.tidal.desktop": "Tidal", "com.amazon.music": "Amazon Music", "com.deezer.deezer-desktop": "Deezer"}


def source_name():
    """Friendly name of what is playing: Spotify, Apple Music, Chrome, ..."""
    if _active == "spotify":
        return "Spotify"
    if _active == MUSIC_SOURCE:
        return "Apple Music"
    return _NAMES.get(_bundle) or (_bundle.rsplit(".", 1)[-1].title() if _bundle else "Now Playing")


def album():
    return spotify.EXTRAS.get("album", "") if _active == "spotify" else _album


def last_sample_time():
    """When the position from the latest get_track_info() was really read. Reading takes
    ~0.3 s, and the beat pulse needs the position to the nearest few hundredths of a second."""
    return _sample_t


def can_shuffle_repeat():
    """Only players with a real scripting interface have shuffle/repeat we can control."""
    return _active in ("spotify", MUSIC_SOURCE)


def _osa(script, timeout=2):
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
        return res.stdout.strip()
    except Exception:
        return ""


def _music_tell(cmd):
    _osa(f'tell application "Music" to {cmd}')


def _read_music_extras():
    """Apple Music's volume / shuffle / repeat, in the same place Spotify's go."""
    out = _osa('tell application "Music" to return (sound volume as string) & "|" & '
               '(shuffle enabled as string) & "|" & (song repeat as string)')
    parts = out.split("|")
    if len(parts) == 3:
        try:
            spotify.EXTRAS["volume"] = int(float(parts[0].replace(",", ".")))
        except ValueError:
            pass
        spotify.EXTRAS["shuffle"] = parts[1].strip().lower() == "true"
        spotify.EXTRAS["repeat"] = parts[2].strip().lower() not in ("off", "")


def _read_system_volume():
    """Mac output volume, shown on the volume slider for other players (read every few seconds)."""
    global _sysvol_read_at
    now = time.time()
    if now - _sysvol_read_at < 5.0:
        return
    _sysvol_read_at = now
    out = _osa("output volume of (get volume settings)")
    try:
        spotify.EXTRAS["volume"] = int(float(out))
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# macOS Now Playing helper
# ---------------------------------------------------------------------------
def _helper_ready():
    """Builds the small helper library on first use (needs Xcode's command-line tools).
    A downloaded app ships it prebuilt, so nothing needs compiling."""
    global _helper_state, _warned, _LIB
    if _helper_state is not None:
        return _helper_state
    prebuilt = os.path.join(_SRC_DIR, "libmr.dylib")
    if os.path.exists(prebuilt):
        _LIB = prebuilt
        _helper_state = True
        return True
    try:
        if not os.path.exists(_LIB) or os.path.getmtime(_LIB) < os.path.getmtime(_SRC):
            os.makedirs(_LIB_DIR, exist_ok=True)
            subprocess.run(["/usr/bin/clang", "-dynamiclib", "-fobjc-arc", "-framework", "Foundation",
                            _SRC, "-o", _LIB], check=True, capture_output=True, timeout=120)
        _helper_state = True
    except Exception as e:
        _helper_state = False
        if not _warned:
            _warned = True
            print(f"[!] Now Playing helper unavailable (only Spotify will work). "
                  f"Install Xcode's command-line tools: xcode-select --install ({e})")
    return _helper_state


def _run(func, **env):
    """Runs one helper function inside Apple's perl; returns its output."""
    if not _helper_ready():
        return ""
    full_env = dict(os.environ)
    full_env.update({k: str(v) for k, v in env.items()})
    try:
        res = subprocess.run(["/usr/bin/perl", "-e", _PERL, _LIB, func], env=full_env,
                             capture_output=True, text=True, timeout=4)
        return res.stdout
    except Exception:
        return ""


def _system_info(with_art=False):
    out = _run("mr_info", MR_ART="1") if with_art else _run("mr_info")
    try:
        info = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
    except ValueError:
        return {}
    return info if info.get("title") else {}


def _art_key(info):
    return "nowplaying:" + "|".join(str(info.get(k, "")) for k in ("title", "artist", "album", "art_id"))


# ---------------------------------------------------------------------------
# One answer for the app
# ---------------------------------------------------------------------------
def get_track_info():
    """(is_playing, track, artist, art_url, pos_sec, dur_sec, track_id) - same as Spotify's."""
    global _active, _album, _sample_t, _bundle
    t0 = time.time()
    sp = spotify.get_spotify_track_info()
    t1 = time.time()
    if sp[0]:                       # Spotify is playing: it wins (and keeps its richer info)
        _active = "spotify"
        _sample_t = (t0 + t1) / 2   # Spotify reads the position part-way through its script
        return sp
    info = _system_info()
    _sample_t = time.time() - 0.01  # Now Playing works the position out right as the helper finishes
    if info and (info.get("playing") or not sp[1]):
        _album = info.get("album", "")
        _bundle = info.get("bundle", "")
        art = _art_key(info) if info.get("has_art") else None
        if info.get("bundle") == MUSIC_BUNDLE:
            _active = MUSIC_SOURCE
            _read_music_extras()
        else:
            _active = SYSTEM_SOURCE
            spotify.EXTRAS["shuffle"] = spotify.EXTRAS["repeat"] = False
            _read_system_volume()
        return (bool(info.get("playing")), info["title"], info.get("artist", ""), art,
                float(info.get("pos") or 0.0), float(info.get("duration") or 0.0), info.get("id", ""))
    _active = "spotify"
    return sp


def fetch_art(art_url):
    """Cover image bytes for the art_url returned by get_track_info()."""
    if art_url.startswith("nowplaying:"):
        info = _system_info(with_art=True)
        if not info.get("art_b64"):
            raise RuntimeError("no artwork from Now Playing")
        return base64.b64decode(info["art_b64"])
    import urllib.request
    req = urllib.request.Request(art_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=3.5) as r:
        return r.read(8 * 1024 * 1024)   # covers are small; never read unbounded data


def current_album():
    if _active == "spotify":
        try:
            res = subprocess.run(["osascript", "-e", 'tell application "Spotify" to album of current track'],
                                 capture_output=True, text=True, timeout=2)
            return res.stdout.strip()
        except Exception:
            return ""
    return _album


# ---------------------------------------------------------------------------
# Playback buttons
# ---------------------------------------------------------------------------
def _system_cmd(cmd, **env):
    _run("mr_cmd", MR_CMD=cmd, **env)


def play_pause():
    if _active == "spotify":
        spotify.spotify_play_pause()
    elif _active == MUSIC_SOURCE:
        _music_tell("playpause")
    else:
        _system_cmd(2)


def next_track():
    if _active == "spotify":
        spotify.spotify_next()
    elif _active == MUSIC_SOURCE:
        _music_tell("next track")
    else:
        _system_cmd(4)


def prev_track():
    if _active == "spotify":
        spotify.spotify_prev()
    elif _active == MUSIC_SOURCE:
        _music_tell("previous track")
    else:
        _system_cmd(5)


def seek(pos_sec):
    if _active == "spotify":
        spotify.spotify_seek(pos_sec)
    elif _active == MUSIC_SOURCE:
        _music_tell(f"set player position to {float(pos_sec)}")
    else:
        _system_cmd(24, MR_POS=float(pos_sec))


def set_volume(vol):
    vol = int(max(0, min(100, vol)))
    if _active == "spotify":
        spotify.spotify_set_volume(vol)
    elif _active == MUSIC_SOURCE:
        _music_tell(f"set sound volume to {vol}")
    else:      # other apps have no volume we can reach: use the Mac's output volume
        _osa(f"set volume output volume {vol}")


def set_shuffle(on):
    if _active == "spotify":
        spotify.spotify_set_shuffle(on)
    elif _active == MUSIC_SOURCE:
        _music_tell(f"set shuffle enabled to {'true' if on else 'false'}")


def set_repeat(on):
    if _active == "spotify":
        spotify.spotify_set_repeat(on)
    elif _active == MUSIC_SOURCE:
        _music_tell(f"set song repeat to {'all' if on else 'off'}")
