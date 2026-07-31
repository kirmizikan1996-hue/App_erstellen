#!/usr/bin/env python3
"""Steuert ein lokal laufendes ComfyUI (z.B. auf einer RTX 4090) per API und
malt eine Layout-Karte im img2img-Verfahren um — der vollautomatische Loop
für Claude Code auf dem lokalen Rechner.

Voraussetzung: ComfyUI laeuft (Standard: http://127.0.0.1:8188) und hat
mindestens einen SDXL-Checkpoint in models/checkpoints.

Aufruf (Beispiel):
    python3 tools/comfy_paint.py mapgen/zone_neu/render_final.png \
        --prompt "hand-painted fantasy MMORPG world map, ..." \
        --denoise 0.55 --out output/painted/zone_comfy_v1.png

Nuetzlich:
    --list-checkpoints   zeigt die installierten Modelle und beendet sich
    --checkpoint NAME    bestimmtes Modell verwenden (sonst: erstes)
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid


def api(host, path, data=None, headers=None):
    req = urllib.request.Request(f"http://{host}{path}", data=data,
                                 headers=headers or {})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def get_checkpoints(host):
    info = json.loads(api(host, "/object_info/CheckpointLoaderSimple"))
    return info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]


def upload_image(host, path):
    boundary = "----claudecomfy"
    name = os.path.basename(path)
    body = (f"--{boundary}\r\nContent-Disposition: form-data; "
            f"name=\"overwrite\"\r\n\r\ntrue\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
            f"filename=\"{name}\"\r\nContent-Type: image/png\r\n\r\n").encode()
    body += open(path, "rb").read() + f"\r\n--{boundary}--\r\n".encode()
    resp = json.loads(api(host, "/upload/image", body,
                          {"Content-Type":
                           f"multipart/form-data; boundary={boundary}"}))
    return resp["name"]


def build_graph(ckpt, image_name, prompt, negative, seed, steps, cfg, denoise):
    return {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "3": {"class_type": "VAEEncode",
              "inputs": {"pixels": ["2", 0], "vae": ["1", 2]}},
        "4": {"class_type": "CLIPTextEncode",
              "inputs": {"text": prompt, "clip": ["1", 1]}},
        "5": {"class_type": "CLIPTextEncode",
              "inputs": {"text": negative, "clip": ["1", 1]}},
        "6": {"class_type": "KSampler",
              "inputs": {"model": ["1", 0], "positive": ["4", 0],
                         "negative": ["5", 0], "latent_image": ["3", 0],
                         "seed": seed, "steps": steps, "cfg": cfg,
                         "sampler_name": "dpmpp_2m", "scheduler": "karras",
                         "denoise": denoise}},
        "7": {"class_type": "VAEDecode",
              "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveImage",
              "inputs": {"images": ["7", 0],
                         "filename_prefix": "claude_map"}},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image", nargs="?")
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--negative", default="pixel art, cartoon, childish, "
                    "blurry, text, watermark, grid lines, ugly, low quality, "
                    "photo, plastic, clay")
    ap.add_argument("--denoise", type=float, default=0.55)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--cfg", type=float, default=6.5)
    ap.add_argument("--seed", type=int, default=-1)
    ap.add_argument("--checkpoint", default=None)
    ap.add_argument("--host", default="127.0.0.1:8188")
    ap.add_argument("--out", default=None)
    ap.add_argument("--list-checkpoints", action="store_true")
    a = ap.parse_args()

    try:
        ckpts = get_checkpoints(a.host)
    except (urllib.error.URLError, OSError) as e:
        sys.exit(f"ComfyUI unter http://{a.host} nicht erreichbar ({e}). "
                 "Laeuft ComfyUI?")
    if a.list_checkpoints:
        print("\n".join(ckpts))
        return
    if not a.image or not a.prompt:
        sys.exit("Bild und --prompt sind erforderlich (oder --list-checkpoints).")

    ckpt = a.checkpoint or ckpts[0]
    print(f"Checkpoint: {ckpt}")
    image_name = upload_image(a.host, a.image)
    print(f"Bild hochgeladen: {image_name}")

    seed = a.seed if a.seed >= 0 else int.from_bytes(os.urandom(4), "big")
    graph = build_graph(ckpt, image_name, a.prompt, a.negative,
                        seed, a.steps, a.cfg, a.denoise)
    client = str(uuid.uuid4())
    resp = json.loads(api(a.host, "/prompt",
                          json.dumps({"prompt": graph,
                                      "client_id": client}).encode(),
                          {"Content-Type": "application/json"}))
    if "prompt_id" not in resp:
        sys.exit(f"ComfyUI hat den Auftrag abgelehnt: {resp}")
    pid = resp["prompt_id"]
    print(f"Auftrag {pid} laeuft (Seed {seed}) ...")

    while True:
        time.sleep(2)
        hist = json.loads(api(a.host, f"/history/{pid}"))
        if pid in hist:
            entry = hist[pid]
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages", [])
                        if m[0] == "execution_error"]
                sys.exit(f"ComfyUI-Fehler: {msgs[:1]}")
            if entry.get("outputs"):
                break

    images = []
    for node_out in hist[pid]["outputs"].values():
        images += node_out.get("images", [])
    if not images:
        sys.exit("Kein Bild im Ergebnis gefunden.")
    img = images[0]
    data = api(a.host, "/view?filename=" + urllib.request.quote(img["filename"])
               + "&subfolder=" + urllib.request.quote(img.get("subfolder", ""))
               + "&type=" + img.get("type", "output"))
    out = a.out or "output/painted/" + os.path.splitext(
        os.path.basename(a.image))[0] + "_painted.png"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    open(out, "wb").write(data)
    print(f"Gemalte Karte -> {out}")


if __name__ == "__main__":
    main()
