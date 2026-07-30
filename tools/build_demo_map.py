#!/usr/bin/env python3
"""Baut eine spielbare Demo-Map (Dorf am See) als Tiled-kompatibles JSON.

Kernidee: Die Map wird NICHT Tile für Tile von Hand gemalt, sondern als
High-Level-Beschreibung (See hier, Häuser dort, Wege dazwischen) — das
Autotiling wählt automatisch die korrekten Übergangs-Tiles (Wang-Ecken).

Aufruf:
    python3 tools/build_demo_map.py --seed 3 --out maps/demo_village.json
"""
import argparse
import json
import os

import numpy as np

META = json.load(open("assets/tilesets/basic/tileset_meta.json"))
ID = META["ids"]
GRASS, WATER, DIRTT = 0, 1, 2  # Terrain-Codes auf dem Ecken-Gitter


def blob(corner, cy, cx, r, value, rng, wobble=0.25):
    """Organischer Fleck auf dem Ecken-Gitter (verrauschter Kreis)."""
    yy, xx = np.mgrid[0:corner.shape[0], 0:corner.shape[1]]
    d = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    corner[d < r * (1 + rng.normal(0, wobble, d.shape))] = value


def path(corner, a, b, rng):
    """Leicht geschlängelter, schmaler Weg (2 Ecken breit = 1 Tile) zwischen
    zwei Punkten auf dem Ecken-Gitter."""
    steps = int(np.hypot(b[0] - a[0], b[1] - a[1]) * 3) + 1
    for i in range(steps + 1):
        t = i / steps
        y = a[0] + (b[0] - a[0]) * t + np.sin(t * np.pi * 2) * 0.8
        x = a[1] + (b[1] - a[1]) * t + np.cos(t * np.pi * 3) * 0.6
        y, x = int(round(y)), int(round(x))
        for dy in (0, 1):
            for dx in (0, 1):
                yy, xx = y + dy, x + dx
                if 0 <= yy < corner.shape[0] and 0 <= xx < corner.shape[1]:
                    if corner[yy, xx] == GRASS:
                        corner[yy, xx] = DIRTT


def smooth_terrain(corner, terrain, passes=2):
    """Majority-Filter: entfernt einzelne Ecken-Sprenkel (Mini-Inseln/Löcher)."""
    for _ in range(passes):
        n = np.zeros(corner.shape, dtype=int)
        mask = (corner == terrain).astype(int)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dy or dx:
                    n += np.roll(np.roll(mask, dy, 0), dx, 1)
        corner[(corner == terrain) & (n <= 2)] = GRASS
        corner[(corner == GRASS) & (n >= 7)] = terrain
    return corner


def wang_index(nw, ne, sw, se, terrain):
    """Bit-Kombination der 4 Ecken für ein Terrain (Bit gesetzt = Terrain da)."""
    return ((nw == terrain) * 1 + (ne == terrain) * 2 +
            (sw == terrain) * 4 + (se == terrain) * 8)


def ground_layer(corner, rng):
    """Ecken-Gitter (H+1,W+1) -> Tile-IDs (H,W) via Wang-Autotiling."""
    h, w = corner.shape[0] - 1, corner.shape[1] - 1
    out = np.zeros((h, w), dtype=int)
    grass_variants = [ID["grass_1"], ID["grass_2"], ID["grass_3"]]
    for y in range(h):
        for x in range(w):
            nw, ne = corner[y, x], corner[y, x + 1]
            sw, se = corner[y + 1, x], corner[y + 1, x + 1]
            corners = (nw, ne, sw, se)
            if WATER in corners:
                wi = wang_index(nw, ne, sw, se, WATER)
                out[y, x] = ID["water"] if wi == 15 else ID[f"water_grass_{wi}"]
            elif DIRTT in corners:
                di = wang_index(nw, ne, sw, se, DIRTT)
                out[y, x] = ID["dirt"] if di == 15 else ID[f"dirt_grass_{di}"]
            else:
                out[y, x] = rng.choice(grass_variants, p=[0.7, 0.2, 0.1])
    return out


def place_house(deco, collision, y, x, w=3):
    """Haus: Dachreihen + Wandreihe mit Tür in der Mitte."""
    deco[y, x:x + w] = ID["roof_top"]
    deco[y + 1, x] = ID["roof_left"]
    deco[y + 1, x + 1:x + w - 1] = ID["roof_mid"]
    deco[y + 1, x + w - 1] = ID["roof_right"]
    for i in range(w):
        kind = "wall_door" if i == w // 2 else "wall_window"
        deco[y + 2, x + i] = ID[kind]
    collision[y:y + 3, x:x + w] = True
    collision[y + 2, x + w // 2] = False  # Tür begehbar
    return (y + 3, x + w // 2)  # Türvorplatz (für Wege)


def build(seed=3, width=40, height=30, out="maps/demo_village.json"):
    rng = np.random.default_rng(seed)
    corner = np.full((height + 1, width + 1), GRASS, dtype=int)

    # See rechts unten + Fluss zum Nordrand
    blob(corner, height - 6, width - 8, 7, WATER, rng)
    path_pts = [(height - 12, width - 10), (10, width - 14), (0, width - 12)]
    for a, b in zip(path_pts, path_pts[1:]):
        for t in np.linspace(0, 1, 60):
            y = int(a[0] + (b[0] - a[0]) * t + rng.normal(0, 0.4))
            x = int(a[1] + (b[1] - a[1]) * t + np.sin(t * 6) * 1.5)
            if 0 <= y <= height and 0 <= x <= width:
                corner[max(0, y):y + 2, max(0, x):x + 2] = WATER
    smooth_terrain(corner, WATER)

    h, w = height, width
    deco = np.full((h, w), -1, dtype=int)
    collision = np.zeros((h, w), dtype=bool)

    # Häuser auf Grasflächen links/mittig
    doors = []
    for hy, hx, hw in [(5, 6, 3), (7, 16, 4), (14, 5, 3), (17, 14, 3)]:
        doors.append(place_house(deco, collision, hy, hx, hw))

    # Wege: Haus zu Haus + zum Seeufer
    for a, b in zip(doors, doors[1:]):
        path(corner, a, b, rng)
    path(corner, doors[-1], (h - 8, w - 16), rng)

    ground = ground_layer(corner, rng)

    # Deko: Bäume/Steine/Blumen nur auf reinem Gras, nicht auf Wegen/Häusern
    pure_grass = np.isin(ground, [ID["grass_1"], ID["grass_2"], ID["grass_3"]])
    free = pure_grass & (deco == -1)
    spots = np.argwhere(free)
    rng.shuffle(spots)
    n_tree = int(len(spots) * 0.10)
    for i, (y, x) in enumerate(spots[:n_tree]):
        deco[y, x] = rng.choice([ID["tree"], ID["pine"], ID["tree"]])
        collision[y, x] = True
    for y, x in spots[n_tree:n_tree + 14]:
        deco[y, x] = rng.choice([ID["rock"], ID["bush"],
                                 ID["flowers_red"], ID["flowers_blue"]])
        collision[y, x] |= deco[y, x] in (ID["rock"], ID["bush"])

    # Wasser ist nicht begehbar
    water_ids = [ID["water"]] + [ID[f"water_grass_{i}"] for i in range(16) if i != 0]
    collision |= np.isin(ground, water_ids)

    # ---- Tiled-JSON (gid = Tile-ID + 1; 0 = leer)
    def layer(name, data, lid):
        return {"type": "tilelayer", "name": name, "id": lid,
                "width": w, "height": h, "opacity": 1, "visible": True,
                "x": 0, "y": 0, "data": [int(v) + 1 for v in data.flatten()]}

    tiled = {
        "type": "map", "version": "1.10", "orientation": "orthogonal",
        "renderorder": "right-down", "infinite": False,
        "width": w, "height": h,
        "tilewidth": META["tile_size"], "tileheight": META["tile_size"],
        "nextlayerid": 4, "nextobjectid": 1,
        "tilesets": [{
            "firstgid": 1, "name": "basic",
            "image": "../assets/tilesets/basic/tileset.png",
            "imagewidth": META["columns"] * META["tile_size"],
            "imageheight": ((META["count"] + META["columns"] - 1)
                            // META["columns"]) * META["tile_size"],
            "tilewidth": META["tile_size"], "tileheight": META["tile_size"],
            "columns": META["columns"], "tilecount": META["count"],
            "margin": 0, "spacing": 0,
        }],
        "layers": [
            layer("ground", ground, 1),
            layer("decoration", np.where(deco >= 0, deco, -1), 2),
            layer("collision", np.where(collision, ID["rock"], -1), 3),
        ],
    }
    tiled["layers"][2]["visible"] = False  # Kollision nur logisch, nicht sichtbar

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(tiled, f)
    print(f"Map ({w}x{h} Tiles, 3 Layer) -> {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=3)
    p.add_argument("--width", type=int, default=40)
    p.add_argument("--height", type=int, default=30)
    p.add_argument("--out", default="maps/demo_village.json")
    a = p.parse_args()
    build(a.seed, a.width, a.height, a.out)
