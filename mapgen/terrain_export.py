"""Exportiert das Karten-Layout als Daten fuer den Blender-Renderer.

Nutzt die Layout-Logik aus channel_map.py (runde Inseln, Schluchten,
Spannbaum-Bruecken) und schreibt statt eines gemalten Bildes:
  height.png      16-bit Hoehenkarte (Plateaus hoch, Schlucht tief)
  path_mask.png   Wege (weiss = Weg)
  plaza_mask.png  Plaetze (weiss = gepflastert)
  layout.json     Bruecken, Felsen, Doerfer, Spawns, Baeume
  collision.png   Begehbarkeit fuer Unity

Aufruf:  python3 terrain_export.py [--size 2048] [--seed 11] [--islands 14]
"""

import argparse
import json
import math
import os

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter

from channel_map import (build_cells, choose_pois, collect_trees,
                         find_bridges, poisson_points, water_distance)


def chasm_depth(water, max_d=30):
    """Abstand ins Schluchtinnere (fuer die Tiefe der Waende)."""
    depth = np.zeros(water.shape, dtype=np.float32)
    inner = water.copy()
    for i in range(1, max_d):
        inner = ~((~inner) | np.roll(~inner, 1, 0) | np.roll(~inner, -1, 0)
                  | np.roll(~inner, 1, 1) | np.roll(~inner, -1, 1))
        depth[inner] = i
    return depth


def bezier(px, py, cx, cy, n=32):
    mx = (px + cx) / 2 + (py - cy) * 0.12
    my = (py + cy) / 2 - (px - cx) * 0.12
    pts = []
    for t in np.linspace(0, 1, n):
        bx = (1 - t) ** 2 * px + 2 * (1 - t) * t * mx + t * t * cx
        by = (1 - t) ** 2 * py + 2 * (1 - t) * t * my + t * t * cy
        pts.append((bx, by))
    return pts


def main(size, seed, islands, out_dir):
    rng = np.random.default_rng(seed)
    os.makedirs(out_dir, exist_ok=True)

    print("[1/5] Layout berechnen ...")
    seeds = poisson_points(size, islands, size * 0.05, rng)
    labels, water, _ = build_cells(size, seeds, rng)
    wdist = water_distance(water)
    bridges, touching = find_bridges(seeds, labels, water, rng)
    print(f"      {len(bridges)} Bruecken")

    print("[2/5] Hoehenkarte ...")
    depth = chasm_depth(water)
    h = np.zeros((size, size), dtype=np.float32)
    land = ~water
    # Plateau: leichte Kuppe zur Mitte + Mikrorelief
    plateau = np.clip(wdist.astype(np.float32) / 26, 0, 1) ** 0.6
    h[land] = 0.62 + plateau[land] * 0.05
    # Schlucht: steile Waende, unten flacher Boden
    h[water] = 0.62 - np.clip(depth[water] / 16, 0, 1) ** 0.75 * 0.55
    h = gaussian_filter(h, sigma=2.2)
    micro = gaussian_filter(rng.random((size, size)).astype(np.float32), 3) - 0.5
    h += micro * 0.012
    h16 = np.clip(h, 0, 1)
    Image.fromarray((h16 * 65535).astype(np.uint16)).save(
        os.path.join(out_dir, "height.png"))

    print("[3/5] Wege- und Platz-Masken ...")
    path_img = Image.new("L", (size, size), 0)
    pdraw = ImageDraw.Draw(path_img)
    ends_per_cell = {}
    for p0, p1, _w in bridges:
        for p in (p0, p1):
            xi = int(min(max(p[0], 0), size - 1))
            yi = int(min(max(p[1], 0), size - 1))
            ends_per_cell.setdefault(int(labels[yi, xi]), []).append(p)
    for cell, ends in ends_per_cell.items():
        cy, cx = seeds[cell]
        for (px, py) in ends:
            pdraw.line(bezier(px, py, cx, cy), fill=255, width=13,
                       joint="curve")
    for a, b in touching:
        pdraw.line(bezier(seeds[a][1], seeds[a][0], seeds[b][1], seeds[b][0]),
                   fill=255, width=13, joint="curve")

    plaza_img = Image.new("L", (size, size), 0)
    zdraw = ImageDraw.Draw(plaza_img)
    spacing = size / math.sqrt(len(seeds))
    n_villages = max(3, len(seeds) // 12)
    capital, villages = choose_pois(seeds, size, n_villages)
    cy, cx = seeds[capital]
    zdraw.ellipse([cx - spacing * 0.3, cy - spacing * 0.3,
                   cx + spacing * 0.3, cy + spacing * 0.3], fill=255)
    for v in villages:
        vy, vx = seeds[v]
        zdraw.ellipse([vx - spacing * 0.16, vy - spacing * 0.16,
                       vx + spacing * 0.16, vy + spacing * 0.16], fill=255)
    from PIL import ImageFilter
    path_img = path_img.filter(ImageFilter.GaussianBlur(1.4))
    path_img.save(os.path.join(out_dir, "path_mask.png"))
    plaza_img.save(os.path.join(out_dir, "plaza_mask.png"))

    print("[4/5] Felsen, Spawns, Baeume ...")
    boulders = []
    step = 14
    for gy in range(0, size, step):
        for gx in range(0, size, step):
            x = int(gx + rng.integers(step))
            y = int(gy + rng.integers(step))
            if x >= size or y >= size or not land[y, x]:
                continue
            if 2 <= wdist[y, x] <= 9 and rng.random() < 0.65:
                boulders.append({"x": x, "y": y,
                                 "s": round(0.8 + rng.random() * 1.6, 2)})
    spawn_cells = [i for i in range(len(seeds))
                   if i != capital and i not in villages]
    rng.shuffle(spawn_cells)
    spawns = []
    for cell in spawn_cells[: max(3, len(seeds) // 3)]:
        sy, sx = seeds[cell]
        for _ in range(8):
            ox = sx + rng.normal(0, spacing * 0.2)
            oy = sy + rng.normal(0, spacing * 0.2)
            xi = int(min(max(ox, 0), size - 1))
            yi = int(min(max(oy, 0), size - 1))
            if labels[yi, xi] == cell and land[yi, xi] and wdist[yi, xi] > 10:
                spawns.append({"x": xi, "y": yi,
                               "radius": round(spacing * 0.1, 1)})
                break
    trees = collect_trees(land & (wdist >= 3), wdist, size, rng)

    print("[5/5] Speichern ...")
    bridge_meta = [{"x0": p0[0], "y0": p0[1], "x1": p1[0], "y1": p1[1],
                    "length": float(math.hypot(p1[0] - p0[0], p1[1] - p0[1]))}
                   for p0, p1, _w in bridges]
    with open(os.path.join(out_dir, "layout.json"), "w") as f:
        json.dump({"size": size, "seed": seed,
                   "capital": {"x": float(cx), "y": float(cy)},
                   "villages": [{"x": float(seeds[v][1]),
                                 "y": float(seeds[v][0])} for v in villages],
                   "monster_spawns": spawns,
                   "bridges": bridge_meta,
                   "boulders": boulders,
                   "trees": [{"x": x, "y": y, "scale": round(r / 5.5, 2)}
                             for x, y, r in trees]}, f)

    collision = Image.fromarray((water * 255).astype(np.uint8))
    cdraw = ImageDraw.Draw(collision)
    for b in bridge_meta:
        dx, dy = b["x1"] - b["x0"], b["y1"] - b["y0"]
        ln = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / ln * 9, dx / ln * 9
        cdraw.polygon([(b["x0"] + nx, b["y0"] + ny),
                       (b["x1"] + nx, b["y1"] + ny),
                       (b["x1"] - nx, b["y1"] - ny),
                       (b["x0"] - nx, b["y0"] - ny)], fill=0)
    collision.save(os.path.join(out_dir, "collision.png"))
    print(f"Fertig -> {out_dir} (Hoehe, Masken, layout.json, collision.png)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=2048)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--islands", type=int, default=14)
    ap.add_argument("--out", default="terrain_data")
    args = ap.parse_args()
    main(args.size, args.seed, args.islands, args.out)
