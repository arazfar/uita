import * as THREE from "three180";
import { GLTFLoader } from "three180/addons/loaders/GLTFLoader.js";
import { DRACOLoader } from "three180/addons/loaders/DRACOLoader.js";
import { mergeGeometries } from "three180/addons/utils/BufferGeometryUtils.js";

type Coord = [number, number];
type Feature = {
  properties: Record<string, string>;
  geometry: { type: string; coordinates: Coord[] | Coord[][] };
};
const SURFACE = 3;
const east = (lon: number) => (lon + 122.3826) * 88288.08474587766;
const south = (lat: number) => -(lat - 37.6164) * 110989.20390546018;
const point = ([lon, lat]: Coord) => new THREE.Vector2(east(lon), south(lat));

/** Real airport footprints with procedural surface and facade detail. Units are metres, x east and z south. */
export async function createAirport(): Promise<{
  group: THREE.Group;
  dispose: () => void;
}> {
  const group = new THREE.Group();
  group.name = "SFO airport · OSM footprints, schematic procedural detail";
  const draco = new DRACOLoader().setDecoderPath(
    "/candidates/sfo-pack/vendor/three@0.170.0/addons/libs/draco/gltf/",
  );
  const loader = new GLTFLoader().setDRACOLoader(draco);
  const materials: THREE.Material[] = [];
  const geometries: THREE.BufferGeometry[] = [];
  const textures: THREE.Texture[] = [];
  const standard = (
    color: number,
    options: Partial<THREE.MeshStandardMaterialParameters> = {},
  ) => {
    const mat = new THREE.MeshStandardMaterial({
      color,
      roughness: 0.92,
      ...options,
    });
    materials.push(mat);
    return mat;
  };
  const surfaceTexture = (dark: boolean) => {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 256;
    const ctx = canvas.getContext("2d")!;
    let seed = dark ? 304 : 907;
    const rand = () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 4294967296;
    };
    ctx.fillStyle = dark ? "#aaa9a4" : "#d6d2c4";
    ctx.fillRect(0, 0, 256, 256);
    const data = ctx.getImageData(0, 0, 256, 256);
    for (let i = 0; i < data.data.length; i += 4) {
      const d = (rand() - 0.5) * 22;
      data.data[i] += d;
      data.data[i + 1] += d;
      data.data[i + 2] += d;
    }
    ctx.putImageData(data, 0, 0);
    if (!dark) {
      ctx.strokeStyle = "#99998f";
      ctx.lineWidth = 0.6;
      ctx.strokeRect(0, 0, 256, 256);
      ctx.beginPath();
      ctx.moveTo(128, 0);
      ctx.lineTo(128, 256);
      ctx.moveTo(0, 128);
      ctx.lineTo(256, 128);
      ctx.stroke();
    }
    const texture = new THREE.CanvasTexture(canvas);
    texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = 8;
    textures.push(texture);
    return texture;
  };
  const asphalt = standard(0x757b77, {
    map: surfaceTexture(true),
    roughness: 0.96,
  });
  const taxiMat = standard(0xa0a394, { map: asphalt.map });
  const apron = standard(0xc4c0ae, { map: surfaceTexture(false) });
  const paint = standard(0xe2dfce, { roughness: 0.92 });
  const yellow = standard(0xbba76b, { roughness: 0.9 });
  const shoulder = standard(0x84867b);
  const batches = new Map<THREE.Material, THREE.BufferGeometry[]>();
  function addGeometry(g: THREE.BufferGeometry, mat: THREE.Material) {
    const p = g.getAttribute("position");
    const uv: number[] = [];
    for (let i = 0; i < p.count; i++) uv.push(p.getX(i) / 32, p.getZ(i) / 32);
    g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
    g.computeVertexNormals();
    (batches.get(mat) ?? (batches.set(mat, []), batches.get(mat)!)).push(g);
  }
  function strip(
    a: THREE.Vector2,
    b: THREE.Vector2,
    width: number,
    y: number,
    mat: THREE.Material,
  ) {
    const dx = b.x - a.x,
      dz = b.y - a.y,
      length = Math.hypot(dx, dz);
    if (length < 0.01) return;
    const nx = ((-dz / length) * width) / 2,
      nz = ((dx / length) * width) / 2;
    const g = new THREE.BufferGeometry();
    g.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(
        [
          a.x + nx,
          y,
          a.y + nz,
          b.x - nx,
          y,
          b.y - nz,
          a.x - nx,
          y,
          a.y - nz,
          a.x + nx,
          y,
          a.y + nz,
          b.x + nx,
          y,
          b.y + nz,
          b.x - nx,
          y,
          b.y - nz,
        ],
        3,
      ),
    );
    // ENU surface triangles face upward for one-sided physically lit materials.
    addGeometry(g, mat);
  }
  function polyline(
    coords: Coord[],
    width: number,
    y: number,
    mat: THREE.Material,
  ) {
    for (let i = 1; i < coords.length; i++)
      strip(point(coords[i - 1]), point(coords[i]), width, y, mat);
  }
  function polygon(coords: Coord[][], y: number, mat: THREE.Material) {
    const shape = new THREE.Shape(
      coords[0].map((c) => new THREE.Vector2(east(c[0]), -south(c[1]))),
    );
    for (const hole of coords.slice(1))
      shape.holes.push(
        new THREE.Path(
          hole.map((c) => new THREE.Vector2(east(c[0]), -south(c[1]))),
        ),
      );
    const g = new THREE.ShapeGeometry(shape);
    g.rotateX(-Math.PI / 2);
    g.translate(0, y, 0);
    addGeometry(g, mat);
  }
  const response = await fetch("/candidates/data/airports.geojson");
  if (!response.ok)
    throw new Error(`Airport geometry unavailable (${response.status})`);
  const data = (await response.json()) as { features: Feature[] };
  const runways = new Map<string, Coord[]>();
  for (const f of data.features) {
    if (f.properties.airport !== "SFO") continue;
    const { kind } = f.properties;
    if (kind === "apron" && f.geometry.type === "Polygon")
      polygon(f.geometry.coordinates as Coord[][], SURFACE + 0.03, apron);
    if (kind === "taxiway" && f.geometry.type === "LineString") {
      const c = f.geometry.coordinates as Coord[];
      const width = Math.max(
        15,
        Math.min(32, Number(f.properties.width) || 23),
      );
      polyline(c, width + 5, SURFACE + 0.07, shoulder);
      polyline(c, width, SURFACE + 0.11, taxiMat);
      polyline(c, 0.55, SURFACE + 0.14, yellow);
    }
    if (kind === "runway" && f.geometry.type === "LineString") {
      const c = f.geometry.coordinates as Coord[];
      polyline(
        c,
        (Number(f.properties.width) || 61) + 8,
        SURFACE + 0.18,
        shoulder,
      );
      polyline(c, Number(f.properties.width) || 61, SURFACE + 0.2, asphalt);
      const ref = f.properties.ref;
      runways.set(ref, [...(runways.get(ref) || []), ...c]);
    }
  }
  function runwayNumber(
    text: string,
    center: THREE.Vector2,
    direction: THREE.Vector2,
  ) {
    const canvas = document.createElement("canvas");
    canvas.width = 128;
    canvas.height = 192;
    const ctx = canvas.getContext("2d")!;
    const match = text.match(/(\d+)([LR]?)/);
    if (!match) return;
    ctx.fillStyle = "#e2dfce";
    ctx.textAlign = "center";
    ctx.font = "bold 104px Arial, sans-serif";
    ctx.fillText(match[1].replace(/^0/, ""), 64, 102);
    ctx.font = "bold 68px Arial, sans-serif";
    ctx.fillText(match[2], 64, 174);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = 8;
    textures.push(texture);
    const mat = new THREE.MeshStandardMaterial({
      map: texture,
      transparent: true,
      alphaTest: 0.2,
      roughness: 0.95,
      depthWrite: false,
    });
    materials.push(mat);
    const geo = new THREE.PlaneGeometry(17, 32);
    geometries.push(geo);
    const label = new THREE.Mesh(geo, mat);
    label.rotation.x = -Math.PI / 2;
    // Plane top points into the runway, matching the view of an aircraft landing at this threshold.
    label.rotateZ(Math.atan2(-direction.x, -direction.y));
    label.position.set(center.x, SURFACE + 0.31, center.y);
    group.add(label);
  }
  const lights: THREE.Vector3[] = [];
  for (const [ref, coords] of runways) {
    const pts = coords.map(point);
    let A = pts[0],
      B = pts[1],
      length = 0;
    // OSM splits a runway into several ways. Mark only the union's farthest endpoints.
    for (let i = 0; i < pts.length; i++)
      for (let j = i + 1; j < pts.length; j++) {
        const dist = pts[i].distanceTo(pts[j]);
        if (dist > length) {
          length = dist;
          A = pts[i];
          B = pts[j];
        }
      }
    const dir = B.clone().sub(A).normalize(),
      normal = new THREE.Vector2(-dir.y, dir.x);
    const at = (d: number, side = 0) =>
      A.clone().addScaledVector(dir, d).addScaledVector(normal, side);
    for (let d = 90; d < length - 90; d += 60)
      strip(
        at(d),
        at(Math.min(d + 30, length - 90)),
        1.2,
        SURFACE + 0.26,
        paint,
      );
    for (const sign of [-1, 1])
      strip(
        at(0, sign * 28.5),
        at(length, sign * 28.5),
        0.9,
        SURFACE + 0.27,
        paint,
      );
    for (const end of [0, length]) {
      const s = end === 0 ? 1 : -1;
      const inward = dir.clone().multiplyScalar(s);
      const magneticHeading =
        ((Math.atan2(inward.x, -inward.y) * 180) / Math.PI - 13 + 720) % 360;
      const designations = ref.split("/");
      const angularDifference = (name: string) =>
        Math.abs(
          ((Number.parseInt(name, 10) * 10 - magneticHeading + 540) % 360) -
            180,
        );
      const designation = designations.sort(
        (a, b) => angularDifference(a) - angularDifference(b),
      )[0];
      runwayNumber(designation, at(end + s * 80), inward);
      for (let n = -5; n <= 5; n++)
        if (n !== 0)
          strip(
            at(end + s * 9, n * 4.7),
            at(end + s * 48, n * 4.7),
            2.3,
            SURFACE + 0.28,
            paint,
          );
      for (const side of [-1, 1])
        strip(
          at(end + s * 260, side * 18),
          at(end + s * 310, side * 18),
          6,
          SURFACE + 0.28,
          paint,
        );
    }
    for (let d = 0; d < length; d += 58)
      for (const side of [-1, 1]) {
        const p = at(d, side * 33);
        lights.push(new THREE.Vector3(p.x, SURFACE + 1, p.y));
      }
    group.userData.runways ??= [];
    group.userData.runways.push({
      ref,
      start: [A.x, A.y],
      end: [B.x, B.y],
      length,
    });
  }
  for (const [mat, parts] of batches) {
    const unindexed = parts.map((p) => (p.index ? p.toNonIndexed() : p));
    const merged = mergeGeometries(unindexed);
    new Set([...parts, ...unindexed]).forEach((p) => p.dispose());
    if (merged) {
      const mesh = new THREE.Mesh(merged, mat);
      mesh.receiveShadow = true;
      group.add(mesh);
      geometries.push(merged);
    }
  }
  const lightGeo = new THREE.SphereGeometry(0.8, 5, 4);
  geometries.push(lightGeo);
  const lightMat = standard(0xf1e7c4, {
    emissive: 0xe8c982,
    emissiveIntensity: 0.7,
  });
  const edgeLights = new THREE.InstancedMesh(lightGeo, lightMat, lights.length);
  const matrix = new THREE.Matrix4();
  lights.forEach((p, i) =>
    edgeLights.setMatrixAt(i, matrix.makeTranslation(p.x, p.y, p.z)),
  );
  group.add(edgeLights);

  const [buildings, detail] = await Promise.all([
    loader.loadAsync("/candidates/sfo-pack/sfo-buildings.glb"),
    loader.loadAsync("/candidates/assets/overview/airport-detail.glb"),
  ]);
  const colors: Record<string, number> = {
    building: 0xb4b0a0,
    downtown: 0x858b82,
    hangar: 0x939b94,
    parking: 0x7e827b,
    residential: 0xb2ac92,
    terminal: 0xc3c3b5,
  };
  buildings.scene.traverse((obj) => {
    if (!(obj instanceof THREE.Mesh)) return;
    // The broad pack contains San Francisco; the airport view uses local buildings only.
    const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
    geometries.push(obj.geometry);
    materials.push(...mats);
    if (obj.name === "downtown" || obj.name === "tower") {
      obj.visible = false;
      return;
    }
    for (const mat of mats)
      if (mat instanceof THREE.MeshStandardMaterial) {
        mat.color.setHex(colors[mat.name] ?? 0xb5b2a4);
        mat.roughness = 0.86;
        mat.metalness = 0.04;
        mat.side = THREE.FrontSide;
      }
    obj.castShadow = true;
    obj.receiveShadow = true;
  });
  detail.scene.traverse((obj) => {
    if (obj instanceof THREE.Mesh) {
      obj.castShadow = true;
      obj.receiveShadow = true;
      geometries.push(obj.geometry);
      const ms = Array.isArray(obj.material) ? obj.material : [obj.material];
      materials.push(...ms);
    }
  });
  buildings.scene.position.y = detail.scene.position.y = SURFACE + 0.3;
  group.add(buildings.scene, detail.scene);
  group.userData.sources = [
    "© OpenStreetMap contributors",
    "Blender procedural facade detail: schematic",
  ];
  draco.dispose();
  return {
    group,
    dispose() {
      group.removeFromParent();
      new Set(geometries).forEach((g) => g.dispose());
      new Set(materials).forEach((m) => m.dispose());
      textures.forEach((t) => t.dispose());
      draco.dispose();
    },
  };
}
