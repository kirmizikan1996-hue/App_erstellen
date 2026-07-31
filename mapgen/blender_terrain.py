"""Realistischer Karten-Render mit Blender (bpy, headless, Cycles).

Liest die Daten aus terrain_export.py und baut:
  - Terrain mit echter Displacement-Hoehe (Plateaus + Schluchten)
  - Prozedurale PBR-Materialien: Gras, Felswand, Erde/Weg, Pflaster
  - Granit-Felsen als 3D-Instanzen an den Kanten
  - Holzbruecken (Planken + Balken) ueber den Schluchten
  - Sonne + Himmelslicht, orthografische Top-Down-Kamera

Aufruf:  python3 blender_terrain.py --data terrain_data --res 1024 --samples 64
"""

import argparse
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

EXTENT = 100.0          # Weltgroesse in Metern
HSCALE = 9.0            # Hoehe der Plateaus ueber dem Schluchtboden


def clear():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def load_height(data_dir):
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    h = np.asarray(Image.open(os.path.join(data_dir, "height.png")),
                   dtype=np.float32) / 65535.0
    return h


def make_terrain(data_dir, h):
    """Grid-Mesh, Hoehen direkt per foreach_set (schnell und robust)."""
    n = 1024                          # Vertex-Aufloesung des Terrains
    size = h.shape[0]
    idx = (np.linspace(0, size - 1, n)).astype(int)
    hh = h[np.ix_(idx, idx)] * HSCALE

    xs = np.linspace(-EXTENT / 2, EXTENT / 2, n, dtype=np.float32)
    xv, yv = np.meshgrid(xs, -xs)     # -y damit Bild-Y nach Sued zeigt
    verts = np.column_stack([xv.ravel(), yv.ravel(),
                             hh.ravel().astype(np.float32)])

    faces = []
    for r in range(n - 1):
        base = r * n
        for c in range(n - 1):
            faces.append((base + c, base + c + 1,
                          base + n + c + 1, base + n + c))
    me = bpy.data.meshes.new("terrain")
    me.from_pydata(verts.tolist(), [], faces)
    me.update()
    # UV 0..1 ueber die ganze Flaeche fuer die Masken-Texturen
    uv = me.uv_layers.new(name="UVMap")
    co = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    co = co.reshape(-1, 3)
    loops = np.empty(len(me.loops), dtype=np.int64)
    me.loops.foreach_get("vertex_index", loops)
    u = (co[loops, 0] + EXTENT / 2) / EXTENT
    v = (co[loops, 1] + EXTENT / 2) / EXTENT
    uv_data = np.column_stack([u, v]).astype(np.float32).ravel()
    uv.data.foreach_set("uv", uv_data)

    obj = bpy.data.objects.new("Terrain", me)
    bpy.context.collection.objects.link(obj)
    obj.data.shade_smooth()
    return obj


def _img(data_dir, name):
    img = bpy.data.images.load(os.path.join(data_dir, name))
    img.colorspace_settings.name = "Non-Color"
    return img


def terrain_material(data_dir):
    mat = bpy.data.materials.new("Terrain")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.95

    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Normal"], sep.inputs["Vector"])
    sepz = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(geo.outputs["Position"], sepz.inputs["Vector"])

    # --- Gras: zwei Gruentoene, fleckig gemischt, mit Trockengras-Anteil
    n1 = nt.nodes.new("ShaderNodeTexNoise")
    n1.inputs["Scale"].default_value = 9.0
    n1.inputs["Detail"].default_value = 8.0
    grass_mix = nt.nodes.new("ShaderNodeMix")
    grass_mix.data_type = "RGBA"
    grass_mix.inputs["A"].default_value = (0.045, 0.135, 0.030, 1)
    grass_mix.inputs["B"].default_value = (0.120, 0.210, 0.055, 1)
    nt.links.new(n1.outputs["Fac"], grass_mix.inputs["Factor"])
    n2 = nt.nodes.new("ShaderNodeTexNoise")
    n2.inputs["Scale"].default_value = 320.0
    n2.inputs["Detail"].default_value = 10.0
    grass_fine = nt.nodes.new("ShaderNodeMix")
    grass_fine.data_type = "RGBA"
    grass_fine.inputs["Factor"].default_value = 0.5
    nt.links.new(grass_mix.outputs["Result"], grass_fine.inputs["A"])
    grass_fine.inputs["B"].default_value = (0.14, 0.20, 0.06, 1)
    nt.links.new(n2.outputs["Fac"], grass_fine.inputs["Factor"])

    # --- Fels: geschichtetes Grau-Braun fuer Waende
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.inputs["Scale"].default_value = 1.6
    wave.inputs["Distortion"].default_value = 6.0
    wave.bands_direction = "Z"
    rock_ramp = nt.nodes.new("ShaderNodeValToRGB")
    rock_ramp.color_ramp.elements[0].color = (0.09, 0.072, 0.058, 1)
    rock_ramp.color_ramp.elements[1].color = (0.24, 0.20, 0.16, 1)
    nt.links.new(wave.outputs["Fac"], rock_ramp.inputs["Fac"])

    # --- Erde/Weg
    dirt_col = (0.115, 0.078, 0.042, 1)
    plaza_col = (0.22, 0.18, 0.14, 1)

    # Slope: flach = Gras, steil = Fels
    slope_ramp = nt.nodes.new("ShaderNodeMapRange")
    slope_ramp.inputs["From Min"].default_value = 0.55
    slope_ramp.inputs["From Max"].default_value = 0.85
    slope_ramp.inputs["To Min"].default_value = 1.0
    slope_ramp.inputs["To Max"].default_value = 0.0
    nt.links.new(sep.outputs["Z"], slope_ramp.inputs["Value"])
    rock_over_grass = nt.nodes.new("ShaderNodeMix")
    rock_over_grass.data_type = "RGBA"
    nt.links.new(grass_fine.outputs["Result"], rock_over_grass.inputs["A"])
    nt.links.new(rock_ramp.outputs["Color"], rock_over_grass.inputs["B"])
    nt.links.new(slope_ramp.outputs["Result"], rock_over_grass.inputs["Factor"])

    # Schluchtboden: unterhalb einer Hoehe dunkler Fels/Geroell
    floor_ramp = nt.nodes.new("ShaderNodeMapRange")
    floor_ramp.inputs["From Min"].default_value = 1.2
    floor_ramp.inputs["From Max"].default_value = 2.6
    floor_ramp.inputs["To Min"].default_value = 1.0
    floor_ramp.inputs["To Max"].default_value = 0.0
    nt.links.new(sepz.outputs["Z"], floor_ramp.inputs["Value"])
    floor_mix = nt.nodes.new("ShaderNodeMix")
    floor_mix.data_type = "RGBA"
    nt.links.new(rock_over_grass.outputs["Result"], floor_mix.inputs["A"])
    floor_mix.inputs["B"].default_value = (0.012, 0.011, 0.012, 1)
    nt.links.new(floor_ramp.outputs["Result"], floor_mix.inputs["Factor"])

    # Wege und Plaetze per Maske einblenden (nur auf flachem Grund)
    uvn = nt.nodes.new("ShaderNodeTexCoord")
    tex_path = nt.nodes.new("ShaderNodeTexImage")
    tex_path.image = _img(data_dir, "path_mask.png")
    nt.links.new(uvn.outputs["UV"], tex_path.inputs["Vector"])
    path_mix = nt.nodes.new("ShaderNodeMix")
    path_mix.data_type = "RGBA"
    nt.links.new(floor_mix.outputs["Result"], path_mix.inputs["A"])
    path_mix.inputs["B"].default_value = dirt_col
    flat_ramp = nt.nodes.new("ShaderNodeMapRange")
    flat_ramp.inputs["From Min"].default_value = 0.80
    flat_ramp.inputs["From Max"].default_value = 0.93
    flat_ramp.inputs["To Min"].default_value = 0.0
    flat_ramp.inputs["To Max"].default_value = 1.0
    nt.links.new(sep.outputs["Z"], flat_ramp.inputs["Value"])
    path_gate = nt.nodes.new("ShaderNodeMath")
    path_gate.operation = "MULTIPLY"
    nt.links.new(tex_path.outputs["Color"], path_gate.inputs[0])
    nt.links.new(flat_ramp.outputs["Result"], path_gate.inputs[1])
    nt.links.new(path_gate.outputs["Value"], path_mix.inputs["Factor"])

    tex_plaza = nt.nodes.new("ShaderNodeTexImage")
    tex_plaza.image = _img(data_dir, "plaza_mask.png")
    nt.links.new(uvn.outputs["UV"], tex_plaza.inputs["Vector"])
    plaza_mix = nt.nodes.new("ShaderNodeMix")
    plaza_mix.data_type = "RGBA"
    nt.links.new(path_mix.outputs["Result"], plaza_mix.inputs["A"])
    cobble = nt.nodes.new("ShaderNodeTexVoronoi")
    cobble.inputs["Scale"].default_value = 260.0
    cobble_ramp = nt.nodes.new("ShaderNodeValToRGB")
    cobble_ramp.color_ramp.elements[0].color = (0.13, 0.11, 0.09, 1)
    cobble_ramp.color_ramp.elements[1].color = (0.26, 0.22, 0.18, 1)
    nt.links.new(uvn.outputs["UV"], cobble.inputs["Vector"])
    nt.links.new(cobble.outputs["Distance"], cobble_ramp.inputs["Fac"])
    nt.links.new(cobble_ramp.outputs["Color"], plaza_mix.inputs["B"])
    nt.links.new(tex_plaza.outputs["Color"], plaza_mix.inputs["Factor"])

    nt.links.new(plaza_mix.outputs["Result"], bsdf.inputs["Base Color"])

    # Bump: feines Rauschen + grobes Fels-Relief an Haengen
    bumpn = nt.nodes.new("ShaderNodeTexNoise")
    bumpn.inputs["Scale"].default_value = 260.0
    bumpn.inputs["Detail"].default_value = 12.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.8
    nt.links.new(bumpn.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def rock_material():
    mat = bpy.data.materials.new("Granite")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.9
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 18.0
    noise.inputs["Detail"].default_value = 12.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.10, 0.10, 0.11, 1)
    ramp.color_ramp.elements[1].color = (0.32, 0.31, 0.33, 1)
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.6
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def wood_material():
    mat = bpy.data.materials.new("Wood")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.75
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.inputs["Scale"].default_value = 6.0
    wave.inputs["Distortion"].default_value = 3.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.14, 0.075, 0.032, 1)
    ramp.color_ramp.elements[1].color = (0.28, 0.16, 0.07, 1)
    nt.links.new(wave.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def world_xy(px, py, size):
    """Pixel -> Weltkoordinaten (y gespiegelt wie beim Terrain)."""
    x = px / (size - 1) * EXTENT - EXTENT / 2
    y = -(py / (size - 1) * EXTENT - EXTENT / 2)
    return x, y


def height_at(h, px, py):
    size = h.shape[0]
    xi = int(min(max(px, 0), size - 1))
    yi = int(min(max(py, 0), size - 1))
    return h[yi, xi] * HSCALE


def add_rocks(layout, h, mat):
    """Basis-Fels einmal bauen, dann als verlinkte Kopien verteilen."""
    size = layout["size"]
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=0.5)
    proto = bpy.context.active_object
    # Fels-Form: Displace-Modifier mit Clouds-Textur
    tex = bpy.data.textures.new("rocktex", type="CLOUDS")
    tex.noise_scale = 0.45
    mod = proto.modifiers.new("disp", "DISPLACE")
    mod.texture = tex
    mod.strength = 0.45
    bpy.ops.object.modifier_apply(modifier="disp")
    proto.data.materials.append(mat)
    proto.hide_render = True
    proto.hide_set(True)

    rng = np.random.default_rng(7)
    for b in layout["boulders"]:
        x, y = world_xy(b["x"], b["y"], size)
        z = height_at(h, b["x"], b["y"])
        inst = proto.copy()               # teilt das Mesh (leichtgewichtig)
        inst.hide_render = False
        s = 0.55 * b["s"]
        inst.scale = (s * (0.8 + rng.random() * 0.6),
                      s * (0.8 + rng.random() * 0.6),
                      s * (0.7 + rng.random() * 0.5))
        inst.rotation_euler = (0, 0, rng.random() * 6.28)
        inst.location = (x, y, z + s * 0.25)
        bpy.context.collection.objects.link(inst)


def add_bridges(layout, h, mat):
    """Holzbruecken: Planken-Deck + Laengsbalken + Gelaender."""
    size = layout["size"]
    deck_w = 1.6
    for b in layout["bridges"]:
        x0, y0 = world_xy(b["x0"], b["y0"], size)
        x1, y1 = world_xy(b["x1"], b["y1"], size)
        z0 = height_at(h, b["x0"], b["y0"])
        z1 = height_at(h, b["x1"], b["y1"])
        z = max(z0, z1) + 0.05
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy)
        if ln < 0.5:
            continue
        ang = math.atan2(dy, dx)
        cx_, cy_ = (x0 + x1) / 2, (y0 + y1) / 2

        # Deck aus einzelnen Planken
        n_planks = max(int(ln / 0.42), 3)
        for i in range(n_planks):
            t = (i + 0.5) / n_planks
            px = x0 + dx * t
            py = y0 + dy * t
            bpy.ops.mesh.primitive_cube_add(location=(px, py, z))
            p = bpy.context.active_object
            p.scale = (0.18, deck_w / 2, 0.035)
            p.rotation_euler = (0, 0, ang)
            p.data.materials.append(mat)
        # zwei Laengsbalken darunter + Gelaender darueber
        for off, dz, sy in ((deck_w / 2 - 0.1, -0.09, 0.09),
                            (-deck_w / 2 + 0.1, -0.09, 0.09),
                            (deck_w / 2, 0.35, 0.04),
                            (-deck_w / 2, 0.35, 0.04)):
            ox = -math.sin(ang) * off
            oy = math.cos(ang) * off
            bpy.ops.mesh.primitive_cube_add(
                location=(cx_ + ox, cy_ + oy, z + dz))
            r = bpy.context.active_object
            r.scale = (ln / 2 + 0.3, sy, 0.05 if dz < 0 else 0.03)
            r.rotation_euler = (0, 0, ang)
            r.data.materials.append(mat)


def add_water():
    """Wasserflaeche am Schluchtboden: aus den Schluchten werden Fluesse."""
    bpy.ops.mesh.primitive_plane_add(size=EXTENT * 1.02, location=(0, 0, 1.35))
    plane = bpy.context.active_object
    mat = bpy.data.materials.new("Water")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.020, 0.075, 0.110, 1)
    bsdf.inputs["Roughness"].default_value = 0.08
    bsdf.inputs["Metallic"].default_value = 0.15
    ripple = nt.nodes.new("ShaderNodeTexNoise")
    ripple.inputs["Scale"].default_value = 55.0
    ripple.inputs["Detail"].default_value = 8.0
    ripple.inputs["Distortion"].default_value = 0.6
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.25
    nt.links.new(ripple.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    plane.data.materials.append(mat)


def tree_material():
    mat = bpy.data.materials.new("Tree")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Roughness"].default_value = 0.9
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = 14.0
    n.inputs["Detail"].default_value = 6.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.018, 0.075, 0.020, 1)
    ramp.color_ramp.elements[1].color = (0.060, 0.160, 0.045, 1)
    nt.links.new(n.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.9
    nt.links.new(n.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def add_trees(layout, h, mat, max_trees=550, min_dist=2.0):
    """Weniger, dafuer schoenere Baeume: mehrlappige Kronen (Haupt-Kugel +
    2 Nebenlappen), starke Groessenvariation, Mindestabstand — so bleiben
    die Sonnenschatten der einzelnen Baeume sichtbar."""
    size = layout["size"]
    trees = layout.get("trees", [])
    rng = np.random.default_rng(1)
    rng.shuffle(trees)
    # Ausduennen mit Mindestabstand (Weltkoordinaten)
    kept, cells = [], set()
    for t in trees:
        x, y = world_xy(t["x"], t["y"], size)
        key = (int(x / min_dist), int(y / min_dist))
        if key in cells:
            continue
        cells.add(key)
        kept.append((t, x, y))
        if len(kept) >= max_trees:
            break

    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1.0)
    proto = bpy.context.active_object
    for v in proto.data.vertices:
        d = 1.0 + 0.20 * math.sin(v.co.x * 7.3) * math.cos(v.co.y * 5.1) \
            + 0.14 * math.sin(v.co.z * 9.7)
        v.co *= d
    proto.data.materials.append(mat)
    rng = np.random.default_rng(2)
    for t, x, y in kept:
        z = height_at(h, t["x"], t["y"])
        s = 0.62 * t.get("scale", 1.0) * (0.7 + rng.random() * 0.9)
        # Hauptkrone + 2 kleinere Lappen -> organische Silhouette
        lobes = [(0.0, 0.0, 1.0)]
        for _ in range(2):
            ang = rng.random() * 6.28
            lobes.append((math.cos(ang) * s * 0.55,
                          math.sin(ang) * s * 0.55,
                          0.55 + rng.random() * 0.25))
        for ox, oy, ls in lobes:
            obj = proto.copy()
            obj.location = (x + ox, y + oy, z + s * ls * 0.6)
            obj.scale = (s * ls, s * ls, s * ls * 0.75)
            obj.rotation_euler = (0, 0, rng.random() * 6.28)
            bpy.context.collection.objects.link(obj)
    proto.hide_render = True
    proto.hide_viewport = True


ROOF_OFFSET = math.pi / 4  # Kegel-Basisvertices liegen auf den Achsen,
                           # Wuerfel-Ecken bei 45 Grad -> Dach passend drehen


def add_houses(layout, h):
    """Einfache Haeuser (Kubus + Pyramidendach) rings um Hauptstadt- und
    Dorfplaetze — aus der Top-Down-Sicht tragen vor allem die Daecher."""
    size = layout["size"]
    wall_mat = bpy.data.materials.new("Wall")
    wall_mat.use_nodes = True
    wall_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"] \
        .default_value = (0.62, 0.55, 0.44, 1)
    roof_mat = bpy.data.materials.new("Roof")
    roof_mat.use_nodes = True
    rb = roof_mat.node_tree.nodes["Principled BSDF"]
    rb.inputs["Base Color"].default_value = (0.28, 0.075, 0.05, 1)
    rb.inputs["Roughness"].default_value = 0.85

    rng = np.random.default_rng(5)
    spots = [(layout["capital"], 2.6, 9, 1.7)] + \
            [(v, 1.6, 5, 1.35) for v in layout["villages"]]
    for center, ring_r, count, s in spots:
        for i in range(count):
            ang = i * 2 * math.pi / count + rng.normal(0, 0.15)
            px = center["x"] + math.cos(ang) * ring_r * size / EXTENT
            py = center["y"] + math.sin(ang) * ring_r * size / EXTENT
            x, y = world_xy(px, py, size)
            z = height_at(h, px, py)
            rot = ang + math.pi / 2 + rng.normal(0, 0.2)
            wh = 0.34 * s
            half = 0.38 * s
            bpy.ops.mesh.primitive_cube_add(
                location=(x, y, z + wh / 2))
            wall = bpy.context.active_object
            wall.scale = (half, half, wh / 2)
            wall.rotation_euler = (0, 0, rot)
            wall.data.materials.append(wall_mat)
            bpy.ops.mesh.primitive_cone_add(
                vertices=4, radius1=half * 1.5, depth=0.30 * s,
                location=(x, y, z + wh + 0.15 * s))
            roof = bpy.context.active_object
            roof.rotation_euler = (0, 0, rot + ROOF_OFFSET)
            roof.data.materials.append(roof_mat)


def setup_light_camera(res):
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 60))
    sun = bpy.context.active_object
    sun.data.energy = 6.5
    sun.data.angle = math.radians(1.6)
    sun.rotation_euler = (math.radians(34), 0, math.radians(130))
    sun.data.color = (1.0, 0.96, 0.88)

    bpy.ops.object.camera_add(location=(0, 0, 80), rotation=(0, 0, 0))
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
    bg.inputs["Color"].default_value = (0.50, 0.62, 0.80, 1)
    bg.inputs["Strength"].default_value = 0.65
    scene.view_settings.look = "AgX - Punchy"
    scene.view_settings.exposure = 0.35


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="terrain_data")
    ap.add_argument("--res", type=int, default=1024)
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--out", default="terrain_data/render.png")
    args = ap.parse_args(sys.argv[1:])

    print("[1/5] Daten laden ...")
    h = load_height(args.data)
    layout = json.load(open(os.path.join(args.data, "layout.json")))

    print("[2/5] Terrain bauen ...")
    clear()
    terrain = make_terrain(args.data, h)
    terrain.data.materials.append(terrain_material(args.data))

    print("[3/5] Felsen, Bruecken, Wasser, Baeume ...")
    add_rocks(layout, h, rock_material())
    add_bridges(layout, h, wood_material())
    add_water()
    add_trees(layout, h, tree_material())
    add_houses(layout, h)

    print("[4/5] Licht und Kamera ...")
    setup_light_camera(args.res)
    bpy.context.scene.cycles.samples = args.samples

    print("[5/5] Rendern ...")
    bpy.context.scene.render.filepath = args.out
    bpy.ops.render.render(write_still=True)
    print(f"Fertig -> {args.out}")


if __name__ == "__main__":
    main()
