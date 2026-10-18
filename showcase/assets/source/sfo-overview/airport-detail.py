"""Build lightweight schematic airport facade detail from existing OSM footprints.
Blender coordinate system: x=east, y=north, z=up, metres relative to SFO ATCT.
Run: blender -b -t 2 --python showcase/assets/source/sfo-overview/airport-detail.py
"""
import bpy, json, math, random
from pathlib import Path
from mathutils import Vector
from mathutils.geometry import tessellate_polygon
ROOT=Path(__file__).resolve().parents[4]
random.seed(321)
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
features=json.loads((ROOT/'showcase/candidates/sfo-pack/sfo-aeroway.geojson').read_text())['features']
materials={}; geometry={}
def mat(name,color,metal=0,rough=.7):
 m=bpy.data.materials.new(name); m.diffuse_color=(*color,1); m.use_nodes=True
 bs=m.node_tree.nodes.get('Principled BSDF'); bs.inputs['Base Color'].default_value=(*color,1); bs.inputs['Metallic'].default_value=metal; bs.inputs['Roughness'].default_value=rough
 materials[name]=m; geometry[name]=[[],[]]
mat('Warm metal roofs',(.64,.63,.57),.16,.65)
mat('Curtain glazing',(.12,.22,.23),.32,.24)
mat('Roof service equipment',(.34,.37,.35),.16,.8)
mat('Structural concrete',(.64,.63,.58),0,.85)
mat('Terminal glass mullions',(.42,.45,.43),.3,.5)
mat('Apron service details',(.71,.69,.61),.1,.6)

def pt(c): return ((c[0]+122.3826)*88288.08474587766,(c[1]-37.6164)*110989.20390546018)
def box(name,c,size,angle=0):
 vs,fs=geometry[name]; k=len(vs); ca,sa=math.cos(angle),math.sin(angle)
 for z in [-1,1]:
  for y in [-1,1]:
   for x in [-1,1]:
    dx=x*size[0]/2; dy=y*size[1]/2; vs.append((c[0]+dx*ca-dy*sa,c[1]+dx*sa+dy*ca,c[2]+z*size[2]/2))
 fs.extend(tuple(k+i for i in f) for f in [(0,1,3,2),(4,6,7,5),(0,4,5,1),(2,3,7,6),(0,2,6,4),(1,5,7,3)])
def line(name,a,b,z,width,height):
 dx=b[0]-a[0]; dy=b[1]-a[1]; L=math.hypot(dx,dy)
 if L>.3: box(name,((a[0]+b[0])/2,(a[1]+b[1])/2,z),(L,width,height),math.atan2(dy,dx))
def inside(x,y,poly):
 ok=False; j=len(poly)-1
 for i in range(len(poly)):
  xi,yi=poly[i]; xj,yj=poly[j]
  if (yi>y)!=(yj>y) and x < (xj-xi)*(y-yi)/(yj-yi)+xi: ok=not ok
  j=i
 return ok
def footprint_base(poly,h):
 # The original GLB contains way-based footprints; the two relation-based terminals need solid bases.
 ring=poly[:-1] if poly[0]==poly[-1] else poly
 if sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(ring,ring[1:]+ring[:1]))<0: ring=list(reversed(ring))
 vs,fs=geometry['Structural concrete']; k=len(vs)
 vs.extend((x,y,z) for z in (0,h) for x,y in ring); n=len(ring)
 for i in range(n): j=(i+1)%n; fs.append((k+i,k+j,k+n+j,k+n+i))
 roof_vs,roof_fs=geometry['Warm metal roofs']
 roof_points=[Vector((x,y,h)) for x,y in ring]
 for indices in tessellate_polygon([roof_points]):
  tri=[roof_points[i] if isinstance(i,int) else i for i in indices]
  q=len(roof_vs); roof_vs.extend(tuple(v) for v in tri); roof_fs.append((q,q+1,q+2) if (tri[1]-tri[0]).cross(tri[2]-tri[0]).z>0 else (q,q+2,q+1))
terminal_count=0
for f in features:
 if f['properties'].get('kind')!='terminal' or f['geometry']['type']!='Polygon': continue
 poly=[pt(c) for c in f['geometry']['coordinates'][0]]; h=float(f['properties'].get('height',20)); terminal_count+=1
 if f['properties'].get('osm_id','').startswith('relation/'): footprint_base(poly,h)
 for a,b in zip(poly,poly[1:]):
  L=math.dist(a,b)
  # A continuous glazed band and pale parapet make the actual footprint legible in sunlight.
  line('Curtain glazing',a,b,h-5,1.6,6)
  line('Warm metal roofs',a,b,h+.5,1.8,1.1)
  if L>12:
   for j in range(1,int(L/9)):
    t=j/(int(L/9)); x=a[0]+(b[0]-a[0])*t; y=a[1]+(b[1]-a[1])*t
    box('Terminal glass mullions',(x,y,h-5),(1.3,1.3,6.2))
 xmin,xmax=min(p[0] for p in poly),max(p[0] for p in poly); ymin,ymax=min(p[1] for p in poly),max(p[1] for p in poly)
 for x in range(math.ceil(xmin/30)*30,int(xmax),30):
  for y in range(math.ceil(ymin/30)*30,int(ymax),30):
   if all(inside(x+dx,y+dy,poly) for dx,dy in [(-9,-7),(9,-7),(9,7),(-9,7)]):
    box('Roof service equipment',(x,y,h+1.5),(12,7,3))
    box('Warm metal roofs',(x,y,h+3.15),(12.4,7.4,.3))
    box('Curtain glazing',(x+9,y,h+.25),(3,12,.5))
# Tower has a curved shaft, two deck rings, and a twelve-sided glass control room.
def cylinder(name,x,y,z,r0,r1,h,n=16):
 vs,fs=geometry[name]; k=len(vs)
 for zz,rr in [(z-h/2,r0),(z+h/2,r1)]:
  for i in range(n):
   a=2*math.pi*i/n; vs.append((x+math.cos(a)*rr,y+math.sin(a)*rr,zz))
 fs.append(tuple(k+i for i in range(n-1,-1,-1))); fs.append(tuple(k+n+i for i in range(n)))
 for i in range(n): j=(i+1)%n; fs.append((k+i,k+j,k+n+j,k+n+i))
tower=next(f for f in features if f['properties'].get('kind')=='tower')
coords=tower['geometry']['coordinates']
if 'centroid' in tower['properties']: tx,ty=pt(tower['properties']['centroid'])
elif tower['geometry']['type']=='Polygon': tx,ty=pt(coords[0][0])
else: tx,ty=pt(coords)
tower_vertex_start={name:len(parts[0]) for name,parts in geometry.items()}
# Existing OSM tower is hidden at runtime because this model supplies its full silhouette.
cylinder('Structural concrete',tx,ty,29.5,6,3.8,59,24)
cylinder('Warm metal roofs',tx,ty,59,8.8,9,1.7,12)
cylinder('Curtain glazing',tx,ty,63,8.4,10.2,6.7,12)
cylinder('Warm metal roofs',tx,ty,67.3,11,10.8,1.8,12)
cylinder('Structural concrete',tx,ty,69.2,.5,.5,3,8)
for i in range(12):
 a=math.pi*2*i/12; box('Terminal glass mullions',(tx+9.2*math.cos(a),ty+9.2*math.sin(a),63),(.4,.4,7))
# Match the recorded 67.36 m overall height, including the mast, above the airport surface.
tower_scale=float(tower['properties'].get('height',67.36))/70.7
for name,(vs,_) in geometry.items():
 for i in range(tower_vertex_start[name],len(vs)):
  x,y,z=vs[i]; vs[i]=(x,y,z*tower_scale)
# Service masts on measured apron polygon vertices. These are visual detail, not operational fixtures.
for f in features:
 if f['properties'].get('kind')!='apron' or f['geometry']['type']!='Polygon': continue
 poly=[pt(c) for c in f['geometry']['coordinates'][0]]
 for i in range(0,len(poly)-1,max(1,len(poly)//3)):
  x,y=poly[i]; cylinder('Roof service equipment',x,y,11,.45,.3,22,6)
  box('Apron service details',(x,y,22),(5,1.8,.5))
for name,(vs,fs) in geometry.items():
 mesh=bpy.data.meshes.new(name); mesh.from_pydata(vs,[],fs); mesh.update(); obj=bpy.data.objects.new(name,mesh); bpy.context.collection.objects.link(obj); obj.data.materials.append(materials[name])
# Recalculate exported triangle winding for consistent shadows.
for obj in bpy.context.scene.objects:
 if obj.type=='MESH':
  bpy.context.view_layer.objects.active=obj; obj.select_set(True); bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT'); bpy.ops.mesh.normals_make_consistent(inside=False); bpy.ops.object.mode_set(mode='OBJECT'); obj.select_set(False)
bpy.ops.wm.save_as_mainfile(filepath=str(Path(__file__).with_suffix('.blend')))
bpy.ops.export_scene.gltf(filepath=str(ROOT/'showcase/candidates/assets/overview/airport-detail.glb'),export_format='GLB',export_yup=True,export_apply=True,export_cameras=False,export_lights=False,export_draco_mesh_compression_enable=True,export_draco_mesh_compression_level=6)
print('Airport detail: terminals',terminal_count,'vertices',sum(len(x[0]) for x in geometry.values()))
