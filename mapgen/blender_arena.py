"""Feuer-Arena: runde Gladiatoren-Kampfflaeche, gerendert mit Blender/Cycles.

Aufbau (von innen nach aussen):
  - Sandige Kampfplattform mit Arena-Markierungen und Brandflecken
  - Steinerner Mauerring (einzelne Bloecke) mit Feuerschalen obendrauf
  - Gluehender Lava-Graben rund um die Plattform
  - Aeusserer Ring aus dunklem Vulkangestein mit verstreuten Felsen

Zusaetzlich entstehen collision.png und arena.json (Spawnpunkte) fuer Unity.

Aufruf:  python3 blender_arena.py --res 2048 --samples 96 --out arena/render.png
"""

import argparse
import json
import math
import os
import sys

import bpy
import numpy as np

ARENA_R = 34.0      # Radius der Sandflaeche
WALL_R = 36.5       # Mauerring
LAVA_R0 = 38.5      # Lava-Graben von ... bis
LAVA_R1 = 48.0
ROCK_R = 110.0       # aeusserer Gesteinsrand (Weltgroesse)
EXTENT = 150.0      # Kameraausschnitt


def clear():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


# ----------------------------------------------------------- materials ----

def sand_material():
    mat = bpy.data.materials.new("Sand")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 1.0

    coord = nt.nodes.new("ShaderNodeTexCoord")

    # Grundsand: warme Toene, grob gemischt
    n1 = nt.nodes.new("ShaderNodeTexNoise")
    n1.inputs["Scale"].default_value = 0.35
    n1.inputs["Detail"].default_value = 6.0
    base_mix = nt.nodes.new("ShaderNodeMix")
    base_mix.data_type = "RGBA"
    base_mix.inputs["A"].default_value = (0.44, 0.32, 0.17, 1)
    base_mix.inputs["B"].default_value = (0.58, 0.45, 0.26, 1)
    nt.links.new(coord.outputs["Object"], n1.inputs["Vector"])
    nt.links.new(n1.outputs["Fac"], base_mix.inputs["Factor"])

    # Brandflecken: dunkle verkohlte Stellen (Feuer-Thema)
    scorch = nt.nodes.new("ShaderNodeTexNoise")
    scorch.inputs["Scale"].default_value = 0.14
    scorch.inputs["Detail"].default_value = 5.0
    scorch_ramp = nt.nodes.new("ShaderNodeMapRange")
    scorch_ramp.inputs["From Min"].default_value = 0.62
    scorch_ramp.inputs["From Max"].default_value = 0.75
    nt.links.new(coord.outputs["Object"], scorch.inputs["Vector"])
    nt.links.new(scorch.outputs["Fac"], scorch_ramp.inputs["Value"])
    scorch_mix = nt.nodes.new("ShaderNodeMix")
    scorch_mix.data_type = "RGBA"
    nt.links.new(base_mix.outputs["Result"], scorch_mix.inputs["A"])
    scorch_mix.inputs["B"].default_value = (0.06, 0.045, 0.035, 1)
    nt.links.new(scorch_ramp.outputs["Result"], scorch_mix.inputs["Factor"])

    # Arena-Markierung: dunkler Mittelkreis + Aussenring im Sand
    grad = nt.nodes.new("ShaderNodeTexGradient")
    grad.gradient_type = "SPHERICAL"
    map_ = nt.nodes.new("ShaderNodeMapping")
    map_.inputs["Scale"].default_value = (1 / ARENA_R, 1 / ARENA_R, 1)
    nt.links.new(coord.outputs["Object"], map_.inputs["Vector"])
    nt.links.new(map_.outputs["Vector"], grad.inputs["Vector"])
    # grad: 1 im Zentrum -> 0 am Rand; Ringe ueber ColorRamp-Spitzen
    ring_ramp = nt.nodes.new("ShaderNodeValToRGB")
    cr = ring_ramp.color_ramp
    # Stops: (Position, Grauwert) - Rampe sortiert nach Position!
    stops = [(0.0, 1.0), (0.10, 1.0), (0.12, 0.55), (0.145, 0.55),
             (0.165, 1.0), (0.80, 1.0), (0.83, 0.55), (0.86, 0.55),
             (0.88, 1.0), (0.96, 1.0), (1.0, 0.55)]
    cr.elements[0].position = stops[0][0]
    cr.elements[1].position = stops[-1][0]
    while len(cr.elements) < len(stops):
        cr.elements.new(0.5)
    for e, (pos, val) in zip(sorted(cr.elements, key=lambda e: e.position),
                             stops):
        pass
    # Positionen/Werte robust setzen: erst alle verschieben, dann faerben
    for i, (pos, val) in enumerate(stops):
        cr.elements[i].position = pos
    for e in cr.elements:
        val = dict(stops)[min(dict(stops), key=lambda p: abs(p - e.position))]
        e.color = (val, val, val, 1)
    nt.links.new(grad.outputs["Fac"], ring_ramp.inputs["Fac"])
    ring_mul = nt.nodes.new("ShaderNodeMix")
    ring_mul.data_type = "RGBA"
    ring_mul.blend_type = "MULTIPLY"
    ring_mul.inputs["Factor"].default_value = 1.0
    nt.links.new(scorch_mix.outputs["Result"], ring_mul.inputs["A"])
    nt.links.new(ring_ramp.outputs["Color"], ring_mul.inputs["B"])

    nt.links.new(ring_mul.outputs["Result"], bsdf.inputs["Base Color"])

    # Koernung + flache Wehen im Sand
    grain = nt.nodes.new("ShaderNodeTexNoise")
    grain.inputs["Scale"].default_value = 60.0
    grain.inputs["Detail"].default_value = 10.0
    waves = nt.nodes.new("ShaderNodeTexNoise")
    waves.inputs["Scale"].default_value = 2.6
    waves.inputs["Detail"].default_value = 3.0
    add = nt.nodes.new("ShaderNodeMath")
    add.operation = "ADD"
    nt.links.new(grain.outputs["Fac"], add.inputs[0])
    nt.links.new(waves.outputs["Fac"], add.inputs[1])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.65
    nt.links.new(add.outputs["Value"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def stone_material(dark=False):
    mat = bpy.data.materials.new("Stone")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.92
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 2.2
    noise.inputs["Detail"].default_value = 12.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    if dark:
        ramp.color_ramp.elements[0].color = (0.035, 0.03, 0.028, 1)
        ramp.color_ramp.elements[1].color = (0.16, 0.135, 0.125, 1)
    else:
        ramp.color_ramp.elements[0].color = (0.12, 0.105, 0.10, 1)
        ramp.color_ramp.elements[1].color = (0.34, 0.30, 0.28, 1)
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    big = nt.nodes.new("ShaderNodeTexNoise")
    big.inputs["Scale"].default_value = 0.12
    big.inputs["Detail"].default_value = 6.0
    big_mix = nt.nodes.new("ShaderNodeMix")
    big_mix.data_type = "RGBA"
    big_mix.inputs["Factor"].default_value = 0.5
    nt.links.new(ramp.outputs["Color"], big_mix.inputs["A"])
    dark_fac = nt.nodes.new("ShaderNodeMix")
    dark_fac.data_type = "RGBA"
    nt.links.new(ramp.outputs["Color"], dark_fac.inputs["B"])
    dark_fac.inputs["A"].default_value = (0.01, 0.008, 0.008, 1)
    dark_fac.inputs["Factor"].default_value = 0.55
    nt.links.new(big.outputs["Fac"], big_mix.inputs["Factor"])
    nt.links.new(dark_fac.outputs["Result"], big_mix.inputs["B"])
    nt.links.new(big_mix.outputs["Result"], bsdf.inputs["Base Color"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.7
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def lava_material():
    """Gluehende Lava: dunkle Kruste mit hell leuchtenden Adern."""
    mat = bpy.data.materials.new("Lava")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")

    crust = nt.nodes.new("ShaderNodeBsdfPrincipled")
    crust.inputs["Base Color"].default_value = (0.05, 0.012, 0.006, 1)
    crust.inputs["Roughness"].default_value = 0.9

    emit = nt.nodes.new("ShaderNodeEmission")
    emit_ramp = nt.nodes.new("ShaderNodeValToRGB")
    emit_ramp.color_ramp.elements[0].color = (1.0, 0.08, 0.0, 1)
    emit_ramp.color_ramp.elements[1].color = (1.0, 0.55, 0.06, 1)
    emit.inputs["Strength"].default_value = 3.5

    veins = nt.nodes.new("ShaderNodeTexNoise")
    veins.inputs["Scale"].default_value = 0.15
    veins.inputs["Detail"].default_value = 4.0
    veins.inputs["Distortion"].default_value = 2.0
    coord = nt.nodes.new("ShaderNodeTexCoord")
    nt.links.new(coord.outputs["Object"], veins.inputs["Vector"])

    # Adern: schmale Bereiche des Rauschens leuchten
    vr = nt.nodes.new("ShaderNodeMapRange")
    vr.inputs["From Min"].default_value = 0.475
    vr.inputs["From Max"].default_value = 0.525
    nt.links.new(veins.outputs["Fac"], vr.inputs["Value"])
    dist = nt.nodes.new("ShaderNodeMath")
    dist.operation = "SUBTRACT"
    dist.inputs[0].default_value = 1.0
    nt.links.new(vr.outputs["Result"], dist.inputs[1])
    tri = nt.nodes.new("ShaderNodeMath")          # Dreiecksprofil der Ader
    tri.operation = "ABSOLUTE"
    sub5 = nt.nodes.new("ShaderNodeMath")
    sub5.operation = "SUBTRACT"
    nt.links.new(vr.outputs["Result"], sub5.inputs[0])
    sub5.inputs[1].default_value = 0.5
    nt.links.new(sub5.outputs["Value"], tri.inputs[0])
    inv = nt.nodes.new("ShaderNodeMapRange")
    inv.inputs["From Min"].default_value = 0.0
    inv.inputs["From Max"].default_value = 0.5
    inv.inputs["To Min"].default_value = 1.0
    inv.inputs["To Max"].default_value = 0.0
    nt.links.new(tri.outputs["Value"], inv.inputs["Value"])
    nt.links.new(inv.outputs["Result"], emit_ramp.inputs["Fac"])
    nt.links.new(emit_ramp.outputs["Color"], emit.inputs["Color"])

    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(inv.outputs["Result"], mix.inputs["Fac"])
    nt.links.new(crust.outputs["BSDF"], mix.inputs[1])
    nt.links.new(emit.outputs["Emission"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def fire_material():
    mat = bpy.data.materials.new("Fire")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (1.0, 0.42, 0.04, 1)
    emit.inputs["Strength"].default_value = 6.0
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat


# ------------------------------------------------------------ geometry ----

def build_arena():
    sand = sand_material()
    stone = stone_material()
    dark_rock = stone_material(dark=True)
    lava = lava_material()
    fire = fire_material()

    # Lava-Ebene (unterste Schicht, ueberall)
    bpy.ops.mesh.primitive_plane_add(size=EXTENT * 1.2, location=(0, 0, -1.6))
    lv = bpy.context.active_object
    lv.data.materials.append(lava)

    # Aeusserer Vulkangestein-Ring (mit Loch fuer den Lava-Graben)
    bpy.ops.mesh.primitive_cylinder_add(vertices=256, radius=ROCK_R, depth=1.2,
                                        location=(0, 0, -0.6))
    outer = bpy.context.active_object
    bpy.ops.mesh.primitive_cylinder_add(vertices=256, radius=LAVA_R1, depth=3,
                                        location=(0, 0, -0.6))
    hole = bpy.context.active_object
    boolm = outer.modifiers.new("hole", "BOOLEAN")
    boolm.object = hole
    boolm.operation = "DIFFERENCE"
    bpy.context.view_layer.objects.active = outer
    bpy.ops.object.modifier_apply(modifier="hole")
    bpy.data.objects.remove(hole)
    outer.data.materials.append(dark_rock)

    # Kampfplattform (Sand), leicht erhoeht
    bpy.ops.mesh.primitive_cylinder_add(vertices=256, radius=LAVA_R0, depth=1.6,
                                        location=(0, 0, -0.8))
    base = bpy.context.active_object
    base.data.materials.append(stone)          # Steinsockel seitlich
    bpy.ops.mesh.primitive_cylinder_add(vertices=256, radius=ARENA_R + 1.2,
                                        depth=0.25, location=(0, 0, 0.05))
    plat = bpy.context.active_object
    plat.data.materials.append(sand)

    # Mauerring aus einzelnen Steinbloecken
    rng = np.random.default_rng(3)
    n_blocks = 64
    for i in range(n_blocks):
        a = i * 2 * math.pi / n_blocks
        r = WALL_R - 1.0
        x, y = math.cos(a) * r, math.sin(a) * r
        bpy.ops.mesh.primitive_cube_add(location=(x, y, 0.9))
        blk = bpy.context.active_object
        blk.scale = (1.15, 1.9, 0.9 + rng.random() * 0.25)
        blk.rotation_euler = (rng.normal(0, 0.02), rng.normal(0, 0.02),
                              a + rng.normal(0, 0.015))
        blk.data.materials.append(stone)

    # Feuerschalen auf der Mauer (alle 8 Positionen)
    for i in range(8):
        a = i * 2 * math.pi / 8 + math.pi / 8
        r = WALL_R - 1.0
        x, y = math.cos(a) * r, math.sin(a) * r
        bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=1.05, depth=0.5,
                                            location=(x, y, 2.05))
        bowl = bpy.context.active_object
        bowl.data.materials.append(stone)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8,
                                             radius=0.72,
                                             location=(x, y, 2.45))
        flame = bpy.context.active_object
        flame.scale = (1, 1, 1.5)
        flame.data.materials.append(fire)
        # Punktlicht dazu, damit die Mauer warm angestrahlt wird
        bpy.ops.object.light_add(type="POINT", location=(x, y, 3.2))
        lamp = bpy.context.active_object
        lamp.data.energy = 300
        lamp.data.color = (1.0, 0.55, 0.15)
        lamp.data.shadow_soft_size = 0.6

    # Verstreute Felsen auf dem Aussenring
    tex = bpy.data.textures.new("rocktex", type="CLOUDS")
    tex.noise_scale = 0.45
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=0.5)
    proto = bpy.context.active_object
    mod = proto.modifiers.new("disp", "DISPLACE")
    mod.texture = tex
    mod.strength = 0.5
    bpy.ops.object.modifier_apply(modifier="disp")
    proto.data.materials.append(dark_rock)
    proto.hide_render = True
    proto.hide_set(True)
    for _ in range(260):
        a = rng.random() * 2 * math.pi
        r = LAVA_R1 + 2 + rng.random() * (EXTENT * 0.7 - LAVA_R1)
        s = 0.5 + rng.random() ** 2 * 2.2
        inst = proto.copy()
        inst.hide_render = False
        inst.scale = (s, s * (0.8 + rng.random() * 0.4), s * 0.8)
        inst.rotation_euler = (0, 0, rng.random() * 6.28)
        inst.location = (math.cos(a) * r, math.sin(a) * r, 0.1 + s * 0.2)
        bpy.context.collection.objects.link(inst)

    # Truemmer/Steinchen auf dem Sand am Rand
    for _ in range(40):
        a = rng.random() * 2 * math.pi
        r = ARENA_R * (0.75 + rng.random() * 0.2)
        s = 0.12 + rng.random() * 0.3
        inst = proto.copy()
        inst.hide_render = False
        inst.scale = (s, s, s * 0.7)
        inst.location = (math.cos(a) * r, math.sin(a) * r, 0.2)
        bpy.context.collection.objects.link(inst)


def setup_light_camera(res):
    # Abendsonne: warm und flach -> lange Schatten, dramatisch
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 60))
    sun = bpy.context.active_object
    sun.data.energy = 2.6
    sun.data.angle = math.radians(2.5)
    sun.rotation_euler = (math.radians(35), 0, math.radians(140))
    sun.data.color = (1.0, 0.88, 0.72)

    bpy.ops.object.camera_add(location=(0, 0, 100), rotation=(0, 0, 0))
    cam = bpy.context.active_object
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = EXTENT
    bpy.context.scene.camera = cam

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.use_denoising = True
    scene.render.resolution_x = res
    scene.render.resolution_y = res
    scene.render.image_settings.file_format = "PNG"
    world = scene.world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.14, 0.08, 0.06, 1)   # gluehender Dunst
    bg.inputs["Strength"].default_value = 0.3


def export_gamedata(out_dir, res):
    """Kollisionsmaske + Spawnpunkte fuer Unity."""
    from PIL import Image, ImageDraw
    img = Image.new("L", (res, res), 255)          # 255 = blockiert
    d = ImageDraw.Draw(img)
    c = res / 2
    r_sand = ARENA_R / EXTENT * res
    d.ellipse([c - r_sand, c - r_sand, c + r_sand, c + r_sand], fill=0)
    img.save(os.path.join(out_dir, "collision.png"))

    spawns = []
    for i in range(8):
        a = i * 2 * math.pi / 8
        spawns.append({"x": round(c + math.cos(a) * r_sand * 0.82, 1),
                       "y": round(c + math.sin(a) * r_sand * 0.82, 1)})
    with open(os.path.join(out_dir, "arena.json"), "w") as f:
        json.dump({"resolution": res,
                   "center": {"x": c, "y": c},
                   "sand_radius_px": round(r_sand, 1),
                   "world_extent_m": EXTENT,
                   "spawn_points": spawns}, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", type=int, default=1024)
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--out", default="arena/render.png")
    args = ap.parse_args(sys.argv[1:])
    out_dir = os.path.dirname(args.out) or "."
    os.makedirs(out_dir, exist_ok=True)

    print("[1/4] Szene bauen ...")
    clear()
    build_arena()
    print("[2/4] Licht und Kamera ...")
    setup_light_camera(args.res)
    bpy.context.scene.cycles.samples = args.samples
    print("[3/4] Rendern ...")
    bpy.context.scene.render.filepath = args.out
    bpy.ops.render.render(write_still=True)
    print("[4/4] Spieldaten exportieren ...")
    export_gamedata(out_dir, args.res)
    print(f"Fertig -> {args.out}")


if __name__ == "__main__":
    main()
