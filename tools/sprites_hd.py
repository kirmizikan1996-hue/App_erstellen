#!/usr/bin/env python3
"""Hochaufgeloeste Sprites (128 px+) mit Lichtfuehrung.

Warum das Modul: Unsere Sprites waren 64 px, professionelle Tilesets liegen
bei 140-160 px pro Baum und ~400 px pro Haus — das ist die 5- bis 6-fache
Pixelflaeche. Auf 64x64 passt schlicht keine Rindenstruktur, kein
Wurzelanlauf und keine funf Gruenstufen.

Die vier Techniken, an denen der Qualitaetsunterschied haengt:

  1. FUENF bis SECHS Wertstufen statt drei. Das erzeugt Volumen.
  2. EINE Lichtrichtung fuer alles (hier oben links), inklusive
     Schlagschatten nach unten rechts. Uneinheitliches Licht laesst eine
     Szene sofort zusammengewuerfelt wirken.
  3. AUFGEBROCHENE SILHOUETTE: Blattdupfen auf der Kontur. Eine glatte
     Kante liest sich als Blob, eine ausgefranste als Laub.
  4. DUNKLE AUSSENKANTE, die die Form zusammenbindet.

Alle Funktionen bekommen eine Palette uebergeben, damit Gras-, Feuer- und
Eiszone dieselben Formen mit eigenen Farben nutzen koennen.
"""
import numpy as np

LIGHT = (-0.34, -0.34)      # Lichtrichtung, normiert auf den Blobradius


def canvas_px(w, h):
    return np.zeros((h, w, 4), dtype=float)


def grid_of(img):
    return np.mgrid[0:img.shape[0], 0:img.shape[1]].astype(float)


def paint(img, mask, color, alpha=255):
    img[..., :3][mask] = color
    img[..., 3][mask] = alpha


def cast_shadow(img, cy, cx, ry, rx, color=(46, 58, 40), alpha=112):
    """Schlagschatten. Immer nach unten rechts — konsistent zur Lichtquelle."""
    yy, xx = grid_of(img)
    m = ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2 < 1
    img[..., :3][m] = color
    img[..., 3][m] = np.maximum(img[..., 3][m], alpha)


def lit_blob(img, cy, cx, r, ramp):
    """Kugelig schattierter Ballen: Licht oben links, Kern unten rechts.

    ramp ist eine Liste von Farben von DUNKEL nach HELL.
    """
    yy, xx = grid_of(img)
    m = ((yy - cy) ** 2 + (xx - cx) ** 2) < r * r
    if not m.any():
        return m
    d = np.hypot(yy - (cy + LIGHT[0] * r), xx - (cx + LIGHT[1] * r)) / r
    paint(img, m, ramp[0])
    steps = [(1.25, 1), (0.95, 2), (0.66, 3), (0.38, 4)]
    for lim, idx in steps:
        if idx < len(ramp):
            paint(img, m & (d < lim), ramp[idx])
    if len(ramp) > 5:
        paint(img, m & (d < 0.18), ramp[5])
    return m


def outline(img, mask, color):
    """Dunkle Aussenkante — bindet die Silhouette zusammen."""
    er = (np.roll(mask, 1, 0) & np.roll(mask, -1, 0)
          & np.roll(mask, 1, 1) & np.roll(mask, -1, 1))
    paint(img, mask & ~er, color)


def edge_dabs(img, mask, dark, light, rng, n=140, rmin=1.4, rmax=3.4):
    """Blattdupfen auf der Kontur: bricht die glatte Kante auf."""
    yy, xx = grid_of(img)
    er = (np.roll(mask, 1, 0) & np.roll(mask, -1, 0)
          & np.roll(mask, 1, 1) & np.roll(mask, -1, 1))
    ys, xs = np.where(mask & ~er)
    if len(ys) == 0:
        return
    H, W = mask.shape
    for i in rng.choice(len(ys), size=min(n, len(ys)), replace=False):
        py, px = float(ys[i]), float(xs[i])
        rr = rng.uniform(rmin, rmax)
        m = ((yy - py) ** 2 + (xx - px) ** 2) < rr * rr
        lit = (py < H * 0.42) and (px < W * 0.58)
        paint(img, m, light if lit else dark)


def speckle(img, mask, color, rng, n=40):
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return
    for i in rng.choice(len(ys), size=min(n, len(ys)), replace=False):
        img[ys[i], xs[i], :3] = color


# ------------------------------------------------------------------ Baum ----

def hd_tree(S, leaf, bark, rng, shadow_col=(46, 58, 40), blobs=16):
    """Laubbaum mit Wurzelanlauf, Rindenstruktur und Kronenvolumen.

    leaf: 6 Gruentoene dunkel -> hell.  bark: 4 Brauntoene dunkel -> hell.
    """
    img = canvas_px(S, S)
    yy, xx = grid_of(img)
    cast_shadow(img, S * 0.885, S * 0.545, S * 0.055, S * 0.29, shadow_col)

    # Stamm: unten breiter (Wurzelanlauf), links Licht, rechts Kernschatten
    ty0, ty1 = S * 0.55, S * 0.91
    flare = np.clip((yy - ty0) / (ty1 - ty0), 0, 1) ** 2.3
    half = S * 0.042 + flare * S * 0.080
    trunk = (yy > ty0) & (yy < ty1) & (np.abs(xx - S * 0.5) < half)
    paint(img, trunk, bark[1])
    t = (xx - (S * 0.5 - half)) / (2 * half + 1e-6)
    paint(img, trunk & (t < 0.32), bark[2])
    paint(img, trunk & (t < 0.15), bark[3])
    paint(img, trunk & (t > 0.74), bark[0])
    for _ in range(int(S * 0.22)):                   # Rindenrisse
        y = rng.uniform(ty0, ty1)
        x = S * 0.5 + rng.normal(0, S * 0.035)
        h = rng.uniform(S * 0.03, S * 0.10)
        paint(img, trunk & (np.abs(xx - x) < 1) & (yy > y) & (yy < y + h),
              bark[0])

    # Krone
    cl = []
    for _ in range(blobs):
        a = rng.uniform(0, 2 * np.pi)
        d = rng.uniform(0, S * 0.205)
        cl.append((S * 0.335 + np.sin(a) * d * 0.78,
                   S * 0.500 + np.cos(a) * d,
                   rng.uniform(S * 0.110, S * 0.190)))
    canopy = np.zeros(img.shape[:2], bool)
    for cy, cx, r in cl:
        canopy |= ((yy - cy) ** 2 + (xx - cx) ** 2) < r * r
    paint(img, canopy, leaf[1])
    for cy, cx, r in sorted(cl, key=lambda b: b[0]):
        lit_blob(img, cy, cx, r, leaf)
    low = canopy & (yy > S * 0.45)                   # Kernschatten unten
    img[..., :3][low] = img[..., :3][low] * 0.76

    # Blattbuescheln IM Kroneninneren. Ohne diesen Durchgang bleiben die
    # kugelig schattierten Ballen als saubere Kreise sichtbar und die Krone
    # sieht aus wie ein Haufen Murmeln statt wie Laub.
    ys, xs = np.where(canopy)
    for i in rng.choice(len(ys), size=int(S * 3.0), replace=True):
        py, px = float(ys[i]), float(xs[i])
        rr = rng.uniform(S * 0.014, S * 0.036)
        m = ((yy - py) ** 2 + (xx - px) ** 2) < rr * rr
        base = img[int(py), int(px), :3]
        up = rng.random() < 0.5
        tone = np.clip(base * (1.16 if up else 0.87), 0, 255)
        img[..., :3][m & canopy] = tone

    edge_dabs(img, canopy, leaf[1], leaf[4], rng, n=int(S * 1.2))
    mask = img[..., 3] > 0
    outline(img, mask & (yy < ty0 + 2), leaf[0])
    speckle(img, canopy & (yy < S * 0.36) & (xx < S * 0.66), leaf[5], rng,
            n=int(S * 0.35))
    return np.clip(img, 0, 255)


def hd_conifer(W, H, needle, bark, rng, shadow_col=(46, 58, 40), tiers=5,
               snow=None):
    """Nadelbaum: gestaffelte Kranzlagen, jede mit eigener Lichtkante.

    snow: Farbe fuer die Schneeauflage auf den Zweigenden. Damit wird aus
    derselben Form die Wintertanne.
    """
    img = canvas_px(W, H)
    yy, xx = grid_of(img)
    cast_shadow(img, H * 0.925, W * 0.55, H * 0.038, W * 0.30, shadow_col)
    paint(img, (yy > H * 0.80) & (yy < H * 0.95)
          & (np.abs(xx - W * 0.5) < W * 0.055), bark[1])
    paint(img, (yy > H * 0.80) & (yy < H * 0.95)
          & (np.abs(xx - W * 0.5) < W * 0.02), bark[2])
    top, bot = H * 0.06, H * 0.84
    for k in range(tiers):
        f0 = k / tiers
        f1 = (k + 1.35) / tiers
        ty = top + (bot - top) * f1
        tw = W * (0.13 + 0.36 * f1)
        tri = (yy <= ty) & (yy > top + (bot - top) * f0) & \
              (np.abs(xx - W * 0.5) < tw * (yy - top - (bot - top) * f0)
               / max(1e-6, (bot - top) * (f1 - f0)))
        paint(img, tri, needle[1])
        paint(img, tri & (xx < W * 0.5 - tw * 0.10), needle[2])
        paint(img, tri & (xx < W * 0.5 - tw * 0.28), needle[3])
        paint(img, tri & (yy > ty - H * 0.035), needle[0])
        lip = tri & ~np.roll(tri, 1, 0)
        paint(img, lip, snow if snow else needle[4])
        if snow:                                     # Schnee liegt auf
            paint(img, np.roll(lip, 1, 0) & tri, snow)
            for _ in range(int(W * 0.5)):            # Schneehaeufchen
                px = int(rng.uniform(W * 0.5 - tw, W * 0.5 + tw))
                py = int(ty - rng.uniform(0, H * 0.02))
                if 0 <= px < W and 0 <= py < H and tri[py, px]:
                    rr = rng.uniform(1.0, 2.4)
                    m = ((yy - py) ** 2 + (xx - px) ** 2) < rr * rr
                    paint(img, m & tri, snow)
        for _ in range(int(W * 0.30)):               # Zweigspitzen
            a = rng.uniform(-1, 1)
            px = int(W * 0.5 + a * tw * 1.02)
            py = int(ty - rng.uniform(0, H * 0.03))
            if 0 <= px < W and 0 <= py < H:
                rr = rng.uniform(1.2, 2.6)
                m = ((yy - py) ** 2 + (xx - px) ** 2) < rr * rr
                paint(img, m, needle[3] if a < 0 else needle[0])
    outline(img, img[..., 3] > 0, needle[0])
    return np.clip(img, 0, 255)


def hd_boulder(S, stone, rng, shadow_col=(46, 58, 40), caps=None):
    """Findling aus mehreren Facetten statt einer glatten Ellipse."""
    img = canvas_px(S, S)
    yy, xx = grid_of(img)
    cast_shadow(img, S * 0.80, S * 0.56, S * 0.10, S * 0.40, shadow_col)
    body = np.zeros(img.shape[:2], bool)
    parts = []
    for _ in range(4):
        cy = S * rng.uniform(0.46, 0.62)
        cx = S * rng.uniform(0.35, 0.66)
        ry = S * rng.uniform(0.16, 0.24)
        rx = S * rng.uniform(0.20, 0.30)
        parts.append((cy, cx, ry, rx))
        body |= ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2 < 1
    paint(img, body, stone[1])
    for cy, cx, ry, rx in parts:
        m = ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2 < 1
        d = np.hypot((yy - (cy - ry * 0.36)) / ry, (xx - (cx - rx * 0.36)) / rx)
        paint(img, m & (d < 1.15), stone[2])
        paint(img, m & (d < 0.70), stone[3])
    paint(img, body & (yy > S * 0.66), stone[0])
    speckle(img, body, stone[3], rng, n=int(S * 0.5))
    speckle(img, body, stone[0], rng, n=int(S * 0.4))
    outline(img, body, stone[0])
    if caps is not None:                             # Schnee-/Moosauflage
        up = body & ~np.roll(body, 1, 0)
        paint(img, up, caps)
        paint(img, np.roll(up, 1, 0) & body, caps)
    return np.clip(img, 0, 255)


def hd_dead_tree(S, bark, rng, shadow_col=(46, 58, 40), glow=None, snow=None):
    """Kahler Baum: dicker Stamm, verzweigte Aeste, kein Laub.

    glow: Farbe fuer Glut in den Rindenrissen (Feuerzone).
    snow: Farbe fuer Schneeauflage auf den Astoberseiten (Eiszone).
    """
    img = canvas_px(S, S)
    yy, xx = grid_of(img)
    cast_shadow(img, S * 0.90, S * 0.55, S * 0.045, S * 0.26, shadow_col)

    ty0, ty1 = S * 0.40, S * 0.92
    flare = np.clip((yy - ty0) / (ty1 - ty0), 0, 1) ** 2.4
    half = S * 0.035 + flare * S * 0.085
    trunk = (yy > ty0) & (yy < ty1) & (np.abs(xx - S * 0.5) < half)
    paint(img, trunk, bark[1])
    t = (xx - (S * 0.5 - half)) / (2 * half + 1e-6)
    paint(img, trunk & (t < 0.30), bark[2])
    paint(img, trunk & (t < 0.13), bark[3])
    paint(img, trunk & (t > 0.76), bark[0])

    def limb(x0, y0, ang, ln, w, depth):
        """Ast samt Verzweigungen, nach oben duenner werdend."""
        pts = []
        x, y, a = x0, y0, ang
        for i in range(int(ln)):
            a += rng.normal(0, 0.055)
            x += np.cos(a)
            y += np.sin(a)
            ww = max(0.8, w * (1 - i / ln))
            m = ((yy - y) ** 2 + (xx - x) ** 2) < ww * ww
            paint(img, m, bark[1])
            paint(img, m & (xx < x), bark[2])
            pts.append((x, y, a, ww))
        if depth > 0:
            for _ in range(rng.integers(1, 3)):
                px, py, pa, pw = pts[int(len(pts) * rng.uniform(0.35, 0.8))]
                limb(px, py, pa + rng.choice([-1, 1]) * rng.uniform(0.4, 0.8),
                     ln * rng.uniform(0.42, 0.62), pw * 0.72, depth - 1)

    for k in range(6):
        a = -np.pi / 2 + (k - 2.5) * 0.30 + rng.normal(0, 0.10)
        limb(S * 0.5 + rng.normal(0, S * 0.02),
             ty0 + rng.uniform(0, S * 0.10), a,
             S * rng.uniform(0.20, 0.30), S * 0.028, 2)

    mask = img[..., 3] > 0
    for _ in range(int(S * 0.30)):                    # Rindenrisse
        y = rng.uniform(ty0, ty1)
        x = S * 0.5 + rng.normal(0, S * 0.03)
        h = rng.uniform(S * 0.03, S * 0.09)
        m = trunk & (np.abs(xx - x) < 1) & (yy > y) & (yy < y + h)
        paint(img, m, glow if (glow and rng.random() < 0.45) else bark[0])
    if snow:
        up = mask & ~np.roll(mask, 1, 0)
        paint(img, up, snow)
    outline(img, mask, bark[0])
    return np.clip(img, 0, 255)


def hd_tower(W, H, stone, rng, fire=None, shadow_col=(46, 58, 40), snow=None):
    """Wachturm: Steinschaft mit Lagen, Zinnenkranz, Feuer oben."""
    img = canvas_px(W, H)
    yy, xx = grid_of(img)
    cast_shadow(img, H * 0.955, W * 0.56, H * 0.030, W * 0.42, shadow_col)

    base = (yy > H * 0.78) & (yy < H * 0.96) & (np.abs(xx - W * 0.5) < W * 0.42)
    paint(img, base, stone[1])
    paint(img, base & (xx < W * 0.5), stone[2])
    paint(img, base & (yy > H * 0.92), stone[0])

    shaft = (yy > H * 0.24) & (yy <= H * 0.80) & (np.abs(xx - W * 0.5) < W * 0.30)
    paint(img, shaft, stone[1])
    paint(img, shaft & (xx < W * 0.5 - W * 0.06), stone[2])
    paint(img, shaft & (xx < W * 0.5 - W * 0.17), stone[3])
    paint(img, shaft & (xx > W * 0.5 + W * 0.19), stone[0])
    for y in np.arange(H * 0.26, H * 0.80, H * 0.055):   # Steinlagen
        paint(img, shaft & (np.abs(yy - y) < 1), stone[0])
        for k in range(5):                                # Fugen versetzt
            x = W * 0.20 + k * W * 0.15 + (W * 0.075 if int(y) % 2 else 0)
            paint(img, shaft & (np.abs(yy - y - H * 0.027) < H * 0.026)
                  & (np.abs(xx - x) < 1), stone[0])

    crown = (yy > H * 0.14) & (yy <= H * 0.26) & (np.abs(xx - W * 0.5) < W * 0.40)
    paint(img, crown, stone[2])
    paint(img, crown & (xx > W * 0.5 + W * 0.24), stone[0])
    for k in range(5):                                    # Zinnen
        x = W * 0.5 + (k - 2) * W * 0.17
        m = (yy > H * 0.06) & (yy <= H * 0.16) & (np.abs(xx - x) < W * 0.065)
        paint(img, m, stone[2])
        paint(img, m & (xx < x), stone[3])

    paint(img, (yy > H * 0.58) & (yy < H * 0.80)
          & (np.abs(xx - W * 0.5) < W * 0.09), stone[0])   # Tuer
    for y in (H * 0.36, H * 0.48):                         # Sehschlitze
        paint(img, (np.abs(yy - y) < H * 0.030)
              & (np.abs(xx - W * 0.5) < W * 0.035), stone[0])
        if fire:
            paint(img, (np.abs(yy - y) < H * 0.020)
                  & (np.abs(xx - W * 0.5) < W * 0.022), fire[0])
    if fire:                                               # Feuerkorb oben
        f = (((yy - H * 0.075) / (H * 0.055)) ** 2
             + ((xx - W * 0.5) / (W * 0.13)) ** 2) < 1
        paint(img, f, fire[0])
        paint(img, (((yy - H * 0.055) / (H * 0.032)) ** 2
                    + ((xx - W * 0.5) / (W * 0.075)) ** 2) < 1, fire[1])
    if snow:
        mask = img[..., 3] > 0
        paint(img, mask & ~np.roll(mask, 1, 0), snow)
    outline(img, img[..., 3] > 0, stone[0])
    return np.clip(img, 0, 255)


# ------------------------------------------------------------------ Haus ----

def hd_house(W, H, pal, rng, shingle_rows=11):
    """Haus in leichter 3/4-Ansicht: Dach UND Vorderwand sichtbar.

    Reine Draufsicht wirkt flach; erst die sichtbare Wand gibt dem Gebaeude
    Hoehe. pal braucht: wall, wall_lt, wall_dk, beam, roof, roof_lt,
    roof_dk, ridge, stone, stone_lt, glass, glow, door, ground_shadow.
    """
    img = canvas_px(W, H)
    yy, xx = grid_of(img)
    cast_shadow(img, H - H * 0.045, W * 0.54, H * 0.045, W * 0.46,
                pal["ground_shadow"])

    roof_y0, roof_y1 = int(H * 0.04), int(H * 0.56)
    wall_y1 = int(H * 0.90)
    sock_y0 = int(H * 0.82)

    # --- Wand ---------------------------------------------------------------
    wall = (yy >= roof_y1) & (yy < wall_y1) & (xx >= W * 0.07) & (xx < W * 0.93)
    paint(img, wall, pal["wall"])
    for x in range(int(W * 0.07), int(W * 0.93), max(3, int(W * 0.055))):
        paint(img, wall & (np.abs(xx - x) < 1), pal["wall_dk"])
        paint(img, wall & (np.abs(xx - x - 1.5) < 1), pal["wall_lt"])
    paint(img, wall & (yy < roof_y1 + H * 0.045), pal["wall_dk"])   # Traufschatten
    paint(img, wall & (xx > W * 0.83), pal["wall_dk"])              # Schattenseite

    # --- Sockel aus Bruchstein ---------------------------------------------
    sock = (yy >= sock_y0) & (yy < wall_y1) & (xx >= W * 0.06) & (xx < W * 0.94)
    paint(img, sock, pal["stone"])
    for _ in range(int(W * 0.5)):
        sx = rng.uniform(W * 0.07, W * 0.93)
        sy = rng.uniform(sock_y0 + 1, wall_y1 - 2)
        rx, ry = rng.uniform(W * 0.012, W * 0.030), rng.uniform(2, 4)
        m = ((yy - sy) / ry) ** 2 + ((xx - sx) / rx) ** 2 < 1
        paint(img, m & sock, pal["stone_lt"] if sy < sock_y0 + 4 else pal["stone"])
        paint(img, m & sock & (yy > sy + ry * 0.4), pal["wall_dk"])

    # --- Dach mit einzelnen Schindelreihen ---------------------------------
    roof = (yy >= roof_y0) & (yy < roof_y1) & (xx >= W * 0.02) & (xx < W * 0.98)
    paint(img, roof, pal["roof"])
    step = max(4, (roof_y1 - roof_y0) // shingle_rows)
    for i, y in enumerate(range(roof_y0 + step, roof_y1 + 1, step)):
        row = roof & (yy >= y - step) & (yy < y)
        paint(img, row, pal["roof_lt"] if i % 2 == 0 else pal["roof"])
        paint(img, roof & (np.abs(yy - y) < 1), pal["roof_dk"])   # Reihenfuge
        off = (i % 2) * (W * 0.030)
        for x in np.arange(W * 0.02 + off, W * 0.98, W * 0.060):
            paint(img, row & (np.abs(xx - x) < 1), pal["roof_dk"])
    paint(img, roof & (xx > W * 0.86), pal["roof_dk"])            # Schattenseite
    paint(img, (yy >= roof_y0) & (yy < roof_y0 + max(3, int(H * 0.025)))
          & (xx >= W * 0.02) & (xx < W * 0.98), pal["ridge"])     # First
    paint(img, (yy >= roof_y1 - 2) & (yy < roof_y1)
          & (xx >= W * 0.02) & (xx < W * 0.98), pal["roof_dk"])   # Traufkante

    # --- Schornstein --------------------------------------------------------
    cxs, cxe = W * 0.70, W * 0.80
    ch = (yy < roof_y0 + H * 0.10) & (xx >= cxs) & (xx < cxe)
    paint(img, ch, pal["stone"])
    paint(img, ch & (xx < cxs + W * 0.030), pal["stone_lt"])
    paint(img, (yy < roof_y0 + H * 0.020) & (xx >= cxs - W * 0.015)
          & (xx < cxe + W * 0.015), pal["stone_lt"])

    # --- Tuer ---------------------------------------------------------------
    dx0, dx1 = W * 0.44, W * 0.57
    door = (yy >= roof_y1 + H * 0.10) & (yy < sock_y0 + 2) & \
           (xx >= dx0) & (xx < dx1)
    paint(img, door, pal["door"])
    for x in np.arange(dx0, dx1, W * 0.022):
        paint(img, door & (np.abs(xx - x) < 1), pal["wall_dk"])
    paint(img, door & (yy < roof_y1 + H * 0.13), pal["wall_dk"])
    paint(img, (np.abs(yy - (roof_y1 + H * 0.24)) < 2)
          & (np.abs(xx - (dx1 - W * 0.022)) < 2), pal["glow"])     # Griff

    # --- Fenster mit Sprossen und warmem Licht ------------------------------
    for wx in (W * 0.16, W * 0.72):
        fr = (yy >= roof_y1 + H * 0.09) & (yy < roof_y1 + H * 0.25) & \
             (xx >= wx) & (xx < wx + W * 0.14)
        paint(img, fr, pal["beam"])
        gl = (yy >= roof_y1 + H * 0.11) & (yy < roof_y1 + H * 0.23) & \
             (xx >= wx + W * 0.018) & (xx < wx + W * 0.122)
        # Scheibe: warmes Licht, nach unten hin heller (Lampe steht innen).
        # Diagonale Streifen sahen aus wie Kratzer, nicht wie Glas.
        paint(img, gl, pal["glass"])
        paint(img, gl & (yy > roof_y1 + H * 0.15), pal["glow"])
        paint(img, gl & (yy > roof_y1 + H * 0.19), pal["glow"])
        paint(img, gl & (yy < roof_y1 + H * 0.135), pal["beam"])
        # Sprossenkreuz
        paint(img, gl & (np.abs(xx - (wx + W * 0.070)) < 1.5), pal["beam"])
        paint(img, gl & (np.abs(yy - (roof_y1 + H * 0.17)) < 1.5), pal["beam"])
        paint(img, (np.abs(yy - (roof_y1 + H * 0.25)) < 2)
              & (xx >= wx - W * 0.008) & (xx < wx + W * 0.148), pal["beam"])

    outline(img, img[..., 3] > 0, pal["wall_dk"])
    return np.clip(img, 0, 255)
