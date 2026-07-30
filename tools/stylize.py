#!/usr/bin/env python3
"""Stilisiert eine Layout-/Blockout-Karte zu einem gemalten (painterly) Bild
per KI-Bildgenerator — die Brücke von "Struktur aus Code" zu "AAA-Optik".

Workflow:
  1. tools/worldgen.py oder render_tilemap.py erzeugt das Layout-PNG
     (Struktur: wo ist Wasser, Wald, Stadt — und die Kollisionsdaten)
  2. Dieses Skript schickt Layout + Prompt an einen Bildgenerator (img2img):
     Die KI übermalt die Struktur im gewünschten Stil, Geometrie bleibt erhalten
  3. Claude betrachtet das Ergebnis und iteriert (Prompt/Strength anpassen)

Provider (Auswahl über --provider oder automatisch nach vorhandenem API-Key):
  replicate  ->  env REPLICATE_API_TOKEN   (Flux dev, ~3 Cent/Bild)
  openai     ->  env OPENAI_API_KEY        (gpt-image-1)

Aufruf:
    python3 tools/stylize.py output/world_42.png \
        --prompt "hand-painted fantasy MMORPG world map, lush detailed \
terrain, soft light, rich colors, game art, top-down" \
        --strength 0.55 --out output/world_42_painted.png
"""
import argparse
import base64
import json
import mimetypes
import os
import sys
import time
import urllib.request


def _req(url, data=None, headers=None, method=None):
    r = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(r, timeout=300) as resp:
        return resp.read()


def data_uri(path):
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()


# ---------------------------------------------------------------- Replicate

def replicate_img2img(image_path, prompt, strength, out):
    token = os.environ["REPLICATE_API_TOKEN"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
               "Prefer": "wait=60"}
    body = {"input": {
        "prompt": prompt,
        "image": data_uri(image_path),
        "prompt_strength": strength,     # 0 = Layout pur, 1 = ignoriert Layout
        "num_inference_steps": 40,
        "guidance": 3.5,
        "output_format": "png",
    }}
    resp = json.loads(_req(
        "https://api.replicate.com/v1/models/black-forest-labs/flux-dev/predictions",
        json.dumps(body).encode(), headers))
    # Pollen bis fertig
    while resp["status"] not in ("succeeded", "failed", "canceled"):
        time.sleep(3)
        resp = json.loads(_req(resp["urls"]["get"], headers={
            "Authorization": f"Bearer {token}"}))
    if resp["status"] != "succeeded":
        sys.exit(f"Replicate-Fehler: {resp.get('error')}")
    url = resp["output"][0] if isinstance(resp["output"], list) else resp["output"]
    open(out, "wb").write(_req(url))


# ---------------------------------------------------------------- OpenAI

def openai_img2img(image_path, prompt, strength, out):
    key = os.environ["OPENAI_API_KEY"]
    boundary = "----claudemap"
    img = open(image_path, "rb").read()
    fields = {"model": "gpt-image-1", "prompt": prompt, "size": "1536x1024",
              "input_fidelity": "high" if strength < 0.5 else "low"}
    parts = b""
    for k, v in fields.items():
        parts += (f"--{boundary}\r\nContent-Disposition: form-data; "
                  f"name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    parts += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
              f"filename=\"map.png\"\r\nContent-Type: image/png\r\n\r\n").encode()
    parts += img + f"\r\n--{boundary}--\r\n".encode()
    resp = json.loads(_req(
        "https://api.openai.com/v1/images/edits", parts,
        {"Authorization": f"Bearer {key}",
         "Content-Type": f"multipart/form-data; boundary={boundary}"}))
    open(out, "wb").write(base64.b64decode(resp["data"][0]["b64_json"]))


# ---------------------------------------------------------------- Main

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("image", help="Layout-PNG (z.B. von worldgen/render_tilemap)")
    p.add_argument("--prompt", required=True)
    p.add_argument("--strength", type=float, default=0.55,
                   help="wie stark die KI übermalen darf (0.3=nah am Layout, 0.8=frei)")
    p.add_argument("--provider", choices=["replicate", "openai"], default=None)
    p.add_argument("--out", default=None)
    a = p.parse_args()

    provider = a.provider
    if provider is None:
        if os.environ.get("REPLICATE_API_TOKEN"):
            provider = "replicate"
        elif os.environ.get("OPENAI_API_KEY"):
            provider = "openai"
        else:
            sys.exit("Kein API-Key gefunden. Setze REPLICATE_API_TOKEN oder "
                     "OPENAI_API_KEY (siehe README, Abschnitt 'Gemalter Look').")

    out = a.out or a.image.replace(".png", "_painted.png")
    {"replicate": replicate_img2img, "openai": openai_img2img}[provider](
        a.image, a.prompt, a.strength, out)
    print(f"Gemalte Karte -> {out}")


if __name__ == "__main__":
    main()
