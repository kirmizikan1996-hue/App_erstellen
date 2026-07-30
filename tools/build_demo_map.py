#!/usr/bin/env python3
"""Baut die Demo-Szene "Dorf auf der Waldlichtung" als Tiled-JSON.

Komposition statt Zufallsstreuung:
  - dichter Waldrand als natürlicher Rahmen (erzeugt Geborgenheit)
  - Dorfplatz mit Brunnen als Blickfang im Zentrum
  - Häuser um den Platz, Türen zum Platz orientiert
  - eingezäuntes Feld, Teich, schmale Wege zwischen den Orten
  - Deko in Clustern (Blumen bei Häusern, hohes Gras am Waldrand)

Aufruf:  python3 tools/build_demo_map.py --seed 5 --out maps/demo_village.json
"""
import argparse
import json
import os

import numpy as np

META = json.load(open("assets/tilesets/basic/tileset_meta.json"))
ID, SPR = META["ids"], META["sprites"]
GRASS, WATER, DIRTT = 0, 1, 2


# ------------------------------------------------------------ Terrain

def blob(corner, cy, cx, r, value, rng, wobble=0.18):
    yy, xx = np.mgrid[0:corner.shape[0], 0:corner.shape[1]]
    d = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2)
    corner[d < r * (1 + rng.normal(0, wobble, d.shape))] = value


def smooth_terrain(corner, terrain, passes=2):
    for _ in range(passes):
        mask = (corner == terrain).astype(int)
        n = sum(np.roll(np.roll(mask, dy, 0), dx, 1)
                for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx)
        corner[(corner == terrain) & (n <= 2)] = GRASS
        corner[(corner == GRASS) & (n >= 7)] = terrain
    return corner


def path(corner, a, b, rng):
    """Schmaler, leicht geschwungener Weg auf dem Ecken-Gitter."""
    steps = int(np.hypot(b[0] - a[0], b[1] - a[1]) * 3) + 1
    bend = rng.normal(0, 1.2)
    for i in range(steps + 1):
        t = i / steps
        y = a[0] + (b[0] - a[0]) * t + np.sin(t * np.pi) * bend
        x = a[1] + (b[1] - a[1]) * t + np.sin(t * np.pi * 2) * bend * 0.5
        y, x = int(round(y)), int(round(x))
        for dy in (0, 1):
            for dx in (0, 1):
                yy, xx = y + dy, x + dx
                if 0 <= yy < corner.shape[0] and 0 <= xx < corner.shape[1]:
                    if corner[yy, xx] == GRASS:
                        corner[yy, xx] = DIRTT


def path_L(corner, a, b, rng, via="v"):
    """L-förmige Route (erst vertikal, dann horizontal oder umgekehrt) —
    wirkt wie ein angelegter Dorfweg, vermeidet breite Diagonal-Treppen."""
    mid = (b[0], a[1]) if via == "v" else (a[0], b[1])
    path(corner, a, mid, rng)
    path(corner, mid, b, rng)


def wang_index(nw, ne, sw, se, terrain):
    return ((nw == terrain) * 1 + (ne == terrain) * 2 +
            (sw == terrain) * 4 + (se == terrain) * 8)


def ground_from_corners(corner, rng):
    h, w = corner.shape[0] - 1, corner.shape[1] - 1
    out = np.zeros((h, w), dtype=int)
    gvar = [ID["grass_1"], ID["grass_2"], ID["grass_3"]]
    for y in range(h):
        for x in range(w):
            c4 = (corner[y, x], corner[y, x + 1], corner[y + 1, x], corner[y + 1, x + 1])
            if WATER in c4:
                wi = wang_index(*c4, WATER)
                out[y, x] = ID["water"] if wi == 15 else ID[f"water_grass_{wi}"]
            elif DIRTT in c4:
                di = wang_index(*c4, DIRTT)
                out[y, x] = ID["dirt"] if di == 15 else ID[f"dirt_grass_{di}"]
            else:
                out[y, x] = gvar[rng.choice(3, p=[0.72, 0.18, 0.10])]
    return out


# ------------------------------------------------------------ Objekte

class Scene:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.deco = np.full((h, w), -1, dtype=int)
        self.overlay = np.full((h, w), -1, dtype=int)  # Baumkronen etc. über allem
        self.occupied = np.zeros((h, w), dtype=bool)
        self.collision = np.zeros((h, w), dtype=bool)

    def free(self, y, x, h, w):
        if y < 0 or x < 0 or y + h > self.h or x + w > self.w:
            return False
        return not self.occupied[y:y + h, x:x + w].any()

    def stamp(self, name, y, x, collide="all", walk_under_top=False):
        s = SPR[name]
        ids = np.array(s["tiles"])
        h, w = s["h"], s["w"]
        target = self.deco
        if walk_under_top:  # oberste Reihe (Baumkrone) über Spieler-Layer
            self.overlay[y, x:x + w] = ids[0]
            self.deco[y + 1:y + h, x:x + w] = ids[1:]
        else:
            target[y:y + h, x:x + w] = ids
        self.occupied[y:y + h, x:x + w] = True
        if collide == "all":
            self.collision[y:y + h, x:x + w] = True
        elif collide == "bottom":
            self.collision[y + h - 1:y + h, x:x + w] = True
        return True

    def put(self, tile_name, y, x, collide=False):
        if not self.free(y, x, 1, 1):
            return False
        self.deco[y, x] = ID[tile_name]
        self.occupied[y, x] = True
        self.collision[y, x] |= collide
        return True


def place_house(scene, name, y, x):
    """Haus stempeln; Rückgabe: Türvorplatz-Tile (begehbar)."""
    s = SPR[name]
    scene.stamp(name, y, x)
    door_x = x + s["w"] // 2
    door_y = y + s["h"] - 1
    scene.collision[door_y, door_x] = False        # Türtile begehbar (Eingang)
    return (door_y + 1, door_x)


# ------------------------------------------------------------ Szene

def build(seed=5, width=48, height=36, out="maps/demo_village.json"):
    rng = np.random.default_rng(seed)
    w, h = width, height
    corner = np.full((h + 1, w + 1), GRASS, dtype=int)
    scene = Scene(w, h)

    # --- Teich unten rechts
    blob(corner, h - 7, w - 9, 5.5, WATER, rng)
    smooth_terrain(corner, WATER)

    # --- Häuser um den Platz (Türen zeigen zum Platz)
    plaza = (h // 2 - 1, w // 2 - 2)  # Platz-Zentrum (Tile)
    d1 = place_house(scene, "house_a", plaza[0] - 9, plaza[1] - 7)
    d2 = place_house(scene, "house_b", plaza[0] - 9, plaza[1] + 3)
    d3 = place_house(scene, "house_a", plaza[0] + 3, plaza[1] - 10)

    # --- Dorfplatz: Steinfläche (gerundet) + Brunnen
    py, px = plaza
    for y in range(py - 2, py + 4):
        for x in range(px - 3, px + 5):
            if (y - py - 0.5) ** 2 / 9 + (x - px - 0.5) ** 2 / 16 < 1.15:
                scene.put("stone_1" if rng.random() < 0.7 else "stone_2", y, x)
    scene.stamp("well", py - 1, px, collide="all")

    # --- Feld mit Zaun und Setzlingen
    fy, fx, fh, fw = h - 10, 6, 6, 10
    for y in range(fy + 1, fy + fh - 1):
        for x in range(fx + 1, fx + fw - 1):
            corner[y:y + 2, x:x + 2] = DIRTT
    for x in range(fx, fx + fw):
        if x != fx + fw // 2:  # Gatter-Lücke oben
            scene.put("fence_h", fy, x, collide=True)
        scene.put("fence_h", fy + fh - 1, x, collide=True)
    for y in range(fy + 1, fy + fh - 1):
        scene.put("fence_v", y, fx, collide=True)
        scene.put("fence_v", y, fx + fw - 1, collide=True)
    gate = (fy, fx + fw // 2)

    # --- Wege: Türen -> Platz, Platz -> Feldgatter, Teich, Südausgang
    plaza_edge = (py + 3, px + 1)
    for a in (d1, d2, d3):
        path(corner, a, (py - 2 if a[0] < py else py + 3, a[1]), rng)
    path_L(corner, (py + 3, px - 2), (gate[0] - 1, gate[1]), rng, via="v")
    path_L(corner, (py + 1, px + 5), (h - 7, w - 9), rng, via="h")  # zum Teichufer
    path(corner, (py + 3, px + 1), (h - 1, px + 3), rng)            # Südausgang

    ground = ground_from_corners(corner, rng)

    # Boden-Tiles unter Platz/Deko nicht mit Wegen kollidieren lassen:
    # (Platz-Steine liegen im Deko-Layer über dem Boden -> nichts zu tun)

    # --- Waldrand: außen eine geschlossene Waldwand (sequenziell dicht
    #     gepackt), nach innen schnell ausdünnend zu Einzelbäumen
    grass_ids = [ID["grass_1"], ID["grass_2"], ID["grass_3"]]

    def try_tree(y, x):
        big = rng.random() < 0.8
        sh, sw = (2, 2) if big else (2, 1)
        if not scene.free(y, x, sh, sw):
            return
        if not np.isin(ground[y:y + sh, x:x + sw], grass_ids).all():
            return
        name = rng.choice(["tree_a", "tree_b", "tree_c"]) if big \
            else rng.choice(["pine_a", "pine_b"])
        scene.stamp(name, y, x, collide="bottom", walk_under_top=True)

    # dichte Wand: Randstreifen sequenziell scannen -> lückenloses Packen
    for y in range(h - 1):
        for x in range(w - 1):
            dist = min(y, x, h - 2 - y, w - 2 - x)
            if dist < 5 and rng.random() < (0.97 - dist * 0.09):
                try_tree(y, x)
    # Ausläufer: vereinzelte Bäume in der Lichtung
    order = [(y, x) for y in range(4, h - 5) for x in range(4, w - 5)]
    rng.shuffle(order)
    for y, x in order:
        dist = min(y, x, h - 2 - y, w - 2 - x)
        if rng.random() < max(0.0, 0.30 - dist * 0.025):
            try_tree(y, x)

    # --- Deko-Cluster
    pure = np.isin(ground, grass_ids)

    def cluster(names, cy, cx, n, radius, collide=False):
        for _ in range(n * 3):
            y = int(cy + rng.normal(0, radius))
            x = int(cx + rng.normal(0, radius))
            if 0 <= y < h and 0 <= x < w and pure[y, x]:
                if scene.put(str(rng.choice(names)), y, x, collide=collide):
                    n -= 1
                    if n == 0:
                        return

    for dy_, dx_ in (d1, d2, d3):
        cluster(["flowers_red", "flowers_blue"], dy_, dx_, 4, 3)
    cluster(["tall_grass"], 8, w - 10, 7, 3)
    cluster(["tall_grass"], h - 6, 22, 6, 3)
    cluster(["bush", "rock"], h - 12, w - 16, 4, 4, collide=True)
    cluster(["flowers_blue", "tall_grass"], h - 9, w - 6, 4, 2)

    # --- Setzlinge ins Feld (über den Acker)
    for y in range(fy + 1, fy + fh - 1):
        for x in range(fx + 1, fx + fw - 1):
            if scene.deco[y, x] == -1 and ground[y, x] == ID["dirt"]:
                scene.deco[y, x] = ID["sprouts"]

    # --- Kollision: Wasser blockiert
    scene.collision |= np.isin(ground, [ID["water"]] +
                               [ID[f"water_grass_{i}"] for i in range(1, 16)])

    # ------------------------------------------------------------ Export
    def layer(name, data, lid, visible=True):
        return {"type": "tilelayer", "name": name, "id": lid,
                "width": w, "height": h, "opacity": 1, "visible": visible,
                "x": 0, "y": 0, "data": [int(v) + 1 for v in data.flatten()]}

    ts = META["tile_size"]
    tiled = {
        "type": "map", "version": "1.10", "orientation": "orthogonal",
        "renderorder": "right-down", "infinite": False,
        "width": w, "height": h, "tilewidth": ts, "tileheight": ts,
        "nextlayerid": 5, "nextobjectid": 1,
        "tilesets": [{
            "firstgid": 1, "name": "basic",
            "image": "../assets/tilesets/basic/tileset.png",
            "imagewidth": META["columns"] * ts,
            "imageheight": ((META["count"] + META["columns"] - 1) // META["columns"]) * ts,
            "tilewidth": ts, "tileheight": ts, "columns": META["columns"],
            "tilecount": META["count"], "margin": 0, "spacing": 0,
        }],
        "layers": [
            layer("ground", ground, 1),
            layer("decoration", scene.deco, 2),
            layer("overlay", scene.overlay, 3),   # Baumkronen: über dem Spieler rendern
            layer("collision", np.where(scene.collision, 1, -1), 4, visible=False),
        ],
    }
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(tiled, f)
    print(f"Szene ({w}x{h}, 4 Layer) -> {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=5)
    p.add_argument("--width", type=int, default=48)
    p.add_argument("--height", type=int, default=36)
    p.add_argument("--out", default="maps/demo_village.json")
    a = p.parse_args()
    build(a.seed, a.width, a.height, a.out)
