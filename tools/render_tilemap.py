#!/usr/bin/env python3
"""Rendert eine Tiled-JSON-Map mit ihrem Tileset als PNG-Vorschau.

Aufruf:
    python3 tools/render_tilemap.py maps/demo_village.json --out output/demo.png
    python3 tools/render_tilemap.py maps/demo_village.json --collision --grid
"""
import argparse
import json
import os

from PIL import Image, ImageDraw


def load_tileset(map_path, ts):
    base = os.path.dirname(os.path.abspath(map_path))
    img = Image.open(os.path.normpath(os.path.join(base, ts["image"]))).convert("RGBA")
    tiles = {}
    tw, th, cols = ts["tilewidth"], ts["tileheight"], ts["columns"]
    for i in range(ts["tilecount"]):
        r, c = divmod(i, cols)
        tiles[ts["firstgid"] + i] = img.crop(
            (c * tw, r * th, (c + 1) * tw, (r + 1) * th))
    return tiles


def render(map_path, out=None, scale=1, show_collision=False, show_grid=False,
           only=None, transparent=False):
    m = json.load(open(map_path))
    tw, th = m["tilewidth"], m["tileheight"]
    W, H = m["width"] * tw, m["height"] * th
    tiles = {}
    for ts in m["tilesets"]:
        tiles.update(load_tileset(map_path, ts))

    bg = (0, 0, 0, 0) if transparent else (0, 0, 0, 255)
    canvas = Image.new("RGBA", (W, H), bg)
    for lyr in m["layers"]:
        if lyr["type"] != "tilelayer":
            continue
        if only and lyr["name"] not in only:
            continue
        if not lyr["visible"] and not (show_collision and lyr["name"] == "collision"):
            continue
        for idx, gid in enumerate(lyr["data"]):
            if gid <= 0:
                continue
            y, x = divmod(idx, m["width"])
            if lyr["name"] == "collision":
                overlay = Image.new("RGBA", (tw, th), (220, 40, 40, 90))
                canvas.alpha_composite(overlay, (x * tw, y * th))
            else:
                canvas.alpha_composite(tiles[gid], (x * tw, y * th))

    if show_grid:
        d = ImageDraw.Draw(canvas)
        for x in range(0, W, tw):
            d.line([(x, 0), (x, H)], fill=(0, 0, 0, 60))
        for y in range(0, H, th):
            d.line([(0, y), (W, y)], fill=(0, 0, 0, 60))

    if scale != 1:
        canvas = canvas.resize((W * scale, H * scale), Image.NEAREST)

    out = out or "output/" + os.path.splitext(os.path.basename(map_path))[0] + ".png"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    canvas.save(out) if transparent else canvas.convert("RGB").save(out)
    print(f"Vorschau -> {out}")
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("map")
    p.add_argument("--out", default=None)
    p.add_argument("--scale", type=int, default=1)
    p.add_argument("--collision", action="store_true", help="Kollision rot einblenden")
    p.add_argument("--grid", action="store_true")
    p.add_argument("--layers", default=None,
                   help="nur diese Layer rendern, z.B. ground oder decoration,overlay")
    p.add_argument("--transparent", action="store_true",
                   help="Hintergrund transparent lassen (fuer Sprite-Ebenen)")
    a = p.parse_args()
    only = set(a.layers.split(",")) if a.layers else None
    render(a.map, a.out, a.scale, a.collision, a.grid, only, a.transparent)
