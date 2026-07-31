#!/usr/bin/env python3
"""Baut aus dem Welt-Layout eine BEGEHBARE Zone als Tiled-Map (32 px Raster).

Warum ueberhaupt: Die gemalte PNG-Karte (zone_arena.py + ComfyUI) ist eine
Uebersichtskarte aus grosser Hoehe — dort ist eine ganze Stadt ~200 px breit,
waehrend ein einzelnes Haus im Spielmassstab schon 160 px hat. Auf so einer
Karte kann der Spieler nicht laufen (siehe docs/karten_learnings.md).

Dieses Skript schneidet eine Region aus dem Welt-Layout und baut sie im
echten Spielmassstab neu auf: Wege 4-6 Tiles breit, Arenen ~40 Tiles im
Durchmesser, Haeuser als 5x4-Sprites. Die Wege kommen aus layout.json,
damit Uebersichtskarte und Zone dieselbe Welt zeigen.

Aufruf:
    python3 mapgen/zone_tiles.py --center capital --out maps/zone_hauptstadt.json
    python3 mapgen/zone_tiles.py --center arena0 --tiles 128 --region 620
"""
import argparse
import json
import math
import os

import numpy as np
from PIL import Image

WATER, GRASS, DIRT, COBBLE, ARENA = 0, 1, 2, 3, 4


def load_meta(ts_dir):
    meta = json.load(open(os.path.join(ts_dir, "tileset_meta.json")))
    img = Image.open(os.path.join(ts_dir, "tileset.png"))
    meta["imagewidth"], meta["imageheight"] = img.size
    return meta


def pick_center(layout, name):
    if name == "capital":
        return layout["capital"]["x"], layout["capital"]["y"]
    for key, prefix in (("arenas", "arena"), ("villages", "village")):
        if name.startswith(prefix):
            i = int(name[len(prefix):])
            e = layout[key][i]
            return e["x"], e["y"]
    x, y = name.split(",")
    return float(x), float(y)


def disc(grid, cx, cy, r, value, wob=None):
    """Kreis in die Terrainmatrix stempeln, Rand leicht unregelmaessig."""
    H, W = grid.shape
    y0, y1 = max(0, int(cy - r) - 1), min(H, int(cy + r) + 2)
    x0, x1 = max(0, int(cx - r) - 1), min(W, int(cx + r) + 2)
    if y0 >= y1 or x0 >= x1:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d = np.hypot(yy - cy, xx - cx)
    rr = r
    if wob is not None:
        a = np.arctan2(yy - cy, xx - cx)
        rr = r * (1 + 0.06 * np.sin(a * 5 + wob) + 0.04 * np.sin(a * 3 - wob))
    grid[y0:y1, x0:x1][d <= rr] = value


def stroke(grid, pts, half, value):
    """Polylinie mit Breite in die Terrainmatrix zeichnen."""
    for i in range(1, len(pts)):
        (ax, ay), (bx, by) = pts[i - 1], pts[i]
        seg = math.hypot(bx - ax, by - ay)
        for t in np.linspace(0, 1, max(2, int(seg) + 2)):
            disc(grid, ax + (bx - ax) * t, ay + (by - ay) * t, half, value)


def corners(mask):
    """Eckenraster: Ecke gesetzt, wenn eines der 4 angrenzenden Tiles gesetzt."""
    H, W = mask.shape
    p = np.zeros((H + 2, W + 2), bool)
    p[1:-1, 1:-1] = mask
    return (p[:-1, :-1] | p[:-1, 1:] | p[1:, :-1] | p[1:, 1:])


def combos(mask):
    """Wang-Index je Tile aus den 4 Ecken (1=NW, 2=NE, 4=SW, 8=SE)."""
    c = corners(mask)
    return (c[:-1, :-1] * 1 + c[:-1, 1:] * 2
            + c[1:, :-1] * 4 + c[1:, 1:] * 8).astype(int)


def build(layout_path, collision_path, ts_dir, center_name, tiles, region, out,
          seed):
    rng = np.random.default_rng(seed)
    layout = json.load(open(layout_path))
    meta = load_meta(ts_dir)
    ids, sprites = meta["ids"], meta["sprites"]
    coll_img = np.asarray(Image.open(collision_path).convert("L"))
    world = layout["size"]

    cx, cy = pick_center(layout, center_name)
    scale = region / tiles                     # Welt-Pixel pro Tile
    ox, oy = cx - region / 2, cy - region / 2  # linke obere Ecke in Weltkoords
    print(f"Zone um ({cx:.0f}, {cy:.0f}) — {tiles}x{tiles} Tiles, "
          f"{scale:.2f} Welt-px pro Tile, {tiles * meta['tile_size']} px gross")

    def to_tile(wx, wy):
        return (wx - ox) / scale, (wy - oy) / scale

    terr = np.full((tiles, tiles), GRASS, dtype=np.int8)

    # --- Strassennetz aus dem Welt-Layout ----------------------------------
    for road in layout["roads"]:
        pts = [to_tile(px, py) for px, py in road["points"]]
        if all(not (-20 < x < tiles + 20 and -20 < y < tiles + 20) for x, y in pts):
            continue
        half = max(1.5, road["width"] / scale / 2)
        stroke(terr, pts, half, COBBLE if road["paved"] else DIRT)

    # --- Plaetze -----------------------------------------------------------
    spacing = world / math.sqrt(14)
    towns = [(layout["capital"], spacing * 0.21)]
    towns += [(v, spacing * 0.13) for v in layout["villages"]]
    towns_in = []
    for t, r_world in towns:
        tx, ty = to_tile(t["x"], t["y"])
        tr = r_world / scale
        if -tr < tx < tiles + tr and -tr < ty < tiles + tr:
            towns_in.append((tx, ty, tr))
            disc(terr, tx, ty, tr, COBBLE, wob=rng.random() * 6)

    # --- Arenen ZULETZT (vor dem Wasser) -----------------------------------
    # Die Schneisen sind aus demselben Material wie der Kampfboden. Zieht man
    # sie als Erdweg durch die Arena, zerschneiden sie die Flaeche in Fetzen —
    # und die Strassen wuerden sie ebenfalls ueberfahren.
    arenas_in = []
    for a in layout["arenas"]:
        ax, ay = to_tile(a["x"], a["y"])
        # Radius deckeln: 1:1 aus der Weltkarte waeren es >40 Tiles und die
        # Arena fraesse ein Drittel der Zone — Schneisen und Waldguertel
        # waeren dann nicht mehr als Form erkennbar.
        ar = min(a["radius"] / scale, tiles * 0.105)
        if -ar < ax < tiles + ar and -ar < ay < tiles + ar:
            arenas_in.append((ax, ay, ar, a["lane_angles_rad"]))
            disc(terr, ax, ay, ar, ARENA, wob=rng.random() * 6)
            for la in a["lane_angles_rad"]:      # vier Zugaenge nach aussen
                sx_, sy_ = ax + math.cos(la) * ar * 0.8, ay + math.sin(la) * ar * 0.8
                ex, ey = ax + math.cos(la) * ar * 1.5, ay + math.sin(la) * ar * 1.5
                stroke(terr, [(sx_, sy_), (ex, ey)], ar * 0.17, ARENA)

    # --- Wasser zuletzt: ueberschreibt alles, kein Weg im Meer -------------
    gy, gx = np.mgrid[0:tiles, 0:tiles]
    wx = np.clip(((gx + 0.5) * scale + ox).astype(int), 0, world - 1)
    wy = np.clip(((gy + 0.5) * scale + oy).astype(int), 0, world - 1)
    terr[coll_img[wy, wx] > 128] = WATER

    # --- Ground-Layer ------------------------------------------------------
    c_water = combos(terr == WATER)
    c_cobble = combos(terr == COBBLE)
    c_arena = combos(terr == ARENA)
    c_dirt = combos(terr == DIRT)

    grass_pool = [ids["grass_1"], ids["grass_2"], ids["grass_3"], ids["grass_4"]]
    flower_pool = [ids["grass_flowers_red"], ids["grass_flowers_blue"],
                   ids["grass_flowers_yellow"]]
    # Wang-Index 15 = Tile liegt komplett im Material. Dafuer die Varianten
    # nehmen, sonst besteht jede grosse Flaeche aus EINEM wiederholten Tile
    # und sieht wie Tapete aus.
    full = {
        "water": [ids["water"]],
        "cobble": [ids["cobble_1"], ids["cobble_2"]],
        "arena": [ids["arena_1"], ids["arena_2"]],
        "dirt": [ids["dirt_1"], ids["dirt_2"]],
    }

    def solid(kind):
        pool = full[kind]
        return pool[int(rng.integers(len(pool)))]

    ground = np.zeros((tiles, tiles), dtype=int)
    for y in range(tiles):
        for x in range(tiles):
            if c_water[y, x]:
                ground[y, x] = (solid("water") if c_water[y, x] == 15
                                else ids[f"water_grass_{c_water[y, x]}"])
            elif c_cobble[y, x]:
                ground[y, x] = (solid("cobble") if c_cobble[y, x] == 15
                                else ids[f"cobble_grass_{c_cobble[y, x]}"])
            elif c_arena[y, x]:
                ground[y, x] = (solid("arena") if c_arena[y, x] == 15
                                else ids[f"arena_grass_{c_arena[y, x]}"])
            elif c_dirt[y, x]:
                ground[y, x] = (solid("dirt") if c_dirt[y, x] == 15
                                else ids[f"dirt_grass_{c_dirt[y, x]}"])
            elif rng.random() < 0.05:
                ground[y, x] = flower_pool[int(rng.integers(3))]
            else:
                ground[y, x] = grass_pool[int(rng.integers(4))]

    deco = np.zeros((tiles, tiles), dtype=int)
    over = np.zeros((tiles, tiles), dtype=int)
    block = terr == WATER

    def free(x, y, w=1, h=1, pad=0):
        if x - pad < 0 or y - pad < 0 or x + w + pad > tiles or y + h + pad > tiles:
            return False
        area = terr[y - pad:y + h + pad, x - pad:x + w + pad]
        if np.any(area == WATER) or np.any(area == COBBLE):
            return False
        return not np.any(over[y - pad:y + h + pad, x - pad:x + w + pad])

    def put_sprite(name, x, y, blocking=True):
        s = sprites[name]
        for r_ in range(s["h"]):
            for c in range(s["w"]):
                over[y + r_, x + c] = s["tiles"][r_][c]
        if blocking:                       # nur der Fuss blockt, nicht die Krone
            block[y + s["h"] - 1, x:x + s["w"]] = True
            if s["h"] > 1:
                block[y + s["h"] - 2, x:x + s["w"]] = True

    # Reihenfolge ist wichtig: Bebauung zuerst, sonst belegt der Wald den
    # Platzrand und es passt kein Haus mehr hin.
    tree_names = ["tree_a", "tree_b", "tree_c", "pine_a", "pine_b"]
    n_trees = 0

    # --- Haeuser rund um die Plaetze ---------------------------------------
    house_names = ["house_a", "house_b", "house_c"]
    n_houses = 0
    for tx, ty, tr in towns_in:
        n_ring = max(10, int(tr * 1.1))          # Haeuser saeumen den Platz
        for k in range(n_ring):
            a = k * 2 * math.pi / n_ring + rng.random() * 0.18
            name = house_names[int(rng.integers(3))]
            s = sprites[name]
            # Abstand so, dass der GANZE Fussabdruck neben dem Pflaster liegt,
            # sonst faellt fast jedes Haus durch die free()-Pruefung
            clear = max(s["w"], s["h"]) / 2 + 2
            d = tr + clear + rng.random() * 5
            hx = int(tx + math.cos(a) * d - s["w"] / 2)
            hy = int(ty + math.sin(a) * d - s["h"] / 2)
            if free(hx, hy, s["w"], s["h"], pad=1) and terr[hy, hx] == GRASS:
                put_sprite(name, hx, hy)
                n_houses += 1
        wx_, wy_ = int(tx - 1), int(ty - 1)
        if free(wx_, wy_, 2, 2):
            put_sprite("well", wx_, wy_)

    # --- Baeume aus dem Welt-Layout ----------------------------------------
    for t in layout["trees"]:
        tx, ty = to_tile(t["x"], t["y"])
        x, y = int(tx), int(ty)
        name = tree_names[int(rng.integers(len(tree_names)))]
        s = sprites[name]
        if free(x, y, s["w"], s["h"]) and terr[y, x] == GRASS:
            put_sprite(name, x, y)
            n_trees += 1

    # --- Waldgruppen: die Welt-Baumliste ist zu duenn fuer Spielmassstab ---
    for _ in range(int(tiles * tiles * 0.004)):
        gxc, gyc = rng.integers(0, tiles, 2)
        for _ in range(int(rng.integers(4, 12))):    # Gruppe statt Einzelbaum
            x = int(gxc + rng.normal(0, 5))
            y = int(gyc + rng.normal(0, 5))
            name = tree_names[int(rng.integers(len(tree_names)))]
            s = sprites[name]
            if free(x, y, s["w"], s["h"]) and terr[y, x] == GRASS:
                put_sprite(name, x, y)
                n_trees += 1

    # --- Monsterlager in den Arenen ----------------------------------------
    for ax, ay, ar, lanes in arenas_in:
        # Waldguertel + Felsen als natuerliche Wand, offen NUR an den vier
        # Schneisen. Ohne diese Umschliessung ist die Arena bloss ein
        # Erdfleck im offenen Gras — erst die Wand macht daraus eine
        # Kampfflaeche, die man aus genau vier Richtungen betritt.
        for band in (1.06, 1.20, 1.34):
            n_ring = max(18, int(ar * band * 2.0))
            for k in range(n_ring):
                a = k * 2 * math.pi / n_ring + rng.random() * 0.06
                if any(abs(math.atan2(math.sin(a - la), math.cos(a - la))) < 0.40
                       for la in lanes):
                    continue
                x = int(ax + math.cos(a) * ar * band + rng.normal(0, 1.2))
                y = int(ay + math.sin(a) * ar * band + rng.normal(0, 1.2))
                if not (0 <= x < tiles and 0 <= y < tiles):
                    continue
                if rng.random() < 0.55:
                    name = tree_names[int(rng.integers(len(tree_names)))]
                    s = sprites[name]
                    if free(x, y, s["w"], s["h"]) and terr[y, x] == GRASS:
                        put_sprite(name, x, y)
                        n_trees += 1
                elif not over[y, x] and not deco[y, x] and terr[y, x] != WATER:
                    deco[y, x] = ids["boulder"]
                    block[y, x] = True
        for k in range(3):
            a = lanes[0] + 0.8 + k * 2.1
            d = ar * 0.62
            x, y = int(ax + math.cos(a) * d), int(ay + math.sin(a) * d)
            if free(x, y, 2, 2) and terr[y, x] == ARENA:
                put_sprite("tent", x, y)
        tx_, ty_ = int(ax + math.cos(lanes[1] + 0.5) * ar * 0.72), \
            int(ay + math.sin(lanes[1] + 0.5) * ar * 0.72)
        if free(tx_, ty_, 1, 2) and terr[ty_, tx_] == ARENA:
            put_sprite("totem", tx_, ty_)
        # Feuerstelle in der Mitte + Knochen ringsum
        if 0 <= int(ay) < tiles and 0 <= int(ax) < tiles:
            deco[int(ay), int(ax)] = ids["campfire"]
        # Dichte an der Flaeche ausrichten, nicht am Radius — sonst verliert
        # sich die Deko in einer 40 Tiles breiten Arena
        arena_props = [ids["bones"], ids["bones"], ids["skull"],
                       ids["boulder"], ids["tall_grass"], ids["campfire"]]
        for _ in range(int(math.pi * ar * ar * 0.07)):
            a, d = rng.random() * 2 * math.pi, ar * math.sqrt(rng.random()) * 0.92
            x, y = int(ax + math.cos(a) * d), int(ay + math.sin(a) * d)
            if 0 <= x < tiles and 0 <= y < tiles and terr[y, x] == ARENA \
                    and not over[y, x] and not deco[y, x]:
                p = arena_props[int(rng.integers(len(arena_props)))]
                deco[y, x] = p
                if p == ids["boulder"]:
                    block[y, x] = True

    # --- Streudeko auf der Wiese -------------------------------------------
    grass_props = [ids["bush"], ids["fern"], ids["mushrooms"], ids["log"],
                   ids["boulder"], ids["tall_grass"]]
    for _ in range(int(tiles * tiles * 0.05)):
        x, y = int(rng.integers(tiles)), int(rng.integers(tiles))
        if terr[y, x] == GRASS and not over[y, x] and not deco[y, x]:
            p = grass_props[int(rng.integers(len(grass_props)))]
            deco[y, x] = p
            if p in (ids["boulder"], ids["log"]):
                block[y, x] = True

    # --- Laternen an den Pflasterstrassen ----------------------------------
    for _ in range(int(tiles * tiles * 0.004)):
        x, y = int(rng.integers(1, tiles - 1)), int(rng.integers(1, tiles - 1))
        if terr[y, x] == GRASS and not over[y, x] and not deco[y, x] \
                and np.any(terr[y - 1:y + 2, x - 1:x + 2] == COBBLE):
            deco[y, x] = ids["lantern"]

    # --- Tiled-JSON --------------------------------------------------------
    ts_rel = os.path.relpath(os.path.join(ts_dir, "tileset.png"),
                             os.path.dirname(os.path.abspath(out))
                             ).replace("\\", "/")

    def layer(name, arr, lid, visible=True, dense=False):
        # dense=True: jede Zelle ist ein echtes Tile. Noetig, weil Tile-Index 0
        # (grass_1) sonst als "leer" durchfaellt und schwarze Loecher gibt.
        data = ([int(v) + 1 for v in arr.flatten()] if dense
                else [int(v) + 1 if v else 0 for v in arr.flatten()])
        return {"id": lid, "name": name, "type": "tilelayer", "visible": visible,
                "opacity": 1, "x": 0, "y": 0, "width": tiles, "height": tiles,
                "data": data}

    tmap = {
        "type": "map", "version": "1.10", "tiledversion": "1.10.2",
        "orientation": "orthogonal", "renderorder": "right-down",
        "infinite": False, "width": tiles, "height": tiles,
        "tilewidth": meta["tile_size"], "tileheight": meta["tile_size"],
        "nextlayerid": 5, "nextobjectid": 1,
        "properties": [
            {"name": "world_origin_x", "type": "float", "value": round(ox, 2)},
            {"name": "world_origin_y", "type": "float", "value": round(oy, 2)},
            {"name": "world_px_per_tile", "type": "float", "value": round(scale, 4)},
        ],
        "tilesets": [{
            "firstgid": 1, "name": "painted", "image": ts_rel,
            "imagewidth": meta["imagewidth"], "imageheight": meta["imageheight"],
            "tilewidth": meta["tile_size"], "tileheight": meta["tile_size"],
            "columns": meta["columns"], "tilecount": meta["count"],
            "margin": 0, "spacing": 0}],
        "layers": [layer("ground", ground, 1, dense=True),
                   layer("decoration", deco, 2), layer("overlay", over, 3),
                   layer("collision", block.astype(int), 4, visible=False)],
    }
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as f:
        json.dump(tmap, f)

    px = tiles * meta["tile_size"]
    print(f"  {n_trees} Baeume, {n_houses} Haeuser, {len(arenas_in)} Arenen, "
          f"{len(towns_in)} Orte")
    print(f"  blockiert: {block.mean() * 100:.0f} % der Flaeche")
    print(f"Fertig -> {out}  ({tiles}x{tiles} Tiles = {px}x{px} px)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--layout", default="mapgen/zone_arena/layout.json")
    ap.add_argument("--collision", default="mapgen/zone_arena/collision.png")
    ap.add_argument("--tileset", default="assets/tilesets/painted")
    ap.add_argument("--center", default="capital",
                    help="capital | arena0.. | village0.. | x,y")
    ap.add_argument("--tiles", type=int, default=128)
    ap.add_argument("--region", type=float, default=620,
                    help="Wieviel Welt-Pixel die Zone abdeckt")
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--out", default="maps/zone_hauptstadt.json")
    a = ap.parse_args()
    build(a.layout, a.collision, a.tileset, a.center, a.tiles, a.region,
          a.out, a.seed)
