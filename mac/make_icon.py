#!/usr/bin/env python3
"""Draws the Glowtrack app icon and writes every size it is needed at: the Mac app icon (.icns) and the
web icons (home-screen, installable-app, maskable, favicon .ico/.png/.svg).

    /usr/bin/python3 mac/make_icon.py

Two floor lamps, seven glowing zones each, colours flowing from crimson through orange and amber to warm
white, standing on a dark warm surface. Needs Pillow; the .icns is made with macOS's iconutil.
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


FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><linearGradient id="g" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#D62839"/><stop offset=".25" stop-color="#FF7A30"/><stop offset=".5" stop-color="#FFA82E"/><stop offset=".75" stop-color="#FFE296"/><stop offset="1" stop-color="#FFF4D6"/></linearGradient><radialGradient id="p"><stop offset="0" stop-color="#FF4F34" stop-opacity=".55"/><stop offset="1" stop-color="#FF4F34" stop-opacity="0"/></radialGradient></defs><rect width="64" height="64" rx="14" fill="#17110F"/><ellipse cx="22" cy="50" rx="14" ry="6" fill="url(#p)"/><ellipse cx="42" cy="50" rx="14" ry="6" fill="url(#p)"/><rect x="17.5" y="9" width="9" height="40" rx="4.5" fill="url(#g)"/><rect x="37.5" y="9" width="9" height="40" rx="4.5" fill="url(#g)"/></svg>
"""


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


def lamp_tube(size, cx, top, seg_w, height):
    """One lamp: a slim rounded column of light whose colour flows smoothly bottom to top."""
    tube = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(tube)
    for y in range(int(top), int(top + height) + 1):
        t = 1 - (y - top) / height                      # 0 at the bottom, 1 at the top
        pos = t * (len(FLOW) - 1)
        i = min(len(FLOW) - 2, int(pos)); f = pos - i
        c = tuple(int(FLOW[i][k] + (FLOW[i + 1][k] - FLOW[i][k]) * f) for k in range(3))
        d.line([(cx - seg_w / 2, y), (cx + seg_w / 2, y)], fill=c + (255,))
    hl = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(hl).rounded_rectangle([cx - seg_w * 0.30, top + seg_w * 0.4, cx - seg_w * 0.12, top + height - seg_w * 0.4], radius=seg_w * 0.09, fill=(255, 255, 255, 80))
    tube.alpha_composite(hl)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([cx - seg_w / 2, top, cx + seg_w / 2, top + height], radius=seg_w / 2, fill=255)
    tube.putalpha(ImageChops.multiply(tube.split()[3], mask))
    return tube


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

    cx_l, cx_r = S * 0.37, S * 0.63
    seg_w, height = S * 0.078, S * 0.60
    top = S * 0.165
    floor_y = top + height
    lamps = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    for cx in (cx_l, cx_r):
        lamps.alpha_composite(lamp_tube(S, cx, int(top), int(seg_w), int(height)))

    # light spilling onto the wall (wide and soft, then tight and bright), and onto the floor
    for radius, a in ((S * 0.2, 0.85), (S * 0.09, 0.8), (S * 0.035, 0.7)):
        g = lamps.filter(ImageFilter.GaussianBlur(radius))
        r_, g_, b_, al = g.split()
        canvas.alpha_composite(Image.merge("RGBA", (r_, g_, b_, al.point(lambda v, a=a: min(255, int(v * a * 2.3))))))
    pool = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    pd = ImageDraw.Draw(pool)
    for cx in (cx_l, cx_r):
        pd.ellipse([cx - S * 0.24, floor_y - S * 0.03, cx + S * 0.24, floor_y + S * 0.12], fill=FLOW[1] + (170,))
    canvas.alpha_composite(pool.filter(ImageFilter.GaussianBlur(S * 0.055)))
    bases = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bases)
    for cx in (cx_l, cx_r):                                  # base plates, the tubes stand in them
        bd.ellipse([cx - S * 0.1, floor_y - S * 0.026, cx + S * 0.1, floor_y + S * 0.03], fill=(74, 56, 48, 255))
        bd.ellipse([cx - S * 0.1, floor_y - S * 0.026, cx + S * 0.1, floor_y + S * 0.03], outline=(255, 190, 120, 120), width=5)
    canvas.alpha_composite(bases)
    canvas.alpha_composite(lamps)

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
