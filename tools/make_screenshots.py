#!/usr/bin/env python3
"""Takes the README screenshots of every design with the built-in demo mode (a made-up song and pretend lamps).

    /usr/bin/python3 tools/make_screenshots.py [--base http://127.0.0.1:8765] [--only a,b]

Needs the Glowtrack server running (it only serves the page; demo mode never reads or sends anything real)
and Google Chrome. Writes PNGs to docs/screenshots/. See server/web/demo.js for the demo address options.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "screenshots")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
DESK, PHONE, CLASSIC = (1100, 800), (500, 760), (1180, 1060)    # window sizes (Chrome never makes a window narrower than 500, and its own bar takes some of the height)
BAR = 87                                        # height of the bar in Chrome's headless window
NAMES = {"classic": "classic", "a": "a-instrument", "b": "b-dot", "c": "c-poster", "d": "d-stage"}

SHOTS = []                                      # (file, query, window, final width in pixels)
for t in ("classic", "a", "b", "c", "d"):
    SHOTS.append((f"{NAMES[t]}-main", f"theme={t}", CLASSIC if t == "classic" else DESK, 1600))
for t in ("a", "b", "c", "d"):
    SHOTS.append((f"{NAMES[t]}-lyrics", f"theme={t}&screen=full&lyrics=1&pos=38", DESK, 1600))
for t in ("a", "b", "c", "d"):
    SHOTS.append((f"{NAMES[t]}-phone", f"theme={t}", PHONE, 640))


def chrome(args, url):
    profile = tempfile.mkdtemp()
    cmd = [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
           "--virtual-time-budget=9000", f"--user-data-dir={profile}"] + args + [url]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def take(base, name, query, window, width):
    url = f"{base}/?demo=1&shot=1&{query}"
    size = f"--window-size={window[0]},{window[1]}"
    # Chrome's page area is shorter than its window when it prints the page than when it takes the picture
    # (by the height of its own bar), so measure in a window that much taller to get the same page area
    dom = chrome([f"--window-size={window[0]},{window[1] + BAR}", "--dump-dom"], url).stdout
    m = re.search(r'data-rect="([^"]*)"', dom)
    if not m:
        sys.exit(f"{name}: the page never reported its size (is the server running at {base}?)")
    left, top, w, h, dpr, iw, ih = json.loads(m.group(1).replace("&quot;", '"'))
    if abs(ih - window[1]) > 1:
        sys.exit(f"{name}: the measured page is {ih}px tall but the picture will be {window[1]}px; adjust BAR")
    tmp = os.path.join(tempfile.mkdtemp(), "shot.png")
    chrome([size, f"--screenshot={tmp}"], url)
    img = Image.open(tmp).convert("RGB")
    box = tuple(int(round(v * dpr)) for v in (left, top, left + w, top + h))
    img = img.crop(box)
    img = img.resize((width, int(round(img.height * width / img.width))), Image.LANCZOS)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name + ".png")
    img.save(path, optimize=True)
    print(f"{name}.png  {img.size[0]}x{img.size[1]}  {os.path.getsize(path) // 1024} KB")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    if not os.path.exists(CHROME):
        sys.exit("Google Chrome is needed (it is only used to take the pictures)")
    only = [s for s in a.only.split(",") if s]
    for name, query, window, width in SHOTS:
        if only and not any(o in name for o in only):
            continue
        take(a.base, name, query, window, width)


if __name__ == "__main__":
    main()
