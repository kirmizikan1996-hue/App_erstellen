#!/usr/bin/env python3
"""Baut eine begehbare Zone in gemalter Optik — Boden gemalt, Sprites scharf.

Der Trick: NICHT die fertige Karte durch img2img schicken. Bei Denoise 0.35
werden Baeume zu Blobs, bei 0.45 loest der Sampler die 64-px-Sprites ganz im
Gras auf (Haeuser ueberleben, weil sie mit 160 px gross genug sind).

Deshalb getrennt:
  1. nur den ground-Layer rendern  -> kachelweise durch ComfyUI malen
  2. decoration + overlay transparent rendern
  3. Sprites unveraendert auf den gemalten Boden legen

Ergebnis: gemalter Untergrund ohne Pixel-Look, Baeume und Haeuser gestochen
scharf. Die Tilemap bleibt die Wahrheit fuer Kollision (docs/karten_learnings.md).

Aufruf:
    python3 tools/build_painted_zone.py maps/zone_hauptstadt.json \
        --out output/painted/zone_hauptstadt.png --denoise 0.45
"""
import argparse
import os
import subprocess
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
GROUND_PROMPT = (
    "hand-painted top-down fantasy RPG ground texture, lush meadow with varied "
    "grass tones and wildflowers, weathered cobblestone pavement, dirt road, "
    "sandy shore, painterly brushwork, rich saturated color, warm sunlight, "
    "high detail")


def run(cmd):
    print("  $", " ".join(os.path.basename(c) if c.endswith(".py") else c
                          for c in cmd[1:]))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit(f"Abbruch: {cmd[1]} endete mit Code {r.returncode}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("map")
    ap.add_argument("--out", required=True)
    ap.add_argument("--denoise", type=float, default=0.45)
    ap.add_argument("--seed", type=int, default=777)
    ap.add_argument("--chunk", type=int, default=1024)
    ap.add_argument("--overlap", type=int, default=128)
    ap.add_argument("--prompt", default=GROUND_PROMPT)
    ap.add_argument("--keep-temp", action="store_true")
    a = ap.parse_args()

    if a.denoise > 0.5:
        print(f"WARNUNG: Denoise {a.denoise} — ab ~0.5 erfindet das Modell "
              "Mauern und Boegen, die nicht in der Kollision stehen.")

    out_dir = os.path.dirname(os.path.abspath(a.out)) or "."
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(a.out))[0]
    g_raw = os.path.join(out_dir, f"_{base}_ground.png")
    g_pai = os.path.join(out_dir, f"_{base}_ground_painted.png")
    props = os.path.join(out_dir, f"_{base}_props.png")

    print("[1/4] Boden-Layer rendern ...")
    run([sys.executable, os.path.join(HERE, "render_tilemap.py"), a.map,
         "--layers", "ground", "--out", g_raw])

    print("[2/4] Boden kachelweise malen (dauert ein paar Minuten) ...")
    run([sys.executable, os.path.join(HERE, "comfy_paint_tiles.py"), g_raw,
         "--prompt", a.prompt, "--denoise", str(a.denoise),
         "--seed", str(a.seed), "--chunk", str(a.chunk),
         "--overlap", str(a.overlap), "--out", g_pai])

    print("[3/4] Sprite-Ebenen transparent rendern ...")
    run([sys.executable, os.path.join(HERE, "render_tilemap.py"), a.map,
         "--layers", "decoration,overlay", "--transparent", "--out", props])

    print("[4/4] Sprites auf den gemalten Boden legen ...")
    ground = Image.open(g_pai).convert("RGBA")
    sprites = Image.open(props).convert("RGBA")
    if ground.size != sprites.size:
        sys.exit(f"Groessen passen nicht: {ground.size} vs {sprites.size}")
    ground.alpha_composite(sprites)
    ground.convert("RGB").save(a.out)

    if not a.keep_temp:
        for f in (g_raw, g_pai, props):
            if os.path.exists(f):
                os.remove(f)
    print(f"Fertig -> {a.out}")


if __name__ == "__main__":
    main()
