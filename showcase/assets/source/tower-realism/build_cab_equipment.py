"""Original tower desk equipment, generated through Blender MCP.

Run with Blender's Python, or execute this file through Blender MCP. The script
creates a new scene and never clears or overwrites the user's existing scene.
Coordinates supplied to helpers are Three.js coordinates: X right, Y up, -Z
toward the windows. The glTF export is Y-up, metres, with no placement transform.
"""

from pathlib import Path
import math
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "candidates/assets/tower-realism"
OUT.mkdir(parents=True, exist_ok=True)
previous_scene = bpy.context.scene
scene = bpy.data.scenes.new("UITA Tower Equipment")
bpy.context.window.scene = scene
collection = bpy.data.collections.new("UITA Original Cab Equipment")
scene.collection.children.link(collection)
scene.unit_settings.scale_length = 1.0
objects = []


def coord(p):
    return (p[0], -p[2], p[1])


def material(name, color, roughness, metalness=0, emission=0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    shader = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Roughness"].default_value = roughness
    shader.inputs["Metallic"].default_value = metalness
    if emission:
        shader.inputs["Emission Color"].default_value = (*color, 1)
        shader.inputs["Emission Strength"].default_value = emission
    mat.diffuse_color = (*color, 1)
    return mat


rubber = material("Cab - soft black elastomer", (.017, .023, .026), .91)
body = material("Cab - graphite powder coat", (.055, .072, .077), .67, .28)
metal = material("Cab - brushed aluminium", (.29, .34, .36), .33, .83)
keys = material("Cab - off white keys", (.58, .62, .6), .61)
paper = material("Cab - ivory strip paper", (.76, .75, .65), .95)
ink = material("Cab - printed markings", (.12, .15, .15), .98)
screen = material("Cab - instrument black glass", (.006, .027, .027), .22, .12)
green = material("Cab - phosphor green", (.18, .68, .41), .38, emission=.7)
amber = material("Cab - amber indicator", (.9, .33, .035), .4, emission=.8)
blue = material("Cab - blue strip holder", (.05, .22, .31), .63)


def mesh(name, vertices, faces, mat):
    data = bpy.data.meshes.new(name)
    data.from_pydata([coord(v) for v in vertices], [], faces)
    data.update()
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.data.materials.append(mat)
    objects.append(obj)
    return obj


def box(name, center, size, mat, bevel=0):
    x, y, z = center
    w, h, d = (s / 2 for s in size)
    obj = mesh(name, [
        (x-w, y-h, z-d), (x+w, y-h, z-d), (x+w, y+h, z-d), (x-w, y+h, z-d),
        (x-w, y-h, z+d), (x+w, y-h, z+d), (x+w, y+h, z+d), (x-w, y+h, z+d),
    ], [(0,3,2,1), (4,5,6,7), (0,1,5,4), (1,2,6,5), (2,3,7,6), (3,0,4,7)], mat)
    if bevel:
        bevel_type = next(i.identifier for i in bpy.types.Modifier.bl_rna.properties["type"].enum_items if i.identifier == "BEVEL")
        mod = obj.modifiers.new("Machined edge radii", bevel_type)
        mod.width = bevel
        mod.segments = 3
    return obj


def tube(name, points, radius, mat, segments=10, closed=False):
    pts = [Vector(p) for p in points]
    vertices, faces = [], []
    for i, p in enumerate(pts):
        tangent = (pts[(i+1) % len(pts)] - pts[i-1]) if closed else (pts[min(i+1, len(pts)-1)] - pts[max(0,i-1)])
        tangent.normalize()
        reference = Vector((0,1,0)) if abs(tangent.y) < .95 else Vector((1,0,0))
        a = tangent.cross(reference).normalized()
        b = tangent.cross(a).normalized()
        for j in range(segments):
            v = p + radius * (math.cos(j*math.tau/segments)*a + math.sin(j*math.tau/segments)*b)
            vertices.append(tuple(v))
    ring_count = len(pts) if closed else len(pts)-1
    for i in range(ring_count):
        for j in range(segments):
            ni = (i+1) % len(pts)
            faces.append((i*segments+j, i*segments+(j+1)%segments, ni*segments+(j+1)%segments, ni*segments+j))
    if not closed:
        faces += [tuple(range(segments-1,-1,-1)), tuple((len(pts)-1)*segments+j for j in range(segments))]
    obj = mesh(name, vertices, faces, mat)
    for p in obj.data.polygons:
        p.use_smooth = True
    return obj


def cylinder(name, center, radius, height, mat, segments=24):
    x, y, z = center
    return tube(name, [(x,y-height/2,z),(x,y+height/2,z)], radius, mat, segments)


def text(name, value, pos, size, mat):
    data = bpy.data.curves.new(name, type="FONT")
    data.body = value
    data.size = size
    data.extrude = 0
    data.resolution_u = 2
    obj = bpy.data.objects.new(name, data)
    collection.objects.link(obj)
    obj.location = coord(pos)
    # Native Blender text lies on XY. This corresponds to a horizontal desk label.
    obj.data.materials.append(mat)
    objects.append(obj)
    return obj


# Left communications panel: visible at the edge of the ground radar display.
box("Comms instrument housing", (-1.23,.81,-.91), (.49,.08,.36), body, .012)
box("Recessed faceplate", (-1.23,.853,-.91), (.46,.009,.33), metal, .004)
box("Display gasket", (-1.27,.861,-.98), (.32,.009,.12), rubber, .004)
box("Display lens", (-1.27,.867,-.98), (.302,.005,.101), screen, .002)
text("Panel display legend", "LOCAL / MONITOR", (-1.405,.871,-.982), .017, green)
text("Panel display secondary", "COM 1   COM 2", (-1.4,.871,-.947), .012, keys)
for i in range(4):
    x = -1.39+i*.09
    box("Comms square switch", (x,.867,-.852), (.064,.017,.048), keys if i<3 else blue, .004)
    text("Switch legend", ["COM","APP","GND","PTT"][i], (x-.023,.877,-.849), .010, ink if i<3 else paper)
    cylinder("Indicator lens", (x,.861,-.811), .004,.002, green if i==0 else screen, 12)
for x in [-1.445,-1.015]:
    for z in [-1.055,-.765]:
        cylinder("Captive faceplate screw", (x,.86,z), .0045,.003, metal, 12)
        box("Screw slot", (x,.862,z), (.005,.001,.001), rubber)
for z in [-1.009,-.918]:
    cylinder("Encoder skirt", (-1.055,.865,z), .025,.008, rubber)
    cylinder("Knurled volume dial", (-1.055,.879,z), .02,.025, body)
    for j in range(18):
        a = math.tau*j/18
        cylinder("Dial knurl", (-1.055+math.cos(a)*.020,.88,z+math.sin(a)*.020), .0015,.020, metal, 6)
    box("Dial index", (-1.055,.893,z-.010), (.002,.001,.012), keys)
for row in range(4):
    for col in range(12):
        cylinder("Speaker grille perforation", (-1.437+col*.008,.861,-.795+row*.008), .0016,.001, rubber, 6)

# Gooseneck microphone: no large opaque object in the runway sightline.
box("Microphone weighted foot", (-.84,.79,-.69), (.105,.036,.115), body, .014)
box("Microphone talk key", (-.84,.813,-.66), (.048,.012,.024), rubber, .004)
stem = [(-.84,.81,-.72),(-.84,.9,-.73),(-.83,1.015,-.70),(-.80,1.10,-.65),(-.77,1.13,-.59)]
tube("Flexible microphone stem", stem, .006, rubber, 12)
tube("Microphone steel neck", stem[-2:], .0065, metal, 12)
tube("Microphone windscreen", [(-.77,1.13,-.59),(-.74,1.14,-.54)], .016, rubber, 20)

# A lightweight headset rests on the left front corner, with a curled lead.
headset = [(-1.24+math.cos(a)*.105,.805+math.sin(a)*.012,-.48+math.sin(a)*.105) for a in [i*math.pi/30 for i in range(31)]]
tube("Headset spring band", headset, .007, metal, 10)
tube("Headset padded band", headset[5:26], .013, rubber, 12)
for x in [-1.345,-1.135]:
    box("Headset ear capsule", (x,.808,-.48), (.047,.048,.071), body, .019)
    box("Headset soft ear cushion", (x,.837,-.48), (.042,.018,.064), rubber, .011)
tube("Headset boom", [(-1.345,.812,-.48),(-1.37,.80,-.42),(-1.34,.795,-.36),(-1.30,.795,-.345)], .003, metal, 8)
tube("Headset voice capsule", [(-1.30,.795,-.345),(-1.275,.795,-.345)], .007, rubber, 12)
coil=[]
for i in range(240):
    t=i/239
    coil.append((-1.13+.18*t,.784+.007*math.sin(t*math.tau*18),-.48-.15*t+.007*math.cos(t*math.tau*18)))
tube("Coiled headset lead", coil, .0018, rubber, 6)
tube("Headset lead tail", [coil[-1],(-.94,.785,-.69),(-1.02,.786,-.75)], .002, rubber, 8)

# Right side flight strip rack. Blank ruled papers are props, never flight data.
box("Strip rack base", (1.41,.785,-.86), (.43,.025,.52), body, .008)
for x in [1.195,1.625]:
    box("Strip rack rail", (x,.809,-.86), (.018,.035,.52), metal, .004)
for k in range(7):
    z=-1.075+k*.068
    box("Flight strip holder", (1.41,.81,z), (.397,.015,.061), blue if k%3 else body, .002)
    box("Blank ruled flight strip", (1.405,.819,z), (.363,.001,.049), paper, .0004)
    for dx in [-.108,.05,.115]:
        box("Strip printed rule", (1.405+dx,.8198,z), (.0005,.0004,.041), ink)
    box("Strip printed rule", (1.405,.8198,z+.005), (.355,.0004,.0005), ink)
text("Rack equipment legend", "FLIGHT STRIPS", (1.23,.825,-.607), .014, keys)

# Tactile details on the front desk edge, plus a slim pencil and cable clips.
for x in [-1.48,-1.00,1.21,1.62]:
    box("Desk cable clip", (x,.775,-1.305), (.025,.008,.023), rubber, .003)
tube("Desk pencil", [(1.16,.779,-.50),(1.29,.779,-.42)], .003, keys, 8)
tube("Desk pencil point", [(1.29,.779,-.42),(1.305,.779,-.411)], .0015, ink, 8)

# Apply bevels and collapse by material: one GLB draw call per material.
bpy.ops.object.select_all(action="DESELECT")
for obj in list(objects):
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if obj.type == "FONT":
        bpy.ops.object.convert(target="MESH")
        obj = bpy.context.view_layer.objects.active
    for modifier in list(obj.modifiers):
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    obj.select_set(False)
for mat in [rubber,body,metal,keys,paper,ink,screen,green,amber,blue]:
    meshes = [obj for obj in collection.objects if obj.type == "MESH"]
    group=[obj for obj in meshes if len(obj.data.materials) and obj.data.materials[0] == mat]
    if not group:
        continue
    bpy.ops.object.select_all(action="DESELECT")
    for obj in group:
        obj.select_set(True)
    bpy.context.view_layer.objects.active=group[0]
    bpy.ops.object.join()
    group[0].name=mat.name

bpy.ops.object.select_all(action="DESELECT")
for obj in collection.objects:
    obj.select_set(True)

# GLB was verified against this exporter's dynamic enum choices through MCP.
bpy.ops.export_scene.gltf(filepath=str(OUT / "cab-equipment.glb"), export_format="GLB", use_selection=True, use_active_scene=True, export_yup=True)

# Preview helpers remain in the dedicated scene, and are excluded from the GLB.
world = bpy.data.worlds.new("Cab equipment preview world")
world.use_nodes=True
bg=next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs[0].default_value=(.34,.39,.42,1)
bg.inputs[1].default_value=.25
scene.world=world
area_type=next(i.identifier for i in bpy.types.Light.bl_rna.properties["type"].enum_items if i.identifier=="AREA")
for name, position, power, size in [("Preview softbox",(0,1.5,3),90,4),("Preview rim",(-2,0,1.5),45,2)]:
    data=bpy.data.lights.new(name,area_type)
    data.energy=power
    data.shape=next(i.identifier for i in bpy.types.AreaLight.bl_rna.properties["shape"].enum_items if i.identifier=="DISK")
    data.size=size
    obj=bpy.data.objects.new(name,data)
    scene.collection.objects.link(obj)
    obj.location=position
    obj.rotation_euler=(Vector((0,.75,.8))-obj.location).to_track_quat('-Z','Y').to_euler()
camera_data=bpy.data.cameras.new("Equipment preview camera")
camera=bpy.data.objects.new("Equipment preview camera",camera_data)
scene.collection.objects.link(camera)
camera.location=coord((0,2.3,.9))
camera.rotation_euler=(Vector(coord((0,.83,-.8)))-camera.location).to_track_quat('-Z','Y').to_euler()
camera_data.lens=22
scene.camera=camera
scene.render.resolution_x=1400
scene.render.resolution_y=800
scene.render.resolution_percentage=80
scene.render.image_settings.file_format=next(i.identifier for i in bpy.types.ImageFormatSettings.bl_rna.properties["file_format"].enum_items if i.identifier=="PNG")
scene.render.filepath=str(OUT / "cab-equipment-preview.png")
scene["original_scene_preserved"]=previous_scene.name
scene["asset_contract"]="Y-up GLB; metres; cab origin; desk y=0.77m; -Z towards windows."
print({"asset":str(OUT / "cab-equipment.glb"),"bytes":(OUT / "cab-equipment.glb").stat().st_size,"meshes":len(collection.objects),"previous_scene":previous_scene.name})
