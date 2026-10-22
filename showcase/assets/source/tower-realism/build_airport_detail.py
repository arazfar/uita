"""SFO building detail derived from the bundled OSM massing, generated in Blender.

Original illustrative facades and equipment; no surveyed gate or facade claim.
Coordinates: Blender X east, Y north, Z up, metres. glTF exports Y up.
Every repeated part is batched by material. Existing footprint heights stay intact.
"""
import bpy
import math
from mathutils import Vector
# PATH_SETUP_BEGIN
from pathlib import Path
import json
ROOT = Path(__file__).resolve().parents[3]
SOURCE_GLB = str(ROOT / 'candidates/sfo-pack/sfo-buildings.glb')
OUTPUT_GLB = str(ROOT / 'candidates/assets/tower-realism/airport-detail.glb')
PREVIEW = str(ROOT / 'candidates/assets/tower-realism/airport-detail-preview.png')
AIRPORTS = json.loads((ROOT / 'candidates/data/airports.geojson').read_text())
APRON_RINGS = [[((c[0]+122.3826)*88288.08474587766,(c[1]-37.6164)*110989.20390546018) for c in f['geometry']['coordinates'][0]] for f in AIRPORTS['features'] if f['properties'].get('airport')=='SFO' and f['properties'].get('kind')=='apron']
# PATH_SETUP_END

scene = bpy.data.scenes.new('SFO Airport Detail')
bpy.context.window.scene = scene
bpy.ops.import_scene.gltf(filepath=SOURCE_GLB)
originals = list(bpy.context.selected_objects)
for obj in originals:
    if obj.name.split('.')[0] in ['downtown', 'residential', 'tower']:
        bpy.data.objects.remove(obj, do_unlink=True)
originals = list(scene.objects)

def material(name, color, roughness=.7, metal=0):
    m=bpy.data.materials.new(name);m.use_nodes=True
    bsdf=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    bsdf.inputs['Base Color'].default_value=(*color,1)
    bsdf.inputs['Roughness'].default_value=roughness
    bsdf.inputs['Metallic'].default_value=metal
    m.diffuse_color=(*color,1)
    return m
mats={
    'concrete':material('Airport · warm precast concrete',(.47,.46,.42),.87),
    'roof':material('Airport · weathered roof',(.30,.33,.33),.94),
    'glass':material('Airport · blue green curtain glass',(.075,.17,.20),.18,.4),
    'glass2':material('Airport · reflected silver glass',(.17,.24,.25),.28,.35),
    'frames':material('Airport · aluminium frames',(.49,.53,.52),.34,.68),
    'dark':material('Airport · recess and service rubber',(.035,.048,.048),.89),
    'rooflight':material('Airport · roof skylights',(.15,.24,.25),.24,.3),
    'white':material('Airport · enamel equipment',(.72,.73,.68),.45,.12),
    'yellow':material('Airport · safety ochre',(.62,.39,.065),.68),
    'metal':material('Airport · galvanized steel',(.28,.32,.33),.46,.75),
    'vent':material('Airport · louver shadow',(.11,.14,.14),.82),
}
batches={key:[[],[]] for key in mats}

def quad(key, vertices):
    points,faces=batches[key];n=len(points);points.extend(vertices);faces.append(tuple(range(n,n+4)))
def box(key, center, size, angle=0):
    c=math.cos(angle);s=math.sin(angle);cx,cy,cz=center;dx,dy,dz=[v/2 for v in size]
    points=[]
    for x,y,z in [(-dx,-dy,-dz),(dx,-dy,-dz),(dx,dy,-dz),(-dx,dy,-dz),(-dx,-dy,dz),(dx,-dy,dz),(dx,dy,dz),(-dx,dy,dz)]:
        points.append((cx+x*c-y*s,cy+x*s+y*c,cz+z))
    for face in [(0,3,2,1),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7),(4,5,6,7)]:quad(key,[points[i] for i in face])
def cylinder(key,center,radius,height,segments=12):
    x,y,z=center
    for i in range(segments):
        a=2*math.pi*i/segments;b=2*math.pi*(i+1)/segments
        quad(key,[(x+radius*math.cos(a),y+radius*math.sin(a),z-height/2),(x+radius*math.cos(b),y+radius*math.sin(b),z-height/2),(x+radius*math.cos(b),y+radius*math.sin(b),z+height/2),(x+radius*math.cos(a),y+radius*math.sin(a),z+height/2)])

def bridge(start,normal,angle,index):
    # Generic telescoping bridge, support bogie and baggage carts. No fake flight IDs.
    x,y,z=start;nx,ny=normal
    def place(key,along,across,h,size):
        box(key,(x+nx*along-ny*across,y+ny*along+nx*across,h),size,angle)
    cylinder('frames',(x,y,4),2.0,7.0)
    place('white',12,0,5.5,(23,3.5,3.2))
    place('dark',12,0,3.85,(23,3.8,.2))
    place('glass',12,0,5.65,(21,3.55,1.5))
    place('white',12,0,7.2,(23,3.8,.23))
    for k in range(13):place('frames',2+k*1.65,0,5.5,(.13,3.65,3.2))
    place('frames',21,0,2.6,(.5,2.5,3.3));place('dark',21,0,.65,(2.2,3.4,1.1))
    place('dark',25,0,5.5,(3,4.4,3.6))
    for k in range(6):place('frames',23.8+k*.45,0,5.5,(.09,4.45,3.65))
    # Ground equipment stays next to the building, clear of operational taxiways.
    place('white',8,8,1.1,(3.5,1.7,1.4));place('glass',7.3,8,1.95,(1.2,1.65,.8))
    place('dark',8,8,.35,(3.1,1.9,.5))
    for k in range(3):
        place('metal',12+k*3,8,.6,(2.3,1.5,.7));place('dark',12+k*3,8,.25,(2,1.65,.35))
        place('yellow',12+k*3,8,1.25,(2.1,1.3,.6))

def in_apron(x,y):
    for ring in APRON_RINGS:
        inside=False
        for i,a in enumerate(ring):
            b=ring[i-1]
            if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:inside=not inside
        if inside:return True
    return False

walls=[];roof_centers=[]
for obj in originals:
    kind=obj.name.split('.')[0];mesh=obj.data
    mesh.materials.clear()
    for key in ['concrete','roof','dark']:mesh.materials.append(mats[key])
    seen=set()
    for p in mesh.polygons:
        p.material_index=1 if p.normal.z>.7 else 0
        verts=[mesh.vertices[i].co.copy() for i in p.vertices]
        if p.normal.z>.8 and p.area>180 and kind in ['terminal','hangar']:
            c=p.center
            if all((c-r).length>25 for r in roof_centers):
                roof_centers.append(c.copy())
                box('metal',(c.x,c.y,c.z+.7),(5.2,3.4,1.4))
                box('vent',(c.x,c.y,c.z+1.43),(4.7,2.9,.12))
                for v in [-1.2,0,1.2]:cylinder('dark',(c.x+v,c.y,c.z+1.55),.55,.13)
        if abs(p.normal.z)>.05 or kind not in ['terminal','hangar','parking']:continue
        top=max(v.z for v in verts);bottom=min(v.z for v in verts)
        edge={ (round(v.x,2),round(v.y,2)) for v in verts }
        if len(edge)!=2 or top-bottom<4:continue
        a,b=sorted(edge);key=(a,b,round(top,1))
        if key in seen:continue
        seen.add(key)
        length=math.hypot(b[0]-a[0],b[1]-a[1]);
        if length<4:continue
        nx,ny=p.normal.x,p.normal.y;tx=(b[0]-a[0])/length;ty=(b[1]-a[1])/length
        angle=math.atan2(ty,tx)
        center=((a[0]+b[0])/2,(a[1]+b[1])/2)
        # Detail near airport; distant city remains cheap massing.
        if math.hypot(*center)>4200:continue
        base=bottom+1.1;hi=top-1.3
        if kind=='terminal':
            base=max(bottom+2,top*.28);hi=top-2.0
        elif kind=='hangar':
            base=bottom+1;hi=top*.75
        else:
            base=bottom+top*.35;hi=top*.72
        if hi-base<1:continue
        x,y=center[0]+nx*.12,center[1]+ny*.12
        box('glass' if kind=='terminal' else 'glass2',(x,y,(base+hi)/2),(length-.3,.16,hi-base),angle)
        for h in [base,hi,top-.3]:
            box('frames',(x+nx*.12,y+ny*.12,h),(length+.15,.4,.22),angle)
        spacing=3.2 if kind=='terminal' else 6
        for i in range(1,int(length/spacing)+1):
            d=i*length/(int(length/spacing)+1)
            box('frames',(a[0]+tx*d+nx*.25,a[1]+ty*d+ny*.25,(base+hi)/2),(.16,.4,hi-base),angle)
        if kind=='terminal':
            # Recessed lower service band and cantilever canopy create actual parallax.
            box('dark',(x,y,base*.55),(length,.18,base*.6),angle)
            box('white',(x+nx*1.0,y+ny*1.0,base),(length+1,2.4,.28),angle)
            # Select only airside faces east/north of the tower. Spacing is illustrative.
            if 28<length<210 and math.hypot(*center)>130 and in_apron(center[0]+nx*18,center[1]+ny*18):
                walls.append((center,(nx,ny),angle,length,top))
        elif kind=='hangar':
            for i in range(1,int(length/8)):
                d=i*8
                box('frames',(a[0]+tx*d+nx*.3,a[1]+ty*d+ny*.3,top*.38),(.25,.4,top*.7),angle)

bridge_centers=[]
def longest_wall(w):
    return -w[3]
for center,n,angle,length,top in sorted(walls,key=longest_wall):
    if len(bridge_centers)>=24:break
    if any(math.dist(center,c)<55 for c in bridge_centers):continue
    bridge_centers.append(center)
    bridge((*center,0),n,math.atan2(n[1],n[0]),len(bridge_centers))

for key,(vertices,faces) in batches.items():
    if not vertices:continue
    mesh=bpy.data.meshes.new('SFO '+key);mesh.from_pydata(vertices,[],faces);mesh.materials.append(mats[key]);mesh.update()
    obj=bpy.data.objects.new('SFO detail · '+key,mesh);scene.collection.objects.link(obj)

bpy.ops.object.select_all(action='DESELECT')
for obj in scene.objects:
    if obj.type=='MESH':obj.select_set(True)
bpy.context.view_layer.objects.active=next(o for o in scene.objects if o.type=='MESH')
bpy.ops.export_scene.gltf(filepath=OUTPUT_GLB,export_format='GLB',use_selection=True,use_active_scene=True,export_yup=True,export_materials='EXPORT',export_draco_mesh_compression_enable=True,export_draco_mesh_compression_level=6)
print('Airport exported; meshes',len([o for o in scene.objects if o.type=='MESH']),'bridges',len(bridge_centers),'roof equipment',len(roof_centers),'background',bpy.app.background)
# Preview from an oblique terminal viewpoint. Camera/light are never in the GLB.
cam_data=bpy.data.cameras.new('Airport preview');cam=bpy.data.objects.new('Airport preview',cam_data);scene.collection.objects.link(cam);scene.camera=cam
cam.location=(650,-850,380);target=Vector((-250,-300,12));cam.rotation_euler=(target-cam.location).to_track_quat('-Z','Y').to_euler();cam_data.lens=46;cam_data.clip_end=100000
sun_data=bpy.data.lights.new('Airport sun','SUN');sun_data.energy=3;sun_data.angle=.15
sun=bpy.data.objects.new('Airport sun',sun_data);scene.collection.objects.link(sun);sun.rotation_euler=(.5,-.4,-.7)
scene.world=bpy.data.worlds.new('Airport sky');scene.world.use_nodes=True
background=next(n for n in scene.world.node_tree.nodes if n.type=='BACKGROUND');background.inputs['Color'].default_value=(.3,.43,.6,1);background.inputs['Strength'].default_value=.5
scene.render.engine='CYCLES';scene.cycles.samples=24
scene.render.resolution_x=1400;scene.render.resolution_y=900;scene.render.resolution_percentage=100
scene.render.filepath=PREVIEW
