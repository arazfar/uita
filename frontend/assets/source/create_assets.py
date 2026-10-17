"""Original Uita meshes. Run Blender --background --python this_file. License: CC0.
Meters are stylized display units; aircraft assets never encode safety/performance.
"""
import bpy, math, os
from mathutils import Vector
ROOT=os.path.abspath(os.path.join(os.path.dirname(__file__),'../../public/assets'))
os.makedirs(ROOT,exist_ok=True)
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
def material(name,color,metal=0):
 m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True;m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(*color,1);m.node_tree.nodes['Principled BSDF'].inputs['Metallic'].default_value=metal;m.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.42;return m
white=material('Pearl fuselage',(.72,.82,.84),.15);navy=material('Navy tail',(.09,.24,.31));glass=material('Cockpit glass',(.035,.10,.14),.5);silver=material('Engine metal',(.32,.41,.46),.55)
def sphere(name,location,scale,mat):
 bpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=8,location=location);o=bpy.context.object;o.name=name;o.scale=scale;o.data.materials.append(mat);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
 for p in o.data.polygons:p.use_smooth=True
 return o
def prism(name,points,height,mat):
 n=len(points);verts=[(x,y,z) for z in (-height/2,height/2) for x,y in points];faces=[tuple(reversed(range(n))),tuple(range(n,2*n))]+[(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)];mesh=bpy.data.meshes.new(name);mesh.from_pydata(verts,[],faces);mesh.update();o=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(o);o.data.materials.append(mat);return o
sphere('Streamlined fuselage',(0,0,0),(.098,.5,.095),white)
for sign in [-1,1]:
 prism('Swept main wing',[(0,-.11),(sign*.48,.09),(sign*.49,.17),(sign*.10,.10)],.022,white)
 prism('Horizontal stabilizer',[(0,.30),(sign*.19,.40),(sign*.19,.45),(0,.41)],.015,white)
 sphere('Engine nacelle',(sign*.22,.0,-.065),(.053,.135,.052),silver)
 sphere('Engine intake',(sign*.22,-.125,-.065),(.041,.008,.04),glass)
 for i in range(10):sphere('Passenger window',(sign*.095,-.24+i*.047,.028),(.003,.008,.009),glass)
sphere('Cockpit canopy',(0,-.355,.054),(.069,.083,.033),glass)
tail=prism('Vertical stabilizer',[(0,.24),(.20,.40),(.20,.47),(0,.44)],.018,navy);tail.rotation_euler[1]=-math.pi/2
bpy.ops.object.select_all(action='SELECT');bpy.context.view_layer.objects.active=bpy.context.selected_objects[0];bpy.ops.object.join()
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(os.path.dirname(__file__),'uita-airliner.blend'))
bpy.ops.export_scene.gltf(filepath=os.path.join(ROOT,'uita-airliner.glb'),export_format='GLB',export_yup=True)
print('Exported original Uita airliner to',ROOT)
# Airport scenery: standalone terminal, concourses, jet bridges and control tower.
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
roof=material('Terminal roof',(.40,.52,.55),.25);concrete=material('Terminal facade',(.55,.66,.65));windows=material('Terminal glazing',(.10,.27,.34),.35)
def box(name,loc,scale,mat):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name=name;o.scale=scale;o.data.materials.append(mat);bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);return o
box('Main terminal',(0,0,.16),(1.05,3.1,.32),concrete)
box('Main roof',(0,0,.34),(1.13,3.18,.05),roof)
box('Terminal glazing',(.53,0,.18),(.025,2.9,.12),windows)
for row in [-1,0,1]:
 box('Concourse',(-1.05,row,.11),(1.45,.36,.22),concrete)
 box('Concourse roof',(-1.05,row,.235),(1.5,.4,.03),roof)
 for x in [-1.6,-1.15,-.7]:
  box('Jet bridge',(x,row+.34,.09),(.09,.4,.12),roof)
  box('Jet bridge head',(x,row+.54,.08),(.16,.12,.16),concrete)
for y in [-.9,0,.9]:box('Roof services',(.1,y,.42),(.28,.24,.12),roof)
bpy.ops.mesh.primitive_cylinder_add(vertices=12,radius=.075,depth=1.4,location=(.15,-1.9,.7));bpy.context.object.name='Control tower shaft';bpy.context.object.data.materials.append(concrete)
bpy.ops.mesh.primitive_cylinder_add(vertices=8,radius=.23,depth=.18,location=(.15,-1.9,1.48));bpy.context.object.name='Tower cab';bpy.context.object.data.materials.append(windows)
bpy.ops.mesh.primitive_cylinder_add(vertices=8,radius=.25,depth=.045,location=(.15,-1.9,1.59));bpy.context.object.name='Tower roof';bpy.context.object.data.materials.append(roof)
box('Tower antenna',(.15,-1.9,1.76),(.025,.025,.3),silver)
bpy.ops.object.select_all(action='SELECT');bpy.context.view_layer.objects.active=bpy.context.selected_objects[0];bpy.ops.object.join()
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(os.path.dirname(__file__),'uita-terminal.blend'))
bpy.ops.export_scene.gltf(filepath=os.path.join(ROOT,'uita-terminal.glb'),export_format='GLB',export_yup=True)
