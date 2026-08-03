#!/usr/bin/env python3
"""Caldera — Vulkanzone mit konzentrischem Aufbau.

Bewusst eine ANDERE Topologie als zone_compose.py. Dort teilt ein Fluss das
Land linear, ein Wegenetz spannt sich frei darueber. Hier ist alles radial
um den Krater organisiert:

    Lavasee          im Zentrum, unpassierbar
    Kraterwall       Basaltring mit DREI Paessen — die einzigen Zugaenge
    Schwefelterrasse gelber Hochlevel-Guertel hinter dem Wall
    Lavastroeme      strahlen nach aussen und zerschneiden das Land in KEILE
    Ringweg          umlaeuft den Berg und quert jeden Strom ueber eine Bruecke
    Speichenwege     fuehren vom Kartenrand nach innen, je einer pro Keil
    Ascheebene       aussen, die normale Farmzone

Das Ergebnis liest sich als Berg, nicht als Landschaft: Schwierigkeit
steigt nach innen, jeder Keil ist ein eigenes Revier, und die Bruecken
sowie die drei Paesse sind die Engstellen.

Aufruf:
    python3 mapgen/zone_caldera.py --tiles 256 --tileset assets/tilesets/fire \
        --out maps/zone_caldera.json
"""
import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zone_compose import (ARENA, CAMP_TYPES, COBBLE, DIRT, FARM, GRASS, ROCK,
                          SAND, TYPE_ORDER, WATER, blob_field, build_ground,
                          curve, dist_to_path, dist_to_segments, fbm2, lay,
                          path_segs)
from zone_tiles import load_meta


def ring_pts(cx, cy, r, n=72, a0=0.0):
    return [(cx + math.cos(a0 + i * 2 * math.pi / n) * r,
             cy + math.sin(a0 + i * 2 * math.pi / n) * r) for i in range(n + 1)]


def wobbly_ray(cx, cy, a, r0, r1, rng, sway=0.16, n=22):
    """Strahl nach aussen, der leicht maeandert — Lavastroeme fliessen nicht
    schnurgerade."""
    pts = []
    for i in range(n + 1):
        t = i / n
        r = r0 + (r1 - r0) * t
        da = math.sin(t * 4.2 + rng.random() * 0.6) * sway * (0.3 + t)
        pts.append((cx + math.cos(a + da) * r, cy + math.sin(a + da) * r))
    return pts


def compose(N, rng, n_flows=6):
    terr = np.full((N, N), GRASS, dtype=np.int8)
    plan = {}
    yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
    cx = cy = N / 2.0
    rad = np.hypot(xx - cx, yy - cy)
    ang = np.arctan2(yy - cy, xx - cx)

    # Von innen nach aussen: Bossplattform, Lavagraben, Sims, Kraterwall,
    # Schwefelterrasse, Ringweg.
    R_boss = N * 0.055
    R_moat = N * 0.100
    R_ledge = N * 0.142
    R_wall = N * 0.182
    R_terrace = N * 0.268
    R_ring = N * 0.335
    plan["center"] = (cx, cy)
    plan["radii"] = {"boss": R_boss, "moat": R_moat, "ledge": R_ledge,
                     "wall": R_wall, "terrace": R_terrace, "ring": R_ring}

    # Kanten aller Ringe leicht wellig, sonst wirkt es wie eine Zielscheibe
    wob = (fbm2(N, rng, 3, 3) - 0.5) * N * 0.035

    # --- Schwefelterrasse (Hochlevel-Guertel) ------------------------------
    lay(terr, rad + wob < R_terrace, SAND)

    # --- Lavastroeme nach aussen: sie zerschneiden das Land in Keile -------
    # ZUERST, damit Wall und See danach sauber darueber liegen. Andersherum
    # schneiden die Stroeme den Krater auf und das Zentrum wird Matsch.
    flow_angles = [i * 2 * math.pi / n_flows + rng.random() * 0.25
                   for i in range(n_flows)]
    flows = []
    for i, a in enumerate(flow_angles):
        reach = N * (0.72 if i % 3 else 0.52)     # nicht alle bis zum Rand
        pts = wobbly_ray(cx, cy, a, R_wall * 1.05, reach, rng)
        d = dist_to_path(N, pts)
        lay(terr, d <= 4.6, SAND)                 # Schwefelsaum
        lay(terr, d <= 2.2, WATER)
        flows.append(pts)
        if i % 3 == 0:                            # manche enden in einem See
            ex, ey = pts[-1]
            f = blob_field(N, ex, ey, N * 0.045, rng, rough=0.3)
            lay(terr, f < 4.0, SAND)
            lay(terr, f < 0, WATER)
    plan["flows"] = flows

    # --- Kraterwall mit drei Paessen ---------------------------------------
    passes = [rng.random() * 2 * math.pi]
    passes += [passes[0] + 2 * math.pi / 3, passes[0] + 4 * math.pi / 3]
    wall = (rad + wob > R_ledge) & (rad + wob < R_wall)
    for pa in passes:                       # Luecken in den Wall schneiden
        d = np.abs(np.arctan2(np.sin(ang - pa), np.cos(ang - pa)))
        wall &= d > 0.15
    lay(terr, wall, ROCK)
    plan["passes"] = passes

    # --- Bosskammer: Plattform im Lavagraben, ueber drei Daemme erreichbar --
    # Der Krater ist kein toter Lavasee, sondern das Ziel der Zone. Der
    # Graben macht ihn gefaehrlich, die Daemme machen ihn begehbar — und sie
    # fluchten mit den Paessen, damit der Weg von aussen durchgehend lesbar
    # bleibt.
    lay(terr, rad + wob * 0.6 < R_ledge, SAND)            # Sims am Grabenrand
    lay(terr, rad + wob * 0.5 < R_moat, WATER)            # Lavagraben
    for pa in passes:
        p0 = (cx + math.cos(pa) * (R_boss * 0.7), cy + math.sin(pa) * (R_boss * 0.7))
        p1 = (cx + math.cos(pa) * (R_ledge + 2), cy + math.sin(pa) * (R_ledge + 2))
        # heller Bimskies, nicht Basaltplatten: sonst verschmelzen die Daemme
        # optisch mit dem gleich dunklen Kraterwall
        lay(terr, dist_to_path(N, [p0, p1]) <= 2.4, DIRT)
    lay(terr, rad + wob * 0.3 < R_boss, ARENA)            # Bossplattform
    plan["boss"] = (cx, cy, R_boss)

    # --- Bergrahmen aussen --------------------------------------------------
    edge_d = np.minimum.reduce([xx, yy, N - 1 - xx, N - 1 - yy])
    band = N * 0.028 * (1.0 + 1.0 * fbm2(N, rng, 4, 3))
    lay(terr, edge_d < band, ROCK)

    # --- Obsidianfelder als Landmarken in den Keilen ------------------------
    spires = []
    for k in range(5):
        a = rng.random() * 2 * math.pi
        r = R_ring + (N * 0.5 - R_ring) * (0.25 + rng.random() * 0.5)
        sx, sy = cx + math.cos(a) * r, cy + math.sin(a) * r
        if not (4 < sx < N - 4 and 4 < sy < N - 4):
            continue
        if terr[int(sy), int(sx)] != GRASS:
            continue
        lay(terr, blob_field(N, sx, sy, N * (0.022 + rng.random() * 0.02),
                             rng, rough=0.5) < 0, ROCK)
        spires.append((sx, sy))
    plan["spires"] = spires

    # --- Ascheebene aufbrechen ---------------------------------------------
    # Aussen ist sonst alles dieselbe Asche. Erkaltete Krusten, Schwefelaugen
    # und ein paar Lavatuempel geben der Flaeche Struktur und Orientierung.
    def open_ash(px, py, r):
        y0, y1 = max(0, int(py - r * 2)), min(N, int(py + r * 2))
        x0, x1 = max(0, int(px - r * 2)), min(N, int(px + r * 2))
        return np.all(np.isin(terr[y0:y1, x0:x1], (GRASS, ROCK, SAND)))

    # Sparsam dosieren: zu viele Flecken machen die Ebene unruhig UND nehmen
    # den Lagern den Platz, den place_camps braucht.
    for _ in range(32):
        px, py = rng.random() * N, rng.random() * N
        r = N * (0.010 + rng.random() * 0.016)
        if terr[int(py), int(px)] != GRASS or not open_ash(px, py, r):
            continue
        kind = SAND if rng.random() < 0.55 else ROCK
        lay(terr, blob_field(N, px, py, r, rng, rough=0.5) < 0, kind)

    pools = 0
    for _ in range(50):
        if pools >= 4:
            break
        px, py = rng.random() * N, rng.random() * N
        r = N * (0.016 + rng.random() * 0.016)
        if terr[int(py), int(px)] != GRASS or not open_ash(px, py, r * 1.7):
            continue
        if np.hypot(px - cx, py - cy) < R_terrace * 1.25:
            continue                       # nicht direkt am Krater
        f = blob_field(N, px, py, r, rng, rough=0.35)
        lay(terr, f < 3.5, SAND)
        lay(terr, f < 0, WATER)
        pools += 1

    # --- Wegenetz: Ringweg + Speichen + Passwege ---------------------------
    roads = []

    # Ringweg aus hellem Bimskies, NICHT aus Basaltplatten: Platten und
    # Kraterwall haben fast dieselbe Helligkeit, der Ring verschwaende darin.
    ring = ring_pts(cx, cy, R_ring, 80)
    lay(terr, dist_to_path(N, ring) <= 2.0, DIRT)
    roads.append(ring)

    # je eine Speiche in der Mitte zwischen zwei Lavastroemen
    spokes = []
    for i in range(n_flows):
        a = (flow_angles[i] + flow_angles[(i + 1) % n_flows]
             + (2 * math.pi if i == n_flows - 1 else 0)) / 2
        outer = (cx + math.cos(a) * N * 0.62, cy + math.sin(a) * N * 0.62)
        inner = (cx + math.cos(a) * R_ring, cy + math.sin(a) * R_ring)
        pts = curve(outer, inner, rng, bow=0.06)
        lay(terr, dist_to_path(N, pts) <= 1.4, DIRT)
        spokes.append(pts)
        roads.append(pts)
    plan["spokes"] = spokes

    # Passwege: vom Ring durch den Wall auf die Terrasse
    for pa in passes:
        p0 = (cx + math.cos(pa) * R_ring, cy + math.sin(pa) * R_ring)
        # bis auf den Sims am Grabenrand; von dort fuehrt der Damm weiter
        p1 = (cx + math.cos(pa) * (R_ledge - 3), cy + math.sin(pa) * (R_ledge - 3))
        pts = curve(p0, p1, rng, bow=0.03)
        lay(terr, dist_to_path(N, pts) <= 1.5, DIRT)
        roads.append(pts)

    road_d = dist_to_segments(N, [s for p in roads for s in path_segs(p)])
    plan["roads"] = roads

    # --- Bruecken dort, wo der Ringweg einen Lavastrom quert ---------------
    bridges = []
    for a in flow_angles:
        bx, by = cx + math.cos(a) * R_ring, cy + math.sin(a) * R_ring
        tx, ty = -math.sin(a), math.cos(a)         # laengs des Rings
        seg = [(bx - tx * 9, by - ty * 9), (bx + tx * 9, by + ty * 9)]
        lay(terr, dist_to_path(N, seg) <= 2.2, DIRT)
        bridges.append((bx, by))
    plan["bridges"] = bridges

    # --- Siedlung: in einem Keil am Ringweg, aussen ------------------------
    ta = flow_angles[0] + math.pi / n_flows
    tx_, ty_ = cx + math.cos(ta) * (R_ring + N * 0.10), \
        cy + math.sin(ta) * (R_ring + N * 0.10)
    plan["town"] = (tx_, ty_)
    main = curve((tx_ - N * 0.09, ty_), (tx_ + N * 0.09, ty_), rng, bow=0.04)
    lay(terr, dist_to_path(N, main) <= 2.0, COBBLE)
    cross = []
    for off in (-N * 0.055, N * 0.050):
        c = curve((tx_ + off, ty_ - N * 0.055), (tx_ + off * 0.9, ty_ + N * 0.055),
                  rng, bow=0.05)
        lay(terr, dist_to_path(N, c) <= 1.4, COBBLE)
        cross.append(c)
    sq = N * 0.022
    terr[int(ty_ - sq):int(ty_ + sq),
         int(tx_ - sq * 1.4):int(tx_ + sq * 1.4)] = COBBLE
    plan["main"], plan["cross"], plan["square"] = main, cross, (tx_, ty_, sq)
    # Anschluss der Siedlung an den Ringweg
    link = curve((tx_, ty_), (cx + math.cos(ta) * R_ring,
                              cy + math.sin(ta) * R_ring), rng, bow=0.05)
    lay(terr, dist_to_path(N, link) <= 1.4, DIRT)

    # --- Schwefelwerk: der GRUND, warum die Siedlung hier steht ------------
    # Vorher lagen Beete und Dorf in verschiedenen Keilen — dann existiert das
    # Dorf ohne Anlass mitten in einer Monsterzone. Der Abbau gehoert in
    # denselben Keil, bergwaerts vom Dorf, mit einem Werksweg dazwischen.
    fields = []
    fa = ta
    fx0 = cx + math.cos(fa) * (R_terrace + N * 0.030) - N * 0.06
    fy0 = cy + math.sin(fa) * (R_terrace + N * 0.030) - N * 0.05
    for r_ in range(2):
        for c_ in range(2):
            w, h = int(N * 0.058), int(N * 0.050)
            x0, y0 = int(fx0 + c_ * N * 0.072), int(fy0 + r_ * N * 0.064)
            if x0 < 2 or y0 < 2 or x0 + w > N - 2 or y0 + h > N - 2:
                continue
            if np.any(np.isin(terr[y0:y0 + h, x0:x0 + w],
                              (WATER, ROCK, COBBLE))):
                continue
            terr[y0:y0 + h, x0:x0 + w] = FARM
            fields.append((x0, y0, w, h))
    plan["fields"] = fields

    # Werksweg Dorf -> Beete: ohne Anbindung waere der Abbau nicht erklaerbar
    if fields:
        fx, fy, fw, fh = fields[0]
        work = curve((tx_, ty_), (fx + fw / 2, fy + fh / 2), rng, bow=0.05)
        lay(terr, dist_to_path(N, work) <= 1.4, DIRT)
        plan["workroad"] = work

    # --- Zonenausgaenge: die Speichen brauchen ein Ziel --------------------
    # Ein Weg, der am Kartenrand einfach aufhoert, wirkt wie ein Fehler.
    # Zwei Speichen enden an einem Torbogen = Uebergang in die Nachbarzone.
    gates = []
    for pts in spokes[:2]:
        gx, gy = pts[0]                    # aeusseres Ende der Speiche
        gx = float(np.clip(gx, 6, N - 7))
        gy = float(np.clip(gy, 6, N - 7))
        lay(terr, dist_to_path(N, [(gx, gy), pts[2]]) <= 2.4, COBBLE)
        gates.append((gx, gy))
    plan["gates"] = gates

    return terr, plan, rad, road_d


def camp_type(terr, road_d, rad, radii, x, y, space, N, rng):
    """Der Typ folgt dem ORT, nicht dem Zufall.

    Gewuerfelte Typen wirken beliebig: ein Banditenlager mitten in der
    Einoede ergibt keinen Sinn, Untote ohne Ruine auch nicht. Aus der Lage
    abgeleitet erzaehlt jedes Lager, warum es dort ist.
    """
    # Schwellen relativ zur Kartengroesse: absolut in Tiles gerechnet kippt
    # bei 256 alles zu "bestien", weil die Taschen dort groesser sind.
    if road_d[y, x] < N * 0.055:
        return "banditen"                     # lauern Reisenden am Weg auf
    if rad[y, x] < radii["terrace"] + N * 0.03:
        return "untote" if rng.random() < 0.55 else "bestien"   # Kraternaehe
    k = max(5, int(N * 0.045))
    y0, y1 = max(0, y - k), min(N, y + k + 1)
    x0, x1 = max(0, x - k), min(N, x + k + 1)
    if (terr[y0:y1, x0:x1] == ROCK).mean() > 0.07:
        return "ruine"                        # bei Fels und Obsidianfeldern
    if space < N * 0.058:
        return "spinnen"                      # enge, abgeschiedene Taschen
    return "bestien"                          # offenes Oedland


def place_camps_radial(N, terr, road_d, rad, rng, radii, n_max):
    """Lager in die Keile setzen — Stufe nach RADIUS statt nach Kernzonen.

    Das ist der Gameplay-Kern dieser Karte: je naeher am Krater, desto
    haerter. Innen (Schwefelterrasse) stehen die Lager dichter und tragen
    tier 'kern', aussen auf der Ascheebene sind sie ruhiger.
    """
    # Innerhalb des Kraterwalls keine Lager: dort liegen Sims, Graben und
    # Bosskammer — die sollen frei bleiben, nicht mit Trash zugestellt werden.
    free = np.isin(terr, (GRASS, SAND)) & (road_d > 3.0) \
        & (rad > radii["wall"] + 4)
    d = distance_transform_edt(free).astype(np.float32)
    yy, xx = np.mgrid[0:N, 0:N]
    camps = []
    while len(camps) < n_max:
        idx = int(np.argmax(d))
        y, x = divmod(idx, N)
        space = float(d[y, x])
        if space < 4.5:
            break
        inner = rad[y, x] < radii["terrace"] + N * 0.03
        r = min(space * 0.66, 9.0) * (0.60 + rng.random() * 0.58)
        camps.append({"x": int(x), "y": int(y), "r": round(r, 1),
                      "tier": "kern" if inner else "rand",
                      "type": camp_type(terr, road_d, rad, radii, x, y,
                                        space, N, rng)})
        clear = r * (1.7 if inner else 2.9)
        d[(xx - x) ** 2 + (yy - y) ** 2 < clear * clear] = 0
    return camps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles", type=int, default=256)
    ap.add_argument("--seed", type=int, default=9)
    ap.add_argument("--flows", type=int, default=5)
    ap.add_argument("--tileset", default="assets/tilesets/fire")
    ap.add_argument("--out", default="maps/zone_caldera.json")
    a = ap.parse_args()

    N = a.tiles
    rng = np.random.default_rng(a.seed)
    meta = load_meta(a.tileset)
    ids, sprites = meta["ids"], meta["sprites"]

    print(f"[1/4] Caldera komponieren ({N}x{N}, {a.flows} Lavastroeme) ...")
    terr, plan, rad, road_d = compose(N, rng, a.flows)

    print("[2/4] Boden aufloesen ...")
    ground = build_ground(terr, ids, rng, N)

    print("[3/4] Lager, Bebauung und Deko ...")
    camps = place_camps_radial(N, terr, road_d, rad, rng, plan["radii"],
                               n_max=max(20, int(N * N / 820)))

    # Banditen lauern AM Weg. Die Greedy-Platzierung setzt Lager aber
    # maximal weit von Wegen weg — deshalb ein eigener Durchgang, sonst
    # entsteht dieser Typ nie.
    taken = [(c["x"], c["y"], c["r"]) for c in camps]
    for pts in plan["roads"]:
        for i in range(3, len(pts) - 3, 5):
            if rng.random() > 0.55:
                continue
            (ax0, ay0), (bx0, by0) = pts[i - 1], pts[i + 1]
            dx, dy = bx0 - ax0, by0 - ay0
            nn = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / nn, dx / nn
            s = 1 if rng.random() < 0.5 else -1
            rr = N * 0.022
            gx = int(pts[i][0] + nx * s * (rr + 4))
            gy = int(pts[i][1] + ny * s * (rr + 4))
            if not (3 < gx < N - 4 and 3 < gy < N - 4):
                continue
            if terr[gy, gx] not in (GRASS, SAND):
                continue
            if any((gx - ox) ** 2 + (gy - oy) ** 2 < (rr + orr + 6) ** 2
                   for ox, oy, orr in taken):
                continue
            camps.append({"x": gx, "y": gy, "r": round(rr, 1),
                          "tier": "rand", "type": "banditen"})
            taken.append((gx, gy, rr))

    # Wachlager flankieren die drei Paesse: der Anlauf zum Boss soll bewacht
    # sein, sonst spaziert man ungehindert bis an den Krater.
    ccx0, ccy0 = plan["center"]
    R0 = plan["radii"]
    r_guard = (R0["wall"] + R0["terrace"]) / 2
    for pa in plan["passes"]:
        for s in (-1, 1):
            gx = int(ccx0 + math.cos(pa + s * 0.34) * r_guard)
            gy = int(ccy0 + math.sin(pa + s * 0.34) * r_guard)
            if not (2 < gx < N - 3 and 2 < gy < N - 3):
                continue
            if terr[gy, gx] not in (GRASS, SAND):
                continue
            camps.append({"x": gx, "y": gy, "r": round(N * 0.030, 1),
                          "tier": "kern", "type": "untote"})
    plan["camps"] = camps
    for c in camps:
        if not CAMP_TYPES[c["type"]]["floor"]:
            continue
        f = blob_field(N, c["x"], c["y"], c["r"], rng, rough=0.30)
        lay(terr, (f < 1.5) & np.isin(terr, (GRASS, SAND)), DIRT)
        lay(terr, (f < 0) & np.isin(terr, (GRASS, SAND, DIRT)), ARENA)
    ground = build_ground(terr, ids, rng, N)   # Lager sind Terrain -> neu

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
    tx_, ty_, _sq = plan["square"]
    for pts in [plan["main"]] + plan["cross"]:
        for i in range(1, len(pts) - 1):
            (ax_, ay_), (bx_, by_) = pts[i - 1], pts[i + 1]
            dx, dy = bx_ - ax_, by_ - ay_
            n = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / n, dx / n
            for side in (1, -1):
                name = house_names[int(rng.integers(3))]
                s = sprites[name]
                off = 4.2 + s["h"] / 2 + rng.random()
                hx = int(pts[i][0] + nx * off * side - s["w"] / 2)
                hy = int(pts[i][1] + ny * off * side - s["h"] / 2)
                if free(hx, hy, s["w"], s["h"]):
                    put(name, hx, hy)
                    n_h += 1
    if free(int(tx_) - 1, int(ty_) - 1, 2, 2):
        put("well", int(tx_) - 1, int(ty_) - 1)

    # --- Paesse als Tor kenntlich machen ------------------------------------
    ccx, ccy = plan["center"]
    R = plan["radii"]
    has = sprites.__contains__
    for pa in plan["passes"]:
        px = int(ccx + math.cos(pa) * (R["wall"] + 2))
        py = int(ccy + math.sin(pa) * (R["wall"] + 2))
        tx2, ty2 = -math.sin(pa), math.cos(pa)         # quer zum Pass
        for s in (-4, 4):
            gx, gy = int(px + tx2 * s), int(py + ty2 * s)
            if 0 <= gx < N - 2 and 0 <= gy < N - 2 and not over[gy, gx] \
                    and terr[gy, gx] != WATER:
                put("totem", gx, gy)
        # Wachturm neben jedem Pass — Landmarke aus der Ferne
        if has("tower"):
            wx = int(px + tx2 * 9)
            wy = int(py + ty2 * 9)
            if 0 <= wx < N - 3 and 0 <= wy < N - 4 and not over[wy, wx] \
                    and terr[wy, wx] in (GRASS, SAND):
                put("tower", wx, wy)

    # --- Zonenausgaenge: Torbogen am Kartenrand -----------------------------
    if has("gate"):
        for (gx, gy) in plan.get("gates", []):
            x, y = int(gx) - 1, int(gy) - 1
            if 0 <= x < N - 4 and 0 <= y < N - 3:
                put("gate", x, y, blocking=False)   # begehbar, es ist ein Tor

    # --- Dorf befestigen: Palisade zur Vulkanseite + zwei Tuerme -----------
    # Eine offene Siedlung neben 80 Monsterlagern ergibt keinen Sinn.
    ta_ = math.atan2(ty_ - ccy, tx_ - ccx)
    for k in range(46):
        a2 = ta_ + math.pi + (k / 45 - 0.5) * 2.1     # Bogen zum Krater hin
        px = int(tx_ + math.cos(a2) * N * 0.075)
        py = int(ty_ + math.sin(a2) * N * 0.075)
        if not (0 <= px < N and 0 <= py < N):
            continue
        if terr[py, px] in (COBBLE, WATER, FARM) or over[py, px] or deco[py, px]:
            continue
        deco[py, px] = ids["fence_h"] if abs(math.sin(a2)) < 0.5 else ids["fence_v"]
        block[py, px] = True
    if has("tower"):
        for s in (-1, 1):
            a2 = ta_ + math.pi + s * 1.05
            wx = int(tx_ + math.cos(a2) * N * 0.075) - 1
            wy = int(ty_ + math.sin(a2) * N * 0.075) - 2
            if 0 <= wx < N - 3 and 0 <= wy < N - 4 and not over[wy, wx]:
                put("tower", wx, wy)

    # --- Bosskammer ausstatten ---------------------------------------------
    bx_, by_, br = plan["boss"]
    n_br = max(8, int(br * 1.1))
    for k in range(n_br):                              # Feuerschalen im Kreis
        t = k * 2 * math.pi / n_br
        x, y = int(bx_ + math.cos(t) * br * 0.82), int(by_ + math.sin(t) * br * 0.82)
        if 0 <= x < N and 0 <= y < N and terr[y, x] == ARENA and not deco[y, x]:
            deco[y, x] = ids["campfire"]
    for _ in range(int(br * br * 0.5)):                # Knochenfeld
        t = rng.random() * 2 * math.pi
        d = br * math.sqrt(rng.random()) * 0.72
        x, y = int(bx_ + math.cos(t) * d), int(by_ + math.sin(t) * d)
        if 0 <= x < N and 0 <= y < N and terr[y, x] == ARENA and not deco[y, x]:
            deco[y, x] = ids["skull"] if rng.random() < 0.35 else ids["bones"]
    for k in range(3):                                 # Totems in der Mitte
        t = k * 2 * math.pi / 3 + 0.4
        x, y = int(bx_ + math.cos(t) * br * 0.35), int(by_ + math.sin(t) * br * 0.35)
        if free(x, y, 1, 2) or (0 <= x < N - 2 and 0 <= y < N - 2
                                and terr[y, x] == ARENA and not over[y, x]):
            put("totem", x, y)

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
        for k in range(-9, 10):
            for j in (-1, 0, 1):
                x, y = int(bx + k), int(by + j)
                if 0 <= x < N and 0 <= y < N and terr[y, x] in (DIRT, WATER):
                    deco[y, x] = ids["bridge_h"]
                    block[y, x] = False

    for c in plan["camps"]:
        cx_, cy_, r = c["x"], c["y"], c["r"]
        spec = CAMP_TYPES[c["type"]]
        props = [ids[p] for p in spec["props"]]
        floor = ARENA if spec["floor"] else terr[cy_, cx_]
        for _ in range(int(r * r * 0.75)):
            t = rng.random() * 2 * math.pi
            d = r * math.sqrt(rng.random()) * 0.92
            x, y = int(cx_ + math.cos(t) * d), int(cy_ + math.sin(t) * d)
            if 0 <= x < N and 0 <= y < N and terr[y, x] == floor \
                    and not over[y, x] and not deco[y, x]:
                deco[y, x] = props[int(rng.integers(len(props)))]
        for k, name in enumerate(spec["sprites"]):
            if c["tier"] != "kern" and k > 0:
                break
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
            if terr[y, x] not in (GRASS, SAND) or rng.random() > 0.55:
                continue
            deco[y, x] = (ids["fence_h"] if spec["ring"] == "fence"
                          else ids["boulder"])
            block[y, x] = True

    nests = [(ids["tall_grass"], 30, 7.0), (ids["mushrooms"], 16, 3.5),
             (ids["boulder"], 14, 4.5), (ids["log"], 9, 3.0),
             (ids["bush"], 12, 4.0), (ids["fern"], 14, 3.2)]
    for tile, n_nest, spread in nests:
        for _ in range(n_nest):
            gx, gy = rng.random() * N, rng.random() * N
            for _ in range(int(rng.integers(5, 16))):
                x = int(gx + rng.normal(0, spread))
                y = int(gy + rng.normal(0, spread))
                if not (0 <= x < N and 0 <= y < N):
                    continue
                if terr[y, x] in (GRASS, ROCK, SAND) and not over[y, x] \
                        and not deco[y, x]:
                    deco[y, x] = tile
                    if tile == ids["boulder"]:
                        block[y, x] = True

    print("[4/4] Speichern ...")
    out_dir = os.path.dirname(os.path.abspath(a.out)) or "."
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(a.out))[0]
    ts_rel = os.path.relpath(os.path.join(a.tileset, "tileset.png"),
                             out_dir).replace("\\", "/")

    def layer(name, arr, lid, visible=True, dense=False):
        data = ([int(v) + 1 for v in arr.flatten()] if dense
                else [int(v) + 1 if v else 0 for v in arr.flatten()])
        return {"id": lid, "name": name, "type": "tilelayer", "visible": visible,
                "opacity": 1, "x": 0, "y": 0, "width": N, "height": N,
                "data": data}

    layers = [layer("ground", ground, 1, dense=True),
              layer("decoration", deco, 2), layer("overlay", over, 3),
              layer("collision", block.astype(int), 4, visible=False)]
    tmap = {"type": "map", "version": "1.10", "tiledversion": "1.10.2",
            "orientation": "orthogonal", "renderorder": "right-down",
            "infinite": False, "width": N, "height": N,
            "tilewidth": meta["tile_size"], "tileheight": meta["tile_size"],
            "nextlayerid": 5, "nextobjectid": 1,
            "tilesets": [{"firstgid": 1, "name": "fire", "image": ts_rel,
                          "imagewidth": meta["imagewidth"],
                          "imageheight": meta["imageheight"],
                          "tilewidth": meta["tile_size"],
                          "tileheight": meta["tile_size"],
                          "columns": meta["columns"],
                          "tilecount": meta["count"], "margin": 0,
                          "spacing": 0}],
            "layers": layers}
    with open(a.out, "w") as f:
        json.dump(tmap, f)

    ts = tmap["tilesets"][0]
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<map version="1.10" tiledversion="1.10.2" orientation="orthogonal"'
           f' renderorder="right-down" width="{N}" height="{N}"'
           f' tilewidth="{meta["tile_size"]}" tileheight="{meta["tile_size"]}"'
           f' infinite="0" nextlayerid="5" nextobjectid="1">',
           f' <tileset firstgid="1" name="fire"'
           f' tilewidth="{meta["tile_size"]}" tileheight="{meta["tile_size"]}"'
           f' tilecount="{meta["count"]}" columns="{meta["columns"]}">',
           f'  <image source="{ts["image"]}" width="{ts["imagewidth"]}"'
           f' height="{ts["imageheight"]}"/>', ' </tileset>']
    for lyr in layers:
        vis = '' if lyr["visible"] else ' visible="0"'
        xml.append(f' <layer id="{lyr["id"]}" name="{lyr["name"]}"'
                   f' width="{N}" height="{N}"{vis}>')
        xml.append('  <data encoding="csv">')
        d = lyr["data"]
        xml.append(",\n".join(",".join(str(v) for v in d[r * N:(r + 1) * N])
                              for r in range(N)))
        xml.append('  </data>')
        xml.append(' </layer>')
    xml.append('</map>')
    with open(os.path.splitext(a.out)[0] + ".tmx", "w") as f:
        f.write("\n".join(xml))

    Image.fromarray((block * 255).astype(np.uint8)).save(
        os.path.join(out_dir, f"{base}_collision.png"))
    with open(os.path.join(out_dir, f"{base}_meta.json"), "w") as f:
        json.dump({"name": base, "width_tiles": N, "height_tiles": N,
                   "tile_size": meta["tile_size"], "camps": plan["camps"],
                   "center": {"x": int(ccx), "y": int(ccy)},
                   "radii": {k: round(v, 1) for k, v in plan["radii"].items()},
                   "passes_rad": [round(p, 3) for p in plan["passes"]],
                   "town": {"x": int(tx_), "y": int(ty_)},
                   "bridges": [{"x": int(bx), "y": int(by)}
                               for bx, by in plan["bridges"]]}, f, indent=2)

    # --- Erreichbarkeitspruefung -------------------------------------------
    # Eine Bosskammer, die keiner betreten kann, faellt sonst erst im Spiel
    # auf. Flutfuellung: liegt die Kammer in derselben begehbaren Region wie
    # die Aussenwelt?
    from scipy.ndimage import label
    lab, _ = label(~block)
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    outer = int(np.argmax(sizes))
    ci, cj = int(ccy), int(ccx)
    if not block[ci, cj] and lab[ci, cj] == outer:
        print("  Bosskammer erreichbar (mit der Aussenwelt verbunden)")
    else:
        print("  WARNUNG: Bosskammer NICHT von aussen erreichbar — "
              "Daemme pruefen (R_moat/R_boss/Passwinkel)")

    names = {"Lava": WATER, "Asche": GRASS, "Weg": DIRT, "Basaltplatten": COBBLE,
             "Lager": ARENA, "Schwefel": SAND, "Basalt": ROCK, "Beete": FARM}
    print("  " + "  ".join(f"{k} {(terr == v).mean() * 100:.0f}%"
                           for k, v in names.items()))
    kern = sum(1 for c in plan["camps"] if c["tier"] == "kern")
    print(f"  {len(plan['camps'])} Lager ({kern} auf der Terrasse), "
          f"{n_h} Haeuser, {len(plan['bridges'])} Bruecken, "
          f"blockiert {block.mean() * 100:.0f}%")
    px = N * meta["tile_size"]
    print(f"Fertig -> {a.out}  ({N}x{N} Tiles = {px}x{px} px)")


if __name__ == "__main__":
    main()
