"""Finds out whether a newer Glowtrack has been released on GitHub.

One plain GET to GitHub's public "latest release" address, at most once a day, and only when the owner
leaves "Check for updates" on in Settings. Nothing about the owner, their lamps or their music is sent;
GitHub sees an ordinary request from their network address. Nothing is downloaded or installed: the
dashboard only offers a link to the release page.
"""
import json
import re
import urllib.request

LATEST_API = "https://api.github.com/repos/omerham/glowtrack/releases/latest"
RELEASES_PAGE = "https://github.com/omerham/glowtrack/releases/latest"


def parse_version(text):
    """'v3.1.4' -> (3, 1, 4); None when it is not a plain version number."""
    m = re.fullmatch(r"v?(\d+)\.(\d+)(?:\.(\d+))?", str(text or "").strip())
    if not m:
        return None
    return tuple(int(x or 0) for x in m.groups())


def is_newer(latest, current):
    a, b = parse_version(latest), parse_version(current)
    return bool(a and b and a > b)


def fetch_latest(timeout=5.0):
    """Returns (version text, release page address), or None when it could not be found out."""
    req = urllib.request.Request(LATEST_API, headers={"User-Agent": "Glowtrack-update-check",
                                                      "Accept": "application/vnd.github+json"})
    try:
        data = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))
    except Exception:
        return None
    tag = str(data.get("tag_name") or "")
    if parse_version(tag) is None:
        return None
    url = str(data.get("html_url") or "")
    if not url.startswith("https://github.com/omerham/glowtrack/"):
        url = RELEASES_PAGE
    return tag.lstrip("v"), url
