"""Rendert eine 2D-MMORPG-Weltkarte mit Blender (bpy, headless).

3D-Terrain aus fraktalem Rauschen, stilisierte Hoehenzonen-Farben,
Sonnenlicht fuer plastische Schattierung, orthografische Top-Down-Kamera.

Aufruf:  python3 blender_map.py [--size 1536] [--seed 7] [--out output/blender_map.png]
"""

import argparse
import math
import sys

import bpy
from mathutils import Vector, noise


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                  bpy.data.cameras):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def build_terrain(seed, grid=512, extent=20.0):
    """Grid-Mesh erzeugen und per fraktalem Rauschen verformen."""
    bpy.ops.mesh.primitive_grid_add(
        x_subdivisions=grid, y_subdivisions=grid, size=extent)
    obj = bpy.context.active_object
    obj.name = "Terrain"
    me = obj.data

    offset = Vector((seed * 13.7, seed * 7.3, seed * 3.1))
    half = extent / 2
    for v in me.vertices:
        p = (v.co + offset) * 0.28
        h = noise.turbulence_vector(p, 6, False)[0]          # fraktal, [-1,1]
        # Domain-Warp fuer organischere Kuesten
        w = noise.noise(p * 0.5 + Vector((5.2, 1.3, 0)))
        h = noise.turbulence_vector(p + Vector((w, w, 0)) * 1.5, 6, False)[0]
        # Insel-Falloff: Raender unter den Meeresspiegel druecken
        d = math.hypot(v.co.x, v.co.y) / half
        h = h * 1.6 - d * d * 1.1 + 0.25
        v.co.z = max(h, -0.35) * 1.9
    me.update()

    # Glaettung fuer weichen, gemalten Look
    mod = obj.modifiers.new("Smooth", "SMOOTH")
    mod.factor = 1.2
    mod.iterations = 3
    return obj


def terrain_material():
    """Stilisierte Hoehenzonen: Sand -> Wiese -> Wald -> Fels -> Schnee."""
    mat = bpy.data.materials.new("TerrainPaint")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfDiffuse")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    noise_tex = nt.nodes.new("ShaderNodeTexNoise")
    mix = nt.nodes.new("ShaderNodeMix")

    # Hoehe (Z) -> Farbverlauf
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.83, 0.74, 0.48, 1)   # Sand
    ramp.color_ramp.elements[1].position = 1.0
    ramp.color_ramp.elements[1].color = (0.93, 0.93, 0.92, 1)   # Schnee
    for pos, col in [(0.06, (0.45, 0.62, 0.30, 1)),   # helle Wiese
                     (0.30, (0.33, 0.50, 0.24, 1)),   # sattes Gras
                     (0.52, (0.22, 0.38, 0.18, 1)),   # Wald
                     (0.70, (0.48, 0.44, 0.40, 1)),   # Fels
                     (0.88, (0.60, 0.57, 0.53, 1))]:  # heller Fels
        e = ramp.color_ramp.elements.new(pos)
        e.color = col

    map_range = nt.nodes.new("ShaderNodeMapRange")
    map_range.inputs["From Min"].default_value = 0.0
    map_range.inputs["From Max"].default_value = 2.6

    # feine Farb-Flecken ("Pinsel-Mottling") ueber das Gelaende legen
    noise_tex.inputs["Scale"].default_value = 55.0
    noise_tex.inputs["Detail"].default_value = 6.0
    mix.data_type = "RGBA"
    mix.blend_type = "OVERLAY"
    mix.inputs["Factor"].default_value = 0.16

    nt.links.new(geo.outputs["Position"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], map_range.inputs["Value"])
    nt.links.new(map_range.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], mix.inputs["A"])
    nt.links.new(noise_tex.outputs["Color"], mix.inputs["B"])
    nt.links.new(mix.outputs["Result"], bsdf.inputs["Color"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def water_material():
    mat = bpy.data.materials.new("Water")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfDiffuse")
    waves = nt.nodes.new("ShaderNodeTexNoise")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    waves.inputs["Scale"].default_value = 8.0
    waves.inputs["Detail"].default_value = 4.0
    ramp.color_ramp.elements[0].color = (0.10, 0.26, 0.42, 1)
    ramp.color_ramp.elements[1].color = (0.16, 0.36, 0.52, 1)
    nt.links.new(waves.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Color"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def scatter_trees(terrain, seed, extent=20.0, count=2600):
    """Stilisierte Baeume (Kugel-Krone) auf mittleren Wiesenhoehen verteilen."""
    import random
    rnd = random.Random(seed)

    # Vorlage: gedrungene Kugel als Krone
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.09)
    proto = bpy.context.active_object
    proto.scale = (1.0, 1.0, 0.75)
    mat = bpy.data.materials.new("TreeGreen")
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = \
        (0.13, 0.30, 0.10, 1)
    proto.data.materials.append(mat)

    # Hoehe des Terrains an (x,y) via Raycast abfragen
    deps = bpy.context.evaluated_depsgraph_get()
    placed = 0
    tries = 0
    while placed < count and tries < count * 12:
        tries += 1
        x = (rnd.random() - 0.5) * extent * 0.98
        y = (rnd.random() - 0.5) * extent * 0.98
        hit, loc, _n, _i, _o, _m = bpy.context.scene.ray_cast(
            deps, Vector((x, y, 10)), Vector((0, 0, -1)))
        if not hit:
            continue
        z = loc.z
        if not (0.35 < z < 1.15):        # nur Wiese/Wald-Zone
            continue
        # Cluster: Rauschen entscheidet, ob hier Wald ist
        if noise.noise(Vector((x * 0.35, y * 0.35, seed))) < 0.12:
            continue
        inst = proto.copy()               # verlinkte Kopie (gleiches Mesh)
        inst.location = (x, y, z + 0.05)
        s = 0.7 + rnd.random() * 0.7
        inst.scale = (s, s, s * 0.75)
        bpy.context.collection.objects.link(inst)
        placed += 1
    proto.hide_render = True
    print(f"  {placed} Baeume platziert")


def setup_scene(size, seed):
    clear_scene()
    terrain = build_terrain(seed)
    terrain.data.materials.append(terrain_material())

    # Wasserflaeche auf Meereshoehe
    bpy.ops.mesh.primitive_plane_add(size=22, location=(0, 0, 0.02))
    water = bpy.context.active_object
    water.data.materials.append(water_material())

    scatter_trees(terrain, seed)

    # Sonne: schraeg fuer plastische Schatten
    bpy.ops.object.light_add(type="SUN", location=(0, 0, 15))
    sun = bpy.context.active_object
    sun.data.energy = 4.0
    sun.data.angle = math.radians(4)
    sun.rotation_euler = (math.radians(35), 0, math.radians(120))

    # Orthografische Kamera senkrecht von oben
    bpy.ops.object.camera_add(location=(0, 0, 30), rotation=(0, 0, 0))
    cam = bpy.context.active_object
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 20.0
    bpy.context.scene.camera = cam

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 40
    scene.cycles.use_denoising = True
    scene.cycles.device = "CPU"
    scene.render.resolution_x = size
    scene.render.resolution_y = size
    scene.render.image_settings.file_format = "PNG"
    scene.world.node_tree.nodes["Background"].inputs["Color"].default_value = \
        (0.7, 0.8, 0.9, 1)
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=1536)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="output/blender_map.png")
    args = ap.parse_args(sys.argv[1:])

    print("[1/3] Szene aufbauen ...")
    setup_scene(args.size, args.seed)
    print("[2/3] Rendern (Cycles, CPU) ...")
    bpy.context.scene.render.filepath = args.out
    bpy.ops.render.render(write_still=True)
    print(f"[3/3] Fertig -> {args.out}")


if __name__ == "__main__":
    main()
