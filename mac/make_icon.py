#!/usr/bin/env python3
"""Draws the Glowtrack app icon and writes every size it is needed at: the Mac app icon (.icns) and the
web icons (home-screen, installable-app, maskable, favicon .ico/.png/.svg).

    /usr/bin/python3 mac/make_icon.py

A glowing orb inside a track ring that is part played, colours running from crimson through orange and amber
to warm white, on a dark warm surface. It stands for light following music, not for any particular lamp, brand or
number of lights. Needs Pillow; the .icns is made with macOS's iconutil.
"""
import math
import os
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(os.path.dirname(HERE), "server", "web")
S = 2048                                   # draw big, shrink for crisp edges

# bottom (zone 1) to top (zone 7)
FLOW = [(214, 40, 57), (246, 79, 52), (255, 122, 48), (255, 168, 46), (255, 202, 84), (255, 226, 150), (255, 244, 214)]


FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><radialGradient id="o"><stop offset="0" stop-color="#FFF6E2"/><stop offset=".5" stop-color="#FFD678"/><stop offset="1" stop-color="#FF6A34"/></radialGradient><linearGradient id="r" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#D62839"/><stop offset=".5" stop-color="#FF7A30"/><stop offset="1" stop-color="#FFE296"/></linearGradient></defs><rect width="64" height="64" rx="14" fill="#17110F"/><circle cx="32" cy="32" r="20.8" fill="none" stroke="#FFEBD7" stroke-opacity=".14" stroke-width="5.5"/><path d="M32 11.2A20.8 20.8 0 1 1 11.2 32" fill="none" stroke="url(#r)" stroke-width="5.5" stroke-linecap="round"/><circle cx="32" cy="32" r="9.5" fill="url(#o)"/></svg>"""


def squircle_mask(size, body):
    """macOS-style rounded square (a superellipse), `body` px wide, centred in a size x size canvas."""
    m = Image.new("L", (size, size), 0)
    px = m.load()
    r, c, n = body / 2.0, size / 2.0, 5.0
    pts = []
    for i in range(720):
        t = 2 * math.pi * i / 720
        x = abs(math.cos(t)) ** (2 / n) * (1 if math.cos(t) >= 0 else -1)
        y = abs(math.sin(t)) ** (2 / n) * (1 if math.sin(t) >= 0 else -1)
        pts.append((c + r * x, c + r * y))
    ImageDraw.Draw(m).polygon(pts, fill=255)
    return m


def lerp_stops(stops, t):
    t = min(1.0, max(0.0, t)) * (len(stops) - 1)
    i = min(len(stops) - 2, int(t)); f = t - i
    return tuple(int(stops[i][k] + (stops[i + 1][k] - stops[i][k]) * f) for k in range(3))


ORB = [(255, 106, 52), (255, 160, 48), (255, 214, 120), (255, 246, 226)]    # edge to centre
ARC = 0.75                                                                   # how far round the track has played


def art_layer():
    """The glow: a bright orb in the middle and a track ring round it, played from the top clockwise, its colour
    running crimson to warm white, with a playhead at the end. Not tied to any lamp, brand or number of lights."""
    c = S / 2
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    R = S * 0.155
    for k in range(int(R), 0, -2):                                # orb, a radial gradient from the edge in
        d.ellipse([c - k, c - k, c + k, c + k], fill=lerp_stops(ORB, 1 - k / R) + (255,))
    rr, w = S * 0.325, S * 0.052
    ro = rr + w / 2                                                  # PIL draws a wide arc inward from its box, so the box is the outer edge
    box = [c - ro, c - ro, c + ro, c + ro]
    d.arc(box, 0, 360, fill=(255, 235, 215, 34), width=int(w))      # the whole track, faint
    steps = int(360 * ARC * 2)
    for i in range(steps):
        a0 = 270 + i * 0.5; a1 = a0 + 0.9
        d.arc(box, a0, a1, fill=lerp_stops(FLOW, i / (steps - 1)) + (255,), width=int(w))
    def end_at(frac):
        ang = math.radians(270 + 360 * ARC * frac)
        return c + rr * math.cos(ang), c + rr * math.sin(ang)
    x0, y0 = end_at(0)                                              # rounded start
    d.ellipse([x0 - w / 2, y0 - w / 2, x0 + w / 2, y0 + w / 2], fill=FLOW[0] + (255,))
    x1, y1 = end_at(1)
    pr = S * 0.046                                                  # the playhead
    d.ellipse([x1 - pr, y1 - pr, x1 + pr, y1 + pr], fill=(255, 246, 226, 255))
    return layer


def draw(full_bleed=False):
    body = S if full_bleed else int(S * 0.805)          # macOS icons leave a margin round the shape
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    bg = Image.new("RGBA", (S, S))                       # dark warm surface, a touch lighter high up
    px = bg.load()
    for y in range(S):
        t = y / (S - 1)
        c = (int(34 - 20 * t), int(25 - 15 * t), int(22 - 13 * t), 255)
        for x in range(S):
            px[x, y] = c
    canvas.alpha_composite(bg)

    art = art_layer()
    for radius, a in ((S * 0.16, 0.55), (S * 0.07, 0.5), (S * 0.025, 0.4)):      # the glow, wide and soft then tight
        g = art.filter(ImageFilter.GaussianBlur(radius))
        r_, g_, b_, al = g.split()
        canvas.alpha_composite(Image.merge("RGBA", (r_, g_, b_, al.point(lambda v, a=a: min(255, int(v * a * 1.8))))))
    canvas.alpha_composite(art)

    if full_bleed:
        return canvas
    mask = squircle_mask(S, body)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(canvas, (0, 0), mask)
    return out


def main():
    icon = draw()
    flat = draw(full_bleed=True)
    tmp = tempfile.mkdtemp()
    iconset = os.path.join(tmp, "AppIcon.iconset")
    os.makedirs(iconset)
    for base in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = base * scale
            name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
            icon.resize((px, px), Image.LANCZOS).save(os.path.join(iconset, name))
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(HERE, "AppIcon.icns")], check=True)
    icon.resize((1024, 1024), Image.LANCZOS).save(os.path.join(tmp, "preview.png"))
    for size, name in ((180, "icon-180.png"), (192, "icon-192.png"), (512, "icon-512.png")):      # square, full bleed, no transparency
        flat.convert("RGB").resize((size, size), Image.LANCZOS).save(os.path.join(WEB, name))
    # maskable: Android/Chrome crop it to any shape, so the art stays inside the central 80% on a solid ground
    mask_canvas = Image.new("RGB", (512, 512))
    md = ImageDraw.Draw(mask_canvas)
    for y in range(512):                                   # same warm gradient as the art, carried out to the edges
        t = min(1.0, max(0.0, (y - 51) / 410.0))
        md.line([(0, y), (512, y)], fill=(int(34 - 20 * t), int(25 - 15 * t), int(22 - 13 * t)))
    mask_canvas.paste(flat.convert("RGB").resize((410, 410), Image.LANCZOS), (51, 51))
    mask_canvas.save(os.path.join(WEB, "icon-maskable-512.png"))
    fav = icon.resize((256, 256), Image.LANCZOS)
    fav.resize((32, 32), Image.LANCZOS).save(os.path.join(WEB, "favicon-32.png"))
    fav.save(os.path.join(WEB, "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    with open(os.path.join(WEB, "favicon.svg"), "w") as f:
        f.write(FAVICON_SVG)
    shutil.copy(os.path.join(tmp, "preview.png"), os.path.join(HERE, "icon-preview.png"))
    if os.environ.get("ICON_SHEET"):
        sheet = Image.new("RGBA", (400, 140), (200, 200, 200, 255))
        x = 8
        for px in (16, 32, 64, 128):
            small = icon.resize((px, px), Image.LANCZOS); sheet.alpha_composite(small, (x, 8)); x += px + 12
        sheet.save(os.path.join(tmp, "sheet.png")); print(os.path.join(tmp, "sheet.png"))
    print("wrote mac/AppIcon.icns, mac/icon-preview.png and the web icons")


if __name__ == "__main__":
    sys.exit(main())
