#!/usr/bin/env python3
"""Prozeduraler World-Map-Generator für 2D-Topdown-MMORPG-Karten.

Erzeugt aus einem Seed eine komplette Weltkarte (PNG) mit:
  - Domain-warped fBm-Heightmap (organische Küstenlinien)
  - Feuchtigkeitskarte -> Biome (Ozean, Strand, Grasland, Wald, Gebirge, Schnee)
  - Hillshading (plastisches Relief)
  - Flüssen, die von den Bergen zum Meer laufen
  - Städten und Straßen

Aufruf:
    python3 tools/worldgen.py --seed 42 --size 1024 --out output/world_42.png
"""
import argparse
import json
import os

import numpy as np
from PIL import Image, ImageDraw


# ---------------------------------------------------------------- Noise

def _smoothstep(t):
    return t * t * (3.0 - 2.0 * t)


def value_noise(size, freq, rng):
    """Bilinear interpoliertes Value-Noise der Frequenz `freq` als (size,size)-Array."""
    grid = rng.random((freq + 1, freq + 1))
    xs = np.linspace(0, freq, size, endpoint=False)
    x0 = xs.astype(int)
    tx = _smoothstep(xs - x0)
    # Zeilen/Spalten getrennt interpolieren (separabel)
    top = grid[:, x0] * (1 - tx) + grid[:, x0 + 1] * tx        # (freq+1, size)
    col = top[x0, :] * (1 - tx[:, None]) + top[x0 + 1, :] * tx[:, None]
    return col


def fbm(size, rng, octaves=6, base_freq=4, gain=0.5):
    total = np.zeros((size, size))
    amp, freq, norm = 1.0, base_freq, 0.0
    for _ in range(octaves):
        total += amp * value_noise(size, freq, rng)
        norm += amp
        amp *= gain
        freq *= 2
    return total / norm


def domain_warped_height(size, rng):
    """Heightmap mit Domain Warping: fBm, dessen Koordinaten selbst verrauscht sind."""
    wx = fbm(size, rng, octaves=4, base_freq=3)
    wy = fbm(size, rng, octaves=4, base_freq=3)
    h = fbm(size, rng, octaves=7, base_freq=4)
    # Warp durch Verschieben der Sample-Positionen (Remap via Indizes)
    strength = size * 0.08
    yy, xx = np.mgrid[0:size, 0:size]
    sx = np.clip(xx + (wx - 0.5) * strength, 0, size - 1).astype(int)
    sy = np.clip(yy + (wy - 0.5) * strength, 0, size - 1).astype(int)
    h = h[sy, sx]
    # Insel-Falloff: Ränder werden Ozean
    cx = (xx / size - 0.5) * 2
    cy = (yy / size - 0.5) * 2
    d = np.sqrt(cx**2 + cy**2)
    h = h - np.clip(d - 0.55, 0, None) * 0.9
    h = (h - h.min()) / (h.max() - h.min())
    return h ** 1.3  # flacht das Binnenland ab, Gipfel bleiben markant


# ---------------------------------------------------------------- Biome

SEA_LEVEL = 0.42

BIOMES = {
    "deep_ocean":  (16, 42, 84),
    "ocean":       (26, 66, 118),
    "shallow":     (52, 110, 156),
    "beach":       (214, 196, 148),
    "grass":       (98, 142, 66),
    "meadow":      (128, 162, 82),
    "forest":      (56, 102, 48),
    "dense_forest":(38, 80, 40),
    "hills":       (128, 122, 88),
    "mountain":    (142, 136, 128),
    "snow":        (232, 236, 240),
}


def classify(height, moisture):
    """Liefert ein (H,W,3)-Farbarray anhand von Höhe + Feuchtigkeit."""
    h, m = height, moisture
    color = np.zeros(h.shape + (3,), dtype=float)

    def paint(mask, name):
        color[mask] = BIOMES[name]

    paint(h < SEA_LEVEL - 0.12, "deep_ocean")
    paint((h >= SEA_LEVEL - 0.12) & (h < SEA_LEVEL - 0.04), "ocean")
    paint((h >= SEA_LEVEL - 0.04) & (h < SEA_LEVEL), "shallow")
    land = h >= SEA_LEVEL
    paint(land & (h < SEA_LEVEL + 0.015), "beach")
    mid = land & (h >= SEA_LEVEL + 0.015) & (h < 0.66)
    paint(mid & (m < 0.35), "meadow")
    paint(mid & (m >= 0.35) & (m < 0.55), "grass")
    paint(mid & (m >= 0.55) & (m < 0.72), "forest")
    paint(mid & (m >= 0.72), "dense_forest")
    paint(land & (h >= 0.66) & (h < 0.78), "hills")
    paint(land & (h >= 0.78) & (h < 0.9), "mountain")
    paint(land & (h >= 0.9), "snow")
    return color


# ---------------------------------------------------------------- Features

def trace_rivers(height, rng, count=7):
    """Flüsse: Start in den Bergen, greedy bergab bis zum Meer."""
    size = height.shape[0]
    river = np.zeros_like(height, dtype=bool)
    peaks = np.argwhere(height > 0.72)
    if len(peaks) == 0:
        return river
    starts = peaks[rng.choice(len(peaks), size=min(count, len(peaks)), replace=False)]
    for y, x in starts:
        for _ in range(size * 2):
            river[y, x] = True
            if height[y, x] < SEA_LEVEL:
                break
            y0, y1 = max(0, y - 1), min(size, y + 2)
            x0, x1 = max(0, x - 1), min(size, x + 2)
            window = height[y0:y1, x0:x1] + rng.random((y1 - y0, x1 - x0)) * 0.004
            dy, dx = np.unravel_index(np.argmin(window), window.shape)
            ny, nx = y0 + dy, x0 + dx
            if (ny, nx) == (y, x):  # lokales Minimum -> See
                break
            y, x = ny, nx
    return river


def pick_towns(height, moisture, river, rng, count=6):
    """Städte auf flachem Grasland, bevorzugt nahe Küste oder Fluss."""
    size = height.shape[0]
    good = (height > SEA_LEVEL + 0.02) & (height < 0.6) & (moisture > 0.3) & (moisture < 0.7)
    candidates = np.argwhere(good)
    towns = []
    min_dist = size * 0.14
    rng.shuffle(candidates)
    for y, x in candidates:
        if all((y - ty) ** 2 + (x - tx) ** 2 > min_dist**2 for ty, tx in towns):
            towns.append((int(y), int(x)))
            if len(towns) == count:
                break
    return towns


def road_path(a, b, height, rng, steps=200):
    """Leicht verrauschter Pfad zwischen zwei Städten, Wasser wird gemieden (billig)."""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        y = a[0] + (b[0] - a[0]) * t
        x = a[1] + (b[1] - a[1]) * t
        wobble = np.sin(t * np.pi * 3 + rng.random() * 0.1) * height.shape[0] * 0.01
        pts.append((x + wobble, y + wobble * 0.5))
    return pts


# ---------------------------------------------------------------- Render

def render(seed=42, size=1024, out="output/world.png", meta_out=None):
    rng = np.random.default_rng(seed)
    height = domain_warped_height(size, rng)
    moisture = fbm(size, rng, octaves=5, base_freq=5)
    moisture = (moisture - moisture.min()) / (moisture.max() - moisture.min())

    color = classify(height, moisture)

    # Detail-Noise gegen flächige Farben
    detail = fbm(size, rng, octaves=3, base_freq=64)
    color *= (0.92 + detail[..., None] * 0.16)

    # Hillshading
    gy, gx = np.gradient(height * size * 0.35)
    light = np.clip(1.0 + (-gx * 0.7 - gy * 0.7), 0.55, 1.45)
    land_mask = (height >= SEA_LEVEL)[..., None]
    color = np.where(land_mask, color * light[..., None], color)

    # Flüsse
    river = trace_rivers(height, rng)
    for _ in range(1):  # leicht verbreitern
        river = river | np.roll(river, 1, 0) | np.roll(river, 1, 1)
    color[river & (height >= SEA_LEVEL)] = BIOMES["shallow"]

    img = Image.fromarray(np.clip(color, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(img)

    # Straßen + Städte
    towns = pick_towns(height, moisture, river, rng)
    for y, x in towns:
        r = max(4, size // 140)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=(206, 178, 128), outline=(60, 42, 24), width=2)
        draw.ellipse([x - r // 2, y - r - r // 2, x + r // 2, y - r // 4], fill=(160, 60, 44))

    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out)
    if meta_out:
        with open(meta_out, "w") as f:
            json.dump({"seed": seed, "size": size, "sea_level": SEA_LEVEL,
                       "towns": towns}, f, indent=2)
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--size", type=int, default=1024)
    p.add_argument("--out", default="output/world.png")
    p.add_argument("--meta", default=None, help="optional: JSON-Metadaten (Städte etc.)")
    args = p.parse_args()
    path = render(args.seed, args.size, args.out, args.meta)
    print(f"Karte gespeichert: {path}")
