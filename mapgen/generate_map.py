"""Hand-painted style 2D world map generator for a top-down MMORPG.

Erzeugt aus einem Seed eine grosse Karte im handgemalten Look:
  - map.png       Sichtbare Karte (Boden-Ebene fuer Unity)
  - biomes.png    Farbcodierte Biom-Daten (fuer Gameplay/Asset-Platzierung)
  - collision.png Schwarz = begehbar, Weiss = blockiert (Wasser/Fels)

Aufruf:  python3 generate_map.py [--size 2048] [--seed 7] [--out output]
"""

import argparse
import json
import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter


# ---------------------------------------------------------------- noise ----

def _value_noise(h, w, cells_y, cells_x, rng):
    """Bilinear-interpoliertes Value-Noise in [0,1]."""
    grid = rng.random((cells_y + 2, cells_x + 2))
    ys = np.linspace(0, cells_y, h, endpoint=False)
    xs = np.linspace(0, cells_x, w, endpoint=False)
    y0 = ys.astype(int)
    x0 = xs.astype(int)
    ty = ys - y0
    tx = xs - x0
    # smoothstep fuer weiche Uebergaenge
    ty = ty * ty * (3 - 2 * ty)
    tx = tx * tx * (3 - 2 * tx)
    ty = ty[:, None]
    tx = tx[None, :]
    g00 = grid[np.ix_(y0, x0)]
    g01 = grid[np.ix_(y0, x0 + 1)]
    g10 = grid[np.ix_(y0 + 1, x0)]
    g11 = grid[np.ix_(y0 + 1, x0 + 1)]
    top = g00 * (1 - tx) + g01 * tx
    bot = g10 * (1 - tx) + g11 * tx
    return top * (1 - ty) + bot * ty


def fbm(h, w, base_cells, octaves, rng, persistence=0.5):
    """Fraktales Rauschen (mehrere Oktaven), normiert auf [0,1]."""
    total = np.zeros((h, w))
    amp = 1.0
    amp_sum = 0.0
    cells = base_cells
    for _ in range(octaves):
        total += amp * _value_noise(h, w, cells, cells, rng)
        amp_sum += amp
        amp *= persistence
        cells *= 2
    total /= amp_sum
    return total


def bilinear_sample(img, yy, xx):
    """img an (float-)Koordinaten yy/xx bilinear abtasten."""
    h, w = img.shape
    yy = np.clip(yy, 0, h - 1.001)
    xx = np.clip(xx, 0, w - 1.001)
    y0 = yy.astype(int)
    x0 = xx.astype(int)
    ty = yy - y0
    tx = xx - x0
    top = img[y0, x0] * (1 - tx) + img[y0, x0 + 1] * tx
    bot = img[y0 + 1, x0] * (1 - tx) + img[y0 + 1, x0 + 1] * tx
    return top * (1 - ty) + bot * ty


# ------------------------------------------------------------- terrain ----

def build_elevation(size, rng):
    """Hoehenkarte mit Domain-Warping fuer organische Kuestenlinien."""
    base = fbm(size, size, 4, 6, rng)
    warp_x = fbm(size, size, 3, 4, rng)
    warp_y = fbm(size, size, 3, 4, rng)
    amp = size * 0.08
    yy, xx = np.mgrid[0:size, 0:size].astype(float)
    elev = bilinear_sample(base, yy + (warp_y - 0.5) * amp, xx + (warp_x - 0.5) * amp)
    # Insel-Tendenz: Raender leicht absenken, damit die Welt vom Meer umgeben ist
    cy = cx = size / 2
    d = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2) / (size * 0.7)
    elev = elev - d ** 2 * 0.35
    elev = (elev - elev.min()) / (elev.max() - elev.min())
    return elev


def trace_rivers(elev, water_mask, rng, count):
    """Fluesse per Gradientenabstieg von hohen Punkten Richtung Meer."""
    size = elev.shape[0]
    rivers = []
    candidates = np.argwhere(elev > 0.7)
    if len(candidates) == 0:
        return rivers
    for _ in range(count):
        y, x = candidates[rng.integers(len(candidates))]
        path = [(float(x), float(y))]
        vy, vx = 0.0, 0.0
        for _ in range(4000):
            yi, xi = int(y), int(x)
            if water_mask[yi, xi]:
                break
            # steilsten Abstieg in kleiner Nachbarschaft suchen
            best, by, bx = elev[yi, xi], 0, 0
            for dy in (-2, -1, 0, 1, 2):
                for dx in (-2, -1, 0, 1, 2):
                    ny, nx = yi + dy, xi + dx
                    if 0 <= ny < size and 0 <= nx < size and elev[ny, nx] < best:
                        best, by, bx = elev[ny, nx], dy, dx
            if by == 0 and bx == 0:
                break  # lokale Senke
            # Traegheit + leichtes Zittern -> geschwungene Laeufe
            vy = 0.6 * vy + 0.4 * by + rng.normal(0, 0.3)
            vx = 0.6 * vx + 0.4 * bx + rng.normal(0, 0.3)
            n = math.hypot(vy, vx) or 1.0
            y = min(max(y + vy / n * 1.5, 0), size - 1)
            x = min(max(x + vx / n * 1.5, 0), size - 1)
            path.append((float(x), float(y)))
        if len(path) > 60:
            rivers.append(path)
    return rivers


# ------------------------------------------------------------ painting ----

PALETTE = {
    "deep_water": (38, 84, 124),
    "water": (52, 108, 148),
    "shallow": (86, 148, 178),
    "sand": (222, 203, 154),
    "grass": (128, 168, 92),
    "grass_dark": (104, 146, 78),
    "forest_floor": (88, 128, 68),
    "rock": (142, 132, 118),
    "snow": (235, 235, 230),
    "ink": (56, 44, 32),
}


def paint_ground(elev, moisture, rng):
    """Grundfarben je Biom mit malerischer Farb-Variation."""
    size = elev.shape[0]
    img = np.zeros((size, size, 3))

    def col(name):
        return np.array(PALETTE[name], dtype=float)

    deep = elev < 0.30
    water = (elev >= 0.30) & (elev < 0.38)
    shallow = (elev >= 0.38) & (elev < 0.40)
    sand = (elev >= 0.40) & (elev < 0.435)
    rock = elev >= 0.78
    snow = elev >= 0.88
    grass = ~(deep | water | shallow | sand | rock)

    img[deep] = col("deep_water")
    img[water] = col("water")
    img[shallow] = col("shallow")
    img[sand] = col("sand")
    img[rock] = col("rock")
    img[snow] = col("snow")

    # Gras: zwischen hell und dunkel je nach Feuchtigkeit mischen
    t = np.clip((moisture - 0.35) / 0.4, 0, 1)[grass][:, None]
    img[grass] = col("grass") * (1 - t) + col("forest_floor") * t

    # malerische Flecken: grobe + feine Helligkeitsvariation ("Pinsel-Mottling")
    blotch = fbm(size, size, 24, 3, rng) - 0.5
    speckle = fbm(size, size, 160, 2, rng) - 0.5
    variation = (blotch * 26 + speckle * 14)[:, :, None]
    land = ~(deep | water | shallow)
    img[land] += variation[land]
    img[~land] += variation[~land] * 0.5

    return np.clip(img, 0, 255), ~land


def coast_lines(img, water_mask):
    """Tusche-Kuestenlinie + helle Wasserringe im handgezeichneten Stil."""
    ink = np.array(PALETTE["ink"], dtype=float)

    def dilate(m, it=1):
        for _ in range(it):
            m = (m | np.roll(m, 1, 0) | np.roll(m, -1, 0)
                 | np.roll(m, 1, 1) | np.roll(m, -1, 1))
        return m

    land = ~water_mask
    outline = dilate(land, 2) & water_mask
    img[outline] = img[outline] * 0.25 + ink * 0.75

    # gestaffelte helle Ringe im Wasser (klassischer Karten-Look)
    grown = land.copy()
    for dist in range(1, 30):
        grown = dilate(grown, 1)
        if dist in (8, 15, 24):
            ring = grown & ~dilate(land, dist - 1) & water_mask
            img[ring] = img[ring] * 0.75 + np.array([190, 220, 235]) * 0.25
    return img


def draw_rivers(draw, rivers):
    for path in rivers:
        if len(path) < 2:
            continue
        draw.line(path, fill=PALETTE["ink"], width=7, joint="curve")
    for path in rivers:
        if len(path) < 2:
            continue
        draw.line(path, fill=PALETTE["shallow"], width=4, joint="curve")


def draw_trees(draw, elev, moisture, rng, size):
    """Waelder als einzeln 'gepinselte' Baeume in Clustern."""
    step = max(10, size // 170)
    forest = (elev > 0.44) & (elev < 0.75) & (moisture > 0.55)
    positions = []
    for gy in range(0, size, step):
        for gx in range(0, size, step):
            x = gx + rng.integers(step)
            y = gy + rng.integers(step)
            if x >= size or y >= size or not forest[y, x]:
                continue
            if rng.random() < 0.75:
                positions.append((x, y, 4 + rng.integers(5)))
    # von oben nach unten zeichnen, damit Ueberlappung natuerlich wirkt
    positions.sort(key=lambda p: p[1])
    for x, y, r in positions:
        draw.ellipse([x - r, y - r + 2, x + r, y + r + 2],
                     fill=(40, 62, 34))                      # Schatten/Umriss
        draw.ellipse([x - r + 1, y - r + 1, x + r - 1, y + r - 1],
                     fill=(74, 112, 52))                     # Krone
        hr = max(1, r // 2)
        draw.ellipse([x - hr, y - r + 2, x + hr, y - r + 2 + hr * 2],
                     fill=(102, 142, 72))                    # Licht von oben


def draw_mountains(draw, elev, rng, size):
    """Berge als handgezeichnete Dreiecke mit Schattierung."""
    step = max(14, size // 120)
    peaks = []
    for gy in range(0, size, step):
        for gx in range(0, size, step):
            x = gx + rng.integers(step)
            y = gy + rng.integers(step)
            if x >= size or y >= size:
                continue
            e = elev[y, x]
            if e > 0.80 and rng.random() < 0.8:
                peaks.append((x, y, e))
    peaks.sort(key=lambda p: p[1])
    for x, y, e in peaks:
        s = int(8 + (e - 0.8) * 90) + rng.integers(4)
        top = (x, y - s)
        left = (x - s, y + s // 2)
        right = (x + s, y + s // 2)
        draw.polygon([top, left, right], fill=(150, 140, 126),
                     outline=PALETTE["ink"], width=2)
        draw.polygon([top, (x + s // 3, y), right],
                     fill=(118, 108, 96))                    # Schattenseite
        if e > 0.87:
            c = s // 2
            draw.polygon([top, (x - c // 2, y - s + c), (x + c // 2, y - s + c)],
                         fill=(240, 240, 238))               # Schneekappe


# ---------------------------------------------------------------- main ----

def generate(size, seed, out_dir):
    rng = np.random.default_rng(seed)
    random.seed(seed)
    os.makedirs(out_dir, exist_ok=True)

    print(f"[1/6] Hoehenkarte ({size}x{size}, Seed {seed}) ...")
    elev = build_elevation(size, rng)
    moisture = fbm(size, size, 5, 4, rng)

    print("[2/6] Boden malen ...")
    img_arr, water_mask = paint_ground(elev, moisture, rng)

    print("[3/6] Kuestenlinien zeichnen ...")
    img_arr = coast_lines(img_arr, water_mask)

    img = Image.fromarray(img_arr.astype(np.uint8))
    img = img.filter(ImageFilter.GaussianBlur(0.6))  # weicher, gemalter Look
    draw = ImageDraw.Draw(img)

    print("[4/6] Fluesse ...")
    rivers = trace_rivers(elev, water_mask, rng, count=max(4, size // 400))
    draw_rivers(draw, rivers)

    print("[5/6] Waelder und Berge ...")
    draw_trees(draw, elev, moisture, rng, size)
    draw_mountains(draw, elev, rng, size)

    print("[6/6] Speichern ...")
    img.save(os.path.join(out_dir, "map.png"))

    # Biom-Datenkarte (fuer Gameplay: 1 Pixel = 1 Zelle)
    biome = np.zeros((size, size, 3), dtype=np.uint8)
    biome[elev < 0.40] = (0, 0, 200)                       # Wasser
    biome[(elev >= 0.40) & (elev < 0.435)] = (230, 210, 120)  # Strand
    biome[(elev >= 0.435)] = (60, 160, 60)                 # Wiese
    biome[(elev > 0.44) & (elev < 0.75) & (moisture > 0.55)] = (20, 90, 20)  # Wald
    biome[elev >= 0.78] = (120, 120, 120)                  # Gebirge
    Image.fromarray(biome).save(os.path.join(out_dir, "biomes.png"))

    collision = ((elev < 0.40) | (elev >= 0.80)).astype(np.uint8) * 255
    Image.fromarray(collision).save(os.path.join(out_dir, "collision.png"))

    with open(os.path.join(out_dir, "map_meta.json"), "w") as f:
        json.dump({"size": size, "seed": seed,
                   "water_below_elevation": 0.40,
                   "mountain_above_elevation": 0.78}, f, indent=2)
    print(f"Fertig -> {out_dir}/map.png, biomes.png, collision.png")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=2048)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="output")
    args = ap.parse_args()
    generate(args.size, args.seed, args.out)
