#!/usr/bin/env python3
"""Frostfjord — Eiszone mit Rueckgrat-und-Rippen-Topologie.

Dritte, bewusst eigene Struktur:

  zone_compose  Fluss teilt das Land, freies Wegenetz MIT Schleifen
  zone_caldera  alles RADIAL um einen Krater
  zone_fjord    ein RUECKGRAT mit RIPPEN — Kuestenstrasse am zugefrorenen
                Fjord, davon zweigen Taeler ins Gletschermassiv ab und
                enden in Sackgassen-Kesseln

Warum das anders spielt: Es gibt kaum Rundwege. Wer ein Tal betritt, muss
denselben Weg zurueck — jedes Tal ist eine abgeschlossene Bespielung mit
eigenem Thema und eigenem Ende. Das Rueckgrat bleibt die sichere Achse.

Aufbau:
  Packeis        begehbare Fjordflaeche im Sueden, mit offenen Rinnen
  Kuestenstrasse das Rueckgrat, laeuft am Ufer entlang
  Gletschermassiv unpassierbare Wand im Norden
  vier Taeler    schneiden ins Massiv, jedes endet in einem Kessel:
                   1 Hafensiedlung mit Eisbruch (der Grund fuer den Ort)
                   2 heisse Quellen — warme Oase, das Alleinstellungsmerkmal
                   3 Spaltenfeld — Gefahrenzone
                   4 Thronkessel — der Boss
  Presseisruecken trennen die Taeler

Aufruf:
    python3 mapgen/zone_fjord.py --tiles 256 --tileset assets/tilesets/ice \
        --out maps/zone_fjord.json
"""
import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt, label

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from zone_compose import (ARENA, CAMP_TYPES, COBBLE, DIRT, FARM, GRASS, ROCK,
                          SAND, WATER, blob_field, build_ground, curve,
                          dist_to_path, dist_to_segments, fbm2, lay, path_segs)
from zone_tiles import load_meta


def wiggle(p0, p1, rng, sway=3.0, n=26):
    """Verbindung mit deutlichem Maeander.

    Ein schwacher Versatz reicht nicht: ueber 35 Tiles Laenge sind 4 Tiles
    seitlich unsichtbar, das Tal wirkt wie ein Fahrstuhlschacht. Zwei
    ueberlagerte Wellen mit unterschiedlicher Frequenz geben den Knick.
    """
    ph1, ph2 = rng.random() * 6.3, rng.random() * 6.3
    pts = []
    for i in range(n + 1):
        t = i / n
        x = p0[0] + (p1[0] - p0[0]) * t
        y = p0[1] + (p1[1] - p0[1]) * t
        env = math.sin(t * math.pi) ** 0.6            # an den Enden fixiert
        f = (math.sin(t * 2.1 + ph1) * 0.75
             + math.sin(t * 5.3 + ph2) * 0.35) * sway * env
        pts.append((x + f, y - f * 0.18))
    return pts


def compose(N, rng):
    terr = np.full((N, N), ROCK, dtype=np.int8)   # Start: alles Gletscher
    plan = {}
    yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
    noise = (fbm2(N, rng, 3, 3) - 0.5)

    # Hoehengliederung. Das Massiv darf nur ein Riegel im Norden sein — mit
    # 44 % frass es die halbe Karte und die Taeler wurden zu duennen Stangen.
    shore_y = N * 0.66 + noise * N * 0.06
    land_y = N * 0.26 + noise * N * 0.04
    lay(terr, yy > shore_y, SAND)                 # Packeis, begehbar
    lay(terr, (yy > land_y) & (yy <= shore_y), GRASS)
    plan["shore_y"] = float(N * 0.66)
    plan["land_y"] = float(N * 0.26)

    # Offene Rinnen im Packeis. Nur zwei, und bewusst NICHT ueber die volle
    # Breite — drei durchgehende Baender sahen aus wie ein Barcode.
    leads = []
    for k, (t0, t1) in enumerate(((-0.05, 0.62), (0.34, 1.05))):
        y0 = N * (0.76 + k * 0.11)
        pts = [(t * N, y0 + math.sin(t * 6 + k * 2) * N * 0.030)
               for t in np.linspace(t0, t1, 26)]
        d = dist_to_path(N, pts)
        lay(terr, (d <= 3.2) & (yy > shore_y + 4), WATER)
        leads.append(pts)
    plan["leads"] = leads

    # --- Vier Taeler schneiden ins Massiv ----------------------------------
    # Jedes endet in einem Kessel. Das sind die "Rippen".
    valleys = []
    vx = [N * 0.16, N * 0.39, N * 0.62, N * 0.86]
    depth = [0.115, 0.155, 0.125, 0.075]          # wie weit ins Massiv
    for i, (bx, dp) in enumerate(zip(vx, depth)):
        top = (bx + rng.normal(0, N * 0.015), N * dp)
        bot = (bx, N * 0.34)
        pts = wiggle(top, bot, rng, sway=N * 0.060)
        # Taeler weiten sich zur Muendung: schmal am Kessel, breit unten.
        # Eine einheitliche Breite laesst sie wie Roehren aussehen.
        n_p = len(pts)
        for a0, a1, w in ((0, 0.42, 0.030), (0.36, 0.74, 0.044),
                          (0.68, 1.0, 0.062)):
            sub = pts[int(a0 * (n_p - 1)):int(a1 * (n_p - 1)) + 1]
            if len(sub) >= 2:
                lay(terr, dist_to_path(N, sub) <= N * w, GRASS)
        # Kessel am oberen Ende
        cr = N * (0.082 if i in (0, 3) else 0.070)
        lay(terr, blob_field(N, top[0], top[1], cr, rng, rough=0.22) < 0, GRASS)
        valleys.append({"pts": pts, "head": top, "r": cr})
    plan["valleys"] = valleys

    # --- Kessel 2: heisse Quellen — die warme Oase -------------------------
    hs = valleys[1]["head"]
    lay(terr, blob_field(N, hs[0], hs[1], valleys[1]["r"] * 0.78, rng, 0.3) < 0,
        ARENA)                                    # aufgetauter Boden
    # KEIN Terrain-Wasser fuer die Becken: eng gesetzt verschmelzen sie zu
    # einem grossen dunklen Bassin. Das Sprite bringt Becken, Dampf und
    # Steinrand selbst mit — es muss nur weit genug auseinander stehen.
    springs = []
    for k in range(5):
        a = k * 2 * math.pi / 5 + rng.random() * 0.4
        d = valleys[1]["r"] * (0.48 + rng.random() * 0.32)
        springs.append((hs[0] + math.cos(a) * d, hs[1] + math.sin(a) * d))
    plan["springs"], plan["spring_head"] = springs, hs

    # --- Kessel 3: Spaltenfeld — Gefahrenzone ------------------------------
    cf = valleys[2]["head"]
    for k in range(9):
        a = rng.random() * math.pi
        ln = valleys[2]["r"] * (0.8 + rng.random() * 0.8)
        p0 = (cf[0] - math.cos(a) * ln, cf[1] - math.sin(a) * ln)
        p1 = (cf[0] + math.cos(a) * ln, cf[1] + math.sin(a) * ln)
        lay(terr, dist_to_path(N, [p0, p1]) <= 1.6, WATER)   # Spalte
    plan["crevasse_head"] = cf

    # --- Kessel 4: Thronkessel, der Boss -----------------------------------
    bh = valleys[3]["head"]
    br = valleys[3]["r"] * 0.52
    lay(terr, blob_field(N, bh[0], bh[1], br * 1.7, rng, 0.18) < 0, GRASS)
    lay(terr, blob_field(N, bh[0], bh[1], br * 1.25, rng, 0.2) < 0, WATER)
    lay(terr, blob_field(N, bh[0], bh[1], br, rng, 0.15) < 0, ARENA)
    # zwei Stege auf die Thronplattform
    for s in (-1, 1):
        p0 = (bh[0] + s * br * 0.5, bh[1] + br * 0.4)
        p1 = (bh[0] + s * br * 2.0, bh[1] + br * 1.5)
        lay(terr, dist_to_path(N, [p0, p1]) <= 2.2, DIRT)
    plan["boss"] = (bh[0], bh[1], br)

    # --- Wegenetz: Rueckgrat + Rippen --------------------------------------
    roads = []
    spine = [(t * N, N * 0.575 + math.sin(t * 4.1) * N * 0.030 + noise[
        int(N * 0.5), int(min(max(t * N, 0), N - 1))] * N * 0.02)
        for t in np.linspace(-0.04, 1.04, 40)]
    lay(terr, dist_to_path(N, spine) <= 2.2, COBBLE)     # gepflasterte Achse
    roads.append(spine)

    for i, v in enumerate(valleys):
        base = v["pts"][-1]
        sy = N * 0.575
        # wiggle statt curve: ueber 50 Tiles ist ein Bezier-Bogen praktisch
        # gerade, und die Rippen sahen aus wie Fahrstuhlschaechte
        rib = wiggle((base[0], sy), v["head"], rng, sway=N * 0.038, n=30)
        lay(terr, dist_to_path(N, rib) <= 1.5, DIRT)
        roads.append(rib)
    # Steg vom Ufer aufs Packeis (Fischerpfad)
    pier = [(N * 0.30, N * 0.60), (N * 0.30, N * 0.76)]
    lay(terr, dist_to_path(N, pier) <= 1.6, DIRT)
    roads.append(pier)
    plan["roads"], plan["spine"] = roads, spine

    road_d = dist_to_segments(N, [s for p in roads for s in path_segs(p)])

    # --- Hafensiedlung an der KUESTE, nicht im Bergkessel ------------------
    # Erster Entwurf setzte den Ort in einen Talkessel — dort war kein Platz
    # fuer den Eisbruch, und geschnitten wird Eis ohnehin auf dem gefrorenen
    # Fjord. Der Ort gehoert ans Ufer, neben den Steg.
    tx_, ty_ = N * 0.30, N * 0.495
    plan["town"] = (tx_, ty_)
    main = curve((tx_ - N * 0.075, ty_), (tx_ + N * 0.075, ty_), rng, bow=0.04)
    lay(terr, dist_to_path(N, main) <= 1.9, COBBLE)
    cross = []
    for off in (-N * 0.042, N * 0.040):
        c = curve((tx_ + off, ty_ - N * 0.045), (tx_ + off * 0.9, ty_ + N * 0.045),
                  rng, bow=0.05)
        lay(terr, dist_to_path(N, c) <= 1.4, COBBLE)
        cross.append(c)
    sq = N * 0.020
    terr[int(ty_ - sq):int(ty_ + sq),
         int(tx_ - sq * 1.4):int(tx_ + sq * 1.4)] = COBBLE
    plan["main"], plan["cross"], plan["square"] = main, cross, (tx_, ty_, sq)

    # Eisbruch direkt neben dem Ort — der wirtschaftliche Grund
    # Der Ort liegt in einem Kessel — feste Offsets landen fast immer im
    # Fels, dann fehlt der Eisbruch komplett und die Siedlung hat wieder
    # keinen Existenzgrund. Deshalb Plaetze suchen statt annehmen.
    # Eisbruch AUF dem Packeis vor dem Ort — so wird Eis tatsaechlich
    # gewonnen, und es gibt dort auch Platz.
    fields = []
    w, h = int(N * 0.055), int(N * 0.045)
    for r_ in range(2):
        for c_ in range(3):
            x0 = int(tx_ - N * 0.10 + c_ * N * 0.070)
            y0 = int(N * 0.715 + r_ * N * 0.058)
            if x0 < 2 or y0 < 2 or x0 + w > N - 2 or y0 + h > N - 2:
                continue
            if np.any(np.isin(terr[y0:y0 + h, x0:x0 + w],
                              (WATER, ROCK, COBBLE, GRASS))):
                continue
            terr[y0:y0 + h, x0:x0 + w] = FARM
            fields.append((x0, y0, w, h))
    plan["fields"] = fields
    if fields:
        fx, fy, fw, fh = fields[0]
        work = curve((tx_, ty_), (fx + fw / 2, fy + fh / 2), rng, bow=0.05)
        lay(terr, dist_to_path(N, work) <= 1.3, DIRT)

    # --- Zonenausgaenge an beiden Enden des Rueckgrats ---------------------
    plan["gates"] = [(6.0, spine[1][1]), (N - 9.0, spine[-2][1])]

    return terr, plan, road_d


def place_camps(N, terr, road_d, rng, plan, n_max):
    """Lager in den Taelern und am Ufer.

    Stufe nach TALTIEFE: je weiter ein Lager vom Rueckgrat weg im Tal
    steckt, desto haerter. Das macht jedes Tal zu einer Steigerung.
    """
    # Packeis bewusst AUSGENOMMEN: braune Lagerflecken auf der Eisflaeche
    # sehen falsch aus, und der Fjord soll Transitraum bleiben, kein Farmfeld.
    free = (terr == GRASS) & (road_d > 3.0)
    d = distance_transform_edt(free).astype(np.float32)
    yy, xx = np.mgrid[0:N, 0:N]
    spine_y = N * 0.575
    camps = []
    while len(camps) < n_max:
        idx = int(np.argmax(d))
        y, x = divmod(idx, N)
        space = float(d[y, x])
        if space < 4.5:
            break
        deep = y < spine_y - N * 0.10          # tief im Tal = schwer
        # kleiner als in den anderen Zonen: grosse zertretene Flaechen
        # zerstoeren im Schneefeld die Ruhe der weissen Ebene
        r = min(space * 0.55, 7.0) * (0.62 + rng.random() * 0.50)
        camps.append({"x": int(x), "y": int(y), "r": round(r, 1),
                      "tier": "kern" if deep else "rand",
                      "type": camp_type(terr, road_d, plan, x, y, space, N, rng)})
        clear = r * (1.75 if deep else 2.9)
        d[(xx - x) ** 2 + (yy - y) ** 2 < clear * clear] = 0
    return camps


def camp_type(terr, road_d, plan, x, y, space, N, rng):
    """Typ folgt dem Ort — dieselbe Regel wie in der Caldera."""
    if road_d[y, x] < N * 0.055:
        return "banditen"                     # ueberfallen die Kuestenstrasse
    if y > plan["shore_y"]:
        return "bestien"                      # Robben/Baeren auf dem Packeis
    hx, hy = plan["crevasse_head"]
    if math.hypot(x - hx, y - hy) < N * 0.20:
        return "untote"                       # im und um das Spaltenfeld
    # Am Fuss des Massivs, wo alte Bauten im Eis stecken. Ueber die
    # Fels-Dichte gemessen griff die Regel nie: die Lagerplatzierung sucht
    # offene Flaechen und meidet Fels systematisch.
    if y < plan["land_y"] + N * 0.075:
        return "ruine"
    if space < N * 0.058:
        return "spinnen"
    return "bestien"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiles", type=int, default=256)
    ap.add_argument("--seed", type=int, default=21)
    ap.add_argument("--tileset", default="assets/tilesets/ice")
    ap.add_argument("--out", default="maps/zone_fjord.json")
    a = ap.parse_args()

    N = a.tiles
    rng = np.random.default_rng(a.seed)
    meta = load_meta(a.tileset)
    ids, sprites = meta["ids"], meta["sprites"]
    has = sprites.__contains__

    print(f"[1/4] Fjord komponieren ({N}x{N}) ...")
    terr, plan, road_d = compose(N, rng)

    print("[2/4] Lager setzen ...")
    camps = place_camps(N, terr, road_d, rng, plan,
                        n_max=max(20, int(N * N / 820)))
    # Banditen am Rueckgrat: die Greedy-Suche meidet Wege, also eigener Lauf
    taken = [(c["x"], c["y"], c["r"]) for c in camps]
    for pts in (plan["spine"],):
        for i in range(3, len(pts) - 3, 4):
            if rng.random() > 0.5:
                continue
            rr = N * 0.022
            s = 1 if rng.random() < 0.5 else -1
            gx, gy = int(pts[i][0]), int(pts[i][1] + s * (rr + 5))
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
    plan["camps"] = camps

    for c in camps:
        if not CAMP_TYPES[c["type"]]["floor"]:
            continue
        f = blob_field(N, c["x"], c["y"], c["r"], rng, rough=0.30)
        lay(terr, (f < 1.5) & np.isin(terr, (GRASS, SAND)), DIRT)
        lay(terr, (f < 0) & np.isin(terr, (GRASS, SAND, DIRT)), ARENA)

    print("[3/4] Bebauung und Deko ...")
    ground = build_ground(terr, ids, rng, N)
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
        if not (0 <= x <= N - s["w"] and 0 <= y <= N - s["h"]):
            return False
        for r_ in range(s["h"]):
            for c in range(s["w"]):
                over[y + r_, x + c] = s["tiles"][r_][c]
        if blocking:
            block[y + s["h"] - 1, x:x + s["w"]] = True
            if s["h"] > 1:
                block[y + s["h"] - 2, x:x + s["w"]] = True
        return True

    tx_, ty_, _sq = plan["square"]
    house_names = ["house_a", "house_b", "house_c"]
    n_h = 0
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
                    if put(name, hx, hy):
                        n_h += 1
    if free(int(tx_) - 1, int(ty_) - 1, 2, 2):
        put("well", int(tx_) - 1, int(ty_) - 1)
    if has("tower"):
        for s in (-1, 1):
            put("tower", int(tx_ + s * N * 0.055), int(ty_ - N * 0.035))

    if has("gate"):
        for (gx, gy) in plan["gates"]:
            put("gate", int(gx) - 1, int(gy) - 1, blocking=False)

    # Heisse Quellen: Dampfsprites um die Becken
    if has("hotspring"):
        for (px, py) in plan["springs"]:
            put("hotspring", int(px) - 1, int(py) - 1, blocking=False)

    # Runensteine am Thronkessel
    bx_, by_, br = plan["boss"]
    for k in range(4):
        t = k * math.pi / 2 + 0.5
        put("totem", int(bx_ + math.cos(t) * br * 0.75),
            int(by_ + math.sin(t) * br * 0.75))
    n_br = max(8, int(br * 1.1))
    for k in range(n_br):
        t = k * 2 * math.pi / n_br
        x, y = int(bx_ + math.cos(t) * br * 0.85), int(by_ + math.sin(t) * br * 0.85)
        if 0 <= x < N and 0 <= y < N and terr[y, x] == ARENA and not deco[y, x]:
            deco[y, x] = ids["campfire"]
    for _ in range(int(br * br * 0.5)):
        t = rng.random() * 2 * math.pi
        d = br * math.sqrt(rng.random()) * 0.7
        x, y = int(bx_ + math.cos(t) * d), int(by_ + math.sin(t) * d)
        if 0 <= x < N and 0 <= y < N and terr[y, x] == ARENA and not deco[y, x]:
            deco[y, x] = ids["skull"] if rng.random() < 0.35 else ids["bones"]

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
                if terr[y, x] == FARM and rng.random() < 0.5:
                    deco[y, x] = ids["crops"]

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

    # Wald am Fuss des Massivs, Deko in Nestern
    tree_names = ["tree_a", "tree_b", "tree_c", "pine_a", "pine_b"]
    n_t = 0
    for _ in range(int(N * N * 0.005)):
        gx, gy = rng.random() * N, rng.random() * N
        for _ in range(int(rng.integers(4, 12))):
            x = int(gx + rng.normal(0, 5))
            y = int(gy + rng.normal(0, 5))
            name = tree_names[int(rng.integers(len(tree_names)))]
            s = sprites[name]
            if free(x, y, s["w"], s["h"]) and terr[y, x] == GRASS:
                if put(name, x, y):
                    n_t += 1
    nests = [(ids["tall_grass"], 26, 6.5), (ids["mushrooms"], 18, 3.2),
             (ids["boulder"], 14, 4.5), (ids["log"], 10, 3.0),
             (ids["bush"], 14, 4.0), (ids["fern"], 16, 3.2)]
    for tile, n_nest, spread in nests:
        for _ in range(n_nest):
            gx, gy = rng.random() * N, rng.random() * N
            for _ in range(int(rng.integers(5, 16))):
                x = int(gx + rng.normal(0, spread))
                y = int(gy + rng.normal(0, spread))
                if not (0 <= x < N and 0 <= y < N):
                    continue
                if terr[y, x] in (GRASS, SAND) and not over[y, x] \
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
            "tilesets": [{"firstgid": 1, "name": "ice", "image": ts_rel,
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
           f' <tileset firstgid="1" name="ice"'
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
                   "boss": {"x": int(bx_), "y": int(by_), "r": round(br, 1)},
                   "town": {"x": int(tx_), "y": int(ty_)},
                   "hot_springs": [{"x": int(px), "y": int(py)}
                                   for px, py in plan["springs"]],
                   "valley_heads": [{"x": int(v["head"][0]),
                                     "y": int(v["head"][1])}
                                    for v in plan["valleys"]]}, f, indent=2)

    # Erreichbarkeit des Thronkessels pruefen
    lab, _ = label(~block)
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    outer = int(np.argmax(sizes))
    bi, bj = int(by_), int(bx_)
    if not block[bi, bj] and lab[bi, bj] == outer:
        print("  Thronkessel erreichbar")
    else:
        print("  WARNUNG: Thronkessel NICHT erreichbar — Stege pruefen")

    names = {"Wasser": WATER, "Schnee": GRASS, "Pfad": DIRT, "Strasse": COBBLE,
             "Lager": ARENA, "Packeis": SAND, "Gletscher": ROCK, "Eisbruch": FARM}
    print("  " + "  ".join(f"{k} {(terr == v).mean() * 100:.0f}%"
                           for k, v in names.items()))
    kern = sum(1 for c in plan["camps"] if c["tier"] == "kern")
    print(f"  {len(plan['camps'])} Lager ({kern} tief im Tal), {n_h} Haeuser, "
          f"{n_t} Baeume, blockiert {block.mean() * 100:.0f}%")
    px = N * meta["tile_size"]
    print(f"Fertig -> {a.out}  ({N}x{N} Tiles = {px}x{px} px)")


if __name__ == "__main__":
    main()
