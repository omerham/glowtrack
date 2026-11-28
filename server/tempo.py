"""Song tempo lookup (Deezer, then songbpm.com) and the song-position energy curve."""
import bisect
import collections
import json
import re
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_BPM = 120.0
UNKNOWN_SOURCES = ("Default", "Not found (default)")   # no real tempo was found
_BPM_CACHE = {}
_HTTP_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def clean_track_title(track):
    """Strips version suffixes so lookups match the original song.
    'Bohemian Rhapsody - Remastered 2011' -> 'Bohemian Rhapsody'
    'Anti-Hero' stays 'Anti-Hero' (only ' - ' with spaces is a suffix)."""
    t = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", track or "")
    t = re.split(r"\s+-\s+", t)[0]
    return t.strip()


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _http_get(url, timeout=4.0):
    req = urllib.request.Request(url, headers=_HTTP_UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", errors="ignore")


def _bpm_from_deezer(title, artist):
    q = urllib.parse.urlencode({"q": f"{artist} {title}", "limit": 6})
    data = json.loads(_http_get(f"https://api.deezer.com/search?{q}")).get("data") or []
    want_t, want_a = _norm(title), _norm(artist.split(",")[0])
    for item in data:
        if want_a and want_a not in _norm(item.get("artist", {}).get("name")):
            continue
        if not _norm(item.get("title")).startswith(want_t):
            continue
        info = json.loads(_http_get(f"https://api.deezer.com/track/{item['id']}"))
        bpm = float(info.get("bpm") or 0)
        if 40.0 <= bpm <= 240.0:
            return round(bpm, 1)
    return None


def _bpm_from_songbpm(title, artist):
    slug = lambda s: re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    a_slug = slug(artist.split(",")[0])
    t_slug = slug(title)
    if not a_slug or not t_slug:
        return None
    html = _http_get(f"https://songbpm.com/@{a_slug}/{t_slug}")
    # The song's own tempo is the first "NNN BPM" on its page
    m = re.search(r"\b(\d{2,3}(?:\.\d+)?)\s*BPM\b", html)
    if m:
        bpm = float(m.group(1))
        if 40.0 <= bpm <= 240.0:
            return bpm
    return None


def fetch_track_bpm(track, artist):
    """Looks up the song's real tempo. Returns (bpm, source_label).
    Tries Deezer first (exact tempo), then songbpm.com. Falls back to 120."""
    if not track:
        return DEFAULT_BPM, "Default"
    key = (_norm(track), _norm(artist))
    if key in _BPM_CACHE:
        return _BPM_CACHE[key]
    title = clean_track_title(track)
    artist = artist or ""
    result = (DEFAULT_BPM, "Not found (default)")
    had_network_error = False
    for source_name, fn in (("Deezer", _bpm_from_deezer), ("SongBPM", _bpm_from_songbpm)):
        try:
            bpm = fn(title, artist)
            if bpm:
                result = (bpm, source_name)
                break
        except urllib.error.HTTPError as e:
            if e.code != 404:
                had_network_error = True
        except Exception as e:
            had_network_error = True
            print(f"[!] BPM lookup via {source_name} failed: {e}")
    # Don't remember a miss caused by being offline - try again next time
    if result[1] != "Not found (default)" or not had_network_error:
        _BPM_CACHE[key] = result
    return result


def calculate_dynamic_intensity(pos_sec, dur_sec):
    if not dur_sec or dur_sec <= 0:
        return 1.0, "Full"
    p = max(0.0, min(1.0, pos_sec / dur_sec))

    if p < 0.12:
        t = p / 0.12
        intensity = 0.68 + 0.14 * t
        section = "Intro Build"
    elif p < 0.35:
        t = (p - 0.12) / 0.23
        intensity = 0.82 + 0.08 * t
        section = "Verse Groove"
    elif p < 0.42:
        t = (p - 0.35) / 0.07
        intensity = 0.90 + 0.10 * (t ** 2)
        section = "Tension Build"
    elif p < 0.58:
        intensity = 1.00
        section = "Chorus Drop"
    elif p < 0.70:
        t = (p - 0.58) / 0.12
        intensity = 0.84 + 0.08 * t
        section = "Bridge"
    elif p < 0.88:
        intensity = 1.00
        section = "Climax Drop"
    else:
        t = (p - 0.88) / 0.12
        intensity = 0.92 - 0.25 * t
        section = "Outro Wind-down"

    return max(0.60, min(1.0, intensity)), section


# ----------------------------------------------------------------------
# Energy from the song's own lyrics
# ----------------------------------------------------------------------
# The fixed curve above assumes every song is built the same way. A song's synced lyrics say more: lines that come
# back again and again are the chorus, a long stretch with no singing is an intro, a break or an outro. This reads
# that structure per song; when a song has no synced lyrics the fixed curve is used as before.

LYRIC_WINDOW = 7.0            # seconds either side of the position that count as "now"
LYRIC_BREAK = 11.0            # silence this long is an instrumental part, not a pause between lines


def build_lyric_profile(synced, dur=0.0):
    """synced: [[seconds, line], ...] as lyrics.py returns it. None when there are too few lines to tell anything."""
    lines = []
    for item in synced or []:
        try:
            t, text = float(item[0]), _norm(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if text:
            lines.append((t, text))
    lines.sort()
    if len(lines) < 8:
        return None
    count = collections.Counter(text for _, text in lines)
    return {"t": [t for t, _ in lines], "rep": [count[text] >= 2 and len(text) >= 6 for _, text in lines],
            "dur": float(dur or 0.0)}


def lyric_energy(profile, pos):
    """(level 0.6-1.0, section name) for a position in a song, from its lyric profile."""
    ts, rep = profile["t"], profile["rep"]
    first, last = ts[0], ts[-1]
    if pos < first:
        if first < 6.0:
            return 0.82, "Verse"
        return 0.66 + 0.16 * max(0.0, min(1.0, pos / first)), "Intro"
    lo = bisect.bisect_left(ts, pos - LYRIC_WINDOW)
    hi = bisect.bisect_right(ts, pos + LYRIC_WINDOW)
    n = hi - lo
    after = pos - last
    if after > LYRIC_BREAK or (n == 0 and pos > first):
        end = profile["dur"] or (last + 30.0)
        if pos > last:
            span = max(5.0, end - last)
            return max(0.6, 0.86 - 0.26 * max(0.0, min(1.0, after / span))), "Outro"
        return 0.84, "Instrumental"
    share = sum(1 for i in range(lo, hi) if rep[i]) / n
    return 0.80 + 0.20 * share, ("Chorus" if share >= 0.5 else "Verse")
