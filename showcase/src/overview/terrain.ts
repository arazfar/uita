import * as THREE from "three180";

/**
 * US Census shoreline and USGS NAIP imagery are geographic source data.
 * Elevations and vegetation are deterministic illustration, not a measured DEM.
 * Local ENU metres match sfo-pack/bounds.json: x east, y up, z south.
 */
const ORIGIN_LON = -122.3826;
const ORIGIN_LAT = 37.6164;
const METRES_LON = 88288.08474587766;
const METRES_LAT = 110989.20390546018;
const EARTH_RADIUS = 6378137;

type Point = [number, number];
type Polygon = Point[][];
type ImageBounds = {
  file: string;
  lonlat_bounds: { west: number; south: number; east: number; north: number };
  epsg3857_extent: { xmin: number; ymin: number; xmax: number; ymax: number };
};
type Coast = {
  features: {
    geometry: { type: string; coordinates: number[][][] | number[][][][] };
  }[];
};

const clamp = (value: number, min = 0, max = 1) =>
  Math.max(min, Math.min(max, value));
const smooth = (a: number, b: number, value: number) => {
  const t = clamp((value - a) / (b - a));
  return t * t * (3 - 2 * t);
};
const toLocal = ([lon, lat]: number[]): Point => [
  (lon - ORIGIN_LON) * METRES_LON,
  -(lat - ORIGIN_LAT) * METRES_LAT,
];
const mercatorY = (latitude: number) =>
  EARTH_RADIUS * Math.log(Math.tan(Math.PI / 4 + (latitude * Math.PI) / 360));

function hash(x: number, y: number): number {
  let n = Math.imul(x, 374761393) + Math.imul(y, 668265263);
  n = Math.imul(n ^ (n >>> 13), 1274126177);
  return ((n ^ (n >>> 16)) >>> 0) / 4294967295;
}
function noise(x: number, y: number): number {
  const ix = Math.floor(x),
    iy = Math.floor(y);
  const fx = smooth(0, 1, x - ix),
    fy = smooth(0, 1, y - iy);
  const a = hash(ix, iy),
    b = hash(ix + 1, iy),
    c = hash(ix, iy + 1),
    d = hash(ix + 1, iy + 1);
  return (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy;
}
function fbm(x: number, z: number): number {
  return (
    noise(x, z) * 0.55 +
    noise(x * 2.1 + 17, z * 2.1) * 0.28 +
    noise(x * 4.3, z * 4.3 + 31) * 0.17
  );
}
function inRing(x: number, z: number, ring: Point[]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [ax, az] = ring[i],
      [bx, bz] = ring[j];
    if (az > z !== bz > z && x < ((bx - ax) * (z - az)) / (bz - az) + ax)
      inside = !inside;
  }
  return inside;
}

// Broad, overlapping ridges avoid the spherical mounds of the earlier candidate.
// Landmarks control scale and location; fine ridges remain procedural.
const HILLS = [
  [-122.434, 37.686, 390, 3100, 2300], // San Bruno Mountain
  [-122.455, 37.635, 255, 2200, 3300], // northern Sweeney Ridge
  [-122.467, 37.598, 380, 2800, 4600], // Peninsula ridge
  [-122.499, 37.55, 560, 3400, 3600], // Montara foothills
  [-122.482, 37.742, 225, 1900, 2600], // western San Francisco hills
  [-122.452, 37.752, 210, 1400, 1700], // Twin Peaks
  [-122.516, 37.841, 370, 3600, 3900], // Marin headlands
  [-122.561, 37.9, 520, 4500, 4800],
  [-122.184, 37.806, 420, 3300, 6200], // East Bay ridge
  [-122.131, 37.739, 510, 3700, 5400],
  [-122.093, 37.653, 580, 4000, 5800],
].map(([lon, lat, height, rx, rz]) => ({
  x: (lon - ORIGIN_LON) * METRES_LON,
  z: -(lat - ORIGIN_LAT) * METRES_LAT,
  height,
  rx,
  rz,
}));

function illustrativeElevation(x: number, z: number): number {
  // The entire airport and nearby shoreline remain at 2 m. No invented hill can
  // intersect an OSM runway, taxiway, terminal, or an airport camera viewpoint.
  const airportDistance = Math.max(
    Math.abs((x - 150) / 4200),
    Math.abs((z + 500) / 4000),
  );
  const airportMask = smooth(0.9, 1.25, airportDistance);
  const warpedX = x + (fbm(x / 1500, z / 1500) - 0.5) * 850;
  const warpedZ = z + (fbm(x / 1500 + 24, z / 1500 - 19) - 0.5) * 850;
  let height = 0;
  for (const hill of HILLS) {
    const dx = (warpedX - hill.x) / hill.rx,
      dz = (warpedZ - hill.z) / hill.rz;
    const radius = dx * dx + dz * dz;
    height += hill.height * Math.exp(-radius * 1.65);
  }
  const ridge = 1 - Math.abs(fbm(x / 1650, z / 1650) * 2 - 1);
  height *= 0.54 + ridge * 0.52;
  height += (fbm(x / 360, z / 360) - 0.5) * Math.min(height * 0.32, 60);
  // Narrow, shallow drainage folds give the near ridges legible shoulders while
  // keeping their landmark-scale heights. This is bounded illustration detail.
  const drainage = 1 - Math.abs(noise(x / 580 + z / 4100, z / 720) * 2 - 1);
  height -= Math.min(Math.max(height - 40, 0) * 0.1, 24) * drainage;
  height +=
    (noise(x / 420 + 7, z / 610 - 11) - 0.5) * Math.min(height * 0.18, 22);
  // Height falls smoothly into the flat urban plain instead of floating above it.
  return 2 + Math.max(0, height - 12) * airportMask;
}

function addImageCoordinates(
  geometry: THREE.BufferGeometry,
  bay: ImageBounds,
  sfo: ImageBounds,
) {
  const position = geometry.getAttribute("position");
  for (const [attribute, bounds] of [
    ["bayUv", bay],
    ["sfoUv", sfo],
  ] as const) {
    const uv = new Float32Array(position.count * 2);
    const extent = bounds.epsg3857_extent;
    for (let i = 0; i < position.count; i++) {
      const lon = ORIGIN_LON + position.getX(i) / METRES_LON;
      const lat = ORIGIN_LAT - position.getZ(i) / METRES_LAT;
      uv[i * 2] =
        ((EARTH_RADIUS * lon * Math.PI) / 180 - extent.xmin) /
        (extent.xmax - extent.xmin);
      uv[i * 2 + 1] =
        (mercatorY(lat) - extent.ymin) / (extent.ymax - extent.ymin);
    }
    geometry.setAttribute(attribute, new THREE.BufferAttribute(uv, 2));
  }
}

export async function createTerrain(): Promise<{
  group: THREE.Group;
  heightAt: (x: number, z: number) => number;
  dispose: () => void;
}> {
  const [coastResponse, boundsResponse] = await Promise.all([
    fetch("/candidates/data/bay-coastline.geojson"),
    fetch("/candidates/sfo-pack/bounds.json"),
  ]);
  if (!coastResponse.ok || !boundsResponse.ok)
    throw new Error("The offline shoreline or imagery bounds could not load.");
  const coast: Coast = await coastResponse.json();
  const bounds: { images: { bay: ImageBounds; sfo: ImageBounds } } =
    await boundsResponse.json();
  const polygons: Polygon[] = [];
  for (const feature of coast.features) {
    const source =
      feature.geometry.type === "Polygon"
        ? [feature.geometry.coordinates]
        : feature.geometry.coordinates;
    for (const polygon of source as number[][][][])
      polygons.push(polygon.map((ring) => ring.map(toLocal)));
  }
  const regions = polygons.map((rings) => ({
    rings,
    minX: Math.min(...rings[0].map((p) => p[0])),
    maxX: Math.max(...rings[0].map((p) => p[0])),
    minZ: Math.min(...rings[0].map((p) => p[1])),
    maxZ: Math.max(...rings[0].map((p) => p[1])),
  }));
  const isLand = (x: number, z: number) =>
    regions.some(
      (region) =>
        x >= region.minX &&
        x <= region.maxX &&
        z >= region.minZ &&
        z <= region.maxZ &&
        inRing(x, z, region.rings[0]) &&
        !region.rings.slice(1).some((ring) => inRing(x, z, ring)),
    );
  // A spatial index keeps shoreline distance cheap and prevents cliffs where a
  // procedural ridge approaches the measured coastline. Height meets the exact
  // coastline smoothly instead of exposing the terrain grid along the water.
  type ShoreSegment = { a: Point; b: Point };
  const shoreCells = new Map<string, ShoreSegment[]>();
  for (const polygon of polygons)
    for (const ring of polygon)
      for (let i = 1; i < ring.length; i++) {
        const a = ring[i - 1],
          b = ring[i],
          segment = { a, b };
        const minX = Math.floor((Math.min(a[0], b[0]) - 600) / 1000),
          maxX = Math.floor((Math.max(a[0], b[0]) + 600) / 1000);
        const minZ = Math.floor((Math.min(a[1], b[1]) - 600) / 1000),
          maxZ = Math.floor((Math.max(a[1], b[1]) + 600) / 1000);
        for (let iz = minZ; iz <= maxZ; iz++)
          for (let ix = minX; ix <= maxX; ix++) {
            const key = `${ix},${iz}`;
            const segments = shoreCells.get(key) ?? [];
            segments.push(segment);
            shoreCells.set(key, segments);
          }
      }
  const terrainElevation = (x: number, z: number) => {
    const elevation = illustrativeElevation(x, z);
    if (elevation <= 2.01) return 2;
    let distance = 600;
    for (const { a, b } of shoreCells.get(
      `${Math.floor(x / 1000)},${Math.floor(z / 1000)}`,
    ) ?? []) {
      const dx = b[0] - a[0],
        dz = b[1] - a[1];
      const t = clamp(
        ((x - a[0]) * dx + (z - a[1]) * dz) / (dx * dx + dz * dz || 1),
      );
      distance = Math.min(
        distance,
        Math.hypot(x - a[0] - t * dx, z - a[1] - t * dz),
      );
    }
    return 2 + (elevation - 2) * smooth(55, 600, distance);
  };
  const heightAt = (x: number, z: number) =>
    isLand(x, z) ? terrainElevation(x, z) : 0;
  const loader = new THREE.TextureLoader();
  const [bayTexture, sfoTexture] = await Promise.all([
    loader.loadAsync("/candidates/sfo-pack/" + bounds.images.bay.file),
    loader.loadAsync("/candidates/sfo-pack/" + bounds.images.sfo.file),
  ]);
  for (const texture of [bayTexture, sfoTexture]) {
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = 8;
    texture.wrapS = texture.wrapT = THREE.ClampToEdgeWrapping;
  }
  const group = new THREE.Group();
  group.name = "SFO geographic shoreline · schematic elevation";
  group.userData.provenance =
    "US Census coastline; USGS NAIP imagery. Elevation and vegetation are procedural illustration, not measured terrain.";

  const terrainMaterial = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    roughness: 0.98,
    metalness: 0,
    vertexColors: true,
  });
  terrainMaterial.onBeforeCompile = (shader) => {
    shader.uniforms.bayImagery = { value: bayTexture };
    shader.uniforms.sfoImagery = { value: sfoTexture };
    shader.vertexShader = shader.vertexShader
      .replace(
        "#include <common>",
        `#include <common>\nattribute vec2 bayUv; attribute vec2 sfoUv; varying vec2 vBayUv; varying vec2 vSfoUv; varying float vGroundHeight;`,
      )
      .replace(
        "#include <begin_vertex>",
        "#include <begin_vertex>\nvBayUv = bayUv; vSfoUv = sfoUv; vGroundHeight = position.y;",
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        `#include <common>\nuniform sampler2D bayImagery; uniform sampler2D sfoImagery; varying vec2 vBayUv; varying vec2 vSfoUv; varying float vGroundHeight;\nfloat coverage(vec2 uv) { vec2 edge = min(uv, 1.0 - uv); return smoothstep(0.0, 0.008, min(edge.x, edge.y)); }`,
      )
      .replace(
        "#include <color_fragment>",
        `
        #include <color_fragment>
        vec3 bayPixel = texture2D(bayImagery, vBayUv).rgb;
        vec3 airportPixel = texture2D(sfoImagery, vSfoUv).rgb;
        // Keep real ground detail while lifting the source's dark baked shadows.
        bayPixel = mix(bayPixel, vec3(0.45, 0.42, 0.32), 0.13);
        float hillMix = smoothstep(20.0, 110.0, vGroundHeight);
        diffuseColor.rgb = mix(diffuseColor.rgb, bayPixel, coverage(vBayUv) * mix(0.88, 0.20, hillMix));
        diffuseColor.rgb = mix(diffuseColor.rgb, airportPixel, coverage(vSfoUv) * 0.96);
      `,
      );
  };
  terrainMaterial.customProgramCacheKey = () => "uita-naip-mercator-drape-v1";

  const straw = new THREE.Color("#8f8751"),
    olive = new THREE.Color("#455b32"),
    stone = new THREE.Color("#9a9275");
  function colorAt(x: number, z: number, height: number, slope = 0) {
    const color = straw.clone().lerp(olive, fbm(x / 760, z / 760) * 0.88);
    color.lerp(stone, smooth(0.18, 0.48, slope) * 0.65);
    color.multiplyScalar(0.8 + noise(x / 110, z / 110) * 0.28);
    if (height < 20) color.lerp(new THREE.Color("#8f9081"), 0.28);
    return color;
  }
  function finishGeometry(geometry: THREE.BufferGeometry, flat = false) {
    const position = geometry.getAttribute("position");
    const colors = new Float32Array(position.count * 3);
    for (let i = 0; i < position.count; i++) {
      const x = position.getX(i),
        z = position.getZ(i),
        h = position.getY(i);
      const adjacent = flat
        ? [h, h, h, h]
        : [
            terrainElevation(x + 120, z),
            terrainElevation(x - 120, z),
            terrainElevation(x, z + 120),
            terrainElevation(x, z - 120),
          ];
      const slope =
        Math.hypot(adjacent[0] - adjacent[1], adjacent[2] - adjacent[3]) / 240;
      const color = colorAt(x, z, h, slope);
      // Broad cavity tint complements actual sunlight; it is intentionally weak
      // enough to preserve the distinction between color and measured elevation.
      const concavity = adjacent.reduce((sum, value) => sum + value, 0) / 4 - h;
      if (!flat) color.multiplyScalar(1 - smooth(0.3, 4.5, concavity) * 0.22);
      color.toArray(colors, i * 3);
    }
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    addImageCoordinates(geometry, bounds.images.bay, bounds.images.sfo);
    geometry.computeVertexNormals();
    geometry.computeBoundingSphere();
    const mesh = new THREE.Mesh(geometry, terrainMaterial);
    mesh.receiveShadow = true;
    mesh.castShadow = false;
    return mesh;
  }

  // The exact polygon base retains narrow inlets and the runway seawall. A regular
  // height grid is used only inland, where its cell size cannot square the coast.
  for (const rings of polygons) {
    const shape = new THREE.Shape(
      rings[0].map(([x, z]) => new THREE.Vector2(x, -z)),
    );
    for (const hole of rings.slice(1))
      shape.holes.push(
        new THREE.Path(hole.map(([x, z]) => new THREE.Vector2(x, -z))),
      );
    const geometry = new THREE.ShapeGeometry(shape);
    geometry.rotateX(-Math.PI / 2);
    geometry.translate(0, 2, 0);
    const mesh = finishGeometry(geometry, true);
    mesh.name = "Exact shoreline with NAIP ground imagery";
    group.add(mesh);
  }

  // 320² cells give a <205k-triangle upper bound before water and flat cells are
  // removed. Chunking permits frustum culling and keeps the airport responsive.
  const extent = { west: -23000, east: 35000, north: -43000, south: 18500 };
  const cells = 320,
    chunkCells = 40;
  const dx = (extent.east - extent.west) / cells,
    dz = (extent.south - extent.north) / cells;
  for (let cz = 0; cz < cells; cz += chunkCells)
    for (let cx = 0; cx < cells; cx += chunkCells) {
      const positions: number[] = [],
        indices: number[] = [],
        lands: boolean[] = [];
      for (let j = 0; j <= chunkCells; j++)
        for (let i = 0; i <= chunkCells; i++) {
          const x = extent.west + (cx + i) * dx,
            z = extent.north + (cz + j) * dz;
          const land = isLand(x, z);
          positions.push(x, land ? terrainElevation(x, z) : -5, z);
          lands.push(land);
        }
      for (let j = 0; j < chunkCells; j++)
        for (let i = 0; i < chunkCells; i++) {
          const a = j * (chunkCells + 1) + i,
            b = a + 1,
            c = a + chunkCells + 1,
            d = c + 1;
          if (![a, b, c, d].every((v) => lands[v])) continue;
          if (Math.max(...[a, b, c, d].map((v) => positions[v * 3 + 1])) < 3.5)
            continue;
          indices.push(a, c, b, b, c, d);
        }
      if (!indices.length) continue;
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute(
        "position",
        new THREE.Float32BufferAttribute(positions, 3),
      );
      geometry.setIndex(indices);
      const mesh = finishGeometry(geometry);
      mesh.name = "Procedural ridge · illustrative elevation";
      group.add(mesh);
    }

  // Instanced, seeded groves provide parallax and real directional shadows. They
  // avoid airport operations, dense urban flats, and the coast's water polygons.
  const treeGeometry = new THREE.IcosahedronGeometry(1, 1);
  treeGeometry.translate(0, 1, 0);
  const treeMaterial = new THREE.MeshStandardMaterial({
    color: 0xffffff,
    roughness: 1,
    metalness: 0,
  });
  const capacity = 8500;
  const trees = new THREE.InstancedMesh(treeGeometry, treeMaterial, capacity);
  trees.name = "Illustrative vegetation · deterministic instanced groves";
  trees.castShadow = true;
  trees.receiveShadow = true;
  const matrix = new THREE.Matrix4(),
    rotation = new THREE.Quaternion(),
    scale = new THREE.Vector3(),
    position = new THREE.Vector3();
  const color = new THREE.Color();
  let count = 0;
  for (let candidate = 0; candidate < 180000 && count < capacity; candidate++) {
    // Most detail belongs to the near Peninsula ridges; distant headlands need
    // fewer instances. High-density islands form recognizable woodland canopies.
    const nearRidge = hash(candidate, 4) < 0.72;
    const x = nearRidge
      ? -11800 + hash(candidate, 13) * 9300
      : -16000 + hash(candidate, 13) * 31000;
    const z = nearRidge
      ? -12800 + hash(candidate, 97) * 20800
      : -30500 + hash(candidate, 97) * 42000;
    if (!isLand(x, z)) continue;
    const h = terrainElevation(x, z);
    if (h < 28 || h > 570) continue;
    const grove = fbm(x / 620, z / 620);
    if (grove < 0.55 || hash(candidate, 71) > (grove - 0.48) * 3.0) continue;
    const slope =
      Math.hypot(
        terrainElevation(x + 40, z) - h,
        terrainElevation(x, z + 40) - h,
      ) / 40;
    if (slope > 0.48) continue;
    const size = 7 + hash(candidate, 33) * 10;
    position.set(x, h - 1, z);
    scale.set(
      size,
      size * (1.0 + hash(candidate, 21) * 0.55),
      size * (0.8 + hash(candidate, 18) * 0.35),
    );
    rotation.setFromAxisAngle(
      new THREE.Vector3(0, 1, 0),
      hash(candidate, 26) * Math.PI * 2,
    );
    matrix.compose(position, rotation, scale);
    trees.setMatrixAt(count, matrix);
    color.setHSL(
      0.24 + hash(candidate, 81) * 0.055,
      0.14 + hash(candidate, 61) * 0.13,
      0.12 + hash(candidate, 51) * 0.1,
    );
    trees.setColorAt(count, color);
    count++;
  }
  trees.count = count;
  trees.instanceMatrix.needsUpdate = true;
  if (trees.instanceColor) trees.instanceColor.needsUpdate = true;
  trees.computeBoundingSphere();
  group.add(trees);
  group.userData.vegetationCount = count;
  group.userData.terrainTriangles = group.children.reduce(
    (sum, child) =>
      child instanceof THREE.Mesh && child !== trees
        ? sum +
          (child.geometry.index?.count ??
            child.geometry.getAttribute("position").count) /
            3
        : sum,
    0,
  );

  return {
    group,
    heightAt,
    dispose: () => {
      group.traverse((object) => {
        if (object instanceof THREE.Mesh) object.geometry.dispose();
      });
      terrainMaterial.dispose();
      treeMaterial.dispose();
      bayTexture.dispose();
      sfoTexture.dispose();
    },
  };
}
