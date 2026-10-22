"""Build the bounded, offline SFO terrain grid. Run: uv run --with pillow fetch_terrain.py.

Terrarium is numeric elevation data, not a display image. RGB decodes to metres.
No vertical exaggeration. The browser flattens airport operations to its existing
local ground datum and tapers the shoreline; this is scenery, never flight evidence.
"""
import concurrent.futures
import hashlib
import io
import json
import math
from pathlib import Path
import struct
from urllib.request import urlopen
from PIL import Image

OUT = Path(__file__).resolve().parents[3] / 'candidates/assets/tower-realism/terrain'
OUT.mkdir(parents=True, exist_ok=True)
ZOOM = 11
EXTENT = [-23000, -43000, 35000, 18500]  # west, north, east, south; ENU metres
SIZE = 401
ORIGIN = [-122.3826, 37.6164]
SCALE = [88288.08474587766, 110989.20390546018]
def tile_pixel(x, z):
    lon = ORIGIN[0] + x / SCALE[0]
    lat = ORIGIN[1] - z / SCALE[1]
    n = 2 ** ZOOM * 256
    return ((lon + 180) / 360 * n,
            (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
points = [tile_pixel(x, z) for x in [EXTENT[0], EXTENT[2]] for z in [EXTENT[1], EXTENT[3]]]
coords = [(x,y) for x in range(int(min(p[0] for p in points)//256), int(max(p[0] for p in points)//256)+1)
          for y in range(int(min(p[1] for p in points)//256), int(max(p[1] for p in points)//256)+1)]
def fetch(coord):
    x,y=coord
    url=f'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{ZOOM}/{x}/{y}.png'
    with urlopen(url, timeout=45) as response: data=response.read()
    image=Image.open(io.BytesIO(data)).convert('RGB')
    if image.size != (256,256): raise ValueError('Unexpected terrain tile size')
    return coord,image,{'url':url,'sha256':hashlib.sha256(data).hexdigest()}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    downloaded=list(executor.map(fetch,coords))
tiles={coord:image for coord,image,_ in downloaded}
def sample(px,py):
    ix,iy=math.floor(px),math.floor(py)
    def height(x,y):
        r,g,b=tiles[(x//256,y//256)].getpixel((x%256,y%256))
        return r*256+g+b/256-32768
    fx,fy=px-ix,py-iy
    return ((height(ix,iy)*(1-fx)+height(ix+1,iy)*fx)*(1-fy)
            +(height(ix,iy+1)*(1-fx)+height(ix+1,iy+1)*fx)*fy)
heights=[]
for j in range(SIZE):
    z=EXTENT[1]+j/(SIZE-1)*(EXTENT[3]-EXTENT[1])
    for i in range(SIZE):
        x=EXTENT[0]+i/(SIZE-1)*(EXTENT[2]-EXTENT[0])
        heights.append(round(sample(*tile_pixel(x,z))))
raw=struct.pack('<'+'h'*len(heights),*heights)
(OUT/'bay-elevation.i16').write_bytes(raw)
metadata={'source':'Mapzen Terrain Tiles / USGS elevation', 'accessed':'2026-10-21',
          'attribution':'Terrain: Mapzen, USGS; ocean bathymetry: NOAA',
          'documentation':'https://github.com/tilezen/joerd/blob/master/docs/formats.md',
          'license':'https://github.com/tilezen/joerd/blob/master/docs/attribution.md',
          'extent':EXTENT,'size':SIZE,'origin_lonlat':ORIGIN,'metres_per_degree':SCALE,
          'encoding':'little-endian signed int16 metres; row-major north to south',
          'resampling':'bilinear Terrarium samples rounded to nearest metre',
          'min':min(heights),'max':max(heights),'sha256':hashlib.sha256(raw).hexdigest(),
          'tiles':[source for _,_,source in downloaded]}
(OUT/'manifest.json').write_text(json.dumps(metadata,indent=2)+'\n')
print(f'{len(downloaded)} tiles → {SIZE}×{SIZE} grid, {len(raw)} bytes, {min(heights)}…{max(heights)} m')
