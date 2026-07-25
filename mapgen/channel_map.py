"""Kanal-Karte im Stil handgemalter MMORPG-Maps.

Die Welt ist eine grosse Landmasse, die von gewundenen Wasserlaeufen in
organische Inseln zerteilt wird. Bruecken verbinden die Inseln an den
engsten Stellen; ein Spannbaum garantiert, dass jede Insel erreichbar ist,
einige Extra-Bruecken schaffen Abkuerzungen und Rundwege.

Ausgabe:
  channel_map.png   Sichtbare Karte
  collision.png     Weiss = blockiert (Wasser), Bruecken sind begehbar
  bridges.json      Brueckenpositionen/-winkel fuer Unity

Aufruf:  python3 channel_map.py [--size 2048] [--seed 3] [--islands 42]
"""

import argparse
import json
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy.spatial import cKDTree


# ------------------------------------------------------------- helpers ----

def _value_noise(h, w, cells, rng):
    grid = rng.random((cells + 2, cells + 2))
    ys = np.linspace(0, cells, h, endpoint=False)
    xs = np.linspace(0, cells, w, endpoint=False)
    y0, x0 = ys.astype(int), xs.astype(int)
    ty, tx = ys - y0, xs - x0
    ty = (ty * ty * (3 - 2 * ty))[:, None]
    tx = (tx * tx * (3 - 2 * tx))[None, :]
    g00 = grid[np.ix_(y0, x0)]
    g01 = grid[np.ix_(y0, x0 + 1)]
    g10 = grid[np.ix_(y0 + 1, x0)]
    g11 = grid[np.ix_(y0 + 1, x0 + 1)]
    return (g00 * (1 - tx) + g01 * tx) * (1 - ty) + \
           (g10 * (1 - tx) + g11 * tx) * ty


def fbm(size, base, octaves, rng):
    total = np.zeros((size, size))
    amp, s, cells = 1.0, 0.0, base
    for _ in range(octaves):
        total += amp * _value_noise(size, size, cells, rng)
        s += amp
        amp *= 0.5
        cells *= 2
    return total / s


def poisson_points(size, count, margin, rng):
    """Gleichmaessig verteilte Inselzentren (Best-Candidate-Sampling)."""
    pts = [rng.uniform(margin, size - margin, 2)]
    while len(pts) < count:
        cand = rng.uniform(margin, size - margin, (24, 2))
        d = cKDTree(pts).query(cand)[0]
        pts.append(cand[np.argmax(d)])
    return np.array(pts)


# ------------------------------------------------------------ geometry ----

def build_cells(size, seeds, rng):
    """Verzerrtes Voronoi: Label je Pixel + Kanal-Maske zwischen den Zellen."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    amp = size * 0.045
    wy = (fbm(size, 6, 4, rng) - 0.5).astype(np.float32) * amp
    wx = (fbm(size, 6, 4, rng) - 0.5).astype(np.float32) * amp
    pts = np.column_stack([(yy + wy).ravel(), (xx + wx).ravel()])
    dist, idx = cKDTree(seeds).query(pts, k=2, workers=-1)
    d1 = dist[:, 0].reshape(size, size)
    d2 = dist[:, 1].reshape(size, size)
    labels = idx[:, 0].reshape(size, size)

    # Kanalbreite variiert mit Rauschen -> mal breite Stroeme, mal enge Passagen
    width = (fbm(size, 5, 3, rng) * 0.5 + 0.55) * size * 0.012
    water = (d2 - d1) < width
    return labels, water, d1


def water_distance(water, max_d=48):
    """Fuer jedes Landpixel: Abstand zum Wasser (gedeckelt), per Dilation."""
    dist = np.full(water.shape, max_d, dtype=np.uint8)
    m = water.copy()
    for d in range(1, max_d):
        m = (m | np.roll(m, 1, 0) | np.roll(m, -1, 0)
             | np.roll(m, 1, 1) | np.roll(m, -1, 1))
        dist[m & (dist == max_d)] = d
    dist[water] = 0
    return dist


def find_bridges(seeds, labels, water, rng, extra_ratio=0.3):
    """Brueckenplanung: Spannbaum ueber alle Inseln + einige Abkuerzungen.

    Fuer jedes Inselpaar wird entlang der Verbindungslinie der Wasserlauf
    gesucht; die Bruecke ueberspannt genau diese Engstelle.
    """
    n = len(seeds)
    size = labels.shape[0]

    def water_run(a, b):
        """Wasserabschnitt auf der Strecke seeds[a]->seeds[b] (oder None)."""
        p0, p1 = seeds[a], seeds[b]
        steps = int(np.hypot(*(p1 - p0)))
        if steps < 4:
            return None
        t = np.linspace(0, 1, steps)
        ys = (p0[0] + (p1[0] - p0[0]) * t).astype(int).clip(0, size - 1)
        xs = (p0[1] + (p1[1] - p0[1]) * t).astype(int).clip(0, size - 1)
        w = water[ys, xs]
        runs, start = [], None
        for i, v in enumerate(w):
            if v and start is None:
                start = i
            elif not v and start is not None:
                runs.append((start, i))
                start = None
        if start is not None:
            runs.append((start, steps))
        if len(runs) != 1:      # Linie kreuzt mehrere Kanaele -> kein direkter Nachbar
            return None
        s, e = runs[0]
        # Label vor/nach dem Wasser muss zu a bzw. b gehoeren
        if labels[ys[max(s - 3, 0)], xs[max(s - 3, 0)]] != a:
            return None
        if labels[ys[min(e + 2, steps - 1)], xs[min(e + 2, steps - 1)]] != b:
            return None
        pad = 6                 # Bruecke ragt beidseitig aufs Ufer
        s2, e2 = max(s - pad, 0), min(e + pad, steps - 1)
        return ((float(xs[s2]), float(ys[s2])), (float(xs[e2]), float(ys[e2])),
                e - s)

    # Kandidaten: Inselpaare, deren Verbindungslinie genau einen Kanal kreuzt
    cand = {}
    for a in range(n):
        for b in range(a + 1, n):
            if np.hypot(*(seeds[a] - seeds[b])) > size * 0.22:
                continue
            r = water_run(a, b)
            if r is not None:
                cand[(a, b)] = r

    # Kruskal-Spannbaum: kurze/enge Uebergaenge zuerst -> "schlaue" Bruecken
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ordered = sorted(cand.items(), key=lambda kv: kv[1][2])
    bridges, extras = [], []
    for (a, b), run in ordered:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
            bridges.append(run)
        else:
            extras.append(run)
    # Abkuerzungen: die engsten uebrigen Uebergaenge, sparsam eingesetzt
    rng.shuffle(extras)
    extras.sort(key=lambda r: r[2])
    bridges += extras[: int(len(bridges) * extra_ratio)]
    return bridges


# ------------------------------------------------------------ painting ----

PAL = {
    "deep": (43, 74, 84), "water": (58, 96, 104), "shore": (86, 128, 130),
    "bank": (46, 38, 26), "grass": (104, 120, 62), "grass_dark": (76, 96, 50),
    "dirt": (128, 102, 64), "path": (158, 128, 82),
    "tree_dark": (34, 52, 28), "tree": (56, 82, 40), "tree_hi": (82, 108, 52),
    "plank": (146, 110, 66), "plank_dark": (112, 82, 48), "rail": (58, 42, 26),
}


def paint_base(size, water, wdist, rng):
    img = np.zeros((size, size, 3))
    deep = water & (wdist == 0)

    # Wassertiefe: Mitte der Kanaele dunkler
    inner = water.copy()
    depth = np.zeros((size, size), dtype=np.uint8)
    for i in range(1, 14):
        inner = ~((~inner) | np.roll(~inner, 1, 0) | np.roll(~inner, -1, 0)
                  | np.roll(~inner, 1, 1) | np.roll(~inner, -1, 1))
        depth[inner] = i
    t = np.clip(depth / 10, 0, 1)[..., None]
    img[water] = (np.array(PAL["water"]) * (1 - t) + np.array(PAL["deep"]) * t)[water]

    # Land: Grasmischung + Erde-Flecken, malerische Helligkeitsvariation
    land = ~water
    mix = fbm(size, 10, 4, rng)
    dirt = fbm(size, 7, 3, rng)
    g = np.array(PAL["grass"]) ; gd = np.array(PAL["grass_dark"]) ; dr = np.array(PAL["dirt"])
    t2 = np.clip((mix - 0.35) / 0.35, 0, 1)[..., None]
    base = g * (1 - t2) + gd * t2
    td = np.clip((dirt - 0.62) / 0.14, 0, 1)[..., None]
    base = base * (1 - td) + dr * td
    img[land] = base[land]
    blotch = fbm(size, 28, 3, rng) - 0.5
    speck = fbm(size, 170, 2, rng) - 0.5
    img[land] += ((blotch * 24 + speck * 12)[..., None])[land]

    # Ufer: dunkle Tusche-Kante + heller Flachwassersaum
    bank = (wdist == 0) & water
    edge = (wdist >= 1) & (wdist <= 2)
    img[edge] = img[edge] * 0.55 + np.array(PAL["bank"]) * 0.45
    shore = water & (depth <= 2)
    img[shore] = img[shore] * 0.7 + np.array(PAL["shore"]) * 0.3
    # Land nahe dem Ufer leicht abdunkeln (gemalte Tiefe)
    near = land & (wdist <= 6)
    img[near] *= 0.88
    _ = deep, bank
    return np.clip(img, 0, 255)


def draw_bridge(draw, cdraw, p0, p1):
    """Holzbruecke von p0 nach p1 (Planken + Gelaender), begehbar."""
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length < 4:
        return None
    ux, uy = dx / length, dy / length          # laengs
    nx, ny = -uy, ux                            # quer
    hw = 9                                      # halbe Breite

    def quad(a0, a1, w):
        return [(a0[0] + nx * w, a0[1] + ny * w),
                (a1[0] + nx * w, a1[1] + ny * w),
                (a1[0] - nx * w, a1[1] - ny * w),
                (a0[0] - nx * w, a0[1] - ny * w)]

    draw.polygon(quad(p0, p1, hw + 2), fill=PAL["rail"])          # Aussenkante
    draw.polygon(quad(p0, p1, hw), fill=PAL["plank"])
    # Planken quer zur Laufrichtung
    steps = max(int(length // 7), 1)
    for i in range(steps):
        t0 = i / steps
        a = (x0 + dx * t0, y0 + dy * t0)
        b = (a[0] + ux * 2.5, a[1] + uy * 2.5)
        draw.polygon(quad(a, b, hw), fill=PAL["plank_dark"])
    # Gelaender
    for s in (1, -1):
        draw.line([(x0 + nx * hw * s, y0 + ny * hw * s),
                   (x1 + nx * hw * s, y1 + ny * hw * s)],
                  fill=PAL["rail"], width=3)
    cdraw.polygon(quad(p0, p1, hw), fill=0)                       # begehbar
    return {"x0": x0, "y0": y0, "x1": x1, "y1": y1,
            "angle_deg": math.degrees(math.atan2(dy, dx)), "length": length}


def draw_paths(draw, seeds, bridges, labels, size):
    """Erdpfade: Brueckenenden mit dem Inselzentrum verbinden."""
    ends_per_cell = {}
    for p0, p1, _ in bridges:
        for p in (p0, p1):
            xi = int(min(max(p[0], 0), size - 1))
            yi = int(min(max(p[1], 0), size - 1))
            ends_per_cell.setdefault(int(labels[yi, xi]), []).append(p)
    for cell, ends in ends_per_cell.items():
        cy, cx = seeds[cell]
        for (px, py) in ends:
            mx = (px + cx) / 2 + (py - cy) * 0.12   # leichte Kurve
            my = (py + cy) / 2 - (px - cx) * 0.12
            pts = []
            for t in np.linspace(0, 1, 24):
                bx = (1 - t) ** 2 * px + 2 * (1 - t) * t * mx + t * t * cx
                by = (1 - t) ** 2 * py + 2 * (1 - t) * t * my + t * t * cy
                pts.append((bx, by))
            draw.line(pts, fill=PAL["path"], width=7, joint="curve")


def draw_trees(draw, land_ok, wdist, size, rng):
    """Dichte Baumreihen an Ufern und am Kartenrand, Cluster im Inneren."""
    border = 46
    forest_noise = fbm(size, 9, 3, rng)
    positions = []
    step = max(8, size // 260)
    for gy in range(0, size, step):
        for gx in range(0, size, step):
            x = int(gx + rng.integers(step))
            y = int(gy + rng.integers(step))
            if x >= size or y >= size or not land_ok[y, x]:
                continue
            d = wdist[y, x]
            on_border = x < border or y < border or x > size - border or y > size - border
            near_bank = 4 <= d <= 16
            in_cluster = forest_noise[y, x] > 0.62 and d > 10
            p = 0.9 if on_border else (0.55 if near_bank else (0.5 if in_cluster else 0.02))
            if rng.random() < p:
                positions.append((x, y, 4 + int(rng.integers(4))))
    positions.sort(key=lambda p: p[1])
    for x, y, r in positions:
        draw.ellipse([x - r, y - r + 2, x + r, y + r + 2], fill=PAL["tree_dark"])
        draw.ellipse([x - r + 1, y - r + 1, x + r - 1, y + r - 1], fill=PAL["tree"])
        hr = max(1, r // 2)
        draw.ellipse([x - hr, y - r + 2, x + hr, y - r + 2 + hr * 2],
                     fill=PAL["tree_hi"])


# ---------------------------------------------------------------- main ----

def generate(size, seed, islands, out_dir):
    rng = np.random.default_rng(seed)
    os.makedirs(out_dir, exist_ok=True)

    print(f"[1/7] {islands} Inselzentren verteilen ...")
    seeds = poisson_points(size, islands, size * 0.05, rng)

    print("[2/7] Wasserlaeufe formen ...")
    labels, water, _d1 = build_cells(size, seeds, rng)
    wdist = water_distance(water)

    print("[3/7] Bruecken planen (Spannbaum + Abkuerzungen) ...")
    bridges = find_bridges(seeds, labels, water, rng)
    print(f"      {len(bridges)} Bruecken")

    print("[4/7] Boden malen ...")
    img_arr = paint_base(size, water, wdist, rng)
    img = Image.fromarray(img_arr.astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(0.5))
    draw = ImageDraw.Draw(img)

    collision = Image.fromarray((water * 255).astype(np.uint8))
    cdraw = ImageDraw.Draw(collision)

    print("[5/7] Pfade und Bruecken zeichnen ...")
    draw_paths(draw, seeds, bridges, labels, size)
    bridge_meta = []
    for p0, p1, _w in bridges:
        meta = draw_bridge(draw, cdraw, p0, p1)
        if meta:
            bridge_meta.append(meta)

    print("[6/7] Baeume setzen ...")
    # keine Baeume direkt auf Bruecken/Pfad-Enden
    land_ok = ~water & (wdist >= 3)
    draw_trees(draw, land_ok, wdist, size, rng)

    print("[7/7] Speichern ...")
    img.save(os.path.join(out_dir, "channel_map.png"))
    collision.save(os.path.join(out_dir, "collision.png"))
    with open(os.path.join(out_dir, "bridges.json"), "w") as f:
        json.dump({"size": size, "seed": seed,
                   "islands": [{"x": float(s[1]), "y": float(s[0])} for s in seeds],
                   "bridges": bridge_meta}, f, indent=2)
    print(f"Fertig -> {out_dir}/channel_map.png ({len(bridge_meta)} Bruecken)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=2048)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--islands", type=int, default=42)
    ap.add_argument("--out", default="output")
    args = ap.parse_args()
    generate(args.size, args.seed, args.islands, args.out)
