#!/usr/bin/env python3
"""Malt eine GROSSE Karte kachelweise durch ComfyUI und blendet die Naehte.

Wofuer: Die Tile-Zonen (4096x4096) sind Pixel-Art. Einmal komplett durch
img2img zu schicken geht nicht — SDXL ist auf 1024 trainiert und verdoppelt
bei der Groesse die Details. Also in ueberlappenden 1024er-Kacheln malen und
mit weichem Uebergang zusammensetzen.

WICHTIG: Denoise niedrig halten (0.30-0.40). Die Karte muss deckungsgleich
mit collision.png bleiben — bei 0.5+ erfindet das Modell Mauern und Boegen,
die es in der Kollision nicht gibt (siehe docs/karten_learnings.md).

Aufruf:
    python3 tools/comfy_paint_tiles.py output/zone.png --out output/zone_painted.png \
        --prompt "hand-painted top-down fantasy RPG map, ..." --denoise 0.35
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from comfy_paint import api, build_graph, get_checkpoints, upload_image


def run_chunk(host, ckpt, path, prompt, negative, seed, steps, cfg, denoise):
    """Eine Kachel durch ComfyUI schicken und das Ergebnis zurueckgeben."""
    name = upload_image(host, path)
    graph = build_graph(ckpt, name, prompt, negative, seed, steps, cfg, denoise)
    resp = json.loads(api(host, "/prompt",
                          json.dumps({"prompt": graph,
                                      "client_id": str(uuid.uuid4())}).encode(),
                          {"Content-Type": "application/json"}))
    if "prompt_id" not in resp:
        sys.exit(f"ComfyUI hat den Auftrag abgelehnt: {resp}")
    pid = resp["prompt_id"]
    while True:
        time.sleep(1.5)
        hist = json.loads(api(host, f"/history/{pid}"))
        if pid not in hist:
            continue
        status = hist[pid].get("status", {})
        if status.get("status_str") == "error":
            msgs = [m for m in status.get("messages", [])
                    if m[0] == "execution_error"]
            sys.exit(f"ComfyUI-Fehler: {msgs[:1]}")
        if hist[pid].get("outputs"):
            break
    images = []
    for node_out in hist[pid]["outputs"].values():
        images += node_out.get("images", [])
    if not images:
        sys.exit("Kein Bild im Ergebnis.")
    im = images[0]
    data = api(host, "/view?filename=" + urllib.request.quote(im["filename"])
               + "&subfolder=" + urllib.request.quote(im.get("subfolder", ""))
               + "&type=" + im.get("type", "output"))
    tmp = path + ".result.png"
    open(tmp, "wb").write(data)
    out = np.asarray(Image.open(tmp).convert("RGB"), dtype=np.float32)
    os.remove(tmp)
    return out


def feather(h, w, overlap):
    """Gewichtsmaske: in der Mitte 1, zu den Raendern weich auslaufend."""
    def ramp(n):
        r = np.ones(n, dtype=np.float32)
        k = max(1, min(overlap, n // 2))
        edge = np.linspace(0.02, 1.0, k, dtype=np.float32)
        r[:k] = edge
        r[-k:] = edge[::-1]
        return r
    return np.outer(ramp(h), ramp(w))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--negative", default="pixel art, pixelated, blocky, "
                    "jagged edges, dithering, 8-bit, retro, mosaic, grid lines, "
                    "text, watermark, blurry, low quality, seam")
    ap.add_argument("--denoise", type=float, default=0.35)
    ap.add_argument("--steps", type=int, default=35)
    ap.add_argument("--cfg", type=float, default=7.0)
    ap.add_argument("--seed", type=int, default=777)
    ap.add_argument("--chunk", type=int, default=1024)
    ap.add_argument("--overlap", type=int, default=128)
    ap.add_argument("--checkpoint", default=None)
    ap.add_argument("--host", default="127.0.0.1:8188")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    if a.denoise > 0.45:
        print(f"WARNUNG: Denoise {a.denoise} ist hoch — das Modell erfindet "
              "Details, die nicht in der Kollision stehen.")

    try:
        ckpts = get_checkpoints(a.host)
    except (urllib.error.URLError, OSError) as e:
        sys.exit(f"ComfyUI unter http://{a.host} nicht erreichbar ({e}).")
    ckpt = a.checkpoint or ckpts[0]

    src = Image.open(a.image).convert("RGB")
    W, H = src.size
    step = a.chunk - a.overlap
    xs = list(range(0, max(1, W - a.overlap), step))
    ys = list(range(0, max(1, H - a.overlap), step))
    xs = [min(x, max(0, W - a.chunk)) for x in xs]
    ys = [min(y, max(0, H - a.chunk)) for y in ys]
    xs, ys = sorted(set(xs)), sorted(set(ys))
    total = len(xs) * len(ys)
    print(f"{W}x{H} -> {total} Kacheln a {a.chunk}px (Ueberlappung {a.overlap}), "
          f"Checkpoint {ckpt}, Denoise {a.denoise}")

    acc = np.zeros((H, W, 3), dtype=np.float32)
    wsum = np.zeros((H, W), dtype=np.float32)
    tmp = os.path.join(os.path.dirname(os.path.abspath(a.out)), "_chunk_tmp.png")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)) or ".", exist_ok=True)

    n = 0
    t0 = time.time()
    for y0 in ys:
        for x0 in xs:
            n += 1
            cw, ch = min(a.chunk, W - x0), min(a.chunk, H - y0)
            src.crop((x0, y0, x0 + cw, y0 + ch)).save(tmp)
            # Gleicher Seed fuer alle Kacheln: haelt den Stil konsistent
            painted = run_chunk(a.host, ckpt, tmp, a.prompt, a.negative,
                                a.seed, a.steps, a.cfg, a.denoise)
            painted = painted[:ch, :cw]
            m = feather(ch, cw, a.overlap)
            acc[y0:y0 + ch, x0:x0 + cw] += painted * m[..., None]
            wsum[y0:y0 + ch, x0:x0 + cw] += m
            done = time.time() - t0
            print(f"  [{n}/{total}] ({x0},{y0})  {done:.0f}s "
                  f"~{done / n * (total - n):.0f}s verbleibend")

    if os.path.exists(tmp):
        os.remove(tmp)
    out = acc / np.maximum(wsum, 1e-6)[..., None]
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(a.out)
    print(f"Fertig -> {a.out}")


if __name__ == "__main__":
    main()
