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
    total = np.zeros((size, size), dtype=np.float32)
    amp, s, cells = 1.0, 0.0, base
    for _ in range(octaves):
        total += amp * _value_noise(size, size, cells, rng).astype(np.float32)
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
    amp = size * 0.045
    wy = (fbm(size, 6, 4, rng) - 0.5) * amp
    wx = (fbm(size, 6, 4, rng) - 0.5) * amp

    # Kanalbreite variiert mit Rauschen -> mal breite Stroeme, mal enge Passagen
    # Basis ist der typische Inselabstand, damit Fluesse bei jeder
    # Kartengroesse gleich breit bleiben
    spacing = size / math.sqrt(len(seeds))
    width = (fbm(size, 5, 3, rng) * 0.5 + 0.55) * spacing * 0.078

    # zeilenweise KDTree-Abfrage, damit auch 8192px in den Speicher passen
    tree = cKDTree(seeds)
    labels = np.empty((size, size), dtype=np.int32)
    water = np.empty((size, size), dtype=bool)
    chunk = max(1, (2048 * 2048) // size)
    xs_row = np.arange(size, dtype=np.float32)
    for y0 in range(0, size, chunk):
        y1 = min(y0 + chunk, size)
        yy = np.repeat(np.arange(y0, y1, dtype=np.float32), size)
        xx = np.tile(xs_row, y1 - y0)
        pts = np.column_stack([yy + wy[y0:y1].ravel(),
                               xx + wx[y0:y1].ravel()])
        dist, idx = tree.query(pts, k=2, workers=-1)
        labels[y0:y1] = idx[:, 0].reshape(y1 - y0, size)
        water[y0:y1] = ((dist[:, 1] - dist[:, 0])
                        .reshape(y1 - y0, size) < width[y0:y1])
    return labels, water, None


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

    # Kandidaten: nur echte Nachbarn (naechste 8 Inseln je Zentrum),
    # deren Verbindungslinie genau einen Kanal kreuzt
    k = min(9, n)
    _, nbr = cKDTree(seeds).query(seeds, k=k, workers=-1)
    cand = {}
    for a in range(n):
        for b in nbr[a][1:]:
            b = int(b)
            lo, hi = min(a, b), max(a, b)
            if (lo, hi) in cand:
                continue
            r = water_run(lo, hi)
            if r is not None:
                cand[(lo, hi)] = r

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
    "deep": (30, 56, 66), "water": (46, 80, 90), "shore": (74, 116, 118),
    "bank": (40, 32, 22), "cliff": (74, 60, 42), "cliff_hi": (116, 98, 68),
    "grass": (92, 108, 56), "grass_dark": (64, 84, 44),
    "dirt": (112, 88, 54), "path": (150, 120, 76),
    "tree_dark": (28, 44, 24), "tree": (48, 72, 36), "tree_hi": (72, 98, 46),
    "plank": (146, 110, 66), "plank_dark": (112, 82, 48), "rail": (52, 38, 24),
    "plaza": (140, 110, 70), "plaza_dark": (106, 82, 52),
    "stone": (128, 124, 116),
}


def paint_base(size, water, wdist, rng):
    img = np.zeros((size, size, 3), dtype=np.float32)
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
    g = np.array(PAL["grass"], dtype=np.float32)
    gd = np.array(PAL["grass_dark"], dtype=np.float32)
    dr = np.array(PAL["dirt"], dtype=np.float32)
    t2 = np.clip((mix - 0.35) / 0.35, 0, 1)[..., None]
    base = g * (1 - t2) + gd * t2
    td = np.clip((dirt - 0.62) / 0.14, 0, 1)[..., None]
    base = base * (1 - td) + dr * td
    img[land] = base[land]
    blotch = fbm(size, 28, 3, rng) - 0.5
    speck = fbm(size, 170, 2, rng) - 0.5
    img[land] += ((blotch * 24 + speck * 12)[..., None])[land]

    # Flachwassersaum am Rand der Kanaele
    shore = water & (depth <= 2)
    img[shore] = img[shore] * 0.7 + np.array(PAL["shore"], dtype=np.float32) * 0.3

    # Klippen-Ufer: felsige Kante mit Licht (oben) und Schatten (unten),
    # als wuerde die Insel ein Stueck ueber dem Wasser liegen
    cliff = land & (wdist <= 2)
    img[cliff] = img[cliff] * 0.40 + np.array(PAL["cliff"], dtype=np.float32) * 0.60
    lit = cliff & np.roll(water, 1, 0)      # Wasser noerdlich -> Kante faengt Licht
    img[lit] = img[lit] * 0.45 + np.array(PAL["cliff_hi"], dtype=np.float32) * 0.55
    shadow = cliff & np.roll(water, -1, 0)  # Wasser suedlich -> Kante im Schatten
    img[shadow] *= 0.62
    # dunkle Tusche-Linie direkt an der Wasserkante
    ink_line = water & (np.roll(land, 1, 0) | np.roll(land, -1, 0)
                        | np.roll(land, 1, 1) | np.roll(land, -1, 1))
    img[ink_line] = img[ink_line] * 0.45 + np.array(PAL["bank"], dtype=np.float32) * 0.55

    # Land nahe dem Ufer leicht abdunkeln (gemalte Tiefe)
    near = land & (wdist >= 3) & (wdist <= 8)
    img[near] *= 0.90

    # Vignette: Raender abdunkeln, damit die Welt geschlossen wirkt
    ax = np.linspace(-1, 1, size, dtype=np.float32)
    r2 = ax[:, None] ** 2 + ax[None, :] ** 2
    fall = (1.0 - 0.16 * np.clip(r2 - 0.45, 0, 1))[..., None]
    img *= fall

    _ = deep
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


def draw_detail(draw, land_ok, size, rng):
    """Grasbueschel und Steinchen fuer lebendigen Boden."""
    tufts = int((size / 2048) ** 2 * 9000)
    for _ in range(tufts):
        x = int(rng.integers(size))
        y = int(rng.integers(size))
        if not land_ok[y, x]:
            continue
        c = PAL["grass_dark"] if rng.random() < 0.7 else PAL["tree_hi"]
        for dx in (-2, 0, 2):
            draw.line([(x + dx, y + 2), (x + dx * 1.5, y - 2 - int(rng.integers(2)))],
                      fill=c, width=1)
    stones = tufts // 10
    for _ in range(stones):
        x = int(rng.integers(size))
        y = int(rng.integers(size))
        if not land_ok[y, x]:
            continue
        r = 1 + int(rng.integers(2))
        draw.ellipse([x - r, y - r, x + r, y + r], fill=PAL["stone"])
        draw.ellipse([x - r, y, x + r, y + r], fill=(96, 92, 84))


def choose_pois(seeds, size, count):
    """Hauptstadt = zentralste Insel; Doerfer weit verteilt (Farthest-Point)."""
    center = np.array([size / 2, size / 2])
    capital = int(np.argmin(np.linalg.norm(seeds - center, axis=1)))
    chosen = [capital]
    for _ in range(count):
        d = np.min(
            np.linalg.norm(seeds[:, None, :] - seeds[chosen][None, :, :], axis=2),
            axis=1)
        # Rand meiden: dort liegen die Waldguertel
        margin = size * 0.1
        d[(seeds[:, 0] < margin) | (seeds[:, 0] > size - margin)
          | (seeds[:, 1] < margin) | (seeds[:, 1] > size - margin)] = -1
        chosen.append(int(np.argmax(d)))
    return capital, chosen[1:]


def draw_plaza(draw, block, x, y, r, size, rng):
    """Gepflasterter Platz mit unregelmaessigem, weichem Rand; blockt Baeume."""
    # blobbiger Umriss statt hartem Kreis: Radius je Winkel leicht variieren
    angles = np.linspace(0, 2 * math.pi, 28, endpoint=False)
    wob = 1 + (rng.random(len(angles)) - 0.5) * 0.28
    # Uebergangssaum: festgetretene Erde, in den Rasen auslaufend
    rim = [(x + math.cos(a) * r * w * 1.14, y + math.sin(a) * r * w * 1.14)
           for a, w in zip(angles, wob)]
    draw.polygon(rim, fill=PAL["dirt"])
    body = [(x + math.cos(a) * r * w, y + math.sin(a) * r * w)
            for a, w in zip(angles, wob)]
    draw.polygon(body, fill=PAL["plaza"])

    # Pflastersteine: versetzte Ringe kleiner Steine mit Farbvariation
    tones = [(150, 122, 82), (138, 110, 72), (126, 100, 66), (144, 116, 80)]
    ring_r = r - 5
    while ring_r > 3:
        n = max(6, int(2 * math.pi * ring_r / 9))
        a0 = rng.random() * math.pi
        for i in range(n):
            a = a0 + i * 2 * math.pi / n
            sx = x + math.cos(a) * ring_r + rng.normal(0, 1.2)
            sy = y + math.sin(a) * ring_r + rng.normal(0, 1.2)
            sw = 3.4 + rng.random() * 1.6
            sh = 2.6 + rng.random() * 1.4
            tone = tones[int(rng.integers(len(tones)))]
            draw.ellipse([sx - sw, sy - sh, sx + sw, sy + sh],
                         fill=tone, outline=PAL["plaza_dark"])
        ring_r -= 7
    draw.ellipse([x - 4, y - 3, x + 4, y + 3], fill=tones[0],
                 outline=PAL["plaza_dark"])

    # einzelne Grasbueschel am Rand lassen den Platz eingewachsen wirken
    for _ in range(max(6, r // 3)):
        a = rng.random() * 2 * math.pi
        rr = r * (0.95 + rng.random() * 0.25)
        gx, gy = x + math.cos(a) * rr, y + math.sin(a) * rr
        for dx in (-2, 0, 2):
            draw.line([(gx + dx, gy + 2), (gx + dx * 1.5, gy - 2)],
                      fill=PAL["grass_dark"], width=1)

    y0, y1 = max(int(y - r * 1.3), 0), min(int(y + r * 1.3), size)
    x0, x1 = max(int(x - r * 1.3), 0), min(int(x + r * 1.3), size)
    block[y0:y1, x0:x1] = True


def collect_trees(land_ok, wdist, size, rng):
    """Dichte Baumreihen an Ufern und am Kartenrand, Cluster im Inneren."""
    border = int(size * 0.022)
    # Waldcluster-Groesse ist absolut (in Pixeln), nicht relativ zur Karte
    forest_noise = fbm(size, max(4, size // 230), 3, rng)
    positions = []
    step = 9        # fest, damit die Baumdichte bei jeder Kartengroesse stimmt
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
    return positions


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

    print("[5/7] Pfade, Plaetze und Bruecken zeichnen ...")
    draw_paths(draw, seeds, bridges, labels, size)

    # Besondere Orte: Hauptstadt-Insel im Zentrum + verteilte Doerfer
    block = np.zeros((size, size), dtype=bool)
    n_villages = max(4, len(seeds) // 12)
    capital, villages = choose_pois(seeds, size, n_villages)
    spacing = size / math.sqrt(len(seeds))
    cy, cx = seeds[capital]
    draw_plaza(draw, block, int(cx), int(cy), int(spacing * 0.30), size, rng)
    for v in villages:
        vy, vx = seeds[v]
        draw_plaza(draw, block, int(vx), int(vy), int(spacing * 0.16), size, rng)

    bridge_meta = []
    for p0, p1, _w in bridges:
        meta = draw_bridge(draw, cdraw, p0, p1)
        if meta:
            bridge_meta.append(meta)

    print("[6/7] Bodendetails setzen, Baumpositionen berechnen ...")
    land_ok = ~water & (wdist >= 3) & ~block
    draw_detail(draw, land_ok, size, rng)
    # Baeume werden NICHT in die Karte gemalt: sie kommen in Unity als
    # eigene Assets mit Collider an genau diese exportierten Positionen
    trees = collect_trees(land_ok, wdist, size, rng)
    print(f"      {len(trees)} Baumpositionen")

    print("[7/7] Speichern ...")
    img.save(os.path.join(out_dir, "channel_map.png"))
    collision.save(os.path.join(out_dir, "collision.png"))
    with open(os.path.join(out_dir, "trees.json"), "w") as f:
        json.dump({"size": size,
                   "trees": [{"x": x, "y": y, "scale": round(r / 5.5, 2)}
                             for x, y, r in trees]}, f)
    with open(os.path.join(out_dir, "bridges.json"), "w") as f:
        json.dump({"size": size, "seed": seed,
                   "islands": [{"x": float(s[1]), "y": float(s[0])} for s in seeds],
                   "capital": {"x": float(cx), "y": float(cy)},
                   "villages": [{"x": float(seeds[v][1]), "y": float(seeds[v][0])}
                                for v in villages],
                   "bridges": bridge_meta}, f, indent=2)
    print(f"Fertig -> {out_dir}/channel_map.png "
          f"({len(bridge_meta)} Bruecken, 1 Hauptstadt, {len(villages)} Doerfer)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=2048)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--islands", type=int, default=42)
    ap.add_argument("--out", default="output")
    args = ap.parse_args()
    generate(args.size, args.seed, args.islands, args.out)
