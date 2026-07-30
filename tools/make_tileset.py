#!/usr/bin/env python3
"""Generiert ein Starter-Tileset (32x32 px, 8 Spalten) als PNG + Metadaten-JSON.

Das ist bewusst austauschbar: Legt man später ein Profi-Tileset (z.B. von
Kenney/itch.io) mit gleicher Struktur ab, rendern alle Maps sofort damit.

Aufruf:
    python3 tools/make_tileset.py
Erzeugt:
    assets/tilesets/basic/tileset.png
    assets/tilesets/basic/tileset_meta.json
"""
import json
import os

import numpy as np
from PIL import Image

TILE = 32
COLS = 8
rng = np.random.default_rng(7)


def noise_tex(base, var=10, speckle=None, speckle_n=40):
    """Grundtextur: Basisfarbe + Pixelrauschen + optionale Sprenkel."""
    img = np.ones((TILE, TILE, 3), dtype=float) * base
    img += rng.normal(0, var, (TILE, TILE, 1))
    if speckle is not None:
        for _ in range(speckle_n):
            x, y = rng.integers(0, TILE, 2)
            img[y, x] = speckle
    return img


def grass(variant=0):
    g = noise_tex((94 + variant * 2, 139 + variant, 62), 8,
                  speckle=(70, 110, 48), speckle_n=25)
    # ein paar Grashalme
    for _ in range(10):
        x, y = rng.integers(2, TILE - 2, 2)
        g[y - 1:y + 1, x] = (120, 170, 80)
    return g


def water(frame=0):
    w = noise_tex((44, 96, 148), 5)
    for i in range(3):
        y = (4 + i * 11 + frame * 3) % TILE
        x0 = rng.integers(0, 10)
        w[y, x0:x0 + 14] = (110, 160, 200)
    return w


def sand():
    return noise_tex((208, 188, 140), 7, speckle=(180, 158, 110), speckle_n=30)


def dirt():
    d = noise_tex((136, 104, 72), 8, speckle=(110, 82, 54), speckle_n=35)
    for _ in range(4):
        x, y = rng.integers(3, TILE - 3, 2)
        d[y:y + 2, x:x + 3] = (160, 132, 96)
    return d


def stone_floor():
    s = noise_tex((150, 148, 144), 6)
    s[::8, :] = (110, 108, 104)
    s[:, ::8] = (110, 108, 104)
    return s


def corner_mask(combo, soft=0.0):
    """Maske (TILE,TILE) aus 4 Ecken (Bit 0=NW,1=NE,2=SW,3=SE) per bilinearer
    Interpolation -> organisch gerundete Übergänge."""
    c = np.array([[1.0 if combo & 1 else 0.0, 1.0 if combo & 2 else 0.0],
                  [1.0 if combo & 4 else 0.0, 1.0 if combo & 8 else 0.0]])
    t = (np.arange(TILE) + 0.5) / TILE
    top = c[0, 0] * (1 - t) + c[0, 1] * t
    bot = c[1, 0] * (1 - t) + c[1, 1] * t
    m = top[None, :] * (1 - t)[:, None] + bot[None, :] * t[:, None]
    if soft > 0:
        m += rng.normal(0, soft, (TILE, TILE))
    return m > 0.5


def blend_wang(over_fn, under_fn, combo, edge=None):
    """Übergangs-Tile: `over` liegt in den markierten Ecken über `under`."""
    under, over = under_fn(), over_fn()
    mask = corner_mask(combo, soft=0.06)
    out = np.where(mask[..., None], over, under)
    if edge is not None:  # heller Saum an der Grenze (z.B. nasser Sand)
        border = (mask ^ np.roll(mask, 1, 0)) | (mask ^ np.roll(mask, 1, 1))
        border[0, :] = border[:, 0] = False  # kein Wrap-Around-Saum am Tilerand
        out[border] = edge
    return out


def tree(base_fn, canopy=(44, 96, 40), trunk=(96, 66, 40)):
    t = base_fn()
    yy, xx = np.mgrid[0:TILE, 0:TILE]
    t[(yy > 24) & (abs(xx - 16) < 3)] = trunk
    d = np.sqrt((xx - 16) ** 2 + (yy - 13) ** 2)
    canopy_mask = d + rng.normal(0, 0.8, d.shape) < 11
    t[canopy_mask] = canopy
    t[canopy_mask & (d < 7) & (yy < 13)] = tuple(min(255, c + 28) for c in canopy)
    return t


def rock(base_fn):
    r = base_fn()
    yy, xx = np.mgrid[0:TILE, 0:TILE]
    d = np.sqrt((xx - 16) ** 2 + ((yy - 18) * 1.3) ** 2)
    m = d + rng.normal(0, 0.7, d.shape) < 9
    r[m] = (138, 134, 128)
    r[m & (yy < 14)] = (170, 166, 160)
    r[m & (yy > 22)] = (100, 98, 94)
    return r


def flowers(base_fn, color):
    f = base_fn()
    for _ in range(6):
        x, y = rng.integers(3, TILE - 3, 2)
        f[y, x - 1:x + 2] = color
        f[y - 1:y + 2, x] = color
        f[y, x] = (240, 224, 120)
    return f


def wall(kind="plain"):
    w = noise_tex((196, 178, 150), 5)
    w[::6, :] = (168, 150, 122)
    for y in range(0, TILE, 6):  # Fachwerk-Anmutung
        off = 3 if (y // 6) % 2 else 0
        w[y:y + 6, (off + 10) % 16::16] = w[y:y + 6, (off + 10) % 16::16] * 0 + (168, 150, 122)
    if kind == "door":
        w[10:, 10:22] = (104, 72, 44)
        w[10:, 10] = w[10:, 21] = (70, 46, 26)
        w[20:23, 18:20] = (210, 180, 90)
    if kind == "window":
        w[8:20, 8:24] = (90, 120, 150)
        w[8:20, 15:17] = (60, 46, 30)
        w[13:15, 8:24] = (60, 46, 30)
        w[7:9, 7:25] = (120, 96, 64)
        w[19:21, 7:25] = (120, 96, 64)
    return w


def roof(part):
    r = noise_tex((168, 74, 56), 6)
    for y in range(0, TILE, 5):
        r[y, :] = (128, 52, 40)
        off = 4 if (y // 5) % 2 else 0
        r[y:y + 5, off::8] = r[y:y + 5, off::8] * 0.82
    if part == "left":
        r[:, 0:2] = (110, 44, 34)
    if part == "right":
        r[:, -2:] = (110, 44, 34)
    if part == "top":
        r[0:3, :] = (196, 96, 72)
    return r


def build():
    tiles, names = [], []

    def add(name, arr):
        names.append(name)
        tiles.append(np.clip(arr, 0, 255).astype(np.uint8))

    # --- Basis (IDs 0..7)
    add("grass_1", grass(0)); add("grass_2", grass(1)); add("grass_3", grass(2))
    add("sand", sand()); add("dirt", dirt()); add("water", water(0))
    add("water_2", water(1)); add("stone_floor", stone_floor())

    # --- Wang-Sets: 16 Ecken-Kombis (IDs 8..23 Wasser, 24..39 Pfad)
    for combo in range(16):
        add(f"water_grass_{combo}",
            blend_wang(water, grass, combo, edge=(196, 186, 150)))
    for combo in range(16):
        add(f"dirt_grass_{combo}", blend_wang(dirt, grass, combo))

    # --- Dekoration (IDs 40..47)
    add("tree", tree(grass))
    add("pine", tree(grass, canopy=(30, 76, 46)))
    add("rock", rock(grass))
    add("bush", tree(grass, canopy=(60, 110, 50), trunk=(60, 110, 50)))
    add("flowers_red", flowers(grass, (200, 60, 60)))
    add("flowers_blue", flowers(grass, (90, 110, 210)))
    add("tree_sand", tree(sand, canopy=(80, 130, 60)))
    add("rock_sand", rock(sand))

    # --- Gebäude (IDs 48..55)
    add("wall", wall()); add("wall_door", wall("door")); add("wall_window", wall("window"))
    add("roof_left", roof("left")); add("roof_mid", roof("mid")); add("roof_right", roof("right"))
    add("roof_top", roof("top")); add("stone_path", stone_floor())

    rows = (len(tiles) + COLS - 1) // COLS
    sheet = np.zeros((rows * TILE, COLS * TILE, 4), dtype=np.uint8)
    for i, t in enumerate(tiles):
        r, c = divmod(i, COLS)
        sheet[r * TILE:(r + 1) * TILE, c * TILE:(c + 1) * TILE, :3] = t
        sheet[r * TILE:(r + 1) * TILE, c * TILE:(c + 1) * TILE, 3] = 255

    out_dir = "assets/tilesets/basic"
    os.makedirs(out_dir, exist_ok=True)
    Image.fromarray(sheet).save(f"{out_dir}/tileset.png")
    meta = {"tile_size": TILE, "columns": COLS, "count": len(tiles),
            "ids": {n: i for i, n in enumerate(names)}}
    with open(f"{out_dir}/tileset_meta.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(f"{len(tiles)} Tiles -> {out_dir}/tileset.png")


if __name__ == "__main__":
    build()
