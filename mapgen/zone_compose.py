#!/usr/bin/env python3
"""Komponierte Spielzone im Stil klassischer MMORPG-Karten (Metin2/Pyungmoo).

Das Vorbild macht drei Dinge, die eine Karte lebendig machen:

  1. Ein DICHTES WEGENETZ MIT SCHLEIFEN statt eines Sterns. Die Wege
     verbinden sich untereinander, es gibt Rundwege und Abkuerzungen.
  2. Die Wege zerschneiden das Land in TASCHEN — und genau dort sitzen die
     Monsterlager. Ohne Wegenetz gibt es keine Taschen, und ohne Taschen
     keine sinnvollen Spawn-Plaetze; die Flaeche wirkt leer.
  3. BERGE RAHMEN die Karte und begrenzen das Spielfeld natuerlich.

Dazu kommt die Komposition aus der Vorversion: Fluss mit Furten, Meer mit
Strand, Stadt an der Furt, Aecker, Arena im Felskessel.

Baeume kommen bewusst NICHT vor — das Terrain muss ohne sie tragen.

Aufruf:  python3 mapgen/zone_compose.py --out maps/zone_furt.json
"""
import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt
from scipy.sparse.csgraph import minimum_spanning_tree
from scipy.spatial import Delaunay

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zone_tiles import combos, load_meta

WATER, GRASS, DIRT, COBBLE, ARENA, SAND, ROCK, FARM = range(8)


# --------------------------------------------------------- Distanzfelder ----
# Terrain wird NICHT durch aneinandergereihte Kreise gestempelt — das gibt
# ausgefranste Treppenraender und Wege wie Matschflecken. Stattdessen den
# Abstand zur Mittellinie ausrechnen und schwellen: konstante Breite,
# glatte Kanten.

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


def dist_to_segments(N, segs):
    """Kleinster Abstand jedes Feldes zu einer Menge von Strecken."""
    yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
    best = np.full((N, N), 1e9, dtype=np.float32)
    for ax, ay, bx, by in segs:
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        if L2 < 1e-9:
            continue
        t = np.clip(((xx - ax) * dx + (yy - ay) * dy) / L2, 0, 1)
        np.minimum(best, np.hypot(xx - (ax + t * dx), yy - (ay + t * dy)),
                   out=best)
    return best


def path_segs(pts):
    return [(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1])
            for i in range(1, len(pts))]


def dist_to_path(N, pts):
    return dist_to_segments(N, path_segs(pts))


def blob_field(N, cx, cy, r, rng, rough=0.20, cells=3):
    yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
    n = fbm2(N, rng, cells, 3) - 0.5
    return np.hypot(xx - cx, yy - cy) - r * (1.0 + rough * 2.0 * n)


def lay(terr, mask, value):
    terr[mask] = value


def bez(p0, p1, p2, n=18):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1])
            for t in np.linspace(0, 1, n)]


def curve(a, b, rng, bow=0.16):
    """Verbindung mit seitlichem Bogen — gerade Linien wirken tot."""
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    dx, dy = b[0] - a[0], b[1] - a[1]
    s = (rng.random() - 0.5) * 2 * bow
    return bez(a, (mx - dy * s, my + dx * s), b)


# ------------------------------------------------------------- Wegenetz ----

def poisson(N, count, margin, rng, ok):
    """Gut verteilte Punkte auf erlaubtem Grund."""
    pts, tries = [], 0
    minr = N / math.sqrt(count) * 0.72
    while len(pts) < count and tries < count * 400:
        tries += 1
        x = rng.random() * (N - 2 * margin) + margin
        y = rng.random() * (N - 2 * margin) + margin
        if not ok[int(y), int(x)]:
            continue
        if any((x - px) ** 2 + (y - py) ** 2 < minr * minr for px, py in pts):
            continue
        pts.append((x, y))
    return pts


def road_web(N, nodes, land, rng, loop_ratio=0.55):
    """Delaunay -> Spannbaum (alles erreichbar) + Extrakanten (Rundwege).

    Nur der Spannbaum waere wieder ein Baum ohne Schleifen — genau das
    macht Karten langweilig. Die Extrakanten erzeugen die Rundwege.
    """
    P = np.array(nodes)
    tri = Delaunay(P)
    edges = set()
    for s in tri.simplices:
        for a, b in ((s[0], s[1]), (s[1], s[2]), (s[2], s[0])):
            edges.add((min(a, b), max(a, b)))

    def crosses_water(a, b):
        for t in np.linspace(0, 1, 24):
            x = int(P[a][0] + (P[b][0] - P[a][0]) * t)
            y = int(P[a][1] + (P[b][1] - P[a][1]) * t)
            if not (0 <= x < N and 0 <= y < N) or not land[y, x]:
                return True
        return False

    usable = [(a, b) for a, b in edges if not crosses_water(a, b)]
    n = len(P)
    W = np.zeros((n, n))
    for a, b in usable:
        W[a, b] = W[b, a] = math.dist(P[a], P[b])
    mst = minimum_spanning_tree(W).toarray()
    keep = {(min(a, b), max(a, b))
            for a, b in zip(*np.nonzero(mst))}

    rest = sorted([e for e in usable if e not in keep],
                  key=lambda e: math.dist(P[e[0]], P[e[1]]))
    keep.update(rest[:int(len(rest) * loop_ratio)])

    return [curve(tuple(P[a]), tuple(P[b]), rng) for a, b in keep], keep


# ---------------------------------------------------------- Monsterlager ----

# Lagertypen: gleiche Mechanik, unterschiedliche Optik. 70 identische
# Zeltlager wirken wie Schablone — verschiedene Reviere geben der Karte
# Charakter und dem Spieler eine Orientierung, wo er gerade farmt.
CAMP_TYPES = {
    "banditen": {"floor": True, "props": ["campfire", "bones", "campfire"],
                 "sprites": ["tent", "tent"], "ring": "fence"},
    "untote":   {"floor": True, "props": ["skull", "bones", "bones", "skull"],
                 "sprites": ["totem"], "ring": "boulder"},
    "bestien":  {"floor": True, "props": ["log", "bones", "boulder", "log"],
                 "sprites": [], "ring": "boulder"},
    "spinnen":  {"floor": False, "props": ["tall_grass", "mushrooms",
                                           "tall_grass", "tall_grass"],
                 "sprites": [], "ring": "boulder"},
    "ruine":    {"floor": True, "props": ["boulder", "skull", "tall_grass"],
                 "sprites": ["totem"], "ring": "boulder"},
}
TYPE_ORDER = list(CAMP_TYPES)


def place_camps(N, terr, road_d, rng, cores, n_max):
    """Lager in die Taschen zwischen den Wegen setzen.

    Greedy groesster freier Kreis: immer dort, wo gerade am meisten Platz
    ist. In den Kerngebieten duerfen die Lager dichter stehen — so entstehen
    Jagdreviere mit Betrieb und ruhigere Randzonen, statt gleichmaessig
    verteilter Langeweile.
    """
    free = (terr == GRASS) & (road_d > 3.0)
    d = distance_transform_edt(free).astype(np.float32)
    yy, xx = np.mgrid[0:N, 0:N]
    camps = []
    while len(camps) < n_max:
        idx = int(np.argmax(d))
        y, x = divmod(idx, N)
        space = float(d[y, x])
        if space < 4.5:
            break
        # Groesse streuen: gleich grosse Kreise wirken wie Schablone.
        # Grosse Lager = Gruppen-Pull, kleine = einzelne Nester.
        r = min(space * 0.66, 9.5) * (0.60 + rng.random() * 0.60)
        inner = any(c[y, x] for c in cores)
        camps.append({"x": int(x), "y": int(y), "r": round(r, 1),
                      "tier": "kern" if inner else "rand",
                      "type": TYPE_ORDER[int(rng.integers(len(TYPE_ORDER)))]})
        clear = r * (1.75 if inner else 2.9)   # im Kern duerfen sie dichter
        d[(xx - x) ** 2 + (yy - y) ** 2 < clear * clear] = 0
    return camps


# ----------------------------------------------------------------- Bau ----

def compose(N, rng):
    terr = np.full((N, N), GRASS, dtype=np.int8)
    plan = {}
    yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)

    def road(pts, half, surface, shoulder=None):
        d = dist_to_path(N, pts)
        if shoulder is not None:
            lay(terr, d <= half + shoulder, DIRT)
        lay(terr, d <= half, surface)
        return d

    # --- Bergrahmen: begrenzt das Spielfeld, wie im Vorbild ----------------
    edge_d = np.minimum.reduce([xx, yy, N - 1 - xx, N - 1 - yy])
    band = N * 0.030 * (1.0 + 1.0 * fbm2(N, rng, 4, 3))
    lay(terr, edge_d < band, ROCK)
    plan["frame"] = band

    # --- Fluss von Nord nach Sued, Meer im Suedosten -----------------------
    river = [(N * 0.62 + math.sin(t * 3.1) * N * 0.05, t * N)
             for t in np.linspace(-0.05, 1.05, 26)]
    dr = dist_to_path(N, river)
    lay(terr, dr <= 4.8, SAND)
    lay(terr, dr <= 2.4, WATER)
    plan["river"] = river

    sea = blob_field(N, N * 1.95, N * 1.85, N * 1.60, rng, rough=0.05, cells=2)
    lay(terr, sea < 7.0, SAND)
    lay(terr, sea < 0, WATER)

    land = ~np.isin(terr, (WATER, ROCK))

    # --- Wegenetz ----------------------------------------------------------
    # Wenige Knoten + duenne Wege: das Verhaeltnis entscheidet. Mit zu vielen
    # Knoten verschmilzt das Netz zu einer braunen Flaeche — die Taschen
    # muessen deutlich groesser sein als der Weg breit. Knotenzahl mit der
    # FLAECHE skalieren, damit die Taschengroesse bei jeder Kartengroesse gleich
    # bleibt.
    nodes = poisson(N, max(12, int(N * N / 1160)), N * 0.08, rng, land)
    paths, edges = road_web(N, nodes, land, rng, loop_ratio=0.38)
    segs = [s for p in paths for s in path_segs(p)]
    road_d = dist_to_segments(N, segs)
    lay(terr, (road_d <= 1.3) & land, DIRT)
    plan["nodes"], plan["paths"] = nodes, paths

    # --- Furten ueber den Fluss: die einzigen Uebergaenge ------------------
    bridges = [(N * 0.62 + math.sin(t * 3.1) * N * 0.05, t * N)
               for t in (0.28, 0.66)]
    for (bx, by) in bridges:
        lay(terr, dist_to_path(N, [(bx - 9, by), (bx + 9, by)]) <= 2.2, DIRT)
    plan["bridges"] = bridges

    # --- Hauptstrasse: eine gepflasterte Route quer durch die Zone ---------
    P = np.array(nodes)
    west = int(np.argmin(P[:, 0] + abs(P[:, 1] - N * 0.55) * 0.4))
    town_node = int(np.argmin(np.hypot(P[:, 0] - (bridges[1][0] - N * 0.14),
                                       P[:, 1] - bridges[1][1])))
    main = curve(tuple(P[west]), tuple(P[town_node]), rng, bow=0.10)
    road(main, 2.1, COBBLE)
    road(curve(tuple(P[town_node]), bridges[1], rng, bow=0.05), 2.1, COBBLE)
    tx, ty = P[town_node]
    plan["town"], plan["main"] = (tx, ty), main

    # --- Stadt: Querstrassen + kleiner Marktplatz --------------------------
    cross = []
    for off, ln in ((-N * 0.075, N * 0.065), (N * 0.070, N * 0.060)):
        c = curve((tx + off, ty - ln), (tx + off * 0.9, ty + ln), rng, bow=0.06)
        road(c, 1.5, COBBLE)
        cross.append(c)
    sq = N * 0.024
    terr[int(ty - sq):int(ty + sq),
         int(tx - sq * 1.4):int(tx + sq * 1.4)] = COBBLE
    plan["cross"], plan["square"] = cross, (tx, ty, sq)

    # --- Aecker in einer Tasche neben der Stadt ----------------------------
    fields = []
    fx0, fy0 = tx - N * 0.26, ty + N * 0.09
    for r_ in range(2):
        for c_ in range(2):
            w = int(N * (0.062 + rng.random() * 0.018))
            h = int(N * (0.052 + rng.random() * 0.016))
            x0 = int(fx0 + c_ * N * 0.085 + rng.integers(-2, 3))
            y0 = int(fy0 + r_ * N * 0.078 + rng.integers(-2, 3))
            if x0 < 2 or y0 < 2 or x0 + w > N - 2 or y0 + h > N - 2:
                continue
            if np.any(np.isin(terr[y0:y0 + h, x0:x0 + w], (WATER, ROCK, COBBLE))):
                continue
            terr[y0:y0 + h, x0:x0 + w] = FARM
            fields.append((x0, y0, w, h))
    plan["fields"] = fields

    # --- Arena im Felskessel, oestlich des Flusses -------------------------
    ax, ay, ar = N * 0.83, N * 0.30, N * 0.085
    lay(terr, blob_field(N, ax, ay, ar * 1.6, rng, rough=0.16) < 0, ROCK)
    lay(terr, blob_field(N, ax, ay, ar, rng, rough=0.12) < 0, ARENA)
    lanes = [i * math.pi / 2 + 0.42 for i in range(4)]
    for la in lanes:
        p0 = (ax + math.cos(la) * ar * 0.6, ay + math.sin(la) * ar * 0.6)
        p1 = (ax + math.cos(la) * ar * 2.1, ay + math.sin(la) * ar * 2.1)
        lay(terr, dist_to_path(N, [p0, p1]) <= 2.3, ARENA)
    plan["arena"] = (ax, ay, ar, lanes)

    # --- Wiese aufbrechen --------------------------------------------------
    def open_meadow(px, py, r):
        y0, y1 = max(0, int(py - r * 2)), min(N, int(py + r * 2))
        x0, x1 = max(0, int(px - r * 2)), min(N, int(px + r * 2))
        return np.all(np.isin(terr[y0:y1, x0:x1], (GRASS, ROCK)))

    for _ in range(80):
        px, py = rng.random() * N, rng.random() * N
        r = N * (0.014 + rng.random() * 0.022)
        if terr[int(py), int(px)] != GRASS or not open_meadow(px, py, r):
            continue
        lay(terr, blob_field(N, px, py, r, rng, rough=0.5) < 0, ROCK)

    ponds = []
    for _ in range(60):
        if len(ponds) >= 3:
            break
        px, py = rng.random() * N, rng.random() * N
        r = N * (0.016 + rng.random() * 0.016)
        if terr[int(py), int(px)] != GRASS or not open_meadow(px, py, r * 1.7):
            continue
        f = blob_field(N, px, py, r, rng, rough=0.35)
        lay(terr, f < 3.0, SAND)
        lay(terr, f < 0, WATER)
        ponds.append((px, py, r))
    plan["ponds"] = ponds

    # --- Monsterlager in die Taschen ---------------------------------------
    # Mehrere Kerngebiete = mehrere Jagdreviere mit hoher Dichte, dazwischen
    # ruhigere Zonen. Ein einziger Kern gibt der Karte nur einen Hotspot.
    core_cs = [(N * 0.30, N * 0.34), (N * 0.24, N * 0.72), (N * 0.80, N * 0.62)]
    cores = [np.hypot(xx - cx_, yy - cy_) < N * 0.20 for cx_, cy_ in core_cs]
    camps = place_camps(N, terr, road_d, rng, cores,
                        n_max=max(20, int(N * N / 780)))
    for c in camps:
        if not CAMP_TYPES[c["type"]]["floor"]:
            continue          # Spinnennester bleiben im hohen Gras
        f = blob_field(N, c["x"], c["y"], c["r"], rng, rough=0.30)
        lay(terr, (f < 1.5) & (terr == GRASS), DIRT)
        lay(terr, (f < 0) & np.isin(terr, (GRASS, DIRT)), ARENA)
    plan["camps"], plan["cores"] = camps, core_cs

    return terr, plan


def build_ground(terr, ids, rng, N):
    order = [("water", WATER), ("cobble", COBBLE), ("arena", ARENA),
             ("farm", FARM), ("rock", ROCK), ("sand", SAND), ("dirt", DIRT)]
    cs = {name: combos(terr == code) for name, code in order}
    full = {"water": ["water"], "cobble": ["cobble_1", "cobble_2"],
            "arena": ["arena_1", "arena_2"], "farm": ["farm_1", "farm_2"],
            "rock": ["rock", "rock_2", "rock_3"], "sand": ["sand_1", "sand_2"],
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
                    g[y, x] = (ids[f"water_grass_{c}"] if name == "water"
                               else ids[f"{name}_grass_{c}"])
                break
            else:
                g[y, x] = (flower_pool[int(rng.integers(3))]
                           if rng.random() < 0.06
                           else grass_pool[int(rng.integers(4))])
    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles", type=int, default=256)
    ap.add_argument("--seed", type=int, default=12)
    ap.add_argument("--tileset", default="assets/tilesets/painted")
    ap.add_argument("--out", default="maps/zone_furt.json")
    a = ap.parse_args()

    N = a.tiles
    rng = np.random.default_rng(a.seed)
    meta = load_meta(a.tileset)
    ids, sprites = meta["ids"], meta["sprites"]

    print(f"[1/4] Terrain und Wegenetz komponieren ({N}x{N}) ...")
    terr, plan = compose(N, rng)

    print("[2/4] Boden aufloesen ...")
    ground = build_ground(terr, ids, rng, N)

    print("[3/4] Bebauung, Lager und Deko ...")
    deco = np.zeros((N, N), dtype=int)
    over = np.zeros((N, N), dtype=int)
    block = np.isin(terr, (WATER, ROCK))

    def free(x, y, w=1, h=1, pad=0):
        if x - pad < 0 or y - pad < 0 or x + w + pad > N or y + h + pad > N:
            return False
        area = terr[y - pad:y + h + pad, x - pad:x + w + pad]
        if np.any(np.isin(area, (WATER, COBBLE, FARM, ROCK, ARENA))):
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

    house_names = ["house_a", "house_b", "house_c"]
    n_h = 0
    tx, ty, _sq = plan["square"]
    for pts in [plan["main"]] + plan["cross"]:
        dense = [p for p in pts if math.dist(p, (tx, ty)) < N * 0.12]
        for i in range(1, len(dense) - 1):
            (ax_, ay_), (bx_, by_) = dense[i - 1], dense[i + 1]
            dx, dy = bx_ - ax_, by_ - ay_
            n = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / n, dx / n
            for side in (1, -1):
                name = house_names[int(rng.integers(3))]
                s = sprites[name]
                off = 4.2 + s["h"] / 2 + rng.random()
                hx = int(dense[i][0] + nx * off * side - s["w"] / 2)
                hy = int(dense[i][1] + ny * off * side - s["h"] / 2)
                if free(hx, hy, s["w"], s["h"]):
                    put(name, hx, hy)
                    n_h += 1
    if free(int(tx) - 1, int(ty) - 1, 2, 2):
        put("well", int(tx) - 1, int(ty) - 1)

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

    for (bx, by) in plan["bridges"]:
        for dx in range(-9, 10):
            for dy in (-1, 0, 1):
                x, y = int(bx + dx), int(by + dy)
                if 0 <= x < N and 0 <= y < N:
                    deco[y, x] = ids["bridge_h"]
                    block[y, x] = False

    # Lager nach Typ ausstatten — Banditenlager, Untotenfeld, Bestienhoehle,
    # Spinnennest und Ruine sehen unterschiedlich aus, obwohl die Mechanik
    # dieselbe ist. Das gibt dem Spieler Orientierung, wo er gerade farmt.
    for c in plan["camps"]:
        cx_, cy_, r = c["x"], c["y"], c["r"]
        spec = CAMP_TYPES[c["type"]]
        props = [ids[p] for p in spec["props"]]
        floor = ARENA if spec["floor"] else GRASS

        if 0 <= cy_ < N and 0 <= cx_ < N and not deco[cy_, cx_] \
                and terr[cy_, cx_] == floor:
            deco[cy_, cx_] = props[0]
        for _ in range(int(r * r * 0.75)):
            t = rng.random() * 2 * math.pi
            d = r * math.sqrt(rng.random()) * 0.92
            x, y = int(cx_ + math.cos(t) * d), int(cy_ + math.sin(t) * d)
            if 0 <= x < N and 0 <= y < N and terr[y, x] == floor \
                    and not over[y, x] and not deco[y, x]:
                deco[y, x] = props[int(rng.integers(len(props)))]

        for k, name in enumerate(spec["sprites"]):
            if c["tier"] != "kern" and k > 0:
                break                     # Randlager bleiben schlichter
            t = 1.1 + k * 2.4
            x = int(cx_ + math.cos(t) * r * 0.55)
            y = int(cy_ + math.sin(t) * r * 0.55)
            if 0 <= x < N - 2 and 0 <= y < N - 2 and terr[y, x] == floor \
                    and not over[y, x]:
                put(name, x, y)

        n_ring = max(8, int(r * 1.6))
        for k in range(n_ring):
            t = k * 2 * math.pi / n_ring
            x = int(cx_ + math.cos(t) * r * 1.15)
            y = int(cy_ + math.sin(t) * r * 1.15)
            if not (0 <= x < N and 0 <= y < N) or over[y, x] or deco[y, x]:
                continue
            if terr[y, x] != GRASS or rng.random() > 0.55:
                continue
            if spec["ring"] == "fence":
                deco[y, x] = ids["fence_h"] if abs(math.sin(t)) < 0.5 \
                    else ids["fence_v"]
            else:
                deco[y, x] = ids["boulder"]
            block[y, x] = True

    # Die grosse Arena ist kein Lager, sondern der Bossplatz — eigene,
    # groebere Ausstattung
    ax, ay, ar, lanes = plan["arena"]
    arena_props = [ids["bones"], ids["skull"], ids["campfire"], ids["boulder"]]
    for _ in range(int(math.pi * ar * ar * 0.09)):
        t = rng.random() * 2 * math.pi
        d = ar * math.sqrt(rng.random()) * 0.9
        x, y = int(ax + math.cos(t) * d), int(ay + math.sin(t) * d)
        if 0 <= x < N and 0 <= y < N and terr[y, x] == ARENA and not deco[y, x]:
            deco[y, x] = arena_props[int(rng.integers(len(arena_props)))]

    nests = [(ids["tall_grass"], 30, 7.0), (ids["mushrooms"], 12, 3.5),
             (ids["boulder"], 14, 4.5), (ids["log"], 9, 3.0)]
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
            "properties": [{"name": "monster_camps", "type": "string",
                            "value": json.dumps(plan["camps"])}],
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
    out_dir = os.path.dirname(os.path.abspath(a.out)) or "."
    os.makedirs(out_dir, exist_ok=True)
    with open(a.out, "w") as f:
        json.dump(tmap, f)

    # --- Beigaben fuer Unity ----------------------------------------------
    # Der collision-Layer im Tiled-JSON traegt zwar die Info, aber als
    # Tile-IDs — unbrauchbar ohne Importer. Deshalb zusaetzlich eine
    # eindeutige Maske und eine flache Metadatei, die JsonUtility direkt
    # deserialisieren kann (siehe docs/unity_import.md).
    base = os.path.splitext(os.path.basename(a.out))[0]
    Image.fromarray((block * 255).astype(np.uint8)).save(
        os.path.join(out_dir, f"{base}_collision.png"))

    ax_, ay_, ar_, lanes_ = plan["arena"]
    meta_out = {
        "name": base,
        "width_tiles": N, "height_tiles": N, "tile_size": meta["tile_size"],
        "camps": plan["camps"],
        "arena": {"x": int(ax_), "y": int(ay_), "r": round(ar_, 1),
                  "lane_angles_rad": [round(l, 3) for l in lanes_]},
        "town": {"x": int(plan["square"][0]), "y": int(plan["square"][1])},
        "bridges": [{"x": int(bx), "y": int(by)} for bx, by in plan["bridges"]],
        "cores": [{"x": int(cx_), "y": int(cy_)} for cx_, cy_ in plan["cores"]],
    }
    with open(os.path.join(out_dir, f"{base}_meta.json"), "w") as f:
        json.dump(meta_out, f, indent=2)

    names = {"Wasser": WATER, "Wiese": GRASS, "Weg": DIRT, "Pflaster": COBBLE,
             "Lager": ARENA, "Sand": SAND, "Fels": ROCK, "Acker": FARM}
    print("  " + "  ".join(f"{k} {(terr == v).mean() * 100:.0f}%"
                           for k, v in names.items()))
    kern = sum(1 for c in plan["camps"] if c["tier"] == "kern")
    print(f"  {len(plan['paths'])} Wegstuecke, {len(plan['camps'])} Lager "
          f"({kern} im Kerngebiet), {n_h} Haeuser, blockiert {block.mean()*100:.0f}%")
    px = N * meta["tile_size"]
    print(f"Fertig -> {a.out}  ({N}x{N} Tiles = {px}x{px} px)")


if __name__ == "__main__":
    main()
