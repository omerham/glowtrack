"""Time-synced lyrics for the full-screen lyrics view.

Lyrics come from LRCLIB (lrclib.net), a free, open lyrics database that needs
no account or key. Each song is looked up once and kept in memory."""
import json
import re
import threading
import urllib.parse
import urllib.request

import players

API = "https://lrclib.net/api"
USER_AGENT = "Glowtrack/3.0 (album-colour lighting app)"
LRC_LINE = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")

_cache = {}
_lock = threading.Lock()


def _album_name():
    """Album of the current song (helps LRCLIB pick the right version)."""
    return players.current_album()


def _fetch(endpoint, params):
    url = f"{API}/{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def parse_lrc(text):
    """'[01:02.34] words' lines -> [[seconds, words], ...] in time order."""
    out = []
    for raw in (text or "").splitlines():
        stamps = LRC_LINE.findall(raw)
        if not stamps:
            continue
        words = LRC_LINE.sub("", raw).strip()
        for mins, secs in stamps:
            out.append([round(int(mins) * 60 + float(secs.replace(":", ".")), 2), words])
    out.sort(key=lambda x: x[0])
    return out


def _clean_title(title):
    # "Song (feat. X)" / "Song - Remastered 2011" -> "Song"
    t = re.sub(r"\s*[\(\[].*?[\)\]]", "", title)
    t = re.sub(r"\s+-\s+.*$", "", t)
    return t.strip() or title


def _first_artist(artist):
    return re.split(r",|&| feat\.| ft\.| x ", artist, maxsplit=1)[0].strip() or artist


def _result(rec):
    if not rec:
        return None
    synced = parse_lrc(rec.get("syncedLyrics"))
    plain = [l for l in (rec.get("plainLyrics") or "").splitlines()]
    if rec.get("instrumental"):
        return {"status": "instrumental", "synced": [], "plain": []}
    if synced:
        return {"status": "synced", "synced": synced, "plain": []}
    if any(l.strip() for l in plain):
        return {"status": "plain", "synced": [], "plain": plain}
    return None


def _lookup(track, artist, dur):
    album = _album_name()
    # 1. Exact match (title, artist, album, length)
    if album and dur:
        rec = _fetch("get", {"track_name": track, "artist_name": artist,
                             "album_name": album, "duration": int(round(dur))})
        res = _result(rec)
        if res and res["status"] != "plain":
            return res
    # 2. Search, preferring synced lyrics of about the same length
    best, best_score = None, None
    for title in dict.fromkeys([track, _clean_title(track)]):
        recs = _fetch("search", {"track_name": title, "artist_name": _first_artist(artist)}) or []
        for rec in recs[:20]:
            off = abs((rec.get("duration") or 0) - dur) if dur else 0
            if dur and off > 8:
                continue
            score = (0 if rec.get("syncedLyrics") else 1, off)
            if best_score is None or score < best_score:
                best, best_score = rec, score
        if best is not None and best.get("syncedLyrics"):
            break
    # 3. Artist name not matching (e.g. listed under a label): title only, but
    #    then the length has to match closely, and the album helps pick
    if best is None and dur:
        recs = _fetch("search", {"track_name": _clean_title(track)}) or []
        for rec in recs[:30]:
            off = abs((rec.get("duration") or 0) - dur)
            if off > 2:
                continue
            same_album = album and (rec.get("albumName") or "").lower() == album.lower()
            score = (0 if same_album else 1, 0 if rec.get("syncedLyrics") else 1, off)
            if best_score is None or score < best_score:
                best, best_score = rec, score
    return _result(best) or {"status": "none", "synced": [], "plain": []}


def get_lyrics(track, artist, dur):
    track, artist = (track or "").strip(), (artist or "").strip()
    if not track or not artist:
        return {"status": "none", "synced": [], "plain": []}
    key = (track.lower(), artist.lower())
    with _lock:
        if key in _cache:
            return _cache[key]
    try:
        res = _lookup(track, artist, dur)
    except Exception as e:
        # Network trouble: don't remember the failure, try again next time
        print(f"[!] Lyrics lookup failed: {e}")
        return {"status": "error", "synced": [], "plain": []}
    with _lock:
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = res
    return res
