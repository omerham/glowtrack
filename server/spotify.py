"""Talks to the Spotify app on this Mac through AppleScript (works on free accounts)."""
import subprocess
import time


# Volume / shuffle / repeat, read by the same AppleScript call as the track
EXTRAS = {"volume": None, "shuffle": False, "repeat": False}


def get_spotify_track_info():
    script = """
    if application "Spotify" is running then
        tell application "Spotify"
            set pState to player state as string
            set tName to name of current track
            set aName to artist of current track
            set artUrl to artwork url of current track
            set tPos to player position
            set tDur to (duration of current track) / 1000
            set tId to id of current track
            set tVol to sound volume
            set tShuf to shuffling
            set tRep to repeating
            return pState & " ||| " & tName & " ||| " & aName & " ||| " & artUrl & " ||| " & tPos & " ||| " & tDur & " ||| " & tId & " ||| " & tVol & " ||| " & tShuf & " ||| " & tRep
        end tell
    else
        return "NOT_RUNNING"
    end if
    """
    empty = (False, None, None, None, 0.0, 0.0, "")
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=2)
        out = res.stdout.strip()
        if not out or out == "NOT_RUNNING":
            return empty
        parts = out.split(" ||| ")
        if len(parts) >= 6:
            is_playing = (parts[0].lower() == "playing")
            # Some locales print decimals with a comma
            pos = float(parts[4].replace(",", "."))
            dur = float(parts[5].replace(",", "."))
            track_id = parts[6].strip() if len(parts) >= 7 else ""
            if len(parts) >= 10:
                try:
                    EXTRAS["volume"] = int(float(parts[7].replace(",", ".")))
                except ValueError:
                    pass
                EXTRAS["shuffle"] = parts[8].strip().lower() == "true"
                EXTRAS["repeat"] = parts[9].strip().lower() == "true"
            return is_playing, parts[1], parts[2], parts[3], pos, dur, track_id
    except Exception:
        pass
    return empty


def spotify_play_pause():
    try:
        subprocess.run(["osascript", "-e", 'tell application "Spotify" to playpause'], timeout=2)
    except Exception:
        pass


def spotify_next():
    try:
        subprocess.run(["osascript", "-e", 'tell application "Spotify" to next track'], timeout=2)
    except Exception:
        pass


def spotify_prev():
    try:
        subprocess.run(["osascript", "-e", 'tell application "Spotify" to previous track'], timeout=2)
    except Exception:
        pass


def spotify_seek(pos_sec):
    try:
        subprocess.run(["osascript", "-e", f'tell application "Spotify" to set player position to {float(pos_sec)}'], timeout=2)
    except Exception:
        pass


def _tell(cmd):
    try:
        subprocess.run(["osascript", "-e", f'tell application "Spotify" to {cmd}'], timeout=2)
    except Exception:
        pass


def spotify_set_volume(vol):
    vol = int(max(0, min(100, vol)))
    # Spotify lands one step below what it's asked for (31 -> 30), so ask for one more
    _tell(f"set sound volume to {vol + 1 if 0 < vol < 100 else vol}")


def spotify_set_shuffle(on):
    _tell(f"set shuffling to {'true' if on else 'false'}")


def spotify_set_repeat(on):
    _tell(f"set repeating to {'true' if on else 'false'}")


def spotify_connect_and_play():
    """Wakes or launches Spotify, turns on playback, and activates Govee sync."""
    try:
        subprocess.run(["open", "-g", "-a", "Spotify"], timeout=3)
        time.sleep(0.4)
        subprocess.run(["osascript", "-e", 'tell application "Spotify" to play'], timeout=2)
    except Exception as e:
        print(f"[!] spotify_connect_and_play error: {e}")
