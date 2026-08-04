#!/usr/bin/env python3
"""Tileset "painted" (32 px) — im Stil der gemalten Zonenkarte.

Gegenueber assets/tilesets/basic neu:
  * Gras, Erde und Fels mit Value-Noise statt flacher Fuellung (malerisch)
  * Sandstein-Pflasterstrasse + Wang-Uebergang zum Gras
  * Arena-Boden (zertretene Erde) als eigener Terraintyp + Uebergang
  * Klippenkante fuer die Kuesten
  * deutlich mehr Deko-Sprites (Farn, Pilze, Stamm, Knochen, Feuer, Laterne)

Farben sind bewusst an die ComfyUI-Karte angelehnt, damit Uebersichtskarte
und begehbare Zone wie dieselbe Welt aussehen (docs/karten_learnings.md).

Aufruf:  python3 tools/make_tileset_painted.py
Erzeugt: assets/tilesets/painted/tileset.png + tileset_meta.json
"""
import json
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sprites_hd import hd_boulder, hd_conifer, hd_house, hd_tree

# Wertstufen fuer die HD-Sprites: dunkel -> hell. Sechs Stufen beim Laub,
# vier bei Rinde und Stein — daran haengt das Volumen.
LEAF6 = [(26, 46, 30), (38, 68, 40), (54, 92, 48), (78, 122, 58),
         (108, 154, 70), (142, 184, 88)]
NEEDLE5 = [(22, 44, 34), (34, 66, 46), (48, 88, 56), (68, 114, 68),
           (96, 146, 84)]
BARK4 = [(40, 30, 22), (66, 48, 32), (96, 72, 48), (128, 100, 68)]
STONE4 = [(58, 56, 60), (104, 100, 104), (140, 136, 140), (178, 174, 176)]
HOUSE_PAL = {
    "wall": (196, 168, 128), "wall_lt": (224, 200, 164),
    "wall_dk": (108, 86, 62), "beam": (104, 76, 48),
    "roof": (150, 66, 48), "roof_lt": (186, 92, 64),
    "roof_dk": (104, 42, 32), "ridge": (212, 118, 82),
    "stone": (128, 122, 114), "stone_lt": (168, 162, 152),
    "glass": (92, 74, 52), "glow": (255, 206, 124),
    "door": (110, 76, 46), "ground_shadow": (46, 58, 40),
}

TILE = 32
COLS = 16
rng = np.random.default_rng(2027)

P = {
    "grass": (104, 138, 68), "grass_dk": (78, 112, 54), "grass_lt": (134, 166, 88),
    "dirt": (158, 126, 86), "dirt_dk": (122, 94, 60), "dirt_lt": (184, 156, 116),
    "cobble": (182, 164, 132), "cobble_dk": (138, 122, 94),
    "kerb": (150, 132, 102),
    # deutlich dunkler als "dirt", sonst sind Kampfboden und Weg nicht
    # auseinanderzuhalten
    "arena": (132, 108, 76), "arena_dk": (96, 76, 52),
    "deep": (34, 76, 116), "shallow": (74, 148, 170), "foam": (216, 234, 238),
    "sand": (214, 194, 152), "sand_wet": (182, 160, 124),
    "rock": (150, 146, 138), "rock_lt": (188, 184, 174), "rock_dk": (98, 94, 88),
    "wood": (128, 94, 56), "wood_dk": (96, 68, 40),
    "bone": (228, 224, 210),
}


# --------------------------------------------------------------- Helfer ----

def canvas(w=1, h=1):
    return np.zeros((h * TILE, w * TILE, 4), dtype=float)


def grid(img):
    return np.mgrid[0:img.shape[0], 0:img.shape[1]]


def paint(img, mask, color, alpha=255):
    img[..., :3][mask] = color
    img[..., 3][mask] = alpha


def fill(img, color):
    img[..., :3] = color
    img[..., 3] = 255
    return img


def vnoise(shape, cells, r=None):
    """Weiches Value-Noise — gibt Flaechen Struktur statt Pixelrauschen."""
    r = r or rng
    g = r.random((cells + 2, cells + 2))
    ys = np.linspace(0, cells, shape[0], endpoint=False)
    xs = np.linspace(0, cells, shape[1], endpoint=False)
    y0, x0 = ys.astype(int), xs.astype(int)
    fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
    fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
    a, b = g[np.ix_(y0, x0)], g[np.ix_(y0, x0 + 1)]
    c, d = g[np.ix_(y0 + 1, x0)], g[np.ix_(y0 + 1, x0 + 1)]
    return (a * (1 - fx) * (1 - fy) + b * fx * (1 - fy)
            + c * (1 - fx) * fy + d * fx * fy)


def fbm(shape, base=4, oct_=3, r=None):
    out, amp, tot, c = 0.0, 1.0, 0.0, base
    for _ in range(oct_):
        out = out + vnoise(shape, c, r) * amp
        tot += amp
        amp *= 0.5
        c *= 2
    return out / tot


def mottle(img, mask, c_lo, c_hi, cells=4, r=None):
    """Zwei Farbtoene ueber Noise mischen — der Kern des malerischen Looks."""
    t = fbm(img.shape[:2], cells, 3, r)[..., None]
    lo = np.array(c_lo, dtype=float)
    hi = np.array(c_hi, dtype=float)
    col = lo * (1 - t) + hi * t
    img[..., :3][mask] = col[mask]
    img[..., 3][mask] = 255


def toplight(img, mask, strength=0.10):
    """Leichter Licht-zu-Schatten-Verlauf von oben nach unten."""
    g = np.linspace(1 + strength, 1 - strength, img.shape[0])[:, None, None]
    img[..., :3] = np.where(mask[..., None], np.clip(img[..., :3] * g, 0, 255),
                            img[..., :3])


def shadow(img, cy, cx, ry, rx, alpha=72):
    yy, xx = grid(img)
    m = ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2 < 1
    img[..., :3][m] = (34, 42, 30)
    img[..., 3][m] = np.maximum(img[..., 3][m], alpha)


ALL = np.ones((TILE, TILE), bool)


# ---------------------------------------------------------------- Boden ----

def grass(v=0):
    r = np.random.default_rng(10 + v)
    img = canvas()
    mottle(img, ALL, P["grass_dk"], P["grass_lt"], cells=3, r=r)
    # Halme: kurze Striche in Gruppen, damit es nicht wie Rauschen wirkt
    for _ in range(7 + v):
        x, y = r.integers(2, TILE - 3), r.integers(3, TILE - 4)
        for k in range(int(r.integers(2, 5))):
            xx = min(TILE - 1, x + k * 2)
            h = int(r.integers(2, 5))
            img[max(0, y - h):y, xx, :3] = P["grass_dk"]
    for _ in range(6):
        x, y = r.integers(0, TILE, 2)
        img[y, x, :3] = P["grass_lt"]
    toplight(img, ALL, 0.06)
    return img


def grass_flowers(color, v=0):
    img = grass(v)
    r = np.random.default_rng(60 + v)
    for _ in range(5):
        x, y = r.integers(4, TILE - 4, 2)
        for dy, dx in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            img[y + dy, x + dx, :3] = color
        img[y, x, :3] = (246, 230, 128)
        img[y + 2, x, :3] = P["grass_dk"]
    return img


def dirt(v=0):
    r = np.random.default_rng(20 + v)
    img = canvas()
    mottle(img, ALL, P["dirt_dk"], P["dirt_lt"], cells=4, r=r)
    for _ in range(10):                                   # Kiesel
        y, x = r.integers(1, TILE - 2, 2)
        img[y:y + 2, x:x + 2, :3] = P["dirt_lt"]
    for _ in range(8):
        y, x = r.integers(0, TILE, 2)
        img[y, x, :3] = P["dirt_dk"]
    img[..., 3] = 255
    return img


def cobble(v=0):
    """Sandstein-Pflaster: versetzte Reihen, jede Platte einzeln getoent."""
    r = np.random.default_rng(30 + v)
    img = canvas()
    mottle(img, ALL, P["cobble_dk"], (152, 136, 106), cells=3, r=r)
    yy, xx = grid(img)
    for row, y in enumerate(range(-2, TILE, 8)):
        off = 5 if row % 2 else 0
        for x in range(-6 + off, TILE + 6, 11):
            m = ((yy - (y + 3.5)) / 3.2) ** 2 + ((xx - (x + 5)) / 4.8) ** 2 < 1
            # Helligkeit variieren, NICHT pro Kanal — sonst werden die
            # Platten bunt (rosa/gruen) statt Sandstein.
            tone = np.array(P["cobble"], dtype=float) + r.normal(0, 12)
            img[..., :3][m] = np.clip(tone, 0, 255)
            top = m & (yy < y + 3)
            img[..., :3][top] = np.clip(tone + 16, 0, 255)
    img[..., 3] = 255
    toplight(img, ALL, 0.05)
    return img


def arena_floor(v=0):
    """Zertretener Kampfboden: trockene Erde mit Schleifspuren."""
    r = np.random.default_rng(40 + v)
    img = canvas()
    mottle(img, ALL, P["arena_dk"], P["arena"], cells=5, r=r)
    for _ in range(5):                                    # Schleifspuren
        y, x = r.integers(2, TILE - 2, 2)
        ln = int(r.integers(5, 12))
        a = r.random() * np.pi
        for t in range(ln):
            py = int(y + np.sin(a) * (t - ln / 2))
            px = int(x + np.cos(a) * (t - ln / 2))
            if 0 <= py < TILE and 0 <= px < TILE:
                img[py, px, :3] = P["arena_dk"]
    for _ in range(4):
        y, x = r.integers(1, TILE - 2, 2)
        img[y:y + 2, x:x + 2, :3] = (176, 156, 118)
    img[..., 3] = 255
    return img


def water(v=0):
    r = np.random.default_rng(50 + v)
    img = canvas()
    mottle(img, ALL, P["deep"], (54, 112, 150), cells=3, r=r)
    yy, xx = grid(img)
    wave = np.sin((yy + fbm((TILE, TILE), 4, 2, r) * 9) / 3.4)
    img[..., :3] += (wave * 7)[..., None]
    for _ in range(3):                                    # Glanzstriche
        y, x = r.integers(2, TILE - 2), r.integers(0, TILE - 9)
        img[y, x:x + int(r.integers(4, 9)), :3] = (108, 158, 192)
    img[..., :3] = np.clip(img[..., :3], 0, 255)
    img[..., 3] = 255
    return img


def rock_ground(v=0):
    """Fels mit Rissen, Moosflecken und Flechten.

    Eine einzige flache Graustufe laesst Bergrahmen und Felsnasen wie
    Beton aussehen — deshalb mehrere Varianten mit Bewuchs.
    """
    r = np.random.default_rng(70 + v)
    img = canvas()
    mottle(img, ALL, P["rock_dk"], P["rock_lt"], cells=3 + v, r=r)
    for _ in range(7):                                    # Risse
        y, x = r.integers(2, TILE - 2, 2)
        for t in range(int(r.integers(4, 10))):
            py, px = min(TILE - 1, y + t), min(TILE - 1, x + int(r.integers(-1, 2)))
            img[py, px, :3] = P["rock_dk"]
    # Moos in den Fugen: bricht das Grau auf und bindet den Fels ans Gras
    moss = fbm((TILE, TILE), 3, 2, r)
    m = moss > (0.62 - v * 0.06)
    img[..., :3][m] = img[..., :3][m] * 0.55 + np.array((74, 104, 56)) * 0.45
    for _ in range(5 + v * 3):                            # Flechten
        y, x = r.integers(1, TILE - 2, 2)
        img[y:y + 2, x:x + 2, :3] = (150, 158, 132)
    img[..., 3] = 255
    toplight(img, ALL, 0.08)
    return img


# ------------------------------------------------- Wang-Uebergaenge (16) ----

def corner_field(combo, soft=0.05, r=None):
    r = r or rng
    c = np.array([[combo & 1 and 1.0 or 0.0, combo & 2 and 1.0 or 0.0],
                  [combo & 4 and 1.0 or 0.0, combo & 8 and 1.0 or 0.0]])
    t = (np.arange(TILE) + 0.5) / TILE
    top = c[0, 0] * (1 - t) + c[0, 1] * t
    bot = c[1, 0] * (1 - t) + c[1, 1] * t
    m = top[None, :] * (1 - t)[:, None] + bot[None, :] * t[:, None]
    return m + (fbm((TILE, TILE), 3, 2, r) - 0.5) * soft * 6


def over_grass(combo, tile_img, soft, edge_col=None, fringe=0.34):
    """Legt tile_img ueber Gras, Kante ausgefranst."""
    img = grass(0)
    m = corner_field(combo, soft)
    body = m >= 0.5
    img[..., :3][body] = tile_img[..., :3][body]
    fr = (m >= 0.5 - 0.09) & (m < 0.5) & (rng.random((TILE, TILE)) < fringe)
    img[..., :3][fr] = tile_img[..., :3][fr]
    if edge_col is not None:
        e = (m >= 0.5) & (m < 0.55)
        img[..., :3][e] = edge_col
    img[..., 3] = 255
    return img


def water_grass(combo):
    """Strand: Gras -> Sand -> nasser Sand -> Schaum -> Flachwasser -> Tiefe."""
    img = grass(0)
    m = corner_field(combo, 0.05)
    w = water(0)
    paint(img, (m >= 0.30) & (m < 0.44), P["sand"])
    paint(img, (m >= 0.44) & (m < 0.53), P["sand_wet"])
    paint(img, (m >= 0.53) & (m < 0.63), P["shallow"])
    deep = m >= 0.63
    img[..., :3][deep] = w[..., :3][deep]
    foam = (m >= 0.525) & (m < 0.56) & (rng.random((TILE, TILE)) < 0.8)
    paint(img, foam, P["foam"])
    sandm = (m >= 0.30) & (m < 0.53)
    img[..., :3][sandm] += rng.normal(0, 4, (TILE, TILE, 1)).repeat(3, 2)[sandm]
    img[..., :3] = np.clip(img[..., :3], 0, 255)
    img[..., 3] = 255
    return img


def cliff_edge(combo):
    """Felskante zum Wasser: heller Steinsaum mit dunkler Bruchlinie."""
    img = rock_ground(0)
    m = corner_field(combo, 0.05)
    w = water(0)
    deep = m >= 0.60
    img[..., :3][deep] = w[..., :3][deep]
    paint(img, (m >= 0.50) & (m < 0.60), P["rock_dk"])
    paint(img, (m >= 0.42) & (m < 0.50), P["rock_lt"])
    foam = (m >= 0.58) & (m < 0.62) & (rng.random((TILE, TILE)) < 0.6)
    paint(img, foam, P["foam"])
    img[..., 3] = 255
    return img


def sand(v=0):
    """Strand/Duene — hell, koernig, mit ein paar Kieseln."""
    r = np.random.default_rng(80 + v)
    img = canvas()
    mottle(img, ALL, P["sand_wet"], (232, 214, 174), cells=4, r=r)
    for _ in range(26):
        y, x = r.integers(0, TILE, 2)
        img[y, x, :3] = (198, 176, 138)
    for _ in range(5):
        y, x = r.integers(1, TILE - 2, 2)
        img[y:y + 2, x:x + 2, :3] = (176, 168, 152)
    img[..., 3] = 255
    return img


def farmland(v=0):
    """Acker mit Pflugfurchen — quer gepfluegt, damit Felder als Felder lesen."""
    r = np.random.default_rng(90 + v)
    img = canvas()
    mottle(img, ALL, (108, 82, 54), (146, 116, 80), cells=4, r=r)
    for y in range(1 + v * 2, TILE, 6):                   # Furchen
        img[y:y + 2, :, :3] = (92, 70, 46)
        img[max(0, y - 1):y, :, :3] = (162, 132, 94)
    for _ in range(8):
        y, x = r.integers(0, TILE, 2)
        img[y, x, :3] = (178, 152, 116)
    img[..., 3] = 255
    return img


def crops():
    """Setzlingsreihen, transparent — kommt ueber den Acker."""
    img = canvas()
    for y in range(3, TILE, 6):
        for x in range(3, TILE - 2, 7):
            img[y:y + 4, x, :3] = (74, 122, 52); img[y:y + 4, x, 3] = 255
            for dx, dy in ((-1, 1), (1, 1), (-2, 2), (2, 2)):
                img[y + dy, x + dx, :3] = (96, 148, 64)
                img[y + dy, x + dx, 3] = 255
    return img


def fence_h():
    img = canvas()
    for y in (14, 21):
        img[y:y + 2, :, :3] = P["wood"]; img[y:y + 2, :, 3] = 255
        img[y, :, :3] = (162, 126, 78)
    for x in (4, 24):
        img[10:27, x:x + 3, :3] = P["wood_dk"]; img[10:27, x:x + 3, 3] = 255
        img[10:27, x, :3] = (150, 114, 70)
        img[27:29, x:x + 4, :3] = (36, 44, 32); img[27:29, x:x + 4, 3] = 70
    return img


def fence_v():
    img = canvas()
    for x in (14, 20):
        img[:, x:x + 2, :3] = P["wood"]; img[:, x:x + 2, 3] = 255
        img[:, x, :3] = (162, 126, 78)
    for y in (4, 24):
        img[y:y + 4, 11:24, :3] = P["wood_dk"]; img[y:y + 4, 11:24, 3] = 255
        img[y, 11:24, :3] = (150, 114, 70)
    return img


def bridge(vertical=False):
    """Holzsteg — Planken quer zur Laufrichtung, Gelaender an den Seiten."""
    img = canvas()
    yy, xx = grid(img)
    long_, cross = (yy, xx) if vertical else (xx, yy)
    deck = abs(cross - 15.5) < 13
    mottle(img, deck, P["wood_dk"], (158, 122, 76), cells=3)
    for k in range(0, TILE, 5):                           # Planken
        paint(img, deck & (abs(long_ - k) < 1), (92, 66, 40))
    for s in (-13, 12):                                   # Gelaender
        paint(img, abs(cross - 15.5 - s) < 1.6, (74, 54, 34))
    return img


# ----------------------------------------------------------------- Deko ----

def bush():
    img = canvas()
    shadow(img, 26, 16, 4, 11)
    yy, xx = grid(img)
    m = np.zeros(img.shape[:2], bool)
    for cy, cx, cr in ((17, 16, 9), (20, 9, 6), (20, 23, 6), (13, 19, 5)):
        m |= ((yy - cy) ** 2 + (xx - cx) ** 2) < cr ** 2
    mottle(img, m, (46, 86, 46), (86, 132, 62), cells=3)
    paint(img, m & (yy > 22), (40, 76, 42))
    for _ in range(7):
        y, x = rng.integers(8, 24), rng.integers(6, 26)
        if m[y, x]:
            img[y, x, :3] = (108, 156, 76)
    return img


def fern():
    img = canvas()
    shadow(img, 27, 16, 3, 8, alpha=55)
    for k in range(9):
        a = -np.pi / 2 + (k - 4) * 0.29
        ln = 9 + rng.random() * 5
        col = (58, 100, 46) if k % 2 else (76, 122, 54)
        for t in np.linspace(0, 1, 14):
            px = int(16 + np.cos(a) * ln * t)
            py = int(26 + np.sin(a) * ln * t)
            if 0 <= px < TILE and 0 <= py < TILE:
                img[py, px, :3] = col
                img[py, px, 3] = 255
    return img


def mushrooms():
    img = canvas()
    for _ in range(4):
        x, y = rng.integers(5, TILE - 5), rng.integers(10, TILE - 4)
        img[y:y + 4, x, :3] = (222, 214, 196); img[y:y + 4, x, 3] = 255
        cap = (208, 74, 62) if rng.random() < 0.7 else (206, 176, 96)
        for dx in range(-3, 4):
            h = 2 if abs(dx) < 2 else 1
            img[y - h:y, x + dx, :3] = cap
            img[y - h:y, x + dx, 3] = 255
        img[y - 2, x - 1, :3] = (244, 236, 226); img[y - 2, x - 1, 3] = 255
    return img


def log():
    img = canvas()
    shadow(img, 22, 16, 3, 13)
    yy, xx = grid(img)
    body = (abs(yy - 17) < 5) & (xx > 2) & (xx < TILE - 3)
    mottle(img, body, P["wood_dk"], P["wood"], cells=3)
    paint(img, body & (yy < 15), (156, 118, 74))
    for x in range(4, TILE - 4, 5):                       # Rindenfugen
        paint(img, body & (abs(xx - x) < 1), P["wood_dk"])
    ring = ((yy - 17) ** 2 / 25 + (xx - TILE + 5) ** 2 / 6) < 1
    paint(img, ring, (176, 146, 104))
    paint(img, ring & (((yy - 17) ** 2 / 9 + (xx - TILE + 5) ** 2 / 2) < 1),
          (146, 116, 78))
    return img


def boulder():
    img = canvas()
    shadow(img, 26, 16, 4, 12)
    yy, xx = grid(img)
    m = ((yy - 18) / 9.0) ** 2 + ((xx - 16) / 11.0) ** 2 < 1
    mottle(img, m, P["rock_dk"], P["rock"], cells=3)
    paint(img, m & (yy < 15), P["rock_lt"])
    paint(img, m & (yy > 24), (86, 82, 78))
    for _ in range(9):
        y, x = rng.integers(10, 27), rng.integers(6, 27)
        if m[y, x]:
            img[y, x, :3] = (206, 202, 194) if rng.random() < 0.5 else (78, 74, 70)
    return img


def bones():
    img = canvas()
    for _ in range(3):
        x, y = rng.integers(6, TILE - 6), rng.integers(8, TILE - 6)
        a = rng.random() * np.pi
        for t in range(-4, 5):
            px, py = int(x + np.cos(a) * t), int(y + np.sin(a) * t)
            if 0 <= px < TILE and 0 <= py < TILE:
                img[py, px, :3] = P["bone"]; img[py, px, 3] = 255
        for s in (-4, 4):
            px, py = int(x + np.cos(a) * s), int(y + np.sin(a) * s)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if 0 <= px + dx < TILE and 0 <= py + dy < TILE:
                        img[py + dy, px + dx, :3] = P["bone"]
                        img[py + dy, px + dx, 3] = 255
    return img


def skull():
    img = canvas()
    shadow(img, 23, 16, 3, 8, alpha=60)
    yy, xx = grid(img)
    m = ((yy - 16) / 7.0) ** 2 + ((xx - 16) / 8.0) ** 2 < 1
    paint(img, m, P["bone"])
    paint(img, m & (yy < 13), (244, 240, 228))
    for ex in (12, 20):                                   # Augenhoehlen
        paint(img, ((yy - 16) ** 2 / 6 + (xx - ex) ** 2 / 4) < 1, (58, 52, 46))
    paint(img, (abs(yy - 22) < 2) & (abs(xx - 16) < 4), (206, 200, 186))
    return img


def campfire():
    img = canvas()
    shadow(img, 24, 16, 4, 11, alpha=70)
    yy, xx = grid(img)
    ring = (((yy - 22) / 5.0) ** 2 + ((xx - 16) / 8.0) ** 2 < 1)
    paint(img, ring, (86, 80, 72))
    paint(img, ring & (yy < 20), (128, 122, 112))
    for a in (0.4, 1.5, 2.6):                             # Scheite
        for t in range(-6, 7):
            px, py = int(16 + np.cos(a) * t), int(22 + np.sin(a) * t * 0.55)
            if 0 <= px < TILE and 0 <= py < TILE:
                img[py, px, :3] = P["wood"]; img[py, px, 3] = 255
    flame = (((yy - 15) / 7.0) ** 2 + ((xx - 16) / 4.0) ** 2 < 1)
    paint(img, flame, (238, 148, 54))
    paint(img, flame & (yy > 14), (248, 206, 96))
    paint(img, (((yy - 12) / 4.0) ** 2 + ((xx - 16) / 2.0) ** 2 < 1), (252, 238, 168))
    return img


def lantern():
    img = canvas()
    shadow(img, 29, 16, 2, 5, alpha=60)
    yy, xx = grid(img)
    paint(img, (yy > 14) & (yy < 29) & (abs(xx - 16) < 2), (72, 58, 42))
    head = (((yy - 11) / 5.0) ** 2 + ((xx - 16) / 4.0) ** 2 < 1)
    paint(img, head, (250, 218, 132))
    paint(img, head & (yy < 9), (252, 240, 196))
    paint(img, (abs(yy - 6) < 2) & (abs(xx - 16) < 5), (72, 58, 42))
    return img


def signpost():
    img = canvas()
    shadow(img, 29, 16, 2, 6, alpha=60)
    yy, xx = grid(img)
    paint(img, (yy > 12) & (yy < 29) & (abs(xx - 15) < 2), P["wood_dk"])
    board = (yy > 9) & (yy < 18) & (xx > 8) & (xx < 27)
    paint(img, board, P["wood"])
    paint(img, board & (yy < 11), (162, 124, 76))
    paint(img, (yy > 12) & (yy < 15) & (xx > 11) & (xx < 24), P["wood_dk"])
    return img


def tall_grass():
    img = canvas()
    for _ in range(13):
        x, y = rng.integers(3, TILE - 3), rng.integers(10, TILE - 2)
        h = int(rng.integers(6, 11))
        col = (74, 120, 52) if rng.random() < 0.6 else (96, 142, 64)
        img[max(0, y - h):y, x, :3] = col
        img[max(0, y - h):y, x, 3] = 255
        img[max(0, y - h), min(TILE - 1, x + 1), :3] = col
        img[max(0, y - h), min(TILE - 1, x + 1), 3] = 255
    return img


# -------------------------------------------------------------- Sprites ----

def tree_big(seed=0):
    r = np.random.default_rng(300 + seed)
    img = canvas(2, 2)
    shadow(img, 56, 32, 6, 19, alpha=78)
    yy, xx = grid(img)
    trunk = (yy > 36) & (yy < 58) & (abs(xx - 32) < 4)
    mottle(img, trunk, P["wood_dk"], P["wood"], cells=2, r=r)
    canopy = np.zeros(img.shape[:2], bool)
    for cy, cx, cr in ((24, 32, 21), (28, 13, 13), (28, 51, 13),
                       (12, 21, 12), (12, 43, 12)):
        cy += int(r.integers(-2, 3)); cx += int(r.integers(-2, 3))
        canopy |= ((yy - cy) ** 2 + (xx - cx) ** 2) < cr ** 2
    mottle(img, canopy, (44, 84, 46), (94, 146, 68), cells=3, r=r)
    paint(img, canopy & (yy > 32), (40, 76, 44))
    hi = np.zeros_like(canopy)
    for cy, cx, cr in ((16, 24, 11), (12, 38, 9), (24, 18, 7)):
        hi |= ((yy - cy) ** 2 + (xx - cx) ** 2) < cr ** 2
    paint(img, canopy & hi, (112, 166, 80))
    for _ in range(30):
        y, x = int(r.integers(6, 40)), int(r.integers(10, 54))
        if canopy[y, x]:
            img[y, x, :3] = (132, 186, 94)
    er = (canopy & np.roll(canopy, 1, 0) & np.roll(canopy, -1, 0)
          & np.roll(canopy, 1, 1) & np.roll(canopy, -1, 1))
    paint(img, canopy & ~er, (34, 64, 38))
    return img


def pine(seed=0):
    r = np.random.default_rng(400 + seed)
    img = canvas(1, 2)
    shadow(img, 58, 16, 4, 10, alpha=72)
    yy, xx = grid(img)
    paint(img, (yy > 48) & (yy < 60) & (abs(xx - 16) < 3), P["wood_dk"])
    for ty, tw in ((46, 14), (34, 11), (22, 8)):
        tri = (yy <= ty) & (yy > ty - 16) & (abs(xx - 16) < (yy - (ty - 16)) * tw / 16)
        mottle(img, tri, (34, 70, 44), (66, 114, 62), cells=2, r=r)
        paint(img, tri & (xx < 15) & (yy < ty - 4), (78, 128, 68))
        paint(img, tri & (yy > ty - 3), (28, 58, 38))
    return img


def tent():
    """Monsterlager-Zelt 2x2 — dunkles Leder, nicht wie ein Wohnhaus."""
    img = canvas(2, 2)
    shadow(img, 56, 32, 6, 20, alpha=76)
    yy, xx = grid(img)
    body = (yy > 20) & (yy < 56) & (abs(xx - 32) < (yy - 18) * 0.72)
    mottle(img, body, (70, 58, 46), (116, 96, 74), cells=3)
    paint(img, body & (xx < 32), (94, 78, 60))
    paint(img, (yy > 34) & (yy < 56) & (abs(xx - 32) < 7), (40, 33, 27))  # Eingang
    for t in range(18, 56):                               # Firstlinie
        img[t, 32, :3] = (52, 43, 35)
    paint(img, (yy > 12) & (yy < 22) & (abs(xx - 32) < 2), P["wood_dk"])
    paint(img, (yy > 8) & (yy < 14) & (abs(xx - 32) < 5), (168, 72, 60))  # Wimpel
    return img


def totem():
    img = canvas(1, 2)
    shadow(img, 58, 16, 4, 9, alpha=70)
    yy, xx = grid(img)
    pole = (yy > 14) & (yy < 58) & (abs(xx - 16) < 4)
    mottle(img, pole, P["wood_dk"], P["wood"], cells=2)
    for y in (22, 34, 46):                                # Kerbmarken
        paint(img, (abs(yy - y) < 2) & (abs(xx - 16) < 5), (58, 44, 30))
    paint(img, (yy > 6) & (yy < 16) & (abs(xx - 16) < 8), (168, 72, 60))
    paint(img, (yy > 8) & (yy < 13) & (abs(xx - 16) < 4), (228, 214, 196))
    return img


def house(seed=0, w_tiles=5):
    """Fachwerkhaus w x 4 Tiles im Stil der gemalten Karte (rotes Ziegeldach)."""
    r = np.random.default_rng(500 + seed)
    W, H = w_tiles * TILE, 4 * TILE
    img = canvas(w_tiles, 4)
    yy, xx = grid(img)
    roof_y0, roof_y1, wall_y1 = 8, 54, H - 12
    shadow(img, H - 8, W // 2, 6, W // 2 - 6, alpha=74)
    wall = (yy >= roof_y1) & (yy < wall_y1) & (xx >= 8) & (xx < W - 8)
    mottle(img, wall, (214, 200, 176), (242, 232, 214), cells=3, r=r)
    beams = wall & ((xx < 14) | (xx >= W - 14) | (yy >= wall_y1 - 6))
    paint(img, beams, (120, 86, 52))
    eave = (yy >= roof_y1) & (yy < roof_y1 + 7) & (xx >= 8) & (xx < W - 8)
    img[..., :3][eave] *= 0.74
    roof = (yy >= roof_y0) & (yy < roof_y1) & (xx >= 2) & (xx < W - 2)
    mottle(img, roof, (150, 66, 48), (194, 100, 68), cells=3, r=r)
    for i, y in enumerate(range(roof_y0 + 6, roof_y1, 7)):
        paint(img, roof & (yy >= y) & (yy < y + 1), (140, 60, 44))
        off = 8 if i % 2 else 0
        paint(img, roof & (yy >= y - 6) & (yy < y) & ((xx + off) % 16 < 1),
              (162, 76, 54))
    paint(img, (yy >= roof_y0) & (yy < roof_y0 + 4) & (xx >= 2) & (xx < W - 2),
          (208, 112, 78))
    paint(img, roof & ((xx < 5) | (xx >= W - 5)), (134, 58, 44))
    paint(img, (yy >= roof_y1 - 2) & (yy < roof_y1) & (xx >= 2) & (xx < W - 2),
          (114, 48, 38))
    ch = W - 44
    paint(img, (yy < roof_y0 + 6) & (xx >= ch) & (xx < ch + 14), (150, 144, 134))
    paint(img, (yy < 3) & (xx >= ch - 2) & (xx < ch + 16), (118, 112, 104))
    dx0 = W // 2 - 11
    door = (yy >= roof_y1 + 22) & (yy < wall_y1) & (xx >= dx0) & (xx < dx0 + 22)
    arch = ((yy - (roof_y1 + 22)) ** 2 / 90 + (xx - (dx0 + 11)) ** 2 / 121) < 1
    door = door | (arch & (yy < roof_y1 + 24) & (yy > roof_y1 + 12))
    paint(img, door, (132, 92, 56))
    paint(img, door & ((xx - dx0) % 6 < 1), (108, 74, 44))
    paint(img, (yy >= roof_y1 + 40) & (yy < roof_y1 + 44)
          & (xx >= dx0 + 16) & (xx < dx0 + 19), (226, 186, 104))
    for wx in (26, W - 50):
        paint(img, (yy >= roof_y1 + 20) & (yy < roof_y1 + 44)
              & (xx >= wx) & (xx < wx + 24), (120, 86, 52))
        glass = ((yy >= roof_y1 + 23) & (yy < roof_y1 + 41)
                 & (xx >= wx + 3) & (xx < wx + 21))
        paint(img, glass, (146, 178, 196))
        paint(img, glass & ((xx - yy) % 9 < 2), (192, 216, 226))
        paint(img, glass & (abs(xx - wx - 12) < 1), (120, 86, 52))
        paint(img, glass & (abs(yy - roof_y1 - 32) < 1), (120, 86, 52))
        paint(img, (yy >= roof_y1 + 44) & (yy < roof_y1 + 50)
              & (xx >= wx + 1) & (xx < wx + 23), (110, 78, 46))
        for fx in range(wx + 3, wx + 21, 4):
            img[roof_y1 + 43, fx, :3] = ((210, 76, 68) if r.random() < 0.6
                                         else (234, 214, 122))
            img[roof_y1 + 43, fx, 3] = 255
    paint(img, (yy >= wall_y1 - 6) & (yy < wall_y1) & (xx >= 8) & (xx < W - 8)
          & ~door, (152, 144, 132))
    return img


def well():
    img = canvas(2, 2)
    shadow(img, 56, 32, 6, 20, alpha=76)
    yy, xx = grid(img)
    ring = (((yy - 46) / 11.0) ** 2 + ((xx - 32) / 17.0) ** 2 < 1) & ~(
        ((yy - 45) / 6.0) ** 2 + ((xx - 32) / 11.0) ** 2 < 1)
    mottle(img, ring, (116, 110, 102), (182, 176, 164), cells=3)
    paint(img, (((yy - 45) / 6.0) ** 2 + ((xx - 32) / 11.0) ** 2 < 1), (28, 38, 50))
    for x in (12, 48):
        paint(img, (yy > 16) & (yy < 46) & (abs(xx - x) < 2), P["wood"])
    roofm = (yy > 6) & (yy < 20) & (abs(xx - 32) < (yy - 4) * 1.5)
    mottle(img, roofm, (146, 66, 48), (186, 96, 66), cells=2)
    paint(img, (yy > 22) & (yy < 42) & (abs(xx - 32) < 1), (92, 72, 52))
    paint(img, (yy >= 40) & (yy < 45) & (abs(xx - 32) < 4), P["wood"])
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

    for i in range(4):
        add(f"grass_{i + 1}", grass(i))
    add("grass_flowers_red", grass_flowers((214, 78, 70), 1))
    add("grass_flowers_blue", grass_flowers((110, 128, 220), 2))
    add("grass_flowers_yellow", grass_flowers((234, 204, 96), 3))
    for i in range(2):
        add(f"dirt_{i + 1}", dirt(i))
    for i in range(2):
        add(f"cobble_{i + 1}", cobble(i))
    for i in range(2):
        add(f"arena_{i + 1}", arena_floor(i))
    add("water", water(0))
    add("rock", rock_ground(0))
    add("rock_2", rock_ground(1))
    add("rock_3", rock_ground(2))
    for i in range(2):
        add(f"sand_{i + 1}", sand(i))
    for i in range(2):
        add(f"farm_{i + 1}", farmland(i))
    add("crops", crops())
    add("fence_h", fence_h())
    add("fence_v", fence_v())
    add("bridge_h", bridge(False))
    add("bridge_v", bridge(True))

    for combo in range(16):
        add(f"water_grass_{combo}", water_grass(combo))
    for combo in range(16):
        add(f"dirt_grass_{combo}", over_grass(combo, dirt(0), 0.07,
                                              edge_col=(120, 92, 60)))
    for combo in range(16):
        add(f"cobble_grass_{combo}", over_grass(combo, cobble(0), 0.05,
                                                edge_col=P["kerb"]))
    for combo in range(16):
        add(f"arena_grass_{combo}", over_grass(combo, arena_floor(0), 0.08))
    for combo in range(16):
        add(f"cliff_water_{combo}", cliff_edge(combo))
    # Hochland-Kante: dunkler Fusssaum, damit der Fels als Stufe liest
    for combo in range(16):
        add(f"rock_grass_{combo}", over_grass(combo, rock_ground(0), 0.05,
                                              edge_col=(78, 74, 68)))
    for combo in range(16):
        add(f"sand_grass_{combo}", over_grass(combo, sand(0), 0.07))
    for combo in range(16):
        add(f"farm_grass_{combo}", over_grass(combo, farmland(0), 0.04,
                                              edge_col=(96, 74, 48)))

    add("bush", bush())
    add("fern", fern())
    add("mushrooms", mushrooms())
    add("log", log())
    add("boulder", boulder())
    add("bones", bones())
    add("skull", skull())
    add("campfire", campfire())
    add("lantern", lantern())
    add("signpost", signpost())
    add("tall_grass", tall_grass())

    # HD-Sprites: Baeume 4x4 statt 2x2, Haeuser 8x7 statt 5x4.
    # 64 px reichen fuer keinen Wurzelanlauf und keine sechs Gruenstufen.
    for name, seed in (("tree_a", 1), ("tree_b", 2), ("tree_c", 3)):
        add_sprite(name, hd_tree(4 * TILE, LEAF6, BARK4,
                                 np.random.default_rng(300 + seed)))
    for name, seed in (("pine_a", 1), ("pine_b", 2)):
        add_sprite(name, hd_conifer(3 * TILE, 4 * TILE, NEEDLE5, BARK4,
                                    np.random.default_rng(400 + seed)))
    add_sprite("tent", tent())
    add_sprite("totem", totem())
    add_sprite("well", well())
    add_sprite("house_a", hd_house(8 * TILE, 7 * TILE, HOUSE_PAL,
                                   np.random.default_rng(501)))
    add_sprite("house_b", hd_house(8 * TILE, 7 * TILE, HOUSE_PAL,
                                   np.random.default_rng(502), shingle_rows=13))
    add_sprite("house_c", hd_house(6 * TILE, 6 * TILE, HOUSE_PAL,
                                   np.random.default_rng(503), shingle_rows=9))

    rows = (len(tiles) + COLS - 1) // COLS
    sheet = np.zeros((rows * TILE, COLS * TILE, 4), dtype=np.uint8)
    for i, t in enumerate(tiles):
        r_, c = divmod(i, COLS)
        sheet[r_ * TILE:(r_ + 1) * TILE, c * TILE:(c + 1) * TILE] = \
            np.clip(t, 0, 255).astype(np.uint8)

    out_dir = "assets/tilesets/painted"
    os.makedirs(out_dir, exist_ok=True)
    Image.fromarray(sheet).save(f"{out_dir}/tileset.png")
    with open(f"{out_dir}/tileset_meta.json", "w") as f:
        json.dump({"tile_size": TILE, "columns": COLS, "count": len(tiles),
                   "ids": singles, "sprites": sprites}, f, indent=2)
    print(f"{len(tiles)} Tiles ({len(sprites)} Sprites) -> {out_dir}/tileset.png")


if __name__ == "__main__":
    build()
