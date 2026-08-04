#!/usr/bin/env python3
"""Tileset "ice" (32 px) — Frostfjord: Schnee, Gletschereis, Packeis.

Wieder dieselben Tile-NAMEN wie painted/fire, damit die Generatoren ohne
Aenderung damit bauen koennen.

  Wiese   -> Schneefeld mit Sastrugi (Windrippeln)
  Wasser  -> offenes, dunkles Wasser (Rinnen im Packeis) — toedlich
  Sand    -> Packeis, begehbar, mit Presseisruecken
  Fels    -> Gletscherwand / Serac, unpassierbar
  Erde    -> festgetretener Schneepfad
  Pflaster-> Steinstrasse mit Schnee in den Fugen
  Acker   -> Eisbruch (geschnittene Bloecke), crops -> gestapelte Bloecke
  Arena   -> zertrampelter Lagerboden

Handwerkliche Grundregeln, die den Look tragen:
  * Schneeschatten sind BLAU, nicht grau — sonst wirkt Schnee schmutzig.
  * Jedes Objekt bekommt eine helle Oberkante (Schneeauflage) und einen
    blauen Schlagschatten. Das erzeugt die Plastik.
  * Warme Akzente (Feuer, Fenster) sind das einzige Gelb im Bild und
    tragen dadurch die ganze Stimmung.

Aufruf:  python3 tools/make_tileset_ice.py
Erzeugt: assets/tilesets/ice/tileset.png + tileset_meta.json
"""
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_tileset_painted import (ALL, COLS, TILE, canvas, corner_field, fbm,
                                  grid, mottle, paint, toplight)

rng = np.random.default_rng(1812)

C = {
    "snow": (226, 234, 244), "snow_lt": (245, 249, 253),
    "snow_md": (203, 214, 232), "snow_sh": (172, 188, 214),
    "snow_deep": (146, 164, 196),
    "ice": (176, 212, 232), "ice_lt": (222, 242, 250), "ice_dk": (116, 160, 194),
    "glacier": (156, 200, 226), "glacier_dk": (98, 140, 178),
    "water": (30, 60, 96), "water_dk": (16, 36, 62), "slush": (132, 164, 194),
    "stone": (96, 104, 120), "stone_lt": (140, 148, 164),
    "stone_dk": (58, 64, 78),
    "path": (182, 190, 206), "path_dk": (146, 156, 176),
    # Zertretener Schnee ist kuehlgrau, nicht erdbraun. Warme Grautoene
    # wirken im Schneefeld wie Schlammpfuetzen.
    "trample": (148, 154, 166), "trample_dk": (104, 112, 128),
    "wood": (112, 80, 54), "wood_dk": (72, 50, 32), "wood_lt": (152, 116, 80),
    "warm": (255, 194, 106), "warm_hot": (255, 232, 180),
    "crystal": (122, 206, 244), "crystal_lt": (198, 240, 255),
    "bone": (232, 234, 236), "fir": (44, 78, 68), "fir_lt": (72, 112, 96),
    "spring": (96, 206, 200), "spring_lt": (168, 236, 228),
}


def snow_shadow(img, cy, cx, ry, rx, alpha=90):
    """Blauer Schlagschatten. Grau wuerde den Schnee schmutzig machen."""
    yy, xx = grid(img)
    m = ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2 < 1
    img[..., :3][m] = C["snow_deep"]
    img[..., 3][m] = np.maximum(img[..., 3][m], alpha)


def cap(img, mask, color=None):
    """Schneeauflage auf der Oberkante eines Objekts — macht die Plastik."""
    color = color or C["snow_lt"]
    up = mask & ~np.roll(mask, 1, 0)
    img[..., :3][up] = color
    img[..., 3][up] = 255
    up2 = np.roll(up, 1, 0) & mask
    img[..., :3][up2] = C["snow"]
    img[..., 3][up2] = 255


# ------------------------------------------------------------ Untergrund ----

def snow(v=0):
    """Schneefeld mit Sastrugi — vom Wind gezogene Rippeln."""
    r = np.random.default_rng(10 + v)
    img = canvas()
    mottle(img, ALL, C["snow_md"], C["snow_lt"], cells=3, r=r)
    yy, xx = grid(img)
    # Sastrugi: flache Wellen quer, mit hellem Kamm und blauem Trog
    warp = fbm((TILE, TILE), 4, 2, r) * 10
    band = np.sin((yy * 0.9 + xx * 0.35 + warp) / 3.6)
    img[..., :3][band > 0.72] = C["snow_lt"]
    img[..., :3][band < -0.78] = C["snow_sh"]
    for _ in range(5 + v):                       # Funkeln
        y, x = r.integers(0, TILE, 2)
        img[y, x, :3] = (255, 255, 255)
    img[..., 3] = 255
    toplight(img, ALL, 0.03)
    return img


def snow_detail(kind, v=0):
    """Varianten der Wiese: Steine, Eisflecken, Frostblumen."""
    img = snow(v)
    r = np.random.default_rng(60 + v)
    if kind == "stones":
        for _ in range(4):
            y, x = r.integers(3, TILE - 4, 2)
            rr = 2 + r.random() * 2
            yy, xx = grid(img)
            m = ((yy - y) / rr) ** 2 + ((xx - x) / (rr * 1.2)) ** 2 < 1
            paint(img, m, C["stone"])
            paint(img, m & (yy < y), C["stone_lt"])
            cap(img, m)
    elif kind == "ice":
        for _ in range(3):
            y, x = r.integers(4, TILE - 5, 2)
            rr = 3 + r.random() * 3
            yy, xx = grid(img)
            m = ((yy - y) / rr) ** 2 + ((xx - x) / (rr * 1.5)) ** 2 < 1
            paint(img, m, C["ice"])
            paint(img, m & (yy < y), C["ice_lt"])
    else:                                        # Frostblumen
        for _ in range(6):
            y, x = r.integers(3, TILE - 3, 2)
            for a in range(6):
                dx = int(np.cos(a * 1.047) * 2.5)
                dy = int(np.sin(a * 1.047) * 2.5)
                if 0 <= y + dy < TILE and 0 <= x + dx < TILE:
                    img[y + dy, x + dx, :3] = C["crystal_lt"]
            img[y, x, :3] = (255, 255, 255)
    return img


def pack_ice(v=0):
    """"Sand": begehbares Packeis mit Presseisruecken."""
    r = np.random.default_rng(80 + v)
    img = canvas()
    # Bewusst gesaettigter und dunkler als Schnee. Waren beide gleich hell,
    # verschwimmt die Kueste — dieselbe Helligkeitsregel wie bei der Feuerzone.
    mottle(img, ALL, C["ice_dk"], C["ice"], cells=3, r=r)
    yy, xx = grid(img)
    # Schollenraender: lange, leicht gebogene Bruchlinien
    n = fbm((TILE, TILE), 3, 2, r)
    edges = np.abs(n - 0.5) < 0.035
    img[..., :3][edges] = C["ice_dk"]
    ridge = np.roll(edges, -1, 0) & ~edges
    img[..., :3][ridge] = (255, 255, 255)        # aufgepresster Grat
    for _ in range(6):
        y, x = r.integers(0, TILE, 2)
        img[y, x, :3] = C["ice_dk"]
    img[..., 3] = 255
    return img


def open_water(v=0):
    """"Wasser": offene Rinne. Dunkel und kalt — klar als Gefahr lesbar."""
    r = np.random.default_rng(50 + v)
    img = canvas()
    mottle(img, ALL, C["water_dk"], C["water"], cells=3, r=r)
    yy, xx = grid(img)
    wave = np.sin((yy + fbm((TILE, TILE), 4, 2, r) * 8) / 3.8)
    img[..., :3] += (wave * 9)[..., None]
    for _ in range(3):                           # Eisschollen im Wasser
        y, x = r.integers(2, TILE - 6, 2)
        w, h = int(r.integers(4, 9)), int(r.integers(2, 4))
        img[y:y + h, x:x + w, :3] = C["slush"]
        img[y, x:x + w, :3] = C["ice_lt"]
    img[..., :3] = np.clip(img[..., :3], 0, 255)
    img[..., 3] = 255
    return img


def packed_path(v=0):
    """"Erde": festgetretener Schnee. Deutlich dunkler als Neuschnee —
    sonst verschwindet der Weg im Feld (Lektion aus der Feuerzone)."""
    r = np.random.default_rng(20 + v)
    img = canvas()
    mottle(img, ALL, C["path_dk"], C["path"], cells=4, r=r)
    for _ in range(14):                          # Trittspuren
        y, x = r.integers(1, TILE - 3, 2)
        img[y:y + 2, x:x + 3, :3] = (162, 170, 188)
    for _ in range(6):
        y, x = r.integers(0, TILE, 2)
        img[y, x, :3] = C["snow_lt"]
    img[..., 3] = 255
    return img


def stone_road(v=0):
    """"Pflaster": dunkle Steinplatten, Schnee in den Fugen."""
    r = np.random.default_rng(30 + v)
    img = canvas()
    mottle(img, ALL, C["stone_dk"], C["stone"], cells=3, r=r)
    yy, xx = grid(img)
    for row, y in enumerate(range(-2, TILE, 8)):
        off = 5 if row % 2 else 0
        for x in range(-6 + off, TILE + 6, 11):
            m = ((yy - (y + 3.5)) / 3.2) ** 2 + ((xx - (x + 5)) / 4.8) ** 2 < 1
            tone = np.array(C["stone"], dtype=float) + r.normal(0, 11)
            img[..., :3][m] = np.clip(tone, 0, 255)
            img[..., :3][m & (yy < y + 3)] = np.clip(tone + 22, 0, 255)
    # Schnee sammelt sich in den Fugen
    gap = fbm((TILE, TILE), 8, 2, r) > 0.60
    img[..., :3][gap] = C["snow_md"]
    img[..., 3] = 255
    toplight(img, ALL, 0.05)
    return img


def trampled(v=0):
    """"Arena": zertrampelter Lagerboden, Schnee mit Erde vermischt."""
    r = np.random.default_rng(40 + v)
    img = canvas()
    mottle(img, ALL, C["trample_dk"], C["trample"], cells=5, r=r)
    for _ in range(7):                           # Schleifspuren
        y, x = r.integers(2, TILE - 2, 2)
        ln = int(r.integers(5, 12))
        a = r.random() * np.pi
        for t in range(ln):
            py = int(y + np.sin(a) * (t - ln / 2))
            px = int(x + np.cos(a) * (t - ln / 2))
            if 0 <= py < TILE and 0 <= px < TILE:
                img[py, px, :3] = (82, 90, 106)
    for _ in range(4):                           # freigetretene Erde
        y, x = r.integers(1, TILE - 3, 2)
        img[y:y + 3, x:x + 3, :3] = (96, 84, 72)
    for _ in range(5):                           # Schneereste
        y, x = r.integers(1, TILE - 2, 2)
        img[y:y + 2, x:x + 2, :3] = C["snow_md"]
    img[..., 3] = 255
    return img


def glacier(v=0):
    """"Fels": Gletscherwand. Blaues Kerneis, weisse Kanten, Spalten."""
    r = np.random.default_rng(70 + v)
    img = canvas()
    # Gletscher unterscheidet sich von Packeis durch STRUKTUR, nicht nur
    # durch den Ton: breite Spalten mit weisser Lippe und tiefblauem Grund.
    # Nur eingefaerbt sah die Wand aus wie Wasser.
    mottle(img, ALL, C["glacier_dk"], C["glacier"], cells=2 + v, r=r)
    yy, xx = grid(img)
    n = fbm((TILE, TILE), 3 + v, 2, r)
    deep = np.abs(n - 0.5) < 0.060                  # breite Spalte
    img[..., :3][deep] = (46, 84, 124)
    core = np.abs(n - 0.5) < 0.022
    img[..., :3][core] = (30, 62, 98)               # Tiefe der Spalte
    lip = np.roll(deep, -2, 0) & ~deep              # aufgeworfene Kante
    img[..., :3][lip] = (255, 255, 255)
    lip2 = np.roll(deep, -1, 0) & ~deep
    img[..., :3][lip2] = C["ice_lt"]
    # Schneefelder auf den Terrassen
    top = fbm((TILE, TILE), 2, 2, r) > 0.62
    img[..., :3][top & ~deep] = C["snow"]
    for _ in range(5):
        y, x = r.integers(0, TILE, 2)
        img[y, x, :3] = (255, 255, 255)
    img[..., 3] = 255
    toplight(img, ALL, 0.09)
    return img


def ice_quarry(v=0):
    """"Acker": Eisbruch — geschnittene Bloecke, wassergefuellte Rinnen."""
    r = np.random.default_rng(90 + v)
    img = canvas()
    mottle(img, ALL, C["ice"], C["ice_lt"], cells=4, r=r)
    for y in range(1 + v * 2, TILE, 8):          # Schnittfugen quer
        img[y:y + 2, :, :3] = C["water"]
        img[max(0, y - 1):y, :, :3] = C["ice_lt"]
    for x in range(4, TILE, 10):                 # Schnittfugen laengs
        img[:, x:x + 2, :3] = C["water"]
        img[:, max(0, x - 1):x, :3] = C["ice_lt"]
    img[..., 3] = 255
    return img


def ice_blocks():
    """"crops": gestapelte Eisbloecke, transparent ueber den Bruch."""
    img = canvas()
    for gy in range(2, TILE - 6, 9):
        for gx in range(2, TILE - 6, 9):
            w, h = 7, 6
            yy, xx = grid(img)
            m = (yy >= gy) & (yy < gy + h) & (xx >= gx) & (xx < gx + w)
            paint(img, m, C["ice"])
            paint(img, m & (yy < gy + 2), C["ice_lt"])
            paint(img, m & (yy >= gy + h - 1), C["ice_dk"])
            paint(img, m & (xx >= gx + w - 1), C["ice_dk"])
    return img


# ----------------------------------------------------- Wang-Uebergaenge ----

def over_snow(combo, tile_img, soft, edge_col=None, fringe=0.34):
    img = snow(0)
    m = corner_field(combo, soft)
    body = m >= 0.5
    img[..., :3][body] = tile_img[..., :3][body]
    fr = (m >= 0.41) & (m < 0.5) & (rng.random((TILE, TILE)) < fringe)
    img[..., :3][fr] = tile_img[..., :3][fr]
    if edge_col is not None:
        e = (m >= 0.5) & (m < 0.55)
        img[..., :3][e] = edge_col
    img[..., 3] = 255
    return img


def water_edge(combo):
    """Der wichtigste Uebergang: Schnee -> Duenneis -> Schneematsch -> Wasser.

    Das Duenneis ist bewusst eine eigene, hellere Stufe: der Spieler soll
    sehen, wo die Flaeche traegt und wo nicht.
    """
    img = snow(0)
    m = corner_field(combo, 0.05)
    w = open_water(0)
    paint(img, (m >= 0.30) & (m < 0.44), C["ice_lt"])     # Duenneis
    paint(img, (m >= 0.44) & (m < 0.54), C["ice"])
    paint(img, (m >= 0.54) & (m < 0.63), C["slush"])      # Schneematsch
    deep = m >= 0.63
    img[..., :3][deep] = w[..., :3][deep]
    rim = (m >= 0.42) & (m < 0.455) & (rng.random((TILE, TILE)) < 0.8)
    paint(img, rim, (255, 255, 255))                      # Eiskante
    img[..., 3] = 255
    return img


def glacier_edge(combo):
    """Gletscherabbruch ins Wasser: Eiswand, Bruchkante, dunkles Wasser."""
    img = glacier(0)
    m = corner_field(combo, 0.05)
    w = open_water(0)
    deep = m >= 0.60
    img[..., :3][deep] = w[..., :3][deep]
    paint(img, (m >= 0.50) & (m < 0.60), C["glacier_dk"])
    paint(img, (m >= 0.42) & (m < 0.50), C["ice_lt"])
    img[..., 3] = 255
    return img


# ----------------------------------------------------------------- Deko ----

def frozen_shrub():
    """"bush": kahler Strauch mit Raureif und Schneehaube."""
    img = canvas()
    snow_shadow(img, 26, 16, 4, 10, alpha=80)
    yy, xx = grid(img)
    branch = np.zeros(img.shape[:2], bool)
    for a, ln in ((-1.9, 12), (-1.4, 14), (-0.9, 11), (-2.4, 10), (-0.4, 9)):
        for t in range(ln):
            px = int(16 + np.cos(a) * t)
            py = int(27 + np.sin(a) * t)
            if 0 <= px < TILE and 0 <= py < TILE:
                branch[py, max(0, px - 1):px + 1] = True
    paint(img, branch, C["wood_dk"])
    paint(img, branch & (xx < 16), (96, 72, 52))
    cap(img, branch)
    for _ in range(6):                            # Raureifpunkte
        y, x = rng.integers(8, 26), rng.integers(6, 26)
        if branch[y, x]:
            img[y, x, :3] = C["crystal_lt"]
    return img


def frost_crystals():
    """"fern": Eiskristall-Faecher, leicht leuchtend."""
    img = canvas()
    for k in range(7):
        a = -np.pi / 2 + (k - 3) * 0.30
        ln = 8 + rng.random() * 6
        for t in np.linspace(0, 1, 14):
            px = int(16 + np.cos(a) * ln * t)
            py = int(27 + np.sin(a) * ln * t)
            if 0 <= px < TILE and 0 <= py < TILE:
                img[py, px, :3] = C["crystal"] if t < 0.7 else C["crystal_lt"]
                img[py, px, 3] = 255
    paint(img, (np.abs(grid(img)[0] - 28) < 2) & (np.abs(grid(img)[1] - 16) < 5),
          C["ice"])
    return img


def glow_crystals():
    """"mushrooms": leuchtende Eiskristalle — das magische Element."""
    img = canvas()
    yy, xx = grid(img)
    for _ in range(4):
        x, y = rng.integers(6, TILE - 6), rng.integers(10, TILE - 4)
        h = int(rng.integers(6, 11))
        w = 2.2
        m = (np.abs(xx - x) * (h / w) + (yy - y)) < 0
        m &= yy > y - h
        paint(img, m, C["crystal"])
        paint(img, m & (xx < x), C["crystal_lt"])
        # Lichthof
        halo = ((yy - (y - h * 0.6)) ** 2 + (xx - x) ** 2) < 9
        img[..., :3][halo & ~m] = (150, 220, 250)
        img[..., 3][halo & ~m] = np.maximum(img[..., 3][halo & ~m], 90)
    return img


def driftwood():
    """"log": vereister Treibholzstamm."""
    img = canvas()
    snow_shadow(img, 22, 16, 3, 13)
    yy, xx = grid(img)
    body = (np.abs(yy - 17) < 5) & (xx > 2) & (xx < TILE - 3)
    mottle(img, body, C["wood_dk"], C["wood"], cells=3)
    for x in range(4, TILE - 4, 5):
        paint(img, body & (np.abs(xx - x) < 1), C["wood_dk"])
    cap(img, body)
    ring = ((yy - 17) ** 2 / 25 + (xx - TILE + 5) ** 2 / 6) < 1
    paint(img, ring, C["wood_lt"])
    return img


def erratic():
    """"boulder": Findling mit Schneehaube und Eiskante."""
    img = canvas()
    snow_shadow(img, 26, 16, 4, 12)
    yy, xx = grid(img)
    m = ((yy - 18) / 9.0) ** 2 + ((xx - 16) / 11.0) ** 2 < 1
    mottle(img, m, C["stone_dk"], C["stone"], cells=3)
    paint(img, m & (yy > 24), (44, 50, 62))
    cap(img, m)
    for _ in range(7):
        y, x = rng.integers(11, 26), rng.integers(7, 26)
        if m[y, x]:
            img[y, x, :3] = C["stone_lt"]
    return img


def bones_ice():
    img = canvas()
    for _ in range(3):
        x, y = rng.integers(6, TILE - 6), rng.integers(8, TILE - 6)
        a = rng.random() * np.pi
        for t in range(-5, 6):
            px, py = int(x + np.cos(a) * t), int(y + np.sin(a) * t)
            if 0 <= px < TILE and 0 <= py < TILE:
                img[py, px, :3] = C["bone"]; img[py, px, 3] = 255
        for s in (-5, 5):
            px, py = int(x + np.cos(a) * s), int(y + np.sin(a) * s)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if 0 <= px + dx < TILE and 0 <= py + dy < TILE:
                        img[py + dy, px + dx, :3] = C["bone"]
                        img[py + dy, px + dx, 3] = 255
    return img


def skull_ice():
    img = canvas()
    snow_shadow(img, 23, 16, 3, 8, alpha=70)
    yy, xx = grid(img)
    m = ((yy - 16) / 7.0) ** 2 + ((xx - 16) / 8.0) ** 2 < 1
    paint(img, m, C["bone"])
    cap(img, m)
    for ex in (12, 20):
        paint(img, ((yy - 16) ** 2 / 6 + (xx - ex) ** 2 / 4) < 1, (58, 78, 102))
    paint(img, (np.abs(yy - 22) < 2) & (np.abs(xx - 16) < 4), (206, 210, 214))
    return img


def snow_campfire():
    """"campfire": Feuer im Schnee mit aufgetautem Ring — der warme Akzent."""
    img = canvas()
    yy, xx = grid(img)
    thaw = (((yy - 20) / 10.0) ** 2 + ((xx - 16) / 13.0) ** 2 < 1)
    paint(img, thaw, C["trample_dk"])             # Schnee ringsum getaut
    ring = (((yy - 21) / 5.0) ** 2 + ((xx - 16) / 8.0) ** 2 < 1)
    paint(img, ring, C["stone"])
    paint(img, ring & (yy < 19), C["stone_lt"])
    for a in (0.4, 1.5, 2.6):
        for t in range(-6, 7):
            px, py = int(16 + np.cos(a) * t), int(21 + np.sin(a) * t * 0.55)
            if 0 <= px < TILE and 0 <= py < TILE:
                img[py, px, :3] = C["wood"]; img[py, px, 3] = 255
    flame = (((yy - 14) / 7.0) ** 2 + ((xx - 16) / 4.2) ** 2 < 1)
    paint(img, flame, C["warm"])
    paint(img, (((yy - 11) / 4.0) ** 2 + ((xx - 16) / 2.2) ** 2 < 1), C["warm_hot"])
    return img


def witchlight():
    """"lantern": blaue Laterne an einem Eisenhaken."""
    img = canvas()
    snow_shadow(img, 29, 16, 2, 5, alpha=70)
    yy, xx = grid(img)
    paint(img, (yy > 14) & (yy < 29) & (np.abs(xx - 16) < 2), C["stone_dk"])
    head = (((yy - 11) / 5.0) ** 2 + ((xx - 16) / 4.0) ** 2 < 1)
    paint(img, head, C["crystal"])
    paint(img, head & (yy < 10), C["crystal_lt"])
    paint(img, (np.abs(yy - 6) < 2) & (np.abs(xx - 16) < 5), C["stone_dk"])
    halo = (((yy - 11) / 8.0) ** 2 + ((xx - 16) / 7.0) ** 2 < 1) & ~head
    img[..., :3][halo] = (140, 200, 236)
    img[..., 3][halo] = np.maximum(img[..., 3][halo], 70)
    return img


def signpost_ice():
    img = canvas()
    snow_shadow(img, 29, 16, 2, 6, alpha=70)
    yy, xx = grid(img)
    post = (yy > 12) & (yy < 29) & (np.abs(xx - 15) < 2)
    paint(img, post, C["wood_dk"])
    board = (yy > 9) & (yy < 18) & (xx > 8) & (xx < 27)
    paint(img, board, C["wood"])
    cap(img, board)
    paint(img, (yy > 13) & (yy < 15) & (xx > 11) & (xx < 24), C["wood_dk"])
    for x in (11, 17, 23):                        # Eiszapfen
        paint(img, (yy >= 18) & (yy < 21 + (x % 3)) & (np.abs(xx - x) < 1),
              C["ice_lt"])
    return img


def snow_tufts():
    """"tall_grass": gefrorene Halme, die aus dem Schnee ragen."""
    img = canvas()
    for _ in range(13):
        x, y = rng.integers(3, TILE - 3), rng.integers(12, TILE - 2)
        h = int(rng.integers(5, 10))
        col = (140, 130, 106) if rng.random() < 0.6 else (168, 158, 132)
        img[max(0, y - h):y, x, :3] = col
        img[max(0, y - h):y, x, 3] = 255
        img[max(0, y - h), x, :3] = C["snow_lt"]
        img[max(0, y - h), x, 3] = 255
    return img


def ice_stake_h():
    """"fence_h": Palisade aus Eispfaehlen."""
    img = canvas()
    yy, xx = grid(img)
    for x in (5, 13, 21, 29):
        m = (np.abs(xx - x) * 4 + (yy - 27)) < 0
        m &= yy > 9
        paint(img, m, C["ice"])
        paint(img, m & (xx < x), C["ice_lt"])
        paint(img, m & (yy > 24), C["ice_dk"])
    return img


def ice_stake_v():
    return np.rot90(ice_stake_h(), 1).copy()


def plank_bridge(vertical=False):
    """Steg ueber offenes Wasser, mit Schnee auf den Planken."""
    img = canvas()
    yy, xx = grid(img)
    long_, cross = (yy, xx) if vertical else (xx, yy)
    deck = np.abs(cross - 15.5) < 13
    mottle(img, deck, C["wood_dk"], C["wood"], cells=3)
    for k in range(0, TILE, 5):
        paint(img, deck & (np.abs(long_ - k) < 1), (52, 36, 24))
    snowy = deck & (fbm((TILE, TILE), 6, 2, rng) > 0.55)
    paint(img, snowy, C["snow_md"])
    for s in (-13, 12):
        paint(img, np.abs(cross - 15.5 - s) < 1.6, C["wood_lt"])
    return img


# -------------------------------------------------------------- Sprites ----

def snow_fir(seed=0):
    """"tree": Tanne unter Schneelast — die Silhouette der Zone."""
    r = np.random.default_rng(300 + seed)
    img = canvas(2, 2)
    snow_shadow(img, 57, 32, 5, 16, alpha=84)
    yy, xx = grid(img)
    trunk = (yy > 46) & (yy < 60) & (np.abs(xx - 32) < 3)
    paint(img, trunk, C["wood_dk"])
    # drei Kranzlagen, jede mit Schneeauflage
    for ty, tw in ((52, 26), (38, 21), (24, 15)):
        tri = (yy <= ty) & (yy > ty - 20) & \
              (np.abs(xx - 32) < (yy - (ty - 20)) * tw / 20.0)
        mottle(img, tri, C["fir"], C["fir_lt"], cells=2, r=r)
        paint(img, tri & (xx < 30) & (yy < ty - 5), C["fir_lt"])
        # Schnee liegt auf den Zweigenden
        lip = tri & ~np.roll(tri, 1, 0)
        img[..., :3][lip] = C["snow_lt"]
        img[..., 3][lip] = 255
        lip2 = np.roll(lip, 1, 0) & tri
        img[..., :3][lip2] = C["snow"]
    paint(img, (yy > 8) & (yy < 14) & (np.abs(xx - 32) < 2), C["snow_lt"])
    for _ in range(10):
        y, x = int(r.integers(14, 52)), int(r.integers(14, 50))
        if img[y, x, 3] > 0 and r.random() < 0.5:
            img[y, x, :3] = C["snow_lt"]
    return img


def frost_pine(seed=0):
    r = np.random.default_rng(400 + seed)
    img = canvas(1, 2)
    snow_shadow(img, 58, 16, 4, 9, alpha=78)
    yy, xx = grid(img)
    paint(img, (yy > 48) & (yy < 60) & (np.abs(xx - 16) < 2), C["wood_dk"])
    for ty, tw in ((48, 13), (36, 10), (24, 7)):
        tri = (yy <= ty) & (yy > ty - 16) & \
              (np.abs(xx - 16) < (yy - (ty - 16)) * tw / 16.0)
        mottle(img, tri, C["fir"], C["fir_lt"], cells=2, r=r)
        lip = tri & ~np.roll(tri, 1, 0)
        img[..., :3][lip] = C["snow_lt"]
        img[..., 3][lip] = 255
    return img


def hide_tent():
    """"tent": Fellzelt der Jaeger — warm beleuchteter Eingang."""
    img = canvas(2, 2)
    snow_shadow(img, 57, 32, 6, 20, alpha=82)
    yy, xx = grid(img)
    body = (yy > 18) & (yy < 56) & (np.abs(xx - 32) < (yy - 16) * 0.70)
    mottle(img, body, (96, 78, 62), (146, 124, 100), cells=3)
    paint(img, body & (xx < 32), (118, 98, 78))
    cap(img, body)
    for k in range(20, 56, 7):                    # Naehte
        paint(img, body & (np.abs(yy - k) < 1), (78, 62, 48))
    door = (yy > 34) & (yy < 56) & (np.abs(xx - 32) < 7)
    paint(img, door, (46, 36, 28))
    paint(img, door & (yy > 46), C["warm"])       # Feuerschein im Zelt
    for s in (-1, 1):                             # Stangen
        paint(img, (yy > 10) & (yy < 22) & (np.abs(xx - (32 + s * 3)) < 1),
              C["wood_dk"])
    return img


def rune_stone():
    """"totem": Runenstein mit blauem Leuchten."""
    img = canvas(1, 2)
    snow_shadow(img, 58, 16, 4, 10, alpha=80)
    yy, xx = grid(img)
    body = (yy > 16) & (yy < 58) & (np.abs(xx - 16) < 8 - (yy - 16) * 0.04)
    mottle(img, body, C["stone_dk"], C["stone"], cells=2)
    paint(img, body & (xx < 15), C["stone_lt"])
    cap(img, body)
    for y in (26, 36, 46):                        # Runen
        paint(img, (np.abs(yy - y) < 2) & (np.abs(xx - 16) < 5), C["crystal"])
        paint(img, (np.abs(yy - y) < 1) & (np.abs(xx - 16) < 3), C["crystal_lt"])
    return img


def ice_hole():
    """"well": Eisloch zum Fischen — Rand aus Eisbloecken, Seil."""
    img = canvas(2, 2)
    snow_shadow(img, 56, 32, 6, 20, alpha=80)
    yy, xx = grid(img)
    rim = (((yy - 44) / 12.0) ** 2 + ((xx - 32) / 18.0) ** 2 < 1)
    inner = (((yy - 44) / 7.0) ** 2 + ((xx - 32) / 12.0) ** 2 < 1)
    mottle(img, rim & ~inner, C["ice"], C["ice_lt"], cells=3)
    paint(img, inner, C["water_dk"])
    paint(img, inner & (yy < 42), C["water"])
    for x in (14, 50):                            # Gestell
        paint(img, (yy > 14) & (yy < 44) & (np.abs(xx - x) < 2), C["wood_dk"])
    paint(img, (yy > 12) & (yy < 16) & (xx > 12) & (xx < 52), C["wood"])
    cap(img, (yy > 12) & (yy < 16) & (xx > 12) & (xx < 52))
    paint(img, (yy > 16) & (yy < 40) & (np.abs(xx - 32) < 1), (200, 196, 184))
    return img


def hot_spring():
    """"hotspring": das Alleinstellungsmerkmal der Zone.

    Dampfende Quelle im Eis: tuerkises Wasser, aufgetauter Ring mit Moos,
    warme Steine, Dampfschwaden. Farblich der einzige Gegenpol zum Blau —
    und deshalb 3x3 statt 2x2: das Becken soll als Ort wirken, nicht als
    Requisit.
    """
    img = canvas(3, 3)
    yy, xx = grid(img)
    cy, cx = 54, 48
    thaw = (((yy - cy) / 34.0) ** 2 + ((xx - cx) / 42.0) ** 2 < 1)
    mottle(img, thaw, (86, 78, 70), (124, 114, 102), cells=3)
    moss = thaw & (fbm((96, 96), 4, 2, rng) > 0.56)
    paint(img, moss, (78, 116, 84))               # Moos im Warmen
    pool = (((yy - cy) / 22.0) ** 2 + ((xx - cx) / 29.0) ** 2 < 1)
    mottle(img, pool, (52, 152, 150), C["spring"], cells=3)
    paint(img, pool & (((yy - cy) / 14.0) ** 2 + ((xx - cx) / 20.0) ** 2 < 1),
          C["spring_lt"])
    rimm = pool & ~np.roll(pool, 3, 0)
    paint(img, rimm, (206, 246, 240))
    for _ in range(18):                           # warme Steine am Rand
        a = rng.random() * 2 * np.pi
        sx = int(cx + np.cos(a) * 32)
        sy = int(cy + np.sin(a) * 25)
        m = ((yy - sy) ** 2 + (xx - sx) ** 2) < 12
        paint(img, m, C["stone"])
        paint(img, m & (yy < sy), C["stone_lt"])
        cap(img, m)
    for _ in range(22):                           # Dampfschwaden
        x, y = rng.integers(18, 78), rng.integers(4, 40)
        rr = 4 + rng.random() * 6
        m = ((yy - y) / rr) ** 2 + ((xx - x) / (rr * 1.6)) ** 2 < 1
        img[..., :3][m] = (234, 246, 246)
        img[..., 3][m] = np.maximum(img[..., 3][m], 100)
    return img


def longhouse(seed=0, w_tiles=5):
    """"house": Langhaus mit steilem Schneedach und warmen Fenstern.

    Steiles Dach, weil Schnee abrutschen muss — und weil die Silhouette
    dadurch nordisch liest statt mitteleuropaeisch.
    """
    r = np.random.default_rng(500 + seed)
    W, H = w_tiles * TILE, 4 * TILE
    img = canvas(w_tiles, 4)
    yy, xx = grid(img)
    roof_y0, roof_y1, wall_y1 = 4, 58, H - 12
    snow_shadow(img, H - 8, W // 2, 6, W // 2 - 6, alpha=84)
    wall = (yy >= roof_y1) & (yy < wall_y1) & (xx >= 8) & (xx < W - 8)
    mottle(img, wall, (92, 68, 48), (132, 102, 74), cells=3, r=r)
    for x in range(10, W - 10, 9):                # senkrechte Bohlen
        paint(img, wall & (np.abs(xx - x) < 1), (70, 52, 36))
    beams = wall & ((xx < 13) | (xx >= W - 13) | (yy >= wall_y1 - 6))
    paint(img, beams, (62, 46, 32))
    eave = (yy >= roof_y1) & (yy < roof_y1 + 6) & (xx >= 8) & (xx < W - 8)
    img[..., :3][eave] = (54, 42, 30)
    # Steildach: Schindeln unten, dicke Schneeauflage oben
    roof = (yy >= roof_y0) & (yy < roof_y1) & (xx >= 2) & (xx < W - 2)
    mottle(img, roof, (58, 50, 44), (92, 82, 72), cells=3, r=r)
    for i, y in enumerate(range(roof_y0 + 8, roof_y1, 8)):
        paint(img, roof & (yy >= y) & (yy < y + 1), (42, 36, 32))
    # nur die obere Dachhaelfte unter Schnee, sonst verschwinden die
    # Schindeln und das Dach wird eine weisse Platte
    snowcap = roof & (yy < roof_y0 + 18 + (fbm((H, W), 5, 2, r) * 10))
    paint(img, snowcap, C["snow"])
    paint(img, snowcap & (yy < roof_y0 + 16), C["snow_lt"])
    # Eiszapfen an der Traufe
    for x in range(8, W - 8, 7):
        h = int(r.integers(3, 8))
        paint(img, (yy >= roof_y1 - 1) & (yy < roof_y1 - 1 + h)
              & (np.abs(xx - x) < 1), C["ice_lt"])
    ch = W - 44                                   # Schornstein mit Rauch
    paint(img, (yy < roof_y0 + 12) & (xx >= ch) & (xx < ch + 12), C["stone"])
    paint(img, (yy < roof_y0 + 3) & (xx >= ch - 2) & (xx < ch + 14),
          C["stone_lt"])
    dx0 = W // 2 - 10
    door = (yy >= roof_y1 + 20) & (yy < wall_y1) & (xx >= dx0) & (xx < dx0 + 20)
    paint(img, door, (48, 34, 24))
    paint(img, door & ((xx - dx0) % 6 < 1), (34, 24, 18))
    for wx in (26, W - 48):
        fr = ((yy >= roof_y1 + 18) & (yy < roof_y1 + 40)
              & (xx >= wx) & (xx < wx + 22))
        paint(img, fr, (62, 46, 32))
        glass = ((yy >= roof_y1 + 21) & (yy < roof_y1 + 37)
                 & (xx >= wx + 3) & (xx < wx + 19))
        paint(img, glass, C["warm"])              # warmes Licht = Leben
        paint(img, glass & ((xx - yy) % 9 < 2), C["warm_hot"])
        paint(img, glass & (np.abs(xx - wx - 11) < 1), (62, 46, 32))
    paint(img, (yy >= wall_y1 - 6) & (yy < wall_y1) & (xx >= 8) & (xx < W - 8)
          & ~door, C["snow_md"])                  # Schneewehe am Sockel
    return img


def watchtower_ice():
    img = canvas(2, 3)
    yy, xx = grid(img)
    snow_shadow(img, 89, 32, 6, 20, alpha=84)
    base = (yy > 74) & (yy < 92) & (np.abs(xx - 32) < 20)
    mottle(img, base, C["stone_dk"], C["stone"], cells=2)
    shaft = (yy > 26) & (yy <= 76) & (np.abs(xx - 32) < 13)
    mottle(img, shaft, C["stone_dk"], C["stone_lt"], cells=3)
    for y in range(30, 76, 8):
        paint(img, shaft & (np.abs(yy - y) < 1), C["stone_dk"])
    crown = (yy > 16) & (yy <= 28) & (np.abs(xx - 32) < 17)
    mottle(img, crown, C["stone"], C["stone_lt"], cells=2)
    cap(img, crown)
    for x in range(17, 49, 8):
        m = (yy > 10) & (yy <= 18) & (np.abs(xx - x) < 3)
        paint(img, m, C["stone_lt"])
        cap(img, m)
    paint(img, (((yy - 8) / 5.0) ** 2 + ((xx - 32) / 6.0) ** 2 < 1), C["warm"])
    paint(img, (((yy - 6) / 3.0) ** 2 + ((xx - 32) / 3.5) ** 2 < 1), C["warm_hot"])
    paint(img, (yy > 60) & (yy < 76) & (np.abs(xx - 32) < 5), (34, 28, 24))
    for y in (40, 52):
        paint(img, (np.abs(yy - y) < 3) & (np.abs(xx - 32) < 2), C["warm"])
    return img


def ice_gate():
    """"gate": Torbogen aus Eis und Stein mit Runen."""
    img = canvas(3, 2)
    yy, xx = grid(img)
    snow_shadow(img, 60, 48, 5, 34, alpha=80)
    for px in (18, 78):
        pil = (yy > 14) & (yy < 62) & (np.abs(xx - px) < 10)
        mottle(img, pil, C["stone_dk"], C["stone_lt"], cells=2)
        for y in range(18, 62, 8):
            paint(img, pil & (np.abs(yy - y) < 1), C["stone_dk"])
        cap(img, pil)
    lint = (yy > 8) & (yy < 24) & (xx > 8) & (xx < 88)
    mottle(img, lint, C["stone"], C["stone_lt"], cells=2)
    cap(img, lint)
    for rx in range(22, 80, 12):
        paint(img, (np.abs(yy - 17) < 3) & (np.abs(xx - rx) < 2), C["crystal"])
    for px in (18, 78):
        paint(img, (((yy - 6) / 4.0) ** 2 + ((xx - px) / 4.0) ** 2 < 1),
              C["crystal_lt"])
    for x in range(12, 86, 6):                    # Eiszapfen am Sturz
        h = int(rng.integers(3, 9))
        paint(img, (yy >= 24) & (yy < 24 + h) & (np.abs(xx - x) < 1), C["ice_lt"])
    return img


# ---------------------------------------------------------------- Sheet ----

def build():
    singles, sprites, tiles = {}, {}, []

    def add(name, img):
        singles[name] = len(tiles)
        tiles.append(img)

    def add_sprite(name, img):
        th, tw = img.shape[0] // TILE, img.shape[1] // TILE
        ids = []
        for r_ in range(th):
            ids.append([])
            for c in range(tw):
                ids[-1].append(len(tiles))
                tiles.append(img[r_ * TILE:(r_ + 1) * TILE,
                                 c * TILE:(c + 1) * TILE])
        sprites[name] = {"w": tw, "h": th, "tiles": ids}

    add("grass_1", snow(0))
    add("grass_2", snow_detail("stones", 1))
    add("grass_3", snow_detail("ice", 2))
    add("grass_4", snow(3))
    add("grass_flowers_red", snow_detail("frost", 1))
    add("grass_flowers_blue", snow_detail("frost", 2))
    add("grass_flowers_yellow", snow_detail("ice", 3))
    for i in range(2):
        add(f"dirt_{i + 1}", packed_path(i))
    for i in range(2):
        add(f"cobble_{i + 1}", stone_road(i))
    for i in range(2):
        add(f"arena_{i + 1}", trampled(i))
    add("water", open_water(0))
    add("rock", glacier(0))
    add("rock_2", glacier(1))
    add("rock_3", glacier(2))
    for i in range(2):
        add(f"sand_{i + 1}", pack_ice(i))
    for i in range(2):
        add(f"farm_{i + 1}", ice_quarry(i))
    add("crops", ice_blocks())
    add("fence_h", ice_stake_h())
    add("fence_v", ice_stake_v())
    add("bridge_h", plank_bridge(False))
    add("bridge_v", plank_bridge(True))

    for combo in range(16):
        add(f"water_grass_{combo}", water_edge(combo))
    for combo in range(16):
        add(f"dirt_grass_{combo}", over_snow(combo, packed_path(0), 0.07,
                                             edge_col=(160, 170, 190)))
    for combo in range(16):
        add(f"cobble_grass_{combo}", over_snow(combo, stone_road(0), 0.05,
                                               edge_col=C["stone_lt"]))
    for combo in range(16):
        add(f"arena_grass_{combo}", over_snow(combo, trampled(0), 0.08))
    for combo in range(16):
        add(f"cliff_water_{combo}", glacier_edge(combo))
    for combo in range(16):
        add(f"rock_grass_{combo}", over_snow(combo, glacier(0), 0.05,
                                             edge_col=C["ice_lt"]))
    for combo in range(16):
        add(f"sand_grass_{combo}", over_snow(combo, pack_ice(0), 0.07))
    for combo in range(16):
        add(f"farm_grass_{combo}", over_snow(combo, ice_quarry(0), 0.04,
                                             edge_col=C["ice_dk"]))

    add("bush", frozen_shrub())
    add("fern", frost_crystals())
    add("mushrooms", glow_crystals())
    add("log", driftwood())
    add("boulder", erratic())
    add("bones", bones_ice())
    add("skull", skull_ice())
    add("campfire", snow_campfire())
    add("lantern", witchlight())
    add("signpost", signpost_ice())
    add("tall_grass", snow_tufts())

    add_sprite("tree_a", snow_fir(0))
    add_sprite("tree_b", snow_fir(1))
    add_sprite("tree_c", snow_fir(2))
    add_sprite("pine_a", frost_pine(0))
    add_sprite("pine_b", frost_pine(1))
    add_sprite("tent", hide_tent())
    add_sprite("totem", rune_stone())
    add_sprite("well", ice_hole())
    add_sprite("hotspring", hot_spring())
    add_sprite("house_a", longhouse(0, 5))
    add_sprite("house_b", longhouse(1, 5))
    add_sprite("house_c", longhouse(2, 4))
    add_sprite("tower", watchtower_ice())
    add_sprite("gate", ice_gate())

    rows = (len(tiles) + COLS - 1) // COLS
    sheet = np.zeros((rows * TILE, COLS * TILE, 4), dtype=np.uint8)
    for i, t in enumerate(tiles):
        r_, c = divmod(i, COLS)
        sheet[r_ * TILE:(r_ + 1) * TILE, c * TILE:(c + 1) * TILE] = \
            np.clip(t, 0, 255).astype(np.uint8)

    out_dir = "assets/tilesets/ice"
    os.makedirs(out_dir, exist_ok=True)
    Image.fromarray(sheet).save(f"{out_dir}/tileset.png")
    with open(f"{out_dir}/tileset_meta.json", "w") as f:
        json.dump({"tile_size": TILE, "columns": COLS, "count": len(tiles),
                   "ids": singles, "sprites": sprites}, f, indent=2)
    print(f"{len(tiles)} Tiles ({len(sprites)} Sprites) -> {out_dir}/tileset.png")


if __name__ == "__main__":
    build()
