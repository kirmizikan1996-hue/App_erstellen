#!/usr/bin/env python3
"""Komponierte Spielzone — bewusst gestaltet statt zufaellig gestreut.

Warum neu: Die aus der Weltkarte geschnittene Zone (zone_tiles.py) ist
langweilig — ein runder Platz, ein Ring gleicher Haeuser, ueberall dasselbe
Gras, Strassen die sternfoermig vom Zentrum wegzeigen. Kein Denoise-Wert
repariert ein langweiliges Layout.

Was eine Zone interessant macht und hier drinsteckt:
  * Terrainvielfalt   Meer, Fluss, Strand, Acker, Hochland-Fels, Wiese
  * Hoehenstruktur    Plateau im Nordwesten, nur ueber einen Pass erreichbar
  * Engstellen        Fluss teilt die Zone, zwei Bruecken sind die Uebergaenge
  * Landmarken        Stadt an der Furt, Arena in einer Felssenke, Ruine oben
  * Wege mit Grund    die Strasse kurvt um Fels und Fluss, nicht ins Nichts
  * Stadt mit Strassen statt Ring: Hauptstrasse, Querstrassen, Marktplatz

Baeume kommen bewusst NICHT vor — das Terrain muss ohne sie tragen.

Aufruf:  python3 mapgen/zone_compose.py --out maps/zone_furt.json
"""
import argparse
import json
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zone_tiles import combos, load_meta

WATER, GRASS, DIRT, COBBLE, ARENA, SAND, ROCK, FARM = range(8)


# --------------------------------------------------------- Distanzfelder ----
# Terrain wird NICHT durch aneinandergereihte Kreise gestempelt — das gibt
# ausgefranste Treppenraender und Wege, die wie Matschflecken aussehen.
# Stattdessen: Abstand zur Mittellinie bzw. zum Zentrum ausrechnen und
# schwellen. Ergebnis: konstante Wegbreite, glatte Kanten.

def _vnoise(N, cells, rng):
    g = rng.random((cells + 2, cells + 2))
    s = np.linspace(0, cells, N, endpoint=False)
    i = s.astype(int)
    f = s - i
    f = f * f * (3 - 2 * f)
    a, b = g[np.ix_(i, i)], g[np.ix_(i, i + 1)]
    c, d = g[np.ix_(i + 1, i)], g[np.ix_(i + 1, i + 1)]
    fy, fx = f[:, None], f[None, :]
    return (a * (1 - fx) * (1 - fy) + b * fx * (1 - fy)
            + c * (1 - fx) * fy + d * fx * fy)


def fbm2(N, rng, base=4, oct_=3):
    out, amp, tot, c = 0.0, 1.0, 0.0, base
    for _ in range(oct_):
        out = out + _vnoise(N, c, rng) * amp
        tot += amp
        amp *= 0.5
        c *= 2
    return out / tot


def dist_to_path(N, pts):
    """Abstand jedes Feldes zur Polylinie — Grundlage fuer saubere Wege."""
    yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
    best = np.full((N, N), 1e9, dtype=np.float32)
    for i in range(1, len(pts)):
        ax, ay = pts[i - 1]
        bx, by = pts[i]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 < 1e-9:
            continue
        t = np.clip(((xx - ax) * dx + (yy - ay) * dy) / L2, 0, 1)
        best = np.minimum(best, np.hypot(xx - (ax + t * dx), yy - (ay + t * dy)))
    return best


def blob_field(N, cx, cy, r, rng, rough=0.20, cells=3):
    """Radialer Abstand mit welliger Kante — <0 heisst innen."""
    yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
    n = fbm2(N, rng, cells, 3) - 0.5
    return np.hypot(xx - cx, yy - cy) - r * (1.0 + rough * 2.0 * n)


def lay(terr, mask, value):
    terr[mask] = value


def bez(p0, p1, p2, n=60):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
            for t in np.linspace(0, 1, n)]


def wobble(pts, rng, amp=1.6):
    """Leichtes Schlenkern — perfekt gerade Linien wirken tot."""
    out = []
    for i, (x, y) in enumerate(pts):
        f = math.sin(i * 0.35) * amp + rng.normal(0, amp * 0.3)
        out.append((x + f, y - f * 0.5))
    return out


def compose(N, rng):
    """Baut das Terrainraster. Alles hier ist Absicht, nichts ist gestreut."""
    terr = np.full((N, N), GRASS, dtype=np.int8)
    plan = {}

    def road(pts, half, surface, shoulder=None):
        """Weg mit konstanter Breite; optional ein Saum aus Erde daneben."""
        d = dist_to_path(N, pts)
        if shoulder is not None:
            lay(terr, d <= half + shoulder, DIRT)
        lay(terr, d <= half, surface)
        return d

    # --- Hochland-Plateau im Nordwesten ------------------------------------
    hx, hy, hr = N * 0.20, N * 0.18, N * 0.23
    plateau = blob_field(N, hx, hy, hr, rng, rough=0.26)
    lay(terr, plateau < 0, ROCK)
    plan["plateau"] = (hx, hy, hr)

    # Grasinseln auf dem Plateau: eine einfarbige Felsflaeche ist tot
    for _ in range(7):
        a, d = rng.random() * 2 * math.pi, hr * rng.random() * 0.8
        gx, gy = hx + math.cos(a) * d, hy + math.sin(a) * d
        patch = blob_field(N, gx, gy, hr * (0.10 + rng.random() * 0.13), rng, 0.4)
        lay(terr, (patch < 0) & (plateau < 0), GRASS)

    # Der Pass: die einzige Rampe aufs Plateau — Engstelle mit Absicht
    pass_pts = wobble(bez((hx + hr * 0.34, hy + hr * 0.70),
                          (hx + hr * 0.60, hy + hr * 0.98),
                          (hx + hr * 0.66, hy + hr * 1.45)), rng, 1.0)
    lay(terr, dist_to_path(N, pass_pts) <= 3.4, GRASS)
    plan["pass"] = pass_pts

    # --- Arena in einer Felssenke oestlich des Flusses ---------------------
    ax, ay, ar = N * 0.79, N * 0.30, N * 0.105
    bowl = blob_field(N, ax, ay, ar * 1.65, rng, rough=0.16)
    lay(terr, bowl < 0, ROCK)
    lay(terr, blob_field(N, ax, ay, ar, rng, rough=0.12) < 0, ARENA)
    lanes = [i * math.pi / 2 + 0.42 for i in range(4)]
    for la in lanes:                          # vier Schneisen durch den Wall
        p0 = (ax + math.cos(la) * ar * 0.6, ay + math.sin(la) * ar * 0.6)
        p1 = (ax + math.cos(la) * ar * 2.0, ay + math.sin(la) * ar * 2.0)
        lay(terr, dist_to_path(N, [p0, p1]) <= 2.4, ARENA)
    plan["arena"] = (ax, ay, ar, lanes)

    # --- Aecker westlich der Stadt, leicht unregelmaessig ------------------
    fields = []
    fx0, fy0 = N * 0.14, N * 0.60
    for r_ in range(2):
        for c_ in range(3):
            w = int(N * (0.070 + rng.random() * 0.020))
            h = int(N * (0.058 + rng.random() * 0.018))
            x0 = int(fx0 + c_ * N * 0.098 + rng.integers(-3, 4))
            y0 = int(fy0 + r_ * N * 0.088 + rng.integers(-3, 4))
            if x0 < 1 or y0 < 1 or x0 + w > N - 1 or y0 + h > N - 1:
                continue
            terr[y0:y0 + h, x0:x0 + w] = FARM
            fields.append((x0, y0, w, h))
    plan["fields"] = fields

    # --- Strassennetz ------------------------------------------------------
    tx, ty = N * 0.42, N * 0.60          # Stadt am Westufer der Furt
    bridges = [(N * 0.615, N * 0.26), (N * 0.585, N * 0.62)]
    plan["town"], plan["bridges"] = (tx, ty), bridges

    # Genau der Punkt, an dem die Fernstrasse zur Hauptstrasse wird. Enden
    # sie versetzt, laufen beide ein Stueck parallel und die Stadteinfahrt
    # wird doppelt so breit wie gewollt.
    gate = (tx - N * 0.13, ty + N * 0.02)

    roads = []
    # Fernstrasse: Westrand -> an den Aeckern vorbei -> Stadttor
    roads.append((wobble(bez((-3, ty + N * 0.13), (N * 0.22, ty + N * 0.10),
                             gate), rng, 1.2), 2.4, True))
    # ueber die Furt nach Osten zur Arena
    east = wobble(bez((bridges[1][0], bridges[1][1]),
                      (bridges[1][0] + N * 0.13, bridges[1][1] - N * 0.10),
                      (ax - ar * 1.9, ay + ar * 1.4)), rng, 1.6)
    roads.append((east, 2.6, True))
    # Gabelung nach Sueden an die Kueste
    mid = east[len(east) // 2]
    roads.append((wobble(bez(mid, (N * 0.88, N * 0.66), (N * 0.66, N * 0.86)),
                         rng, 1.8), 2.0, False))
    # Stadt -> Nordfurt
    roads.append((wobble(bez((tx + N * 0.02, ty - N * 0.07),
                             (N * 0.50, N * 0.38), bridges[0]), rng, 1.4),
                  2.2, False))
    # Stadt -> Pass hinauf aufs Plateau
    roads.append((wobble(bez((tx - N * 0.03, ty - N * 0.08),
                             (N * 0.30, N * 0.42),
                             pass_pts[len(pass_pts) // 2]), rng, 1.2), 2.0, False))
    for pts, half, paved in roads:
        road(pts, half, COBBLE if paved else DIRT,
             shoulder=1.3 if paved else None)
    plan["roads"] = roads

    # --- Stadt: Hauptstrasse, zwei Querstrassen, Marktplatz ----------------
    # Strassen OHNE Saum und weit auseinander: mit Saum und eng gesetzt
    # verschmelzen Hauptstrasse, Querstrassen und Platz zu einer einzigen
    # Pflasterflaeche — dann gibt es keine Strassen mehr, nur noch Belag.
    main_st = wobble(bez(gate, (tx, ty),
                         (bridges[1][0], bridges[1][1])), rng, 0.8)
    road(main_st, 2.0, COBBLE)
    cross = []
    for off, ln in ((-N * 0.090, N * 0.075), (N * 0.080, N * 0.070)):
        c = wobble(bez((tx + off, ty - ln), (tx + off * 1.10, ty),
                       (tx + off * 0.85, ty + ln)), rng, 0.6)
        road(c, 1.5, COBBLE)
        cross.append(c)
    sq = N * 0.026                       # kleiner Marktplatz an der Kreuzung
    terr[int(ty - sq):int(ty + sq),
         int(tx - sq * 1.4):int(tx + sq * 1.4)] = COBBLE
    plan["main_st"], plan["cross"], plan["square"] = main_st, cross, (tx, ty, sq)

    # --- Fluss: Sandufer, dann Wasser --------------------------------------
    river = wobble(bez((N * 0.66, -3), (N * 0.70, N * 0.42),
                       (N * 0.60, N * 0.95)), rng, 2.2)
    dr = dist_to_path(N, river)
    lay(terr, dr <= 5.2, SAND)
    lay(terr, dr <= 2.6, WATER)
    plan["river"] = river

    # --- Meer im Suedosten mit Strandsaum ----------------------------------
    # Mittelpunkt weit ausserhalb + grosser Radius: so schneidet die Kueste
    # nur die Suedost-Ecke ab. Ein naeherer Mittelpunkt flutet die halbe Zone.
    sea = blob_field(N, N * 1.90, N * 1.90, N * 1.62, rng, rough=0.05, cells=2)
    lay(terr, sea < 7.5, SAND)
    lay(terr, sea < 0, WATER)
    plan["coast"] = sea

    # --- Furten: begehbarer Steg ueber den Fluss ---------------------------
    for (bx, by) in bridges:
        lay(terr, dist_to_path(N, [(bx - 8, by), (bx + 8, by)]) <= 2.2, DIRT)

    # --- Wiese aufbrechen --------------------------------------------------
    # Ohne das sind ueber 50 % der Zone dieselbe gruene Flaeche — der
    # groesste Langeweile-Treiber. Also Felsnasen, Tuempel und ausgetretene
    # Lichtungen streuen, aber nur dort, wo nichts Gebautes liegt.
    def open_meadow(px, py, r):
        y0, y1 = max(0, int(py - r * 2)), min(N, int(py + r * 2))
        x0, x1 = max(0, int(px - r * 2)), min(N, int(px + r * 2))
        return np.all(np.isin(terr[y0:y1, x0:x1], (GRASS, ROCK)))

    outcrops = []
    for _ in range(90):
        if len(outcrops) >= 9:
            break
        px, py = rng.random() * N, rng.random() * N
        r = N * (0.016 + rng.random() * 0.026)
        if terr[int(py), int(px)] != GRASS or not open_meadow(px, py, r):
            continue
        lay(terr, blob_field(N, px, py, r, rng, rough=0.5) < 0, ROCK)
        outcrops.append((px, py, r))

    ponds = []
    for _ in range(60):
        if len(ponds) >= 3:
            break
        px, py = rng.random() * N, rng.random() * N
        r = N * (0.018 + rng.random() * 0.018)
        if terr[int(py), int(px)] != GRASS or not open_meadow(px, py, r * 1.6):
            continue
        f = blob_field(N, px, py, r, rng, rough=0.35)
        lay(terr, f < 3.0, SAND)
        lay(terr, f < 0, WATER)
        ponds.append((px, py, r))

    for _ in range(60):
        px, py = rng.random() * N, rng.random() * N
        r = N * (0.012 + rng.random() * 0.020)
        if terr[int(py), int(px)] != GRASS or not open_meadow(px, py, r):
            continue
        lay(terr, blob_field(N, px, py, r, rng, rough=0.6) < 0, DIRT)

    plan["outcrops"], plan["ponds"] = outcrops, ponds
    return terr, plan


def build_ground(terr, ids, rng, N):
    """Wang-Aufloesung. Reihenfolge = Vorrang beim Uebergang."""
    order = [("water", WATER), ("cobble", COBBLE), ("arena", ARENA),
             ("farm", FARM), ("rock", ROCK), ("sand", SAND), ("dirt", DIRT)]
    cs = {name: combos(terr == code) for name, code in order}
    full = {"water": ["water"], "cobble": ["cobble_1", "cobble_2"],
            "arena": ["arena_1", "arena_2"], "farm": ["farm_1", "farm_2"],
            "rock": ["rock"], "sand": ["sand_1", "sand_2"],
            "dirt": ["dirt_1", "dirt_2"]}
    grass_pool = [ids[f"grass_{i}"] for i in range(1, 5)]
    flower_pool = [ids["grass_flowers_red"], ids["grass_flowers_blue"],
                   ids["grass_flowers_yellow"]]
    g = np.zeros((N, N), dtype=int)
    for y in range(N):
        for x in range(N):
            for name, _code in order:
                c = cs[name][y, x]
                if not c:
                    continue
                if c == 15:
                    pool = full[name]
                    g[y, x] = ids[pool[int(rng.integers(len(pool)))]]
                else:
                    g[y, x] = ids[f"{name}_grass_{c}"] if name != "water" \
                        else ids[f"water_grass_{c}"]
                break
            else:
                g[y, x] = (flower_pool[int(rng.integers(3))]
                           if rng.random() < 0.06
                           else grass_pool[int(rng.integers(4))])
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles", type=int, default=160)
    ap.add_argument("--seed", type=int, default=12)
    ap.add_argument("--tileset", default="assets/tilesets/painted")
    ap.add_argument("--out", default="maps/zone_furt.json")
    a = ap.parse_args()

    N = a.tiles
    rng = np.random.default_rng(a.seed)
    meta = load_meta(a.tileset)
    ids, sprites = meta["ids"], meta["sprites"]

    print(f"[1/4] Terrain komponieren ({N}x{N}) ...")
    terr, plan = compose(N, rng)

    print("[2/4] Boden aufloesen ...")
    ground = build_ground(terr, ids, rng, N)

    print("[3/4] Bebauung und Deko ...")
    deco = np.zeros((N, N), dtype=int)
    over = np.zeros((N, N), dtype=int)
    block = terr == WATER

    def free(x, y, w=1, h=1, pad=0):
        if x - pad < 0 or y - pad < 0 or x + w + pad > N or y + h + pad > N:
            return False
        area = terr[y - pad:y + h + pad, x - pad:x + w + pad]
        if np.any(area == WATER) or np.any(area == COBBLE) \
                or np.any(area == FARM):
            return False
        return not np.any(over[y - pad:y + h + pad, x - pad:x + w + pad])

    def put(name, x, y, blocking=True):
        s = sprites[name]
        for r_ in range(s["h"]):
            for c in range(s["w"]):
                over[y + r_, x + c] = s["tiles"][r_][c]
        if blocking:
            block[y + s["h"] - 1, x:x + s["w"]] = True
            if s["h"] > 1:
                block[y + s["h"] - 2, x:x + s["w"]] = True

    # Haeuser saeumen die Strassen und schauen zur Strasse — kein Ring
    house_names = ["house_a", "house_b", "house_c"]
    n_h = 0
    streets = [plan["main_st"]] + plan["cross"]
    for pts in streets:
        for i in range(2, len(pts) - 2, 3):
            (ax_, ay_), (bx_, by_) = pts[i - 1], pts[i + 1]
            dx, dy = bx_ - ax_, by_ - ay_
            n = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / n, dx / n
            for side in (1, -1):
                name = house_names[int(rng.integers(3))]
                s = sprites[name]
                # dicht an die Strasse ruecken — Haeuser, die 8 Felder weit
                # in der Wiese stehen, definieren keine Strasse
                off = 4.2 + s["h"] / 2 + rng.random()
                hx = int(pts[i][0] + nx * off * side - s["w"] / 2)
                hy = int(pts[i][1] + ny * off * side - s["h"] / 2)
                if free(hx, hy, s["w"], s["h"]):
                    put(name, hx, hy)
                    n_h += 1
    sx, sy, sq = plan["square"]
    if free(int(sx) - 1, int(sy) - 1, 2, 2):
        put("well", int(sx) - 1, int(sy) - 1)

    # Zaeune um die Aecker, Setzlinge drauf
    # Nur dort, wo wirklich noch Acker liegt: Strassen und Fluss werden nach
    # den Feldern gezogen, sonst stehen Zaeune mitten auf dem Pflaster.
    for (x0, y0, w, h) in plan["fields"]:
        for x in range(x0, x0 + w):
            for y in (y0, y0 + h - 1):
                if terr[y, x] == FARM and not deco[y, x]:
                    deco[y, x] = ids["fence_h"]
                    block[y, x] = True
        for y in range(y0, y0 + h):
            for x in (x0, x0 + w - 1):
                if terr[y, x] == FARM and not deco[y, x]:
                    deco[y, x] = ids["fence_v"]
                    block[y, x] = True
        for y in range(y0 + 1, y0 + h - 1):
            for x in range(x0 + 1, x0 + w - 1):
                if terr[y, x] == FARM and rng.random() < 0.55:
                    deco[y, x] = ids["crops"]

    # Bruecken-Planken
    for (bx, by) in plan["bridges"]:
        for dx in range(-7, 8):
            for dy in (-1, 0, 1):
                x, y = int(bx + dx), int(by + dy)
                if 0 <= x < N and 0 <= y < N:
                    deco[y, x] = ids["bridge_h"]
                    block[y, x] = False

    # Arena: Kampfspuren, Felsen am Wall
    ax, ay, ar, lanes = plan["arena"]
    arena_props = [ids["bones"], ids["bones"], ids["skull"], ids["campfire"],
                   ids["boulder"], ids["tall_grass"]]
    for _ in range(int(math.pi * ar * ar * 0.08)):
        t = rng.random() * 2 * math.pi
        d = ar * math.sqrt(rng.random()) * 0.9
        x, y = int(ax + math.cos(t) * d), int(ay + math.sin(t) * d)
        if 0 <= x < N and 0 <= y < N and terr[y, x] == ARENA and not deco[y, x]:
            p = arena_props[int(rng.integers(len(arena_props)))]
            deco[y, x] = p
            if p == ids["boulder"]:
                block[y, x] = True
    for k in range(3):
        t = lanes[0] + 0.9 + k * 2.0
        x, y = int(ax + math.cos(t) * ar * 0.55), int(ay + math.sin(t) * ar * 0.55)
        if free(x, y, 2, 2) and terr[y, x] == ARENA:
            put("tent", x, y)

    # Ruine oben auf dem Plateau als Blickfang
    hx, hy, hr = plan["plateau"]
    for k in range(9):
        t = k * 2 * math.pi / 9
        x, y = int(hx + math.cos(t) * hr * 0.26), int(hy + math.sin(t) * hr * 0.26)
        if 0 <= x < N and 0 <= y < N and terr[y, x] == ROCK and not deco[y, x]:
            deco[y, x] = ids["boulder"]
            block[y, x] = True

    # Deko in Nestern, nicht gleichmaessig gestreut: gleichmaessige Streuung
    # sieht aus wie Rauschen und laesst die Flaeche trotzdem leer wirken.
    nests = [(ids["tall_grass"], 26, 7.0), (ids["mushrooms"], 10, 3.5),
             (ids["boulder"], 12, 4.5), (ids["log"], 8, 3.0)]
    for tile, n_nest, spread in nests:
        for _ in range(n_nest):
            cx_, cy_ = rng.random() * N, rng.random() * N
            for _ in range(int(rng.integers(5, 16))):
                x = int(cx_ + rng.normal(0, spread))
                y = int(cy_ + rng.normal(0, spread))
                if not (0 <= x < N and 0 <= y < N):
                    continue
                if terr[y, x] in (GRASS, ROCK) and not over[y, x] \
                        and not deco[y, x]:
                    deco[y, x] = tile
                    if tile == ids["boulder"]:
                        block[y, x] = True

    print("[4/4] Speichern ...")
    ts_rel = os.path.relpath(os.path.join(a.tileset, "tileset.png"),
                             os.path.dirname(os.path.abspath(a.out))
                             ).replace("\\", "/")

    def layer(name, arr, lid, visible=True, dense=False):
        data = ([int(v) + 1 for v in arr.flatten()] if dense
                else [int(v) + 1 if v else 0 for v in arr.flatten()])
        return {"id": lid, "name": name, "type": "tilelayer", "visible": visible,
                "opacity": 1, "x": 0, "y": 0, "width": N, "height": N,
                "data": data}

    tmap = {"type": "map", "version": "1.10", "tiledversion": "1.10.2",
            "orientation": "orthogonal", "renderorder": "right-down",
            "infinite": False, "width": N, "height": N,
            "tilewidth": meta["tile_size"], "tileheight": meta["tile_size"],
            "nextlayerid": 5, "nextobjectid": 1,
            "tilesets": [{"firstgid": 1, "name": "painted", "image": ts_rel,
                          "imagewidth": meta["imagewidth"],
                          "imageheight": meta["imageheight"],
                          "tilewidth": meta["tile_size"],
                          "tileheight": meta["tile_size"],
                          "columns": meta["columns"],
                          "tilecount": meta["count"],
                          "margin": 0, "spacing": 0}],
            "layers": [layer("ground", ground, 1, dense=True),
                       layer("decoration", deco, 2), layer("overlay", over, 3),
                       layer("collision", block.astype(int), 4, visible=False)]}
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(tmap, f)

    names = {"Wasser": WATER, "Wiese": GRASS, "Weg": DIRT, "Pflaster": COBBLE,
             "Arena": ARENA, "Sand": SAND, "Fels": ROCK, "Acker": FARM}
    share = "  ".join(f"{k} {(terr == v).mean() * 100:.0f}%"
                      for k, v in names.items())
    print(f"  {share}")
    print(f"  {n_h} Haeuser, {len(plan['fields'])} Aecker, "
          f"{len(plan['bridges'])} Bruecken, blockiert {block.mean() * 100:.0f}%")
    px = N * meta["tile_size"]
    print(f"Fertig -> {a.out}  ({N}x{N} Tiles = {px}x{px} px)")


if __name__ == "__main__":
    main()
