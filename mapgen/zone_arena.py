"""Zonen-Karte mit Gameplay-Fokus: begehbare Strassen, Kampfarenen, Deko.

Der Spieler laeuft auf dieser Karte — also muss alles, was er benutzt, im
Layout deutlich genug liegen, um den ComfyUI-Durchgang zu ueberleben
(siehe docs/karten_learnings.md).

Gegenueber channel_map.py neu:
  * Wegehierarchie: breite Pflaster-Hauptstrasse, schmalere Erdpfade
  * Kampfarenen mit VIER Zugaengen (N/O/S/W) zum Pullen aus allen Richtungen
  * Wasser mit Struktur (Tiefe, Wellen, Schaumsaum) statt einfarbiger Flaeche
  * Blumenwiesen und deutlich mehr Prop-Varianten

Ausgabe:
  render_base.png   Layout-Karte, geht so in ComfyUI
  collision.png     Weiss = blockiert, Bruecken/Wege begehbar
  layout.json       Arenen, Doerfer, Bruecken, Baeume fuer Unity

Aufruf:  python3 zone_arena.py [--size 2048] [--seed 7] [--islands 14]
"""

import argparse
import json
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy.ndimage import distance_transform_edt, gaussian_filter

from channel_map import (PAL, build_cells, choose_pois, collect_trees,
                         draw_boulders, draw_bridge, draw_detail, fbm,
                         find_bridges, poisson_points, water_distance)


# Eigene Farben fuer Wasser, Pflaster und Arena
AP = {
    "deep": (28, 62, 96), "mid": (38, 92, 130), "shallow": (66, 140, 162),
    "foam": (206, 228, 232),
    # Warmer Sandstein statt kaltem Grau: kaltes Grau liest der Sampler
    # als Fluss und malt prompt einen Bach mit Wasserfaellen hinein.
    "cobble": (176, 156, 124), "cobble_dark": (118, 100, 76),
    "kerb": (148, 128, 100),
    "arena_floor": (142, 120, 84), "arena_rim": (86, 70, 46),
    "arena_grass": (62, 80, 40),
    "wood": (120, 88, 52), "cloth": (168, 74, 62), "bone": (226, 222, 208),
    "flower": [(220, 96, 84), (232, 206, 104), (238, 238, 230),
               (176, 130, 208), (240, 160, 92)],
}


# ------------------------------------------------------------- Wasser ----

def paint_water(img, water, size, rng):
    """Wasser mit Tiefenverlauf, Wellen und Schaumsaum.

    Wichtig fuers spaetere img2img: eine einfarbige Flaeche bleibt bei
    Denoise 0.55 einfarbig. Struktur, die schon da ist, wird dagegen
    verstaerkt — deshalb malen wir Tiefe und Wellen hier selbst.
    """
    d_land = distance_transform_edt(water).astype(np.float32)   # Abstand zur Kueste
    t = np.clip(d_land / 90.0, 0, 1)[..., None] ** 0.7

    shallow = np.array(AP["shallow"], dtype=np.float32)
    mid = np.array(AP["mid"], dtype=np.float32)
    deep = np.array(AP["deep"], dtype=np.float32)
    col = shallow * (1 - np.clip(t * 2, 0, 1)) + mid * np.clip(t * 2, 0, 1)
    t2 = np.clip((t - 0.5) * 2, 0, 1)
    col = col * (1 - t2) + deep * t2

    # Wellen: zwei versetzte Sinusbaender, vom Rauschen verzerrt
    warp = (fbm(size, 9, 3, rng) - 0.5) * 34
    ys = np.arange(size, dtype=np.float32)[:, None]
    xs = np.arange(size, dtype=np.float32)[None, :]
    wave = (np.sin((ys + warp) / 13.0) * 0.5 + np.sin((xs * 0.6 + ys + warp) / 21.0))
    col += (wave * 7.0)[..., None] * (0.35 + 0.65 * t)

    # Glitzern auf dem tieferen Wasser
    spark = fbm(size, 200, 2, rng)
    col += np.clip((spark - 0.74) * 240, 0, 60)[..., None] * t

    # Schaumsaum entlang der Kueste
    foam = np.clip(1.0 - np.abs(d_land - 3.0) / 4.0, 0, 1)
    foam *= 0.55 + 0.45 * fbm(size, 60, 2, rng)
    col = col * (1 - foam[..., None]) + np.array(AP["foam"],
                                                 dtype=np.float32) * foam[..., None]

    img[water] = col[water]
    return img


# -------------------------------------------------------------- Wiese ----

def paint_meadow(img, land, wdist, size, rng):
    """Grasflaeche mit Farbspiel: Lichtungen, dunklere Waldsaeume, Erdflecken."""
    mix = fbm(size, 9, 4, rng)
    patch = fbm(size, 22, 3, rng)
    dirt = fbm(size, 6, 3, rng)

    g = np.array(PAL["grass"], dtype=np.float32)
    gd = np.array(PAL["grass_dark"], dtype=np.float32)
    bright = np.array((124, 142, 68), dtype=np.float32)
    dr = np.array(PAL["dirt"], dtype=np.float32)

    t = np.clip((mix - 0.34) / 0.34, 0, 1)[..., None]
    base = g * (1 - t) + gd * t
    tb = np.clip((patch - 0.58) / 0.2, 0, 1)[..., None]
    base = base * (1 - tb) + bright * tb          # sonnige Lichtungen
    td = np.clip((dirt - 0.68) / 0.12, 0, 1)[..., None]
    base = base * (1 - td) + dr * td              # vereinzelte Erdflecken

    # Feinstruktur, damit die Flaeche nicht platt wirkt
    blotch = fbm(size, 30, 3, rng) - 0.5
    speck = fbm(size, 190, 2, rng) - 0.5
    base += (blotch * 20 + speck * 13)[..., None]

    # Ufersaum leicht abdunkeln -> gibt der Insel Tiefe
    near = np.clip(1.0 - wdist / 12.0, 0, 1)[..., None]
    base *= (1.0 - 0.14 * near)

    img[land] = base[land]
    return img


def draw_flowers(draw, land_ok, size, rng):
    """Blumenwiesen: lockere Felder statt gleichmaessiger Streuung."""
    field = fbm(size, 14, 3, rng)
    count = int((size / 2048) ** 2 * 2400)
    for _ in range(count):
        x = int(rng.integers(size))
        y = int(rng.integers(size))
        if not land_ok[y, x] or field[y, x] < 0.68:
            continue
        c = AP["flower"][int(rng.integers(len(AP["flower"])))]
        # kleine Gruppe statt Einzelpunkt
        for _ in range(int(rng.integers(2, 5))):
            fx = x + rng.normal(0, 3.5)
            fy = y + rng.normal(0, 3.5)
            draw.ellipse([fx - 1.2, fy - 1.2, fx + 1.2, fy + 1.2], fill=c)
            draw.point((fx, fy + 2), fill=PAL["grass_dark"])


# ------------------------------------------------------------- Strasse ----

def smooth_path(p0, p1, rng, bow=0.12, n=40):
    """Leicht geschwungene Verbindung — gerade Linien wirken unnatuerlich."""
    (px, py), (cx, cy) = p0, p1
    mx = (px + cx) / 2 + (py - cy) * bow + rng.normal(0, 6)
    my = (py + cy) / 2 - (px - cx) * bow + rng.normal(0, 6)
    return [((1 - t) ** 2 * px + 2 * (1 - t) * t * mx + t * t * cx,
             (1 - t) ** 2 * py + 2 * (1 - t) * t * my + t * t * cy)
            for t in np.linspace(0, 1, n)]


def _walk(pts, step):
    """Punkte samt Querrichtung in festem Abstand entlang der Linie."""
    out = []
    carry = 0.0
    for i in range(1, len(pts)):
        (ax, ay), (bx, by) = pts[i - 1], pts[i]
        dx, dy = bx - ax, by - ay
        seg = math.hypot(dx, dy)
        if seg < 1e-6:
            continue
        ux, uy = dx / seg, dy / seg
        d = carry
        while d < seg:
            out.append((ax + ux * d, ay + uy * d, -uy, ux))
            d += step
        carry = d - seg
    return out


def draw_road(draw, pts, rng, width=30, cobbled=True):
    """Strasse in Schichten: Schatten, Bett, Belag, Randsteine.

    cobbled=True  -> Pflaster-Hauptstrasse (breit, hell, gefasst)
    cobbled=False -> ausgetretener Erdpfad (schmaler, weicher)
    """
    hw = width / 2
    draw.line(pts, fill=(72, 58, 36), width=int(width + 6), joint="curve")
    draw.line(pts, fill=PAL["dirt"], width=int(width + 2), joint="curve")

    if not cobbled:
        draw.line(pts, fill=PAL["path"], width=int(width), joint="curve")
        draw.line(pts, fill=(176, 148, 100), width=max(2, int(width * 0.3)),
                  joint="curve")
        # zwei feine Fahrspuren
        for x, y, nx, ny in _walk(pts, 4):
            for s in (1, -1):
                draw.point((x + nx * hw * 0.45 * s, y + ny * hw * 0.45 * s),
                           fill=(136, 108, 70))
        return

    draw.line(pts, fill=AP["cobble_dark"], width=int(width), joint="curve")

    # Pflastersteine: versetzte Reihen quer zur Laufrichtung
    tones = [(182, 162, 130), (166, 146, 116), (194, 176, 144), (152, 134, 106)]
    row = 0
    for x, y, nx, ny in _walk(pts, 7):
        row += 1
        offset = 3.5 if row % 2 else 0.0
        k = int(hw / 7)
        for j in range(-k, k + 1):
            d = j * 7 + offset
            if abs(d) > hw - 2.5:
                continue
            sx = x + nx * d + rng.normal(0, 0.7)
            sy = y + ny * d + rng.normal(0, 0.7)
            sw = 3.0 + rng.random() * 1.2
            sh = 2.4 + rng.random() * 1.0
            draw.ellipse([sx - sw, sy - sh, sx + sw, sy + sh],
                         fill=tones[int(rng.integers(len(tones)))],
                         outline=AP["cobble_dark"])

    # Randsteine fassen die Strasse ein — macht sie als Weg lesbar
    for x, y, nx, ny in _walk(pts, 9):
        for s in (1, -1):
            kx, ky = x + nx * (hw + 1.5) * s, y + ny * (hw + 1.5) * s
            draw.ellipse([kx - 3, ky - 2.2, kx + 3, ky + 2.2],
                         fill=AP["kerb"], outline=(84, 78, 70))


def decorate_roadside(draw, pts, rng, width, size):
    """Wegrand-Deko: Laternen, Wegsteine, Grasbuescheln, Blumen."""
    hw = width / 2
    lamp_every = 0
    for x, y, nx, ny in _walk(pts, 11):
        lamp_every += 1
        for s in (1, -1):
            if rng.random() > 0.62:
                continue
            off = hw + 5 + rng.random() * 7
            px, py = x + nx * off * s, y + ny * off * s
            if not (0 < px < size - 1 and 0 < py < size - 1):
                continue
            roll = rng.random()
            if roll < 0.42:                      # Grasbuschel
                for gdx in (-2, 0, 2):
                    draw.line([(px + gdx, py + 2), (px + gdx * 1.4, py - 3)],
                              fill=PAL["grass_dark"], width=1)
            elif roll < 0.72:                    # Kieselstein
                r = 1.5 + rng.random() * 1.5
                draw.ellipse([px - r, py - r, px + r, py + r], fill=PAL["stone"])
            else:                                # Blume
                c = AP["flower"][int(rng.integers(len(AP["flower"])))]
                draw.ellipse([px - 1.3, py - 1.3, px + 1.3, py + 1.3], fill=c)
        # alle ~5 Schritte eine Laterne an einer Seite
        if lamp_every % 5 == 0 and rng.random() < 0.5:
            s = 1 if rng.random() < 0.5 else -1
            px, py = x + nx * (hw + 6) * s, y + ny * (hw + 6) * s
            draw.ellipse([px - 1.6, py - 1, px + 1.6, py + 6], fill=(58, 46, 32))
            draw.ellipse([px - 3, py - 6, px + 3, py], fill=(240, 214, 130),
                         outline=(70, 56, 36))


# -------------------------------------------------------------- Arena ----

def draw_arena(draw, block, x, y, r, rng, size):
    """Kampfarena mit vier Zugaengen.

    Offene Flaeche zum Kaempfen, ringsum ein aufgebrochener Steinwall.
    In den vier Himmelsrichtungen fuehren Schneisen hinein — so kann man
    Monstergruppen aus vier Richtungen anziehen und kiten.
    """
    ang0 = rng.random() * math.pi / 2       # Arena leicht verdreht
    lanes = [ang0 + i * math.pi / 2 for i in range(4)]
    lane_half = 0.30                        # halbe Schneisenbreite im Bogenmass

    def in_lane(a):
        return any(abs(math.atan2(math.sin(a - la), math.cos(a - la))) < lane_half
                   for la in lanes)

    # Toter, zertretener Grassaum: hebt die Arena klar vom Wiesengruen ab
    angs = np.linspace(0, 2 * math.pi, 40, endpoint=False)
    wob = 1 + (rng.random(len(angs)) - 0.5) * 0.16
    draw.polygon([(x + math.cos(a) * r * w * 1.42, y + math.sin(a) * r * w * 1.42)
                  for a, w in zip(angs, wob)], fill=(78, 84, 46))
    draw.polygon([(x + math.cos(a) * r * w * 1.28, y + math.sin(a) * r * w * 1.28)
                  for a, w in zip(angs, wob)], fill=AP["arena_grass"])
    # Kampfboden: festgetretene Erde
    draw.polygon([(x + math.cos(a) * r * w, y + math.sin(a) * r * w)
                  for a, w in zip(angs, wob)], fill=AP["arena_floor"])
    # KEINE glatte helle Kreisflaeche in der Mitte: ein heller Kern mit
    # dunklem Ring liest der Sampler als Teich und malt Wasser hinein.
    # Stattdessen fleckiger, trockener Kampfboden ohne klaren Rand.
    for _ in range(int(r * 2.2)):
        a = rng.random() * 2 * math.pi
        d = r * math.sqrt(rng.random()) * 0.92
        px, py = x + math.cos(a) * d, y + math.sin(a) * d
        pr = r * (0.10 + rng.random() * 0.16)
        tone = (150, 128, 88) if rng.random() < 0.5 else (122, 102, 70)
        draw.ellipse([px - pr, py - pr * 0.8, px + pr, py + pr * 0.8], fill=tone)
    # Schleifspuren: gibt der Flaeche Richtung statt Becken-Optik
    for _ in range(int(r * 0.5)):
        a = rng.random() * 2 * math.pi
        d = r * rng.random() * 0.85
        px, py = x + math.cos(a) * d, y + math.sin(a) * d
        ln = r * (0.14 + rng.random() * 0.18)
        ta = rng.random() * math.pi
        draw.line([(px - math.cos(ta) * ln, py - math.sin(ta) * ln),
                   (px + math.cos(ta) * ln, py + math.sin(ta) * ln)],
                  fill=(104, 86, 58), width=2)

    # Vier Schneisen nach aussen: schmale Trampelpfade, die im Gras auslaufen
    for la in lanes:
        ex, ey = x + math.cos(la) * r * 1.34, y + math.sin(la) * r * 1.34
        lane = smooth_path((x, y), (ex, ey), rng, bow=0.02, n=18)
        draw.line(lane, fill=AP["arena_grass"], width=int(r * 0.30),
                  joint="curve")
        draw.line(lane, fill=AP["arena_floor"], width=int(r * 0.19),
                  joint="curve")

    # Steinwall mit Luecken an den Schneisen
    n = max(20, int(r / 2.2))
    for i in range(n):
        a = i * 2 * math.pi / n + rng.normal(0, 0.02)
        if in_lane(a):
            continue
        rr = r * (1.02 + rng.random() * 0.10)
        sx, sy = x + math.cos(a) * rr, y + math.sin(a) * rr
        sr = 3.5 + rng.random() * 3.5
        draw.ellipse([sx - sr + 1.5, sy - sr + 2, sx + sr + 1.5, sy + sr + 2],
                     fill=(40, 36, 30))                      # Schatten
        draw.polygon([(sx + math.cos(t) * sr * (0.8 + rng.random() * 0.4),
                       sy + math.sin(t) * sr * (0.8 + rng.random() * 0.4))
                      for t in np.linspace(0, 2 * math.pi, 6, endpoint=False)],
                     fill=(132, 128, 122), outline=(70, 66, 62))

    # Lagerplatz in der Mitte: Feuerstelle, Zelte, Knochen, Totem
    draw.ellipse([x - r * 0.16, y - r * 0.13, x + r * 0.16, y + r * 0.13],
                 fill=(64, 54, 44), outline=(38, 32, 26))
    for _ in range(7):                                        # Feuerholz
        a = rng.random() * 2 * math.pi
        d = r * 0.11
        draw.line([(x + math.cos(a) * d, y + math.sin(a) * d * 0.8),
                   (x - math.cos(a) * d, y - math.sin(a) * d * 0.8)],
                  fill=AP["wood"], width=2)
    draw.ellipse([x - r * 0.06, y - r * 0.05, x + r * 0.06, y + r * 0.05],
                 fill=(238, 168, 72))                         # Glut

    # BEWUSST keine Zelte: dreieckige Zeltdaecher malt der Sampler als
    # Haeuser mit rotem Dach — die Arena wird dann zum Dorf.
    # Knochenfeld statt Lager: liest als wildes Monsterrevier.
    for _ in range(18):
        bx = x + rng.normal(0, r * 0.38)
        by = y + rng.normal(0, r * 0.38)
        if rng.random() < 0.6:                                # Knochensplitter
            draw.ellipse([bx - 2.5, by - 1.2, bx + 2.5, by + 1.2],
                         fill=AP["bone"])
        else:                                                 # Rippenbogen
            for k in range(3):
                draw.arc([bx - 5, by - 4 + k * 2.5, bx + 5, by + 4 + k * 2.5],
                         200, 340, fill=AP["bone"], width=1)
    # Schaedel als Blickfang
    sx, sy = x + rng.normal(0, r * 0.2), y + rng.normal(0, r * 0.2)
    draw.ellipse([sx - 4, sy - 3.5, sx + 4, sy + 3.5], fill=AP["bone"],
                 outline=(150, 146, 132))
    draw.ellipse([sx - 2.2, sy - 1, sx - 0.6, sy + 0.8], fill=(70, 66, 58))
    draw.ellipse([sx + 0.6, sy - 1, sx + 2.2, sy + 0.8], fill=(70, 66, 58))

    # Totem am Rand einer Schneise als Blickfang
    ta = lanes[0] + 0.45
    tx, ty = x + math.cos(ta) * r * 0.85, y + math.sin(ta) * r * 0.85
    draw.line([(tx, ty + r * 0.14), (tx, ty - r * 0.20)], fill=AP["wood"], width=4)
    draw.ellipse([tx - 4, ty - r * 0.26, tx + 4, ty - r * 0.16],
                 fill=AP["cloth"], outline=(70, 34, 28))

    y0, y1 = max(int(y - r * 2.0), 0), min(int(y + r * 2.0), size)
    x0, x1 = max(int(x - r * 2.0), 0), min(int(x + r * 2.0), size)
    block[y0:y1, x0:x1] = True
    return [float(a) for a in lanes]


# --------------------------------------------------------------- Props ----

def draw_props(draw, land_ok, size, rng):
    """Mehr Sprite-Vielfalt: Buesche, Farne, Baumstaemme, Ruinen, Pilze."""
    n = int((size / 2048) ** 2 * 520)
    for _ in range(n):
        x = int(rng.integers(size))
        y = int(rng.integers(size))
        if not land_ok[y, x]:
            continue
        roll = rng.random()

        if roll < 0.42:                                   # Busch
            r = 5 + rng.random() * 5
            draw.ellipse([x - r + 1, y - r * 0.6 + 2, x + r + 1, y + r * 0.7 + 2],
                         fill=(34, 46, 28))
            for k in range(4):
                bx = x + rng.normal(0, r * 0.4)
                by = y + rng.normal(0, r * 0.3)
                br = r * (0.5 + rng.random() * 0.4)
                draw.ellipse([bx - br, by - br * 0.8, bx + br, by + br * 0.8],
                             fill=(52, 76, 38) if k % 2 else (66, 92, 44))

        elif roll < 0.68:                                 # Farn
            for k in range(7):
                a = -math.pi / 2 + (k - 3) * 0.30
                ln = 7 + rng.random() * 5
                draw.line([(x, y + 2),
                           (x + math.cos(a) * ln, y + 2 + math.sin(a) * ln)],
                          fill=(58, 88, 42), width=2)

        elif roll < 0.76:                                 # umgestuerzter Stamm
            a = rng.random() * math.pi
            ln = 10 + rng.random() * 12
            dx, dy = math.cos(a) * ln, math.sin(a) * ln
            draw.line([(x - dx + 1, y - dy + 2), (x + dx + 1, y + dy + 2)],
                      fill=(40, 32, 24), width=7)
            draw.line([(x - dx, y - dy), (x + dx, y + dy)],
                      fill=(104, 78, 48), width=6)
            draw.line([(x - dx, y - dy), (x + dx, y + dy)],
                      fill=(132, 102, 66), width=2)

        elif roll < 0.86:                                 # Pilzgruppe
            for _ in range(int(rng.integers(2, 5))):
                mx, my = x + rng.normal(0, 4), y + rng.normal(0, 4)
                draw.line([(mx, my), (mx, my + 3)], fill=(216, 208, 188), width=1)
                draw.ellipse([mx - 2.2, my - 2, mx + 2.2, my + 1],
                             fill=(196, 76, 62))

        elif roll < 0.94:                                 # Findling
            r = 4 + rng.random() * 4
            draw.polygon([(x + math.cos(t) * r * (0.7 + rng.random() * 0.5),
                           y + math.sin(t) * r * (0.7 + rng.random() * 0.5))
                          for t in np.linspace(0, 2 * math.pi, 6, endpoint=False)],
                         fill=(138, 134, 128), outline=(74, 70, 66))

        elif roll < 0.975:                                # Ruinenmauer
            a = rng.random() * math.pi
            for k in range(int(rng.integers(2, 5))):
                sx = x + math.cos(a) * k * 6
                sy = y + math.sin(a) * k * 6
                h = 3 + rng.random() * 3
                draw.rectangle([sx - 3, sy - h, sx + 3, sy + 2],
                               fill=(146, 140, 128), outline=(84, 80, 74))

        else:                                             # Lagerfeuer-Rest
            draw.ellipse([x - 5, y - 4, x + 5, y + 4], fill=(70, 60, 48))
            for _ in range(4):
                a = rng.random() * 2 * math.pi
                draw.line([(x + math.cos(a) * 4, y + math.sin(a) * 3),
                           (x - math.cos(a) * 4, y - math.sin(a) * 3)],
                          fill=AP["wood"], width=2)


# ---------------------------------------------------------------- main ----

def generate(size, seed, islands, out_dir):
    rng = np.random.default_rng(seed)
    os.makedirs(out_dir, exist_ok=True)

    print(f"[1/8] {islands} Inselzentren verteilen ...")
    seeds = poisson_points(size, islands, size * 0.05, rng)

    print("[2/8] Landmasse und Wasserlaeufe formen ...")
    labels, water, _ = build_cells(size, seeds, rng)
    wdist = water_distance(water)
    land = ~water

    print("[3/8] Bruecken planen ...")
    bridges, touching = find_bridges(seeds, labels, water, rng)
    print(f"      {len(bridges)} Bruecken")

    print("[4/8] Wasser und Wiese malen ...")
    img_arr = np.zeros((size, size, 3), dtype=np.float32)
    img_arr = paint_water(img_arr, water, size, rng)
    img_arr = paint_meadow(img_arr, land, wdist, size, rng)

    # Kuestenkante: heller Felssaum, damit die Insel Hoehe bekommt
    d_water = distance_transform_edt(land).astype(np.float32)
    edge = land & (d_water <= 3)
    img_arr[edge] = img_arr[edge] * 0.35 + np.array(PAL["cliff_hi"],
                                                    dtype=np.float32) * 0.65
    dark = land & (d_water > 3) & (d_water <= 6)
    img_arr[dark] *= 0.88

    img = Image.fromarray(np.clip(img_arr, 0, 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(0.4))
    draw = ImageDraw.Draw(img)

    collision = Image.fromarray((water * 255).astype(np.uint8))
    cdraw = ImageDraw.Draw(collision)

    print("[5/8] Strassennetz bauen ...")
    block = np.zeros((size, size), dtype=bool)
    n_villages = max(3, len(seeds) // 12)
    capital, villages = choose_pois(seeds, size, n_villages)
    towns = set([capital] + list(villages))
    spacing = size / math.sqrt(len(seeds))

    ends_per_cell = {}
    for p0, p1, _w in bridges:
        for p in (p0, p1):
            xi = int(min(max(p[0], 0), size - 1))
            yi = int(min(max(p[1], 0), size - 1))
            ends_per_cell.setdefault(int(labels[yi, xi]), []).append(p)

    roads = []          # (Punkte, Breite, gepflastert)
    for cell, ends in ends_per_cell.items():
        cy, cx = seeds[cell]
        main = cell in towns
        for (px, py) in ends:
            roads.append((smooth_path((px, py), (cx, cy), rng),
                          30 if main else 19, main))
    for a, b in touching:
        main = a in towns and b in towns
        roads.append((smooth_path((seeds[a][1], seeds[a][0]),
                                  (seeds[b][1], seeds[b][0]), rng),
                      30 if main else 19, main))

    for pts, w, cob in roads:
        draw_road(draw, pts, rng, width=w, cobbled=cob)
    for pts, w, _c in roads:
        decorate_roadside(draw, pts, rng, w, size)

    print("[6/8] Doerfer und Kampfarenen setzen ...")
    from channel_map import draw_plaza
    cy, cx = seeds[capital]
    draw_plaza(draw, block, int(cx), int(cy), int(spacing * 0.21), size, rng)
    for v in villages:
        vy, vx = seeds[v]
        draw_plaza(draw, block, int(vx), int(vy), int(spacing * 0.13), size, rng)

    arena_cells = [i for i in range(len(seeds)) if i not in towns]
    rng.shuffle(arena_cells)
    arenas = []
    for cell in arena_cells[: max(3, len(seeds) // 3)]:
        sy, sx = seeds[cell]
        for _ in range(10):
            ox = sx + rng.normal(0, spacing * 0.20)
            oy = sy + rng.normal(0, spacing * 0.20)
            xi = int(min(max(ox, 0), size - 1))
            yi = int(min(max(oy, 0), size - 1))
            if (labels[yi, xi] == cell and land[yi, xi]
                    and wdist[yi, xi] > 16 and not block[yi, xi]):
                r = spacing * (0.17 + rng.random() * 0.04)
                # Zuweg von der Arena zum Inselzentrum
                link = smooth_path((xi, yi), (sx, sy), rng)
                draw_road(draw, link, rng, width=19, cobbled=False)
                roads.append((link, 19, False))     # auch fuer die Tile-Zone
                lanes = draw_arena(draw, block, xi, yi, r, rng, size)
                arenas.append({"x": float(xi), "y": float(yi),
                               "radius": round(float(r), 1),
                               "lane_angles_rad": [round(a, 3) for a in lanes]})
                break
    print(f"      {len(arenas)} Arenen mit je 4 Zugaengen")

    print("[7/8] Felsen, Bruecken, Deko ...")
    # Ausgeduennt: ein durchgehender Steinsaum um jede Insel wirkt wie
    # eine Perlenkette statt wie Natur
    draw_boulders(draw, land & (rng.random((size, size)) < 0.34),
                  wdist, size, rng)

    shadow = Image.new("L", (size, size), 0)
    sdraw = ImageDraw.Draw(shadow)
    for p0, p1, _w in bridges:
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        ln = math.hypot(dx, dy)
        if ln < 4:
            continue
        nx, ny = -dy / ln, dx / ln
        sdraw.polygon([(p0[0] + 3 + nx * 10, p0[1] + 10 + ny * 10),
                       (p1[0] + 3 + nx * 10, p1[1] + 10 + ny * 10),
                       (p1[0] + 3 - nx * 10, p1[1] + 10 - ny * 10),
                       (p0[0] + 3 - nx * 10, p0[1] + 10 - ny * 10)], fill=255)
    arr = np.asarray(img, dtype=np.float32)
    arr[(np.asarray(shadow) > 0) & water] *= 0.45
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(img)

    bridge_meta = []
    for p0, p1, _w in bridges:
        meta = draw_bridge(draw, cdraw, p0, p1)
        if meta:
            bridge_meta.append(meta)

    land_ok = land & (wdist >= 4) & ~block
    draw_props(draw, land_ok, size, rng)
    draw_detail(draw, land_ok, size, rng)
    draw_flowers(draw, land_ok, size, rng)
    trees = collect_trees(land_ok, wdist, size, rng)
    print(f"      {len(trees)} Baumpositionen (kommen als Assets in Unity)")

    print("[8/8] Speichern ...")
    img.save(os.path.join(out_dir, "render_base.png"))
    collision.save(os.path.join(out_dir, "collision.png"))
    with open(os.path.join(out_dir, "layout.json"), "w") as f:
        json.dump({"size": size, "seed": seed,
                   "capital": {"x": float(cx), "y": float(cy)},
                   "villages": [{"x": float(seeds[v][1]), "y": float(seeds[v][0])}
                                for v in villages],
                   "arenas": arenas,
                   # Strassenverlaeufe: die begehbare Tile-Zone baut daraus
                   # dieselben Wege, damit Uebersichtskarte und Zone passen
                   "roads": [{"width": w, "paved": bool(c),
                              "points": [[round(px, 1), round(py, 1)]
                                         for px, py in pts]}
                             for pts, w, c in roads],
                   "bridges": bridge_meta,
                   "trees": [{"x": x, "y": y, "scale": round(r / 5.5, 2)}
                             for x, y, r in trees]}, f, indent=2)
    print(f"Fertig -> {out_dir}/render_base.png "
          f"({len(bridge_meta)} Bruecken, {len(villages)} Doerfer, "
          f"{len(arenas)} Arenen)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=2048)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--islands", type=int, default=14)
    ap.add_argument("--out", default="mapgen/zone_arena")
    args = ap.parse_args()
    generate(args.size, args.seed, args.islands, args.out)
