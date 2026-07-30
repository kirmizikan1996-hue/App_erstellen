#!/usr/bin/env python3
"""Generiert das Tileset v2 (32px) — cozy Pixel-Art-Stil mit Schatten,
Multi-Tile-Sprites (Bäume 2x2, Häuser 5x4, Brunnen 2x2) und weichen
Terrain-Übergängen (Strand mit Schaumkante, Wege mit Grasfransen).

Deko-Sprites haben transparenten Hintergrund und funktionieren damit auf
jedem Untergrund. Austauschbar gegen Profi-Tilesets (siehe README).

Aufruf:  python3 tools/make_tileset.py
Erzeugt: assets/tilesets/basic/tileset.png + tileset_meta.json
"""
import json
import os

import numpy as np

TILE = 32
COLS = 16
rng = np.random.default_rng(11)

# ---------------------------------------------------------------- Helpers

def canvas(w=1, h=1):
    return np.zeros((h * TILE, w * TILE, 4), dtype=float)


def fill(img, color, alpha=255):
    img[..., :3] = color
    img[..., 3] = alpha
    return img


def grid(img):
    return np.mgrid[0:img.shape[0], 0:img.shape[1]]


def paint(img, mask, color, alpha=255):
    img[..., :3][mask] = color
    img[..., 3][mask] = alpha


def ellipse_mask(img, cy, cx, ry, rx, rough=0.0):
    yy, xx = grid(img)
    d = ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2
    if rough:
        d = d + rng.normal(0, rough, d.shape)
    return d < 1.0


def shadow(img, cy, cx, ry, rx, alpha=70):
    m = ellipse_mask(img, cy, cx, ry, rx)
    img[..., :3][m] = (30, 40, 26)
    img[..., 3][m] = np.maximum(img[..., 3][m], alpha)


def pixel_noise(img, mask, amount):
    n = rng.normal(0, amount, img.shape[:2] + (1,))
    img[..., :3] = np.where(mask[..., None], img[..., :3] + n, img[..., :3])


# ---------------------------------------------------------------- Boden

GRASS_BASE = (94, 134, 66)

def grass(variant=0):
    img = canvas()
    fill(img, GRASS_BASE)  # Varianten unterscheiden sich nur im Büschel-Muster
    pixel_noise(img, np.ones(img.shape[:2], bool), 3.5)
    # Grasbüschel: kleine Gruppen dunkler Vertikalstriche (ruhig, wenig Kontrast)
    for _ in range(9):
        x, y = rng.integers(2, TILE - 3, 2)
        for dx in range(rng.integers(2, 4)):
            h = rng.integers(2, 4)
            img[y:y + h, min(TILE - 1, x + dx * 2), :3] = (76, 114, 54)
    for _ in range(5):
        x, y = rng.integers(1, TILE - 1, 2)
        img[y, x, :3] = (116, 156, 82)
    return img


def dirt_tex(shape):
    t = np.ones(shape + (3,)) * (152, 120, 84)
    t += rng.normal(0, 5, shape + (1,))
    for _ in range(shape[0] * shape[1] // 60):
        y, x = rng.integers(1, shape[0] - 2), rng.integers(1, shape[1] - 2)
        t[y:y + 2, x:x + 2] = (170, 148, 118)
    for _ in range(shape[0] * shape[1] // 80):
        y, x = rng.integers(0, shape[0]), rng.integers(0, shape[1])
        t[y, x] = (124, 94, 62)
    return t


def dirt():
    img = canvas()
    img[..., :3] = dirt_tex((TILE, TILE))
    img[..., 3] = 255
    return img


def water_tex(shape):
    t = np.ones(shape + (3,)) * (52, 100, 148)
    t += rng.normal(0, 2.5, shape + (1,))
    for _ in range(shape[0] * shape[1] // 260):
        y, x = rng.integers(2, shape[0] - 2), rng.integers(0, shape[1] - 8)
        t[y, x:x + rng.integers(4, 9)] = (96, 144, 184)
    return t


def water():
    img = canvas()
    img[..., :3] = water_tex((TILE, TILE))
    img[..., 3] = 255
    return img


def stone_floor(variant=0):
    img = canvas()
    fill(img, (176 + variant * 3, 166 + variant * 3, 148))  # warmer Sandstein
    pixel_noise(img, np.ones(img.shape[:2], bool), 4)
    # unregelmäßige Platten
    for y in range(0, TILE, 8):
        off = 4 if (y // 8) % 2 else 0
        img[y, :, :3] = (148, 138, 120)
        for x in range((off + 5) % 10, TILE, 10):
            img[y:y + 8, x, :3] = (148, 138, 120)
    return img


# ------------------------------------------------- Terrain-Übergänge (Wang)

def corner_field(combo, soft=0.05):
    """Kontinuierliches Feld 0..1 aus 4 Eckenwerten (Bit: 1=NW 2=NE 4=SW 8=SE)."""
    c = np.array([[1.0 if combo & 1 else 0.0, 1.0 if combo & 2 else 0.0],
                  [1.0 if combo & 4 else 0.0, 1.0 if combo & 8 else 0.0]])
    t = (np.arange(TILE) + 0.5) / TILE
    top = c[0, 0] * (1 - t) + c[0, 1] * t
    bot = c[1, 0] * (1 - t) + c[1, 1] * t
    m = top[None, :] * (1 - t)[:, None] + bot[None, :] * t[:, None]
    return m + rng.normal(0, soft, m.shape)


def water_grass(combo):
    """Strandübergang: Gras -> Sand -> nasser Sand -> Schaum -> Flachwasser -> Wasser."""
    img = grass(0)
    m = corner_field(combo)
    paint(img, (m >= 0.30) & (m < 0.44), (212, 190, 148))
    paint(img, (m >= 0.44) & (m < 0.52), (184, 162, 126))
    paint(img, (m >= 0.52) & (m < 0.62), (110, 158, 180))
    wm = m >= 0.62
    img[..., :3][wm] = water_tex((TILE, TILE))[wm]
    # Sand-Sprenkel
    sandm = (m >= 0.30) & (m < 0.52)
    pixel_noise(img, sandm, 4)
    # Schaumkante: gestrichelt
    foam = (m >= 0.515) & (m < 0.545) & (rng.random((TILE, TILE)) < 0.75)
    paint(img, foam, (236, 242, 244))
    return img


def dirt_grass(combo):
    """Weg-Übergang: ausgefranste Kante, gestreute Erd-/Graspixel."""
    img = grass(0)
    m = corner_field(combo, soft=0.07)
    dm = m >= 0.5
    img[..., :3][dm] = dirt_tex((TILE, TILE))[dm]
    fringe = (m >= 0.42) & (m < 0.5) & (rng.random((TILE, TILE)) < 0.30)
    paint(img, fringe, (140, 112, 78))
    edge = (m >= 0.48) & (m < 0.515) & (rng.random((TILE, TILE)) < 0.5)
    paint(img, edge, (108, 84, 56))
    return img


# ---------------------------------------------------------------- Deko

def tree_big(seed=0):
    """Laubbaum 2x2 Tiles, transparent, mit Bodenschatten und 3-stufigem Licht."""
    r = np.random.default_rng(100 + seed)
    img = canvas(2, 2)
    shadow(img, 56, 32, 6, 19, alpha=75)
    # Stamm
    yy, xx = grid(img)
    trunk = (yy > 36) & (yy < 58) & (abs(xx - 32) < 4 - (yy - 58) * 0.04)
    paint(img, trunk, (108, 76, 48))
    paint(img, trunk & (xx < 31), (92, 62, 38))
    # Krone: Vereinigung mehrerer Kreise
    # Krone füllt die Sprite-Box fast aus -> Nachbarbäume verschmelzen zu
    # geschlossener Waldmasse
    canopy = np.zeros(img.shape[:2], bool)
    for cy, cx, cr in [(24, 32, 21), (28, 13, 13), (28, 51, 13),
                       (12, 21, 12), (12, 43, 12)]:
        cy += r.integers(-2, 3); cx += r.integers(-2, 3)
        canopy |= ((yy - cy) ** 2 + (xx - cx) ** 2) < cr ** 2
    paint(img, canopy, (62, 112, 56))
    paint(img, canopy & (yy > 30), (50, 94, 48))
    hi = np.zeros_like(canopy)
    for cy, cx, cr in [(16, 24, 11), (12, 38, 9), (24, 18, 7)]:
        hi |= ((yy - cy) ** 2 + (xx - cx) ** 2) < cr ** 2
    paint(img, canopy & hi, (88, 142, 70))
    for _ in range(26):  # Blatt-Glitzer
        y, x = r.integers(6, 40), r.integers(10, 54)
        if canopy[y, x]:
            img[y, x, :3] = (110, 164, 84)
    # dunkler Saum
    er = canopy & np.roll(canopy, 1, 0) & np.roll(canopy, -1, 0) \
        & np.roll(canopy, 1, 1) & np.roll(canopy, -1, 1)
    paint(img, canopy & ~er, (42, 76, 42))
    return img


def pine(seed=0):
    """Nadelbaum 1x2 Tiles."""
    r = np.random.default_rng(200 + seed)
    img = canvas(1, 2)
    shadow(img, 58, 16, 4, 10, alpha=70)
    yy, xx = grid(img)
    paint(img, (yy > 48) & (yy < 60) & (abs(xx - 16) < 3), (100, 70, 44))
    for tier, (ty, tw) in enumerate([(46, 14), (34, 11), (22, 8)]):
        tri = (yy <= ty) & (yy > ty - 16) & (abs(xx - 16) < (yy - (ty - 16)) * tw / 16)
        paint(img, tri, (44, 86, 52))
        paint(img, tri & (xx < 16) & (yy < ty - 4), (58, 106, 62))
        paint(img, tri & (yy > ty - 3), (34, 68, 44))
    return img


def bush():
    img = canvas()
    shadow(img, 27, 16, 4, 11, alpha=65)
    yy, xx = grid(img)
    m = np.zeros(img.shape[:2], bool)
    for cy, cx, cr in [(18, 16, 9), (20, 9, 6), (20, 23, 6)]:
        m |= ((yy - cy) ** 2 + (xx - cx) ** 2) < cr ** 2
    paint(img, m, (58, 104, 52))
    paint(img, m & (yy < 16), (76, 126, 62))
    paint(img, m & (yy > 22), (46, 86, 46))
    return img


def rock_small():
    img = canvas()
    shadow(img, 25, 16, 3, 9, alpha=65)
    m = ellipse_mask(img, 19, 16, 7, 9, rough=0.12)
    yy, _ = grid(img)
    paint(img, m, (148, 142, 132))
    paint(img, m & (yy < 16), (176, 170, 158))
    paint(img, m & (yy > 22), (116, 110, 102))
    return img


def flowers(color):
    img = canvas()
    for _ in range(5):
        x, y = rng.integers(4, TILE - 4, 2)
        img[y + 1, x - 1, :3] = (70, 110, 50); img[y + 1, x - 1, 3] = 255
        img[y + 1, x + 1, :3] = (70, 110, 50); img[y + 1, x + 1, 3] = 255
        for dy, dx in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
            img[y + dy, x + dx, :3] = color
            img[y + dy, x + dx, 3] = 255
        img[y, x, :3] = (244, 228, 120)
        img[y, x, 3] = 255
    return img


def tall_grass():
    img = canvas()
    for _ in range(11):
        x, y = rng.integers(3, TILE - 3), rng.integers(8, TILE - 2)
        h = rng.integers(5, 9)
        col = (72, 116, 52) if rng.random() < 0.6 else (88, 132, 62)
        img[y - h:y, x, :3] = col
        img[y - h:y, x, 3] = 255
        img[y - h, x + rng.integers(-1, 2), :3] = col
        img[y - h, x + rng.integers(-1, 2), 3] = 255
    return img


def sprouts():
    """Setzlinge in Pflanzreihen fürs Feld (transparent, über Acker legen)."""
    img = canvas()
    for y in range(4, TILE, 11):  # dunkle Furchenlinie
        img[y + 5, :, :3] = (128, 98, 66)
        img[y + 5, :, 3] = 255
        for x in range(4, TILE - 2, 8):
            img[y:y + 4, x, :3] = (76, 122, 54); img[y:y + 4, x, 3] = 255
            img[y, x - 1, :3] = (96, 146, 66); img[y, x - 1, 3] = 255
            img[y, x + 1, :3] = (96, 146, 66); img[y, x + 1, 3] = 255
            img[y + 1, x - 2, :3] = (88, 134, 60); img[y + 1, x - 2, 3] = 255
            img[y + 1, x + 2, :3] = (88, 134, 60); img[y + 1, x + 2, 3] = 255
    return img


def fence_h():
    img = canvas()
    for y in (13, 21):
        img[y:y + 3, :, :3] = (150, 112, 68)
        img[y, :, :3] = (172, 134, 84)
        img[y + 2, :, :3] = (118, 86, 52)
        img[y:y + 3, :, 3] = 255
    for x in (3, 27):
        img[9:27, x:x + 4, :3] = (134, 98, 58)
        img[9:27, x, :3] = (158, 122, 74)
        img[9, x:x + 4, :3] = (172, 134, 84)
        img[26, x:x + 4, :3] = (100, 72, 44)
        img[9:27, x:x + 4, 3] = 255
        img[27:29, x:x + 5, :3] = (30, 40, 26)
        img[27:29, x:x + 5, 3] = 60
    return img


def fence_v():
    img = canvas()
    for x in (13, 19):
        img[:, x:x + 3, :3] = (150, 112, 68)
        img[:, x, :3] = (172, 134, 84)
        img[:, x + 2, :3] = (118, 86, 52)
        img[:, x:x + 3, 3] = 255
    for y in (3, 24):
        img[y:y + 5, 11:24, :3] = (134, 98, 58)
        img[y, 11:24, :3] = (172, 134, 84)
        img[y + 4, 11:24, :3] = (100, 72, 44)
        img[y:y + 5, 11:24, 3] = 255
    return img


def well():
    """Dorfbrunnen 2x2."""
    img = canvas(2, 2)
    shadow(img, 56, 32, 6, 20, alpha=75)
    yy, xx = grid(img)
    ring = ellipse_mask(img, 46, 32, 11, 17) & ~ellipse_mask(img, 45, 32, 6, 11)
    paint(img, ring, (150, 144, 134))
    paint(img, ring & (yy < 42), (176, 170, 158))
    paint(img, ring & (yy > 50), (116, 110, 102))
    for _ in range(14):  # Steinfugen
        y, x = rng.integers(36, 56), rng.integers(14, 50)
        if ring[y, x]:
            img[y, x, :3] = (110, 104, 96)
    paint(img, ellipse_mask(img, 45, 32, 6, 11), (30, 38, 48))
    for x in (12, 48):  # Pfosten
        paint(img, (yy > 16) & (yy < 46) & (abs(xx - x) < 2), (120, 86, 52))
    roofm = (yy > 6) & (yy < 20) & (abs(xx - 32) < (yy - 4) * 1.5)
    paint(img, roofm, (172, 84, 58))
    paint(img, roofm & (yy % 5 == 0), (142, 66, 48))
    paint(img, (yy > 22) & (yy < 42) & (abs(xx - 32) < 1), (90, 70, 50))  # Seil
    paint(img, (yy >= 40) & (yy < 45) & (abs(xx - 32) < 4), (134, 98, 58))  # Eimer
    return img


# ---------------------------------------------------------------- Haus

def house(seed=0, w_tiles=5):
    """Fachwerkhaus w x 4 Tiles: Dach mit Überstand, Schornstein, Fenster mit
    Blumenkasten, Bogentür. Tür sitzt mittig in der untersten Reihe."""
    r = np.random.default_rng(300 + seed)
    W, H = w_tiles * TILE, 4 * TILE
    img = canvas(w_tiles, 4)
    yy, xx = grid(img)
    roof_y0, roof_y1 = 8, 54          # Dachfläche
    wall_y1 = H - 12                  # Unterkante Wand
    # Bodenschatten
    shadow(img, H - 8, W // 2, 6, W // 2 - 6, alpha=70)
    # Wand: warmer Putz
    wall = (yy >= roof_y1) & (yy < wall_y1) & (xx >= 8) & (xx < W - 8)
    paint(img, wall, (234, 222, 200))
    pixel_noise(img, wall, 3)
    # Fachwerk-Balken
    beams = wall & ((xx < 14) | (xx >= W - 14) |
                    (yy >= wall_y1 - 6) | (abs(xx - W // 2) < 60) & False)
    paint(img, beams, (124, 88, 54))
    # Traufschatten unter dem Dach
    eave = (yy >= roof_y1) & (yy < roof_y1 + 7) & (xx >= 8) & (xx < W - 8)
    img[..., :3][eave] *= 0.72
    # Dach mit Überstand
    roof = (yy >= roof_y0) & (yy < roof_y1) & (xx >= 2) & (xx < W - 2)
    paint(img, roof, (178, 88, 60))
    for i, y in enumerate(range(roof_y0 + 6, roof_y1, 7)):     # Schindelreihen
        row = roof & (yy >= y) & (yy < y + 1)
        paint(img, row, (146, 66, 48))
        off = 8 if i % 2 else 0
        ticks = roof & (yy >= y - 6) & (yy < y) & ((xx + off) % 16 < 1)
        paint(img, ticks, (156, 72, 52))
    paint(img, (yy >= roof_y0) & (yy < roof_y0 + 4) & (xx >= 2) & (xx < W - 2),
          (200, 106, 74))                                       # First
    paint(img, roof & ((xx < 5) | (xx >= W - 5)), (140, 62, 46))
    paint(img, (yy >= roof_y1 - 2) & (yy < roof_y1) & (xx >= 2) & (xx < W - 2),
          (120, 52, 40))                                        # Traufkante
    # Schornstein
    ch_x = W - 44
    chimney = (yy >= 0) & (yy < roof_y0 + 6) & (xx >= ch_x) & (xx < ch_x + 14)
    paint(img, chimney, (150, 144, 134))
    paint(img, (yy < 3) & (xx >= ch_x - 2) & (xx < ch_x + 16), (120, 114, 106))
    # Tür (Bogen), mittig
    dx0 = W // 2 - 11
    door = (yy >= roof_y1 + 22) & (yy < wall_y1) & (xx >= dx0) & (xx < dx0 + 22)
    arch = ((yy - (roof_y1 + 22)) ** 2 / 90 + (xx - (dx0 + 11)) ** 2 / 121) < 1
    door = door | (arch & (yy < roof_y1 + 24) & (yy > roof_y1 + 12))
    paint(img, door, (136, 96, 58))
    paint(img, door & ((xx - dx0) % 6 < 1), (112, 76, 46))
    paint(img, (yy >= roof_y1 + 40) & (yy < roof_y1 + 44) &
          (xx >= dx0 + 16) & (xx < dx0 + 19), (222, 182, 100))  # Griff
    # Fenster links + rechts
    for wx in (26, W - 50):
        fr = (yy >= roof_y1 + 20) & (yy < roof_y1 + 44) & (xx >= wx) & (xx < wx + 24)
        paint(img, fr, (124, 88, 54))
        glass = (yy >= roof_y1 + 23) & (yy < roof_y1 + 41) & (xx >= wx + 3) & (xx < wx + 21)
        paint(img, glass, (152, 182, 198))
        paint(img, glass & ((xx - yy) % 9 < 2), (188, 212, 222))  # Lichtreflex
        paint(img, glass & (abs(xx - wx - 12) < 1), (124, 88, 54))
        paint(img, glass & (abs(yy - roof_y1 - 32) < 1), (124, 88, 54))
        box = (yy >= roof_y1 + 44) & (yy < roof_y1 + 50) & (xx >= wx + 1) & (xx < wx + 23)
        paint(img, box, (114, 80, 48))
        for fx in range(wx + 3, wx + 21, 4):
            img[roof_y1 + 43, fx, :3] = (206, 74, 66) if r.random() < 0.6 else (230, 210, 120)
            img[roof_y1 + 43, fx, 3] = 255
            img[roof_y1 + 44, fx - 1, :3] = (84, 124, 60)
            img[roof_y1 + 44, fx - 1, 3] = 255
    # Sockel
    base = (yy >= wall_y1 - 6) & (yy < wall_y1) & (xx >= 8) & (xx < W - 8) & ~door
    paint(img, base, (156, 148, 136))
    return img


# ---------------------------------------------------------------- Sheet

def build():
    singles, sprites = {}, {}
    tiles = []

    def add_single(name, img):
        singles[name] = len(tiles)
        tiles.append(img)

    def add_sprite(name, img):
        th, tw = img.shape[0] // TILE, img.shape[1] // TILE
        ids = []
        for r_ in range(th):
            row = []
            for c in range(tw):
                row.append(len(tiles))
                tiles.append(img[r_ * TILE:(r_ + 1) * TILE, c * TILE:(c + 1) * TILE])
            ids.append(row)
        sprites[name] = {"w": tw, "h": th, "tiles": ids}

    add_single("grass_1", grass(0))
    add_single("grass_2", grass(2))
    add_single("grass_3", grass(4))
    add_single("dirt", dirt())
    add_single("water", water())
    add_single("stone_1", stone_floor(0))
    add_single("stone_2", stone_floor(1))
    for combo in range(16):
        add_single(f"water_grass_{combo}", water_grass(combo))
    for combo in range(16):
        add_single(f"dirt_grass_{combo}", dirt_grass(combo))
    add_single("bush", bush())
    add_single("rock", rock_small())
    add_single("flowers_red", flowers((208, 74, 68)))
    add_single("flowers_blue", flowers((104, 122, 214)))
    add_single("tall_grass", tall_grass())
    add_single("sprouts", sprouts())
    add_single("fence_h", fence_h())
    add_single("fence_v", fence_v())

    add_sprite("tree_a", tree_big(0))
    add_sprite("tree_b", tree_big(1))
    add_sprite("tree_c", tree_big(2))
    add_sprite("pine_a", pine(0))
    add_sprite("pine_b", pine(1))
    add_sprite("well", well())
    add_sprite("house_a", house(0))
    add_sprite("house_b", house(1))

    rows = (len(tiles) + COLS - 1) // COLS
    sheet = np.zeros((rows * TILE, COLS * TILE, 4), dtype=np.uint8)
    for i, t in enumerate(tiles):
        r_, c = divmod(i, COLS)
        sheet[r_ * TILE:(r_ + 1) * TILE, c * TILE:(c + 1) * TILE] = \
            np.clip(t, 0, 255).astype(np.uint8)

    from PIL import Image
    out_dir = "assets/tilesets/basic"
    os.makedirs(out_dir, exist_ok=True)
    Image.fromarray(sheet).save(f"{out_dir}/tileset.png")
    with open(f"{out_dir}/tileset_meta.json", "w") as f:
        json.dump({"tile_size": TILE, "columns": COLS, "count": len(tiles),
                   "ids": singles, "sprites": sprites}, f, indent=2)
    print(f"{len(tiles)} Tiles ({len(sprites)} Multi-Tile-Sprites) -> {out_dir}/tileset.png")


if __name__ == "__main__":
    build()
