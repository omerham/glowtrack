"""Colour maths: album-art palette extraction, LED calibration and blending."""
import colorsys
import io
import math

from PIL import Image


def srgb_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

def rgb_to_oklab(r, g, b):
    lr = srgb_to_linear(r)
    lg = srgb_to_linear(g)
    lb = srgb_to_linear(b)
    l_ = max(0.0, 0.4122214708 * lr + 0.5363325363 * lg + 0.0514459929 * lb) ** (1.0 / 3.0)
    m_ = max(0.0, 0.2119034982 * lr + 0.6806995451 * lg + 0.1073969566 * lb) ** (1.0 / 3.0)
    s_ = max(0.0, 0.0883024619 * lr + 0.2817188376 * lg + 0.6299787005 * lb) ** (1.0 / 3.0)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b_val = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    chroma = math.sqrt(a * a + b_val * b_val)
    hue = (math.atan2(b_val, a) + 2 * math.pi) % (2 * math.pi)
    return L, a, b_val, chroma, hue

def calibrate_govee_gamut(r, g, b, vibrancy_mult=1.15):
    """
    Physical Govee LED phosphor calibration:
    - Dedicated White / Cream handling preserves clean, warm studio white for physical Govee LEDs
    - Dedicated pure red diode tuning suppresses green/blue leakage so red stays vivid crimson, never pink
    - Smart gamma lift prevents murky rooms while preserving pure album hues
    - Phosphor tuning gives deep 24K gold on amber and glowing neon violet on purple
    """
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    hue_deg = h * 360.0

    # 1. Dedicated White / Cream / Ivory Handling (Clean, warm, natural studio balance)
    if s <= 0.15 and v >= 0.85:
        return (
            max(0, min(255, int(round(r)))),
            max(0, min(250, int(round(g)))),
            max(0, min(240, int(round(b))))
        )

    # 2. Dedicated Pure Red / Crimson / Scarlet Calibration
    # On Govee white frosted diffuser tubes, ANY blue diode leakage (even B=8)
    # combines with high-energy 465nm photons to turn red into washed-out PINK.
    # When an album has true red (Hue in 320°-360° or 0°-22°, with S >= 0.55 and B < R * 0.58):
    # - Red diode is boosted to full brilliance (220-255)
    # - Green is clamped to at most 4% for warm scarlet, 0 for crimson
    # - Blue is locked to ABSOLUTELY ZERO (0) to eliminate all pink/magenta washout!
    # Only for colours that are actually red: bright enough to see as red.
    # (Without the brightness check a near-black shadow became vivid red.)
    is_true_red = ((hue_deg >= 320.0 or hue_deg <= 22.0) and r > g and (b < r * 0.58)
                   and s >= 0.55 and v >= 0.60)
    if is_true_red:
        r_cal = max(220, min(255, int(round(r * 1.30))))
        if hue_deg <= 15.0:
            g_cal = int(round(min(g * 0.08, 4)))
        else:
            g_cal = 0
        b_cal = 0  # Absolute zero blue ensures Govee LEDs emit pure 625nm crimson/fire red, never pink!
        return (r_cal, g_cal, b_cal)

    # 3. Natural Gamut Scaling for Other Hues (NO artificial saturation floor!)
    s_cal = min(1.0, s * vibrancy_mult)
    v_cal = min(1.0, v ** 0.85)

    br, bg, bb = colorsys.hsv_to_rgb(h, s_cal, v_cal)
    cr, cg, cb = br * 255.0, bg * 255.0, bb * 255.0

    # 4. Hardware Diode Phosphor Tuning
    if 25.0 <= hue_deg <= 42.0:
        # Amber/Gold: pull back green slightly to render deep 24K gold instead of yellow-green
        cg = cg * 0.84
        cr = min(255.0, cr * 1.05)
    elif 265.0 <= hue_deg <= 325.0:
        # Purple/Violet: boost red diode so it's glowing neon ultraviolet, not dull navy
        cr = min(255.0, cr * 1.20)
        cg = cg * 0.75

    return int(round(max(0, min(255, cr)))), int(round(max(0, min(255, cg)))), int(round(max(0, min(255, cb))))

def interpolate_color_rgb(c1, c2, t):
    """Clean linear RGB interpolation that strictly preserves the original pigment."""
    t = max(0.0, min(1.0, float(t)))
    e = t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
    return (
        int(round(c1[0] * (1.0 - e) + c2[0] * e)),
        int(round(c1[1] * (1.0 - e) + c2[1] * e)),
        int(round(c1[2] * (1.0 - e) + c2[2] * e))
    )

def build_7_zone_palette(palette, is_inverted=False):
    """Distributes the album's exact extracted palette across the 7 physical lamp zones."""
    if not palette:
        return [(29, 185, 84)] * 7

    pal = list(palette)
    if is_inverted:
        pal = list(reversed(pal))

    if len(pal) == 1:
        c_crown = pal[0]
        # Pure monochromatic ombre fade: deep 35% tone at base up to 100% radiant crown at top
        c_base = (int(c_crown[0] * 0.35), int(c_crown[1] * 0.35), int(c_crown[2] * 0.35))
        return [interpolate_color_rgb(c_base, c_crown, i / 6.0) for i in range(7)]

    if len(pal) == 2:
        c_crown = pal[0]
        c_base = pal[1]
        return [interpolate_color_rgb(c_base, c_crown, i / 6.0) for i in range(7)]

    # 3+ colors: multi-stop gradient from base (pal[-1]) up to crown (pal[0])
    stops = list(reversed(pal[:min(4, len(pal))]))
    n_stops = len(stops)
    zones = []
    for i in range(7):
        pos = (i / 6.0) * (n_stops - 1)
        idx = int(pos)
        t = pos - idx
        if idx >= n_stops - 1:
            zones.append(stops[-1])
        else:
            zones.append(interpolate_color_rgb(stops[idx], stops[idx + 1], t))
    return zones

CLASH_HOLD = 0.3   # share of a clashing step spent holding the real colour


def flow_gradient(pal):
    """The colour loop as gradient stops [(position 0..1, rgb), ...] - the same
    path sample_palette_continuous() follows. The dashboard animates this
    itself, so the server doesn't have to stream preview frames."""
    if not pal:
        return [(0.0, (29, 185, 84)), (1.0, (29, 185, 84))]
    if len(pal) == 1:
        return [(k / 8.0, sample_palette_continuous(pal, k / 8.0)) for k in range(9)]
    stops = flow_stops(pal)
    n = len(stops)
    out = []
    for i in range(n):
        a, b = stops[i], stops[(i + 1) % n]
        start = i / float(n)
        out.append((start, a))
        if colours_clash(a, b):
            out.append((start + CLASH_HOLD / n, a))
            for k in (0.25, 0.5, 0.75):            # perceptual midpoints
                u = k * k * (3.0 - 2.0 * k)
                out.append((start + (CLASH_HOLD + (1 - CLASH_HOLD) * k) / n, mix_oklab(a, b, u)))
    out.append((1.0, stops[0]))
    return out


def sample_palette_continuous(pal, offset):
    """
    Samples a continuous floating point position along a color palette using smooth
    cubic Hermite interpolation. Eliminates discrete jumps, mid-cycle color collapse,
    and color tearing across lamp zones.
    """
    if not pal:
        return (29, 185, 84)
    n = len(pal)
    if n == 1:
        c = pal[0]
        # For single color albums, create an elegant monochromatic ombre wave
        deep = (int(round(c[0] * 0.40)), int(round(c[1] * 0.40)), int(round(c[2] * 0.40)))
        w = (math.sin(offset * 2.0 * math.pi) + 1.0) / 2.0
        return (int(round(deep[0] + (c[0] - deep[0]) * w)),
                int(round(deep[1] + (c[1] - deep[1]) * w)),
                int(round(deep[2] + (c[2] - deep[2]) * w)))

    stops = flow_stops(pal)
    n = len(stops)
    val = (offset % 1.0) * n
    idx1 = int(val) % n
    idx2 = (idx1 + 1) % n
    t = val - int(val)
    a, b = stops[idx1], stops[idx2]
    if colours_clash(a, b):
        # No album colour fits between these two: hold each real colour a
        # little, then cross over perceptually so the muddy middle stays brief.
        if t < CLASH_HOLD:
            return a
        u = (t - CLASH_HOLD) / (1.0 - CLASH_HOLD)
        return mix_oklab(a, b, u * u * (3.0 - 2.0 * u))
    # Related colours: steady constant-speed blend (smooth motion)
    return (int(round(a[0] + (b[0] - a[0]) * t)),
            int(round(a[1] + (b[1] - a[1]) * t)),
            int(round(a[2] + (b[2] - a[2]) * t)))


# -------------------------------------------------------------------------
# Avoiding invented colours when blending
#
# Blending two very different colours (yellow -> blue, red -> green) on LEDs
# passes through a colour that isn't in the album at all (sage green, olive).
# So: order the album colours so related ones sit next to each other, route a
# clashing pair through another album colour that fits between them, and if
# none fits, only cross over briefly.
# -------------------------------------------------------------------------
def oklab_to_rgb(L, a, b):
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    lin = (4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_,
           -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_,
           -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_)

    def to_srgb(x):
        x = max(0.0, min(1.0, x))
        x = 12.92 * x if x <= 0.0031308 else 1.055 * (x ** (1 / 2.4)) - 0.055
        return int(round(max(0.0, min(1.0, x)) * 255))
    return tuple(to_srgb(x) for x in lin)


def mix_oklab(c1, c2, t):
    """Perceptual blend: keeps brightness even instead of dipping through mud."""
    L1, a1, b1, _, _ = rgb_to_oklab(*c1)
    L2, a2, b2, _, _ = rgb_to_oklab(*c2)
    return oklab_to_rgb(L1 + (L2 - L1) * t, a1 + (a2 - a1) * t, b1 + (b2 - b1) * t)


_CLASH_CACHE = {}


def colours_clash(c1, c2):
    """True when the halfway blend loses most of the colour (e.g. yellow/blue
    -> grey-green). Related colours (red/orange, blue/purple) never clash."""
    key = (tuple(c1), tuple(c2))
    hit = _CLASH_CACHE.get(key)
    if hit is not None:
        return hit
    ch1 = rgb_to_oklab(*c1)[3]
    ch2 = rgb_to_oklab(*c2)[3]
    weakest = min(ch1, ch2)
    result = False
    # White next to red/orange: on lights the blend is pink/peach, a colour
    # the album doesn't have - treat it as a clash so it crosses over quickly.
    L1, _, _, _, h1 = rgb_to_oklab(*c1)
    L2, _, _, _, h2 = rgb_to_oklab(*c2)
    for (Lw, chw), (chc, hc) in (((L1, ch1), (ch2, h2)), ((L2, ch2), (ch1, h1))):
        hue_deg = math.degrees(hc) % 360.0
        if chw < 0.04 and Lw > 0.75 and chc > 0.10 and (hue_deg < 75.0 or hue_deg > 330.0):
            result = True
    if not result and weakest > 0.05:     # otherwise greys/whites can't clash
        mid = tuple((c1[i] + c2[i]) / 2.0 for i in range(3))
        result = rgb_to_oklab(*mid)[3] < 0.65 * weakest
    if len(_CLASH_CACHE) > 4096:
        _CLASH_CACHE.clear()
    _CLASH_CACHE[key] = result
    return result


def _oklab_dist(c1, c2):
    L1, a1, b1, _, _ = rgb_to_oklab(*c1)
    L2, a2, b2, _, _ = rgb_to_oklab(*c2)
    return math.sqrt((L1 - L2) ** 2 + (a1 - a2) ** 2 + (b1 - b2) ** 2)


_STOPS_CACHE = {}


def flow_stops(pal):
    """The loop of colours the moving modes travel through. Uses only album
    colours; may visit one twice to bridge a clashing pair
    (purple, yellow, blue -> purple, yellow, purple, blue)."""
    key = tuple(tuple(c) for c in pal)
    hit = _STOPS_CACHE.get(key)
    if hit is not None:
        return hit
    cols = list(key)
    if len(cols) <= 2:
        stops = cols
    else:
        # Order the loop: fewest clashing neighbours, then shortest colour jumps.
        from itertools import permutations
        first, rest = cols[0], cols[1:]
        best, best_score = None, None
        for perm in permutations(rest):
            loop = [first] + list(perm)
            pairs = list(zip(loop, loop[1:] + loop[:1]))
            score = (sum(colours_clash(a, b) for a, b in pairs),
                     sum(_oklab_dist(a, b) for a, b in pairs))
            if best_score is None or score < best_score:
                best, best_score = loop, score
        # Bridge any remaining clash with an album colour that suits both sides
        stops = []
        for a, b in zip(best, best[1:] + best[:1]):
            stops.append(a)
            if colours_clash(a, b):
                bridges = [c for c in cols if c not in (a, b)
                           and not colours_clash(a, c) and not colours_clash(c, b)]
                if bridges:
                    stops.append(min(bridges, key=lambda c: _oklab_dist(a, c) + _oklab_dist(c, b)))
    if len(_STOPS_CACHE) > 256:
        _STOPS_CACHE.clear()
    _STOPS_CACHE[key] = stops
    return stops


def blend_colours(c1, c2, t):
    """Fade between two colours (song changes). Clashing pairs fade perceptually."""
    if colours_clash(c1, c2):
        t = max(0.0, min(1.0, float(t)))
        return mix_oklab(c1, c2, t * t * t * (t * (t * 6.0 - 15.0) + 10.0))
    return interpolate_color_rgb(c1, c2, t)

def get_dual_split_colors(palette):
    """
    Returns an authentic, high-contrast, harmonious dual color pair (Left, Right)
    from the album palette. If the album is monochromatic or only has 1 color,
    generates a complementary/analogous harmonic split so both lamps always display
    rich contrasting colors and NEVER turn to plain white diodes.
    """
    if not palette:
        c1, c2 = (29, 185, 84), (16, 120, 55)
        return c1, c2

    c1 = palette[0]
    c2 = None

    if len(palette) >= 2:
        # Check remaining palette colors for the best distinct chromatic pair
        for cand in palette[1:]:
            diff = math.sqrt((c1[0] - cand[0])**2 + (c1[1] - cand[1])**2 + (c1[2] - cand[2])**2)
            h, s, v = colorsys.rgb_to_hsv(cand[0]/255.0, cand[1]/255.0, cand[2]/255.0)
            if diff >= 38 and s >= 0.15:
                c2 = cand
                break

    if not c2:
        # Generate an aesthetically harmonic split (+40 degree hue rotation with vibrant saturation)
        h, s, v = colorsys.rgb_to_hsv(c1[0]/255.0, c1[1]/255.0, c1[2]/255.0)
        h2 = (h + 0.11) % 1.0  # +40 degrees in color wheel
        s2 = max(0.50, min(1.0, s * 1.05))
        v2 = max(0.55, min(1.0, v * 0.95))
        r2, g2, b2 = colorsys.hsv_to_rgb(h2, s2, v2)
        c2 = (int(round(r2 * 255)), int(round(g2 * 255)), int(round(b2 * 255)))

    return c1, c2

# -------------------------------------------------------------------------
# Spotify-Authentic Color Extraction (OKLab Perceptual Vibrancy Algorithm)
# -------------------------------------------------------------------------
def is_skin_tone(r, g, b):
    """
    Android Palette standard skin filter:
    Ignores human face skin tones, flash reflections on foreheads, peach/tan flesh
    so Spotify Solid illuminates with the album's authentic background theme color.
    """
    h, l, s = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
    hue_deg = h * 360.0
    if 8.0 <= hue_deg <= 42.0 and s <= 0.85 and l >= 0.30:
        if r > b and (r - b) > 20:
            return True
    if (hue_deg <= 10.0 or hue_deg >= 350.0) and 0.12 <= s <= 0.55 and 0.40 <= l <= 0.85:
        if r > g and r > b:
            return True
    return False

# Colour picking tuning
PICK_MIN_SHARE = 0.03      # a colour must cover at least 3% of the cover
PICK_AREA_WEIGHT = 0.85    # how much area counts vs. colourfulness (was 0.6)
PICK_DUP_DIST = 0.075      # colours closer than this (OKLab) count as the same


WHITE_ACCENT_MIN = 0.015  # white highlights covering 1.5%+ of the cover count as an accent


def extract_spotify_palette(image_bytes, max_colors=5, vibrancy_mult=1.15, white_accent=True):
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    scale = min(1.0, 160.0 / max(w, h))
    if scale < 1.0:
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.BILINEAR)

    pixels = list(img.getdata())
    total_pixels = len(pixels)

    # Step 1: Detect White / Cream canvas presence (e.g. Don Toliver, The Beatles, Drake)
    white_cream_pixels = []
    for r, g, b in pixels:
        h_hls, l_hls, s_hls = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
        if l_hls >= 0.70 and s_hls <= 0.38:
            white_cream_pixels.append((r, g, b, l_hls, s_hls))

    white_ratio = len(white_cream_pixels) / float(total_pixels) if total_pixels > 0 else 0.0

    # Step 2: Collect authentic thematic pixels.
    # Near-black shadow pixels are kept aside: they look "coloured" in the
    # maths (a slightly red shadow) but aren't a colour you'd see on the cover.
    # They're only used if the cover is genuinely dark all over.
    chromatic = []
    shadows = []
    for r, g, b in pixels:
        skin = is_skin_tone(r, g, b)
        h_hls, l_hls, s_hls = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
        if s_hls >= 0.10 and 0.10 <= l_hls <= 0.90:
            L, _, _, chroma, hue = rgb_to_oklab(r, g, b)
            if chroma >= 0.035:
                weight = 0.10 if skin else 1.0
                vib = (s_hls ** 1.8) * (chroma ** 1.5) * max(0.2, 1.0 - 0.45 * abs(l_hls - 0.50)) * weight
                item = (r, g, b, L, chroma, hue, vib, s_hls, l_hls, skin)
                if max(r, g, b) < 56:          # darker than ~22% brightness
                    shadows.append(item)
                else:
                    chromatic.append(item)
    if len(chromatic) < max(30, int(total_pixels * 0.03)):
        chromatic.extend(shadows)              # dark cover: its dark colours are the theme

    if not chromatic and white_ratio >= 0.06:
        white_cream_pixels.sort(key=lambda p: p[3], reverse=True)
        top_w = white_cream_pixels[:max(10, len(white_cream_pixels) // 3)]
        w_col = (int(sum(p[0] for p in top_w) / len(top_w)),
                 int(sum(p[1] for p in top_w) / len(top_w)),
                 int(sum(p[2] for p in top_w) / len(top_w)))
        return [w_col], [calibrate_govee_gamut(w_col[0], w_col[1], w_col[2])]

    if not chromatic:
        return [(240, 235, 230)], [calibrate_govee_gamut(240, 235, 230)]

    # Step 3: 36 Hue Bins (10° each)
    bins = {}
    for item in chromatic:
        b_idx = int((item[5] / (2 * math.pi)) * 36) % 36
        if b_idx not in bins:
            bins[b_idx] = []
        bins[b_idx].append(item)

    # A colour must fill a real part of the cover (not a tiny detail)
    min_cluster_size = max(8, int(total_pixels * PICK_MIN_SHARE))

    scored_clusters = []
    for b_idx in bins:
        # Include the neighbouring 10-degree slices, so a colour spread across
        # nearby shades (e.g. palm-tree greens) still counts as one real colour.
        # Near-identical results from neighbouring slices are merged below.
        pxs = bins[b_idx] + bins.get((b_idx - 1) % 36, []) + bins.get((b_idx + 1) % 36, [])
        if len(pxs) < min_cluster_size or len(bins[b_idx]) < len(pxs) * 0.25:
            continue
        pxs.sort(key=lambda p: p[6], reverse=True)
        top = pxs[:max(5, len(pxs) // 4)]
        avg_r = int(sum(p[0] for p in top) / len(top))
        avg_g = int(sum(p[1] for p in top) / len(top))
        avg_b = int(sum(p[2] for p in top) / len(top))

        L_c, _, _, chroma_c, hue_c = rgb_to_oklab(avg_r, avg_g, avg_b)
        _, l_c, s_c = colorsys.rgb_to_hls(avg_r / 255.0, avg_g / 255.0, avg_b / 255.0)

        skin_ratio = sum(1 for p in pxs if p[9]) / float(len(pxs))
        skin_penalty = 0.10 if skin_ratio > 0.45 else 1.0

        # Spotify Background / Theme Score:
        # Balanced population weight + rich saturation:
        pop_weight = (len(pxs) ** PICK_AREA_WEIGHT)   # bigger areas matter more
        # Rank by area and real colourfulness (OKLab chroma). HLS saturation was
        # used before, but it rates dark muddy colours as "saturated".
        # Darker colours count a bit less - they're mostly shadow tones.
        light_factor = max(0.25, min(1.0, (L_c - 0.15) / 0.35))
        score = pop_weight * (chroma_c ** 1.3) * light_factor * skin_penalty

        scored_clusters.append((score, (avg_r, avg_g, avg_b), chroma_c, L_c, hue_c, len(pxs)))

    scored_clusters.sort(key=lambda x: x[0], reverse=True)

    # Step 4: Include White/Cream ONLY if there are no chromatic clusters (monochrome/greyscale canvas)
    if not scored_clusters and white_ratio >= 0.06:
        white_cream_pixels.sort(key=lambda p: p[3], reverse=True)
        top_w = white_cream_pixels[:max(10, len(white_cream_pixels) // 3)]
        w_r = int(sum(p[0] for p in top_w) / len(top_w))
        w_g = int(sum(p[1] for p in top_w) / len(top_w))
        w_b = int(sum(p[2] for p in top_w) / len(top_w))
        w_L, _, _, w_chroma, w_hue = rgb_to_oklab(w_r, w_g, w_b)
        scored_clusters.append((1.0, (w_r, w_g, w_b), w_chroma, w_L, w_hue, len(white_cream_pixels)))

    raw_pal = []
    for score, rgb, chroma, L, hue, cnt in scored_clusters:
        is_dup = False
        for p_rgb in raw_pal:
            _, _, _, p_chroma, phue = rgb_to_oklab(p_rgb[0], p_rgb[1], p_rgb[2])
            hue_diff = abs((hue - phue + math.pi) % (2 * math.pi) - math.pi) / math.pi
            rgb_diff = math.sqrt((rgb[0] - p_rgb[0]) ** 2 + (rgb[1] - p_rgb[1]) ** 2 + (rgb[2] - p_rgb[2]) ** 2)
            if chroma >= 0.05 and p_chroma >= 0.05 and hue_diff < 0.10:
                is_dup = True
                break
            # Same colour if close AND similar hue (two dark colours can be close
            # in brightness but still clearly different, e.g. olive vs green)
            same_hue = hue_diff < 30.0 / 180.0 or chroma < 0.04 or p_chroma < 0.04
            if same_hue and (rgb_diff < 42 or _oklab_dist(rgb, p_rgb) < PICK_DUP_DIST):
                is_dup = True
                break
        if not is_dup:
            raw_pal.append(rgb)
            if len(raw_pal) >= max_colors:
                break

    if not raw_pal:
        chromatic.sort(key=lambda p: p[6], reverse=True)
        top = chromatic[:max(5, len(chromatic) // 10)]
        raw_pal = [(int(sum(p[0] for p in top)/len(top)), int(sum(p[1] for p in top)/len(top)), int(sum(p[2] for p in top)/len(top)))]

    # Step 5: Big white / cream areas are part of the look too (record sleeves,
    # white backgrounds). If at least a fifth of the cover is white, include it.
    # It goes second, after the main colour - or first if the cover is mostly white.
    if white_ratio >= 0.20 and white_cream_pixels and not any(
            min(c) >= 200 and max(c) - min(c) <= 40 for c in raw_pal):
        whites = sorted(white_cream_pixels, key=lambda p: p[3], reverse=True)
        top_w = whites[:max(10, len(whites) // 2)]
        white = (int(sum(p[0] for p in top_w) / len(top_w)),
                 int(sum(p[1] for p in top_w) / len(top_w)),
                 int(sum(p[2] for p in top_w) / len(top_w)))
        chromatic_ratio = len(chromatic) / float(total_pixels) if total_pixels else 0.0
        pos = 0 if white_ratio >= 0.5 and white_ratio > 2 * chromatic_ratio else min(1, len(raw_pal))
        raw_pal.insert(pos, white)
        raw_pal = raw_pal[:max_colors]
    elif white_accent and white_cream_pixels and white_ratio >= WHITE_ACCENT_MIN and not any(
            min(c) >= 190 and max(c) - min(c) <= 45 for c in raw_pal):
        # Smaller white highlights (smoke, text, a white shirt) become an accent:
        # added last, so the album's main colours still lead.
        whites = sorted(white_cream_pixels, key=lambda p: p[3], reverse=True)
        top_w = whites[:max(5, len(whites) // 2)]
        white = (int(sum(p[0] for p in top_w) / len(top_w)),
                 int(sum(p[1] for p in top_w) / len(top_w)),
                 int(sum(p[2] for p in top_w) / len(top_w)))
        if len(raw_pal) >= max_colors:
            raw_pal[-1] = white
        else:
            raw_pal.append(white)

    lamp_pal = [calibrate_govee_gamut(r, g, b, vibrancy_mult=vibrancy_mult) for r, g, b in raw_pal]
    return raw_pal[:max_colors], lamp_pal[:max_colors]


def led_lift(c, boost):
    """Govee LEDs can't show dark colours (they look dim or switch off).
    Raises a colour's brightest channel to at least `boost` (0..1 of full)
    while keeping the hue and saturation. Pure black (off) stays off."""
    if boost <= 0:
        return c
    m = max(c)
    if m <= 0:
        return c
    floor = 255.0 * boost
    if m >= floor:
        return c
    # Cap how much a nearly-black colour is magnified, so tiny differences in
    # very dark blends can't become big jumps on the lamps.
    k = min(floor / m, 5.0)
    return (min(255, int(round(c[0] * k))), min(255, int(round(c[1] * k))), min(255, int(round(c[2] * k))))


def led_red_correct(c):
    """On Govee LEDs even a little blue mixed into red reads as pink, much more
    than on a screen. For red-to-raspberry hues (about 310-360 degrees, strongest
    near pure red) blue is pulled down so they look red on the lamps. Purples
    and true magentas (below ~310 degrees) are left alone."""
    r, g, b = c
    if r <= 0 or b <= 0 or r < b:
        return c
    h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    hue = h * 360.0
    if s < 0.2 or 25.0 <= hue < 310.0:
        return c
    # Strength fades in smoothly with hue and saturation on BOTH sides of pure
    # red - any hard cut-off makes colours snap during blends.
    if hue >= 310.0:
        t = min(1.0, (hue - 310.0) / 40.0)      # 0 at 310 deg -> 1 at 350+ deg (gentle ramp)
    else:
        t = max(0.0, min(1.0, (25.0 - hue) / 25.0))   # 1 at 0 deg -> 0 at 25 deg
    t = t * t * (3.0 - 2.0 * t)
    w = min(1.0, (s - 0.2) / 0.35)              # 0 at saturation 0.2, 1 at 0.55+
    w = w * w * (3.0 - 2.0 * w)
    keep = 1.0 - 0.8 * t * w                    # keep all blue at the edges, 20% for clear reds
    return (r, g, int(round(b * keep)))


def led_finish(c, boost):
    """Final touch before a colour goes to the lamps: dark boost, then red fix."""
    return led_red_correct(led_lift(c, boost))


def lift_frame(frame, boost):
    return ([led_finish(c, boost) for c in frame[0]], [led_finish(c, boost) for c in frame[1]])
