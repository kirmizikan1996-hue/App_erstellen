#!/usr/bin/env python3
"""Tileset "fire" (32 px) — Vulkanzone: Asche, Lava, Basalt, Schwefel.

Bewusst dieselben Tile-NAMEN wie assets/tilesets/painted. Das Tileset ist
damit ein reiner Skin: derselbe Generator baut mit --tileset eine Feuerzone,
ohne dass eine Zeile Layoutcode geaendert werden muss.

  Wiese   -> Ascheebene mit Glutadern
  Wasser  -> Lava
  Fels    -> Basalt mit gluehenden Rissen
  Sand    -> Schwefelablagerungen
  Acker   -> Schwefelbeete, "crops" -> Schwefelkristalle
  Pflaster-> Basaltplatten,  Weg -> Schlackepfad
  Arena   -> verbrannter Kampfboden

Aufruf:  python3 tools/make_tileset_fire.py
Erzeugt: assets/tilesets/fire/tileset.png + tileset_meta.json
"""
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_tileset_painted import (ALL, COLS, TILE, canvas, corner_field, fbm,
                                  grid, mottle, paint, shadow, toplight)

rng = np.random.default_rng(4711)

F = {
    "ash": (62, 55, 52), "ash_lt": (98, 88, 82), "ash_dk": (38, 33, 32),
    "ember": (228, 112, 40), "ember_hot": (255, 198, 96),
    "lava": (250, 92, 22), "lava_hot": (255, 216, 128), "lava_dk": (162, 38, 10),
    "crust": (46, 36, 34), "crust_lt": (78, 62, 56),
    "basalt": (52, 47, 52), "basalt_lt": (92, 84, 92), "basalt_dk": (28, 25, 30),
    "obsidian": (36, 31, 42), "obsidian_lt": (78, 68, 92),
    "sulfur": (170, 152, 70), "sulfur_lt": (216, 200, 106),
    # Deutlich heller als die Ascheebene: mit aehnlichem Braun wie die Asche
    # verschwinden die Wege komplett im Untergrund. Wege = zertretener,
    # heller Bimskies.
    "cinder": (122, 110, 100), "cinder_lt": (166, 152, 140),
    "bone": (224, 214, 196), "iron": (94, 90, 94),
}


def glow_cracks(img, mask, r, density=0.55, hot=None):
    """Gluehende Risse — sparsam! Ohne die regionale Sperre unten ueberzieht
    das Adernetz die ganze Flaeche und Asche sieht aus wie Lava; dann faellt
    der echte Lavastrom nicht mehr auf."""
    hot = hot or F["ember"]
    n = fbm(img.shape[:2], 6, 3, r)
    # nur in einem Teil der Kachel ueberhaupt Risse zulassen
    region = fbm(img.shape[:2], 2, 2, r) > (1.0 - density * 0.9)
    band = 0.014 * density
    veins = (np.abs(n - 0.5) < band) & region & mask
    img[..., :3][veins] = hot
    core = (np.abs(n - 0.5) < band * 0.35) & region & mask
    img[..., :3][core] = F["ember_hot"]


# ------------------------------------------------------------- Untergrund ----

def ash(v=0):
    """"Wiese" der Feuerzone: Ascheebene mit Glutadern."""
    r = np.random.default_rng(10 + v)
    img = canvas()
    mottle(img, ALL, F["ash_dk"], F["ash_lt"], cells=3, r=r)
    glow_cracks(img, ALL, r, density=0.35 + v * 0.12)
    for _ in range(9):                                   # Ascheflocken
        y, x = r.integers(0, TILE, 2)
        img[y, x, :3] = (128, 118, 110)
    img[..., 3] = 255
    toplight(img, ALL, 0.05)
    return img


def ash_vents(color, v=0):
    """Ersetzt die Blumenvarianten: Glutspalten statt Bluemchen."""
    img = ash(v)
    r = np.random.default_rng(60 + v)
    for _ in range(4):
        x, y = r.integers(5, TILE - 5, 2)
        ln = int(r.integers(3, 7))
        for t in range(ln):
            px = min(TILE - 1, x + t - ln // 2)
            img[y, px, :3] = color
            if 0 <= y - 1 < TILE:
                img[y - 1, px, :3] = F["ember_hot"]
    return img


def lava(v=0):
    """"Wasser": fliessende Lava mit heissen Adern."""
    r = np.random.default_rng(50 + v)
    img = canvas()
    mottle(img, ALL, F["lava_dk"], F["lava"], cells=3, r=r)
    yy, xx = grid(img)
    flow = np.sin((yy + fbm((TILE, TILE), 4, 2, r) * 14) / 4.2)
    img[..., :3] += (flow * 16)[..., None]
    hot = fbm((TILE, TILE), 6, 3, r) > 0.60
    img[..., :3][hot] = F["lava_hot"]
    crust = fbm((TILE, TILE), 3, 2, r) < 0.26          # abgekuehlte Schollen
    img[..., :3][crust] = F["crust"]
    img[..., :3] = np.clip(img[..., :3], 0, 255)
    img[..., 3] = 255
    return img


def cinder(v=0):
    """"Erde": Schlackepfad, grob und dunkel."""
    r = np.random.default_rng(20 + v)
    img = canvas()
    mottle(img, ALL, F["cinder"], F["cinder_lt"], cells=4, r=r)
    for _ in range(12):                                  # dunkle Schlackestuecke
        y, x = r.integers(1, TILE - 2, 2)
        img[y:y + 2, x:x + 2, :3] = (74, 66, 60)
    for _ in range(5):
        y, x = r.integers(0, TILE, 2)
        img[y, x, :3] = F["ember"]
    img[..., 3] = 255
    return img


def basalt_slab(v=0):
    """"Pflaster": geschnittene Basaltplatten mit Glut in den Fugen."""
    r = np.random.default_rng(30 + v)
    img = canvas()
    mottle(img, ALL, F["basalt_dk"], F["basalt"], cells=3, r=r)
    yy, xx = grid(img)
    for row, y in enumerate(range(-2, TILE, 8)):
        off = 5 if row % 2 else 0
        for x in range(-6 + off, TILE + 6, 11):
            m = ((yy - (y + 3.5)) / 3.2) ** 2 + ((xx - (x + 5)) / 4.8) ** 2 < 1
            tone = np.array(F["basalt_lt"], dtype=float) + r.normal(0, 10)
            img[..., :3][m] = np.clip(tone, 0, 255)
            img[..., :3][m & (yy < y + 3)] = np.clip(tone + 18, 0, 255)
    glow_cracks(img, ALL, r, density=0.22)
    img[..., 3] = 255
    toplight(img, ALL, 0.05)
    return img


def scorched(v=0):
    """"Arena": verbrannter Kampfboden, Asche ueber schwarzer Kruste."""
    r = np.random.default_rng(40 + v)
    img = canvas()
    mottle(img, ALL, (34, 28, 26), (86, 72, 64), cells=5, r=r)
    for _ in range(6):                                   # Schleifspuren
        y, x = r.integers(2, TILE - 2, 2)
        ln = int(r.integers(5, 12))
        a = r.random() * np.pi
        for t in range(ln):
            py = int(y + np.sin(a) * (t - ln / 2))
            px = int(x + np.cos(a) * (t - ln / 2))
            if 0 <= py < TILE and 0 <= px < TILE:
                img[py, px, :3] = (24, 20, 19)
    glow_cracks(img, ALL, r, density=0.28)
    img[..., 3] = 255
    return img


def sulfur(v=0):
    """"Sand": Schwefelablagerung, giftig gelb."""
    r = np.random.default_rng(80 + v)
    img = canvas()
    mottle(img, ALL, F["sulfur"], F["sulfur_lt"], cells=4, r=r)
    for _ in range(20):
        y, x = r.integers(0, TILE, 2)
        img[y, x, :3] = (140, 122, 56)
    for _ in range(5):
        y, x = r.integers(1, TILE - 2, 2)
        img[y:y + 2, x:x + 2, :3] = (236, 226, 150)
    img[..., 3] = 255
    return img


def sulfur_bed(v=0):
    """"Acker": abgebaute Schwefelbeete mit Furchen."""
    r = np.random.default_rng(90 + v)
    img = canvas()
    mottle(img, ALL, (118, 104, 52), (162, 146, 72), cells=4, r=r)
    for y in range(1 + v * 2, TILE, 6):
        img[y:y + 2, :, :3] = (86, 74, 38)
        img[max(0, y - 1):y, :, :3] = (196, 182, 96)
    img[..., 3] = 255
    return img


def crystals():
    """"crops": Schwefelkristalle, transparent ueber die Beete."""
    img = canvas()
    for y in range(4, TILE, 7):
        for x in range(4, TILE - 2, 8):
            h = int(rng.integers(4, 8))
            for k in range(h):
                img[y + 3 - k, x, :3] = (238, 226, 140)
                img[y + 3 - k, x, 3] = 255
            img[y + 3, x - 1, :3] = (196, 178, 84); img[y + 3, x - 1, 3] = 255
            img[y + 3, x + 1, :3] = (196, 178, 84); img[y + 3, x + 1, 3] = 255
            img[y + 3 - h, x, :3] = (255, 248, 206)
    return img


def basalt_ground(v=0):
    """"Fels": Basalt mit gluehenden Rissen."""
    r = np.random.default_rng(70 + v)
    img = canvas()
    mottle(img, ALL, F["basalt_dk"], F["basalt_lt"], cells=3 + v, r=r)
    for _ in range(8):                                   # Saeulenfugen
        y, x = r.integers(2, TILE - 2, 2)
        for t in range(int(r.integers(5, 12))):
            py, px = min(TILE - 1, y + t), min(TILE - 1, x + int(r.integers(-1, 2)))
            img[py, px, :3] = F["basalt_dk"]
    glow_cracks(img, ALL, r, density=0.30 + v * 0.10)
    img[..., 3] = 255
    toplight(img, ALL, 0.08)
    return img


# ----------------------------------------------------- Wang-Uebergaenge ----

def over_ash(combo, tile_img, soft, edge_col=None, fringe=0.34):
    img = ash(0)
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


def lava_shore(combo):
    """Der wichtigste Uebergang: Asche -> Kruste -> gluehender Saum -> Lava."""
    img = ash(0)
    m = corner_field(combo, 0.05)
    lv = lava(0)
    paint(img, (m >= 0.30) & (m < 0.46), F["crust_lt"])
    paint(img, (m >= 0.46) & (m < 0.56), F["crust"])
    hot = m >= 0.62
    img[..., :3][hot] = lv[..., :3][hot]
    # gluehende Kante zwischen Kruste und Lava
    rim = (m >= 0.56) & (m < 0.62)
    img[..., :3][rim] = F["ember"]
    rim2 = (m >= 0.595) & (m < 0.625) & (rng.random((TILE, TILE)) < 0.8)
    img[..., :3][rim2] = F["ember_hot"]
    img[..., 3] = 255
    return img


def basalt_cliff(combo):
    img = basalt_ground(0)
    m = corner_field(combo, 0.05)
    lv = lava(0)
    deep = m >= 0.60
    img[..., :3][deep] = lv[..., :3][deep]
    paint(img, (m >= 0.50) & (m < 0.60), F["basalt_dk"])
    paint(img, (m >= 0.42) & (m < 0.50), F["basalt_lt"])
    paint(img, (m >= 0.575) & (m < 0.605), F["ember"])
    img[..., 3] = 255
    return img


# ----------------------------------------------------------------- Deko ----

def obsidian_shards():
    """"bush": Obsidianscherben statt Busch."""
    img = canvas()
    shadow(img, 26, 16, 4, 10)
    yy, xx = grid(img)
    for cx, cy, w, h in ((16, 18, 4, 10), (10, 21, 3, 7), (23, 20, 3, 8)):
        m = (np.abs(xx - cx) * h / w + np.abs(yy - cy) * 1.0) < h
        paint(img, m, F["obsidian"])
        paint(img, m & (xx < cx), F["obsidian_lt"])
    return img


def flame_jet():
    """"fern": kleine Flammenzunge aus einer Spalte."""
    img = canvas()
    yy, xx = grid(img)
    m = (((yy - 20) / 9.0) ** 2 + ((xx - 16) / 4.0) ** 2 < 1) & (yy < 27)
    paint(img, m, F["ember"])
    paint(img, m & (yy > 18), (250, 160, 60))
    paint(img, (((yy - 22) / 5.0) ** 2 + ((xx - 16) / 2.0) ** 2 < 1),
          F["ember_hot"])
    paint(img, (np.abs(yy - 28) < 2) & (np.abs(xx - 16) < 6), F["crust"])
    return img


def ember_vents():
    """"mushrooms": gluehende Loecher im Boden."""
    img = canvas()
    for _ in range(4):
        x, y = rng.integers(5, TILE - 5, 2)
        r_ = 2 + rng.random() * 1.6
        yy, xx = grid(img)
        paint(img, ((yy - y) ** 2 + (xx - x) ** 2) < (r_ + 1.4) ** 2, F["crust"])
        paint(img, ((yy - y) ** 2 + (xx - x) ** 2) < r_ ** 2, F["ember"])
        paint(img, ((yy - y) ** 2 + (xx - x) ** 2) < (r_ * 0.45) ** 2,
              F["ember_hot"])
    return img


def charred_log():
    img = canvas()
    shadow(img, 22, 16, 3, 13)
    yy, xx = grid(img)
    body = (np.abs(yy - 17) < 5) & (xx > 2) & (xx < TILE - 3)
    mottle(img, body, (24, 20, 19), (62, 52, 48), cells=3)
    for x in range(4, TILE - 4, 5):
        paint(img, body & (np.abs(xx - x) < 1), (16, 13, 12))
    paint(img, body & (np.abs(yy - 15) < 1) & (xx % 7 < 2), F["ember"])
    return img


def basalt_rock():
    img = canvas()
    shadow(img, 26, 16, 4, 12)
    yy, xx = grid(img)
    m = ((yy - 18) / 9.0) ** 2 + ((xx - 16) / 11.0) ** 2 < 1
    mottle(img, m, F["basalt_dk"], F["basalt"], cells=3)
    paint(img, m & (yy < 15), F["basalt_lt"])
    paint(img, m & (yy > 24), (20, 18, 22))
    for _ in range(6):
        y, x = rng.integers(11, 26), rng.integers(7, 26)
        if m[y, x]:
            img[y, x, :3] = F["ember"]
    return img


def bones_f():
    img = canvas()
    for _ in range(3):
        x, y = rng.integers(6, TILE - 6), rng.integers(8, TILE - 6)
        a = rng.random() * np.pi
        for t in range(-4, 5):
            px, py = int(x + np.cos(a) * t), int(y + np.sin(a) * t)
            if 0 <= px < TILE and 0 <= py < TILE:
                img[py, px, :3] = F["bone"]; img[py, px, 3] = 255
        for s in (-4, 4):
            px, py = int(x + np.cos(a) * s), int(y + np.sin(a) * s)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if 0 <= px + dx < TILE and 0 <= py + dy < TILE:
                        img[py + dy, px + dx, :3] = F["bone"]
                        img[py + dy, px + dx, 3] = 255
    return img


def skull_f():
    img = canvas()
    shadow(img, 23, 16, 3, 8, alpha=60)
    yy, xx = grid(img)
    m = ((yy - 16) / 7.0) ** 2 + ((xx - 16) / 8.0) ** 2 < 1
    paint(img, m, F["bone"])
    paint(img, m & (yy < 13), (244, 238, 224))
    for ex in (12, 20):                                  # gluehende Augen
        paint(img, ((yy - 16) ** 2 / 6 + (xx - ex) ** 2 / 4) < 1, F["ember"])
    paint(img, (np.abs(yy - 22) < 2) & (np.abs(xx - 16) < 4), (200, 192, 176))
    return img


def brazier():
    """"campfire": eiserne Feuerschale."""
    img = canvas()
    shadow(img, 27, 16, 3, 9)
    yy, xx = grid(img)
    paint(img, (yy > 20) & (yy < 27) & (np.abs(xx - 16) < 7 - (yy - 20) * 0.5),
          F["iron"])
    paint(img, (yy > 24) & (yy < 29) & (np.abs(xx - 16) < 3), (66, 62, 66))
    bowl = (((yy - 19) / 4.0) ** 2 + ((xx - 16) / 8.0) ** 2 < 1)
    paint(img, bowl, (78, 72, 78))
    flame = (((yy - 13) / 7.0) ** 2 + ((xx - 16) / 4.5) ** 2 < 1)
    paint(img, flame, F["ember"])
    paint(img, flame & (yy > 12), (252, 168, 62))
    paint(img, (((yy - 10) / 4.0) ** 2 + ((xx - 16) / 2.2) ** 2 < 1),
          F["ember_hot"])
    return img


def fire_lantern():
    img = canvas()
    shadow(img, 29, 16, 2, 5, alpha=60)
    yy, xx = grid(img)
    paint(img, (yy > 14) & (yy < 29) & (np.abs(xx - 16) < 2), F["iron"])
    head = (((yy - 11) / 5.0) ** 2 + ((xx - 16) / 4.0) ** 2 < 1)
    paint(img, head, F["ember"])
    paint(img, head & (yy < 10), F["ember_hot"])
    paint(img, (np.abs(yy - 6) < 2) & (np.abs(xx - 16) < 5), F["iron"])
    return img


def iron_post():
    img = canvas()
    shadow(img, 29, 16, 2, 6, alpha=60)
    yy, xx = grid(img)
    paint(img, (yy > 12) & (yy < 29) & (np.abs(xx - 15) < 2), F["iron"])
    board = (yy > 9) & (yy < 18) & (xx > 8) & (xx < 27)
    paint(img, board, (72, 68, 72))
    paint(img, board & (yy < 11), (112, 106, 112))
    paint(img, (yy > 12) & (yy < 15) & (xx > 11) & (xx < 24), F["ember"])
    return img


def ash_tufts():
    """"tall_grass": versengte Grasbueschel."""
    img = canvas()
    for _ in range(12):
        x, y = rng.integers(3, TILE - 3), rng.integers(10, TILE - 2)
        h = int(rng.integers(5, 10))
        col = (52, 44, 40) if rng.random() < 0.6 else (84, 70, 60)
        img[max(0, y - h):y, x, :3] = col
        img[max(0, y - h):y, x, 3] = 255
        if rng.random() < 0.35:
            img[max(0, y - h), x, :3] = F["ember"]
    return img


def obsidian_spike_h():
    img = canvas()
    yy, xx = grid(img)
    for x in (6, 16, 26):
        m = (np.abs(xx - x) * 3 + (yy - 26)) < 0
        paint(img, m & (yy > 8), F["obsidian"])
        paint(img, m & (yy > 8) & (xx < x), F["obsidian_lt"])
    return img


def obsidian_spike_v():
    img = obsidian_spike_h()
    return np.rot90(img, 1).copy()


def iron_bridge(vertical=False):
    img = canvas()
    yy, xx = grid(img)
    long_, cross = (yy, xx) if vertical else (xx, yy)
    deck = np.abs(cross - 15.5) < 13
    mottle(img, deck, (52, 48, 52), (104, 98, 104), cells=3)
    for k in range(0, TILE, 5):
        paint(img, deck & (np.abs(long_ - k) < 1), (34, 31, 34))
    for s in (-13, 12):
        paint(img, np.abs(cross - 15.5 - s) < 1.6, F["iron"])
    return img


# -------------------------------------------------------------- Sprites ----

def dead_tree(seed=0):
    """"tree": verkohlter Baum mit Glut im Stamm."""
    r = np.random.default_rng(300 + seed)
    img = canvas(2, 2)
    shadow(img, 56, 32, 6, 16, alpha=78)
    yy, xx = grid(img)
    trunk = (yy > 22) & (yy < 58) & (np.abs(xx - 32) < 4)
    mottle(img, trunk, (22, 19, 18), (58, 48, 44), cells=2, r=r)
    paint(img, trunk & (np.abs(yy % 9) < 1), F["ember"])
    for a, ln, y0 in ((-0.9, 16, 34), (0.9, 15, 30), (-0.5, 11, 24)):
        for t in range(ln):
            px = int(32 + np.cos(a) * t * (1 if a > 0 else -1) * -1)
            py = int(y0 - abs(t) * 0.7)
            if 0 <= px < 64 and 0 <= py < 64:
                img[py, max(0, px - 1):px + 2, :3] = (34, 29, 27)
                img[py, max(0, px - 1):px + 2, 3] = 255
    return img


def spire(seed=0):
    """"pine": Basaltnadel."""
    r = np.random.default_rng(400 + seed)
    img = canvas(1, 2)
    shadow(img, 58, 16, 4, 9, alpha=72)
    yy, xx = grid(img)
    m = (np.abs(xx - 16) * 3.4 + (yy - 60)) < 0
    m &= yy > 8
    mottle(img, m, F["basalt_dk"], F["basalt"], cells=2, r=r)
    paint(img, m & (xx < 15), F["basalt_lt"])
    glow_cracks(img, m, r, density=0.5)
    return img


def demon_tent():
    img = canvas(2, 2)
    shadow(img, 56, 32, 6, 20, alpha=76)
    yy, xx = grid(img)
    body = (yy > 20) & (yy < 56) & (np.abs(xx - 32) < (yy - 18) * 0.72)
    mottle(img, body, (42, 30, 30), (96, 56, 48), cells=3)
    paint(img, body & (xx < 32), (72, 44, 40))
    paint(img, (yy > 34) & (yy < 56) & (np.abs(xx - 32) < 7), (18, 14, 14))
    for t in range(18, 56):
        img[t, 32, :3] = (28, 22, 22)
    paint(img, (yy > 12) & (yy < 22) & (np.abs(xx - 32) < 2), F["iron"])
    paint(img, (yy > 8) & (yy < 14) & (np.abs(xx - 32) < 5), F["ember"])
    return img


def fire_totem():
    img = canvas(1, 2)
    shadow(img, 58, 16, 4, 9, alpha=70)
    yy, xx = grid(img)
    pole = (yy > 14) & (yy < 58) & (np.abs(xx - 16) < 4)
    mottle(img, pole, F["basalt_dk"], F["basalt"], cells=2)
    for y in (22, 34, 46):
        paint(img, (np.abs(yy - y) < 2) & (np.abs(xx - 16) < 5), F["ember"])
    paint(img, (yy > 4) & (yy < 16) & (np.abs(xx - 16) < 7), F["ember"])
    paint(img, (yy > 6) & (yy < 13) & (np.abs(xx - 16) < 4), F["ember_hot"])
    return img


def magma_well():
    img = canvas(2, 2)
    shadow(img, 56, 32, 6, 20, alpha=76)
    yy, xx = grid(img)
    ring = (((yy - 46) / 11.0) ** 2 + ((xx - 32) / 17.0) ** 2 < 1) & ~(
        ((yy - 45) / 6.0) ** 2 + ((xx - 32) / 11.0) ** 2 < 1)
    mottle(img, ring, F["basalt_dk"], F["basalt_lt"], cells=3)
    inner = ((yy - 45) / 6.0) ** 2 + ((xx - 32) / 11.0) ** 2 < 1
    paint(img, inner, F["lava"])
    paint(img, ((yy - 45) / 3.0) ** 2 + ((xx - 32) / 6.0) ** 2 < 1, F["lava_hot"])
    for x in (12, 48):
        paint(img, (yy > 16) & (yy < 46) & (np.abs(xx - x) < 2), F["iron"])
    roofm = (yy > 6) & (yy < 20) & (np.abs(xx - 32) < (yy - 4) * 1.5)
    mottle(img, roofm, (58, 52, 58), (98, 90, 98), cells=2)
    return img


def watchtower():
    """Wachturm 2x3 — Landmarke und Zeichen, dass hier jemand Wache haelt."""
    img = canvas(2, 3)
    yy, xx = grid(img)
    shadow(img, 88, 32, 6, 20, alpha=78)
    base = (yy > 74) & (yy < 92) & (np.abs(xx - 32) < 20)
    mottle(img, base, F["basalt_dk"], F["basalt"], cells=2)
    shaft = (yy > 26) & (yy <= 76) & (np.abs(xx - 32) < 14)
    mottle(img, shaft, F["basalt_dk"], F["basalt_lt"], cells=3)
    for y in range(30, 76, 8):                        # Steinlagen
        paint(img, shaft & (np.abs(yy - y) < 1), F["basalt_dk"])
    crown = (yy > 16) & (yy <= 28) & (np.abs(xx - 32) < 18)
    mottle(img, crown, F["basalt"], F["basalt_lt"], cells=2)
    for x in range(16, 49, 8):                        # Zinnen
        paint(img, (yy > 10) & (yy <= 18) & (np.abs(xx - x) < 3), F["basalt_lt"])
    paint(img, (((yy - 8) / 5.0) ** 2 + ((xx - 32) / 6.0) ** 2 < 1), F["ember"])
    paint(img, (((yy - 6) / 3.0) ** 2 + ((xx - 32) / 3.5) ** 2 < 1),
          F["ember_hot"])
    paint(img, (yy > 60) & (yy < 76) & (np.abs(xx - 32) < 5), (22, 18, 20))
    for y in (40, 52):                                # gluehende Sehschlitze
        paint(img, (np.abs(yy - y) < 3) & (np.abs(xx - 32) < 2), F["ember"])
    return img


def gate():
    """Torbogen 3x2 — markiert Zonenausgaenge und die Kraterpaesse."""
    img = canvas(3, 2)
    yy, xx = grid(img)
    shadow(img, 60, 48, 5, 34, alpha=74)
    for px in (18, 78):
        pil = (yy > 14) & (yy < 62) & (np.abs(xx - px) < 10)
        mottle(img, pil, F["basalt_dk"], F["basalt_lt"], cells=2)
        for y in range(18, 62, 8):
            paint(img, pil & (np.abs(yy - y) < 1), F["basalt_dk"])
    lint = (yy > 8) & (yy < 24) & (xx > 8) & (xx < 88)
    mottle(img, lint, F["basalt"], F["basalt_lt"], cells=2)
    paint(img, (yy > 4) & (yy < 10) & (xx > 4) & (xx < 92), F["basalt_dk"])
    for rx in range(22, 80, 12):                      # gluehende Runen
        paint(img, (np.abs(yy - 16) < 3) & (np.abs(xx - rx) < 2), F["ember"])
    for px in (18, 78):                               # Feuerschalen oben
        paint(img, (((yy - 6) / 4.0) ** 2 + ((xx - px) / 4.0) ** 2 < 1),
              F["ember_hot"])
    return img


def basalt_hut(seed=0, w_tiles=5):
    """"house": Basalthaus mit gluehenden Fenstern und Ascheziegeln."""
    r = np.random.default_rng(500 + seed)
    W, H = w_tiles * TILE, 4 * TILE
    img = canvas(w_tiles, 4)
    yy, xx = grid(img)
    roof_y0, roof_y1, wall_y1 = 8, 54, H - 12
    shadow(img, H - 8, W // 2, 6, W // 2 - 6, alpha=74)
    wall = (yy >= roof_y1) & (yy < wall_y1) & (xx >= 8) & (xx < W - 8)
    mottle(img, wall, (64, 58, 60), (106, 98, 100), cells=3, r=r)
    beams = wall & ((xx < 14) | (xx >= W - 14) | (yy >= wall_y1 - 6))
    paint(img, beams, (38, 34, 36))
    eave = (yy >= roof_y1) & (yy < roof_y1 + 7) & (xx >= 8) & (xx < W - 8)
    img[..., :3][eave] *= 0.72
    roof = (yy >= roof_y0) & (yy < roof_y1) & (xx >= 2) & (xx < W - 2)
    mottle(img, roof, (40, 34, 36), (78, 66, 66), cells=3, r=r)
    for i, y in enumerate(range(roof_y0 + 6, roof_y1, 7)):
        paint(img, roof & (yy >= y) & (yy < y + 1), (28, 24, 25))
        off = 8 if i % 2 else 0
        paint(img, roof & (yy >= y - 6) & (yy < y) & ((xx + off) % 16 < 1),
              (52, 44, 44))
    paint(img, (yy >= roof_y0) & (yy < roof_y0 + 4) & (xx >= 2) & (xx < W - 2),
          (92, 80, 78))
    paint(img, (yy >= roof_y1 - 2) & (yy < roof_y1) & (xx >= 2) & (xx < W - 2),
          (22, 19, 20))
    ch = W - 44
    paint(img, (yy < roof_y0 + 6) & (xx >= ch) & (xx < ch + 14), (70, 64, 66))
    paint(img, (yy < 4) & (xx >= ch + 2) & (xx < ch + 12), F["ember"])
    dx0 = W // 2 - 11
    door = (yy >= roof_y1 + 22) & (yy < wall_y1) & (xx >= dx0) & (xx < dx0 + 22)
    arch = ((yy - (roof_y1 + 22)) ** 2 / 90 + (xx - (dx0 + 11)) ** 2 / 121) < 1
    door = door | (arch & (yy < roof_y1 + 24) & (yy > roof_y1 + 12))
    paint(img, door, (30, 25, 26))
    paint(img, door & ((xx - dx0) % 6 < 1), (18, 15, 16))
    for wx in (26, W - 50):
        paint(img, (yy >= roof_y1 + 20) & (yy < roof_y1 + 44)
              & (xx >= wx) & (xx < wx + 24), (38, 34, 36))
        glass = ((yy >= roof_y1 + 23) & (yy < roof_y1 + 41)
                 & (xx >= wx + 3) & (xx < wx + 21))
        paint(img, glass, F["ember"])                 # Glut hinter dem Fenster
        paint(img, glass & ((xx - yy) % 9 < 2), F["ember_hot"])
        paint(img, glass & (np.abs(xx - wx - 12) < 1), (38, 34, 36))
    paint(img, (yy >= wall_y1 - 6) & (yy < wall_y1) & (xx >= 8) & (xx < W - 8)
          & ~door, (48, 43, 45))
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

    # Namen bleiben wie im painted-Tileset — nur die Optik ist anders
    for i in range(4):
        add(f"grass_{i + 1}", ash(i))
    add("grass_flowers_red", ash_vents(F["ember"], 1))
    add("grass_flowers_blue", ash_vents((250, 140, 40), 2))
    add("grass_flowers_yellow", ash_vents(F["ember_hot"], 3))
    for i in range(2):
        add(f"dirt_{i + 1}", cinder(i))
    for i in range(2):
        add(f"cobble_{i + 1}", basalt_slab(i))
    for i in range(2):
        add(f"arena_{i + 1}", scorched(i))
    add("water", lava(0))
    add("rock", basalt_ground(0))
    add("rock_2", basalt_ground(1))
    add("rock_3", basalt_ground(2))
    for i in range(2):
        add(f"sand_{i + 1}", sulfur(i))
    for i in range(2):
        add(f"farm_{i + 1}", sulfur_bed(i))
    add("crops", crystals())
    add("fence_h", obsidian_spike_h())
    add("fence_v", obsidian_spike_v())
    add("bridge_h", iron_bridge(False))
    add("bridge_v", iron_bridge(True))

    for combo in range(16):
        add(f"water_grass_{combo}", lava_shore(combo))
    for combo in range(16):
        add(f"dirt_grass_{combo}", over_ash(combo, cinder(0), 0.07,
                                            edge_col=(46, 38, 34)))
    for combo in range(16):
        add(f"cobble_grass_{combo}", over_ash(combo, basalt_slab(0), 0.05,
                                              edge_col=(70, 64, 70)))
    for combo in range(16):
        add(f"arena_grass_{combo}", over_ash(combo, scorched(0), 0.08))
    for combo in range(16):
        add(f"cliff_water_{combo}", basalt_cliff(combo))
    for combo in range(16):
        add(f"rock_grass_{combo}", over_ash(combo, basalt_ground(0), 0.05,
                                            edge_col=(24, 21, 25)))
    for combo in range(16):
        add(f"sand_grass_{combo}", over_ash(combo, sulfur(0), 0.07))
    for combo in range(16):
        add(f"farm_grass_{combo}", over_ash(combo, sulfur_bed(0), 0.04,
                                            edge_col=(92, 80, 42)))

    add("bush", obsidian_shards())
    add("fern", flame_jet())
    add("mushrooms", ember_vents())
    add("log", charred_log())
    add("boulder", basalt_rock())
    add("bones", bones_f())
    add("skull", skull_f())
    add("campfire", brazier())
    add("lantern", fire_lantern())
    add("signpost", iron_post())
    add("tall_grass", ash_tufts())

    add_sprite("tree_a", dead_tree(0))
    add_sprite("tree_b", dead_tree(1))
    add_sprite("tree_c", dead_tree(2))
    add_sprite("pine_a", spire(0))
    add_sprite("pine_b", spire(1))
    add_sprite("tent", demon_tent())
    add_sprite("totem", fire_totem())
    add_sprite("well", magma_well())
    add_sprite("tower", watchtower())
    add_sprite("gate", gate())
    add_sprite("house_a", basalt_hut(0, 5))
    add_sprite("house_b", basalt_hut(1, 5))
    add_sprite("house_c", basalt_hut(2, 4))

    rows = (len(tiles) + COLS - 1) // COLS
    sheet = np.zeros((rows * TILE, COLS * TILE, 4), dtype=np.uint8)
    for i, t in enumerate(tiles):
        r_, c = divmod(i, COLS)
        sheet[r_ * TILE:(r_ + 1) * TILE, c * TILE:(c + 1) * TILE] = \
            np.clip(t, 0, 255).astype(np.uint8)

    out_dir = "assets/tilesets/fire"
    os.makedirs(out_dir, exist_ok=True)
    Image.fromarray(sheet).save(f"{out_dir}/tileset.png")
    with open(f"{out_dir}/tileset_meta.json", "w") as f:
        json.dump({"tile_size": TILE, "columns": COLS, "count": len(tiles),
                   "ids": singles, "sprites": sprites}, f, indent=2)
    print(f"{len(tiles)} Tiles ({len(sprites)} Sprites) -> {out_dir}/tileset.png")


if __name__ == "__main__":
    build()
