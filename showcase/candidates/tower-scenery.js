import { createTerrain } from "./tower-terrain.generated.js";

const ROOT = "/candidates/assets/tower-realism/";
const smooth = (a, b, v) => {
  const t = Math.max(0, Math.min(1, (v - a) / (b - a)));
  return t * t * (3 - 2 * t);
};
const local = ([lon, lat]) => [
  (lon + 122.3826) * 88288.08474587766,
  -(lat - 37.6164) * 110989.20390546018,
];

/** Numeric terrain samples are scenery only; never modify flight altitude or runway datum. */
async function elevationSampler() {
  const [metadata, response] = await Promise.all([
    fetch(ROOT + "terrain/manifest.json").then((r) => {
      if (!r.ok) throw Error("Terrain metadata unavailable");
      return r.json();
    }),
    fetch(ROOT + "terrain/bay-elevation.i16"),
  ]);
  if (!response.ok) throw Error("Terrain heights unavailable");
  const raw = await response.arrayBuffer(),
    { size, extent } = metadata;
  if (raw.byteLength !== size * size * 2)
    throw Error("Terrain grid has the wrong size");
  const data = new DataView(raw),
    [west, north, east, south] = extent;
  const at = (i, j) => data.getInt16((j * size + i) * 2, true);
  const sample = (x, z) => {
    const u = Math.max(
      0,
      Math.min(size - 1.001, ((x - west) / (east - west)) * (size - 1)),
    );
    const v = Math.max(
      0,
      Math.min(size - 1.001, ((z - north) / (south - north)) * (size - 1)),
    );
    const i = Math.floor(u),
      j = Math.floor(v),
      fx = u - i,
      fy = v - j;
    const value =
      (at(i, j) * (1 - fx) + at(i + 1, j) * fx) * (1 - fy) +
      (at(i, j + 1) * (1 - fx) + at(i + 1, j + 1) * fx) * fy;
    // The airport stays at the existing simulation ground plane. Outside it,
    // sampled terrain is unexaggerated, with a smooth transition at the boundary.
    const airportDistance = Math.max(
      Math.abs((x - 150) / 3000),
      Math.abs((z + 500) / 3300),
    );
    return Math.max(0, value - 4) * smooth(0.95, 1.35, airportDistance);
  };
  return { sample, metadata };
}

function surfaceTexture(THREE, kind) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 512;
  const ctx = canvas.getContext("2d");
  const data = ctx.createImageData(512, 512);
  let seed = 17017;
  const random = () => {
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  };
  for (let y = 0; y < 512; y++)
    for (let x = 0; x < 512; x++) {
      const p = (y * 512 + x) * 4;
      const seam = kind === "concrete" && (x % 128 < 2 || y % 128 < 2);
      const v =
        (kind === "concrete" ? 194 : 152) +
        (random() - 0.5) * 24 -
        (seam ? 40 : 0);
      data.data.set([v, v, v - (kind === "concrete" ? 6 : 0), 255], p);
    }
  ctx.putImageData(data, 0, 0);
  const texture = new THREE.CanvasTexture(canvas);
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  return texture;
}

/** An offline scene. Footprints and imagery are geographic; facade detail is authored. */
export async function createTowerScenery(
  THREE,
  { airports, loader, originalBuildings, sunDirection },
) {
  const group = new THREE.Group();
  group.name = "SFO detailed scenery";
  const info = {
    ready: false,
    terrain: null,
    buildings: false,
    reflections: false,
  };
  group.userData = info;
  const textures = [],
    ownedMaterials = new Set();
  let terrain = null;
  const dispose = () => {
    group.removeFromParent();
    terrain?.group.removeFromParent();
    terrain?.dispose();
    group.traverse((o) => {
      if (!o.isMesh) return;
      o.geometry.dispose();
      for (const m of [o.material].flat()) {
        for (const value of Object.values(m))
          if (value?.isTexture) textures.push(value);
        ownedMaterials.add(m);
      }
    });
    for (const m of ownedMaterials) m.dispose();
    for (const t of new Set(textures)) t.dispose();
  };
  try {
    const { sample, metadata } = await elevationSampler();
    terrain = await createTerrain({
      elevationAt: sample,
      surfaceHeight: 0,
      provenance:
        "Mapzen / USGS sampled terrain; US Census shoreline; USGS NAIP imagery. Airport flattened to the existing local datum. Vegetation is illustrative.",
    });
    group.add(terrain.group);
    info.terrain = {
      size: metadata.size,
      source: metadata.source,
      triangles: terrain.group.userData.terrainTriangles,
    };
    const airport = new THREE.Group();
    airport.name = "Blender airport architecture";
    group.add(airport);
    const detailed = await loader.loadAsync(ROOT + "airport-detail.glb");
    const roofMaterials = new Set();
    detailed.scene.traverse((o) => {
      if (!o.isMesh) return;
      o.castShadow = true;
      o.receiveShadow = true;
      for (const m of [o.material].flat())
        if (m.name.includes("weathered roof")) roofMaterials.add(m);
    });
    for (const material of roofMaterials) {
      material.onBeforeCompile = (shader) => {
        shader.vertexShader = "varying vec3 roofPoint;\n" + shader.vertexShader;
        shader.vertexShader = shader.vertexShader.replace(
          "#include <begin_vertex>",
          "#include <begin_vertex>\nroofPoint = (modelMatrix * vec4(position, 1.0)).xyz;",
        );
        shader.fragmentShader =
          "varying vec3 roofPoint;\n" + shader.fragmentShader;
        shader.fragmentShader = shader.fragmentShader.replace(
          "#include <color_fragment>",
          `#include <color_fragment>
        vec2 seam = abs(fract(roofPoint.xz / 6.0) - .5);
        vec2 aa = max(fwidth(roofPoint.xz / 6.0), vec2(.002));
        float joint = max(smoothstep(.49-aa.x,.5,seam.x), smoothstep(.49-aa.y,.5,seam.y));
        float stain = sin(roofPoint.x*.071 + sin(roofPoint.z*.13))*sin(roofPoint.z*.057)*.065;
        diffuseColor.rgb *= 1.0 + stain - joint*.13;`,
        );
      };
      material.customProgramCacheKey = () => "tower-roof-weathering-v1";
    }
    airport.add(detailed.scene);
    info.buildings = true;
    // Keep the original remote city massing; the new asset replaces only airport buildings.
    originalBuildings.traverse((o) => {
      if (o.isMesh && /^(downtown|residential)/.test(o.name)) {
        const copy = o.clone();
        copy.geometry = o.geometry.clone();
        copy.material = new THREE.MeshStandardMaterial({
          color: 0xa4a6a0,
          roughness: 0.85,
        });
        ownedMaterials.add(copy.material);
        group.add(copy);
      }
    });
    const concrete = surfaceTexture(THREE, "concrete"),
      asphalt = surfaceTexture(THREE, "asphalt");
    textures.push(concrete, asphalt);
    const apronMaterial = new THREE.MeshStandardMaterial({
      map: concrete,
      color: 0xb2b0a2,
      roughness: 0.92,
      bumpMap: concrete,
      bumpScale: 0.035,
    });
    const taxiMaterial = new THREE.MeshStandardMaterial({
      map: asphalt,
      color: 0xd8dad3,
      roughness: 0.94,
      bumpMap: asphalt,
      bumpScale: 0.018,
    });
    const yellow = new THREE.MeshStandardMaterial({
      color: 0xc4aa58,
      roughness: 0.83,
    });
    [apronMaterial, taxiMaterial, yellow].forEach((m) => ownedMaterials.add(m));
    const { mergeGeometries } = await import(
      /* @vite-ignore */ location.origin +
        "/vendor/three/examples/jsm/utils/BufferGeometryUtils.js"
    );
    const apronParts = [],
      taxiParts = [],
      yellowParts = [];
    const uvWorld = (geometry) => {
      const p = geometry.attributes.position,
        uv = [];
      for (let i = 0; i < p.count; i++) uv.push(p.getX(i) / 32, p.getZ(i) / 32);
      geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
      return geometry;
    };
    const strip = (a, b, width, height) => {
      const dx = b[0] - a[0],
        dz = b[1] - a[1],
        length = Math.hypot(dx, dz);
      if (length < 0.1) return null;
      const g = new THREE.PlaneGeometry(width, length);
      g.rotateX(-Math.PI / 2);
      g.rotateY(Math.atan2(dx, dz));
      g.translate((a[0] + b[0]) / 2, height, (a[1] + b[1]) / 2);
      return uvWorld(g);
    };
    for (const feature of airports) {
      if (
        feature.properties.kind === "apron" &&
        feature.geometry.type === "Polygon"
      ) {
        const rings = feature.geometry.coordinates;
        const shape = new THREE.Shape(
          rings[0].map((c) => {
            const [x, z] = local(c);
            return new THREE.Vector2(x, -z);
          }),
        );
        for (const ring of rings.slice(1))
          shape.holes.push(
            new THREE.Path(
              ring.map((c) => {
                const [x, z] = local(c);
                return new THREE.Vector2(x, -z);
              }),
            ),
          );
        const g = new THREE.ShapeGeometry(shape);
        g.rotateX(-Math.PI / 2);
        g.translate(0, 0.015, 0);
        apronParts.push(uvWorld(g));
      }
      if (
        feature.properties.kind === "taxiway" &&
        feature.geometry.type === "LineString"
      ) {
        const points = feature.geometry.coordinates.map(local);
        for (let i = 1; i < points.length; i++) {
          const surface = strip(points[i - 1], points[i], 20, 0.022);
          if (surface) {
            taxiParts.push(surface);
            yellowParts.push(strip(points[i - 1], points[i], 0.32, 0.034));
          }
        }
      }
    }
    for (const [parts, material, name] of [
      [apronParts, apronMaterial, "Concrete apron slabs"],
      [taxiParts, taxiMaterial, "Taxiway surfaces"],
      [yellowParts, yellow, "Taxiway centerlines"],
    ]) {
      if (!parts.length) continue;
      const merged = mergeGeometries(parts);
      parts.forEach((g) => g.dispose());
      const mesh = new THREE.Mesh(merged, material);
      mesh.name = name;
      mesh.receiveShadow = true;
      group.add(mesh);
    }
    // Fixed sun-projected architecture shadows: one low-cost geometry instead of
    // a kilometre-wide dynamic shadow map. No simulated traffic is baked into it.
    const shadowVertices = [],
      shadowHeight = 0.041;
    detailed.scene.updateMatrixWorld(true);
    detailed.scene.traverse((o) => {
      if (!o.isMesh || !/^(terminal|hangar|parking|building)/.test(o.name))
        return;
      const p = o.geometry.attributes.position,
        ix = o.geometry.index;
      const point = new THREE.Vector3();
      for (let j = 0; j < (ix?.count ?? p.count); j++) {
        point
          .fromBufferAttribute(p, ix ? ix.getX(j) : j)
          .applyMatrix4(o.matrixWorld);
        shadowVertices.push(
          point.x - (sunDirection.x / sunDirection.y) * point.y,
          shadowHeight,
          point.z - (sunDirection.z / sunDirection.y) * point.y,
        );
      }
    });
    const shadowGeometry = new THREE.BufferGeometry();
    shadowGeometry.setAttribute(
      "position",
      new THREE.Float32BufferAttribute(shadowVertices, 3),
    );
    const shadowMaterial = new THREE.MeshBasicMaterial({
      color: 0x222e35,
      transparent: true,
      opacity: 0.24,
      depthWrite: true,
      depthFunc: THREE.LessDepth,
      side: THREE.DoubleSide,
    });
    ownedMaterials.add(shadowMaterial);
    const shadow = new THREE.Mesh(shadowGeometry, shadowMaterial);
    shadow.name = "Fixed daylight architecture shadows";
    group.add(shadow);

    // Original periodic wave data; no remote normal-map dependency.
    const size = 256,
      normalBytes = new Uint8Array(size * size * 4);
    const hash = (x, y) => {
      let n = Math.imul(x & 63, 374761393) + Math.imul(y & 63, 668265263);
      n = Math.imul(n ^ (n >>> 13), 1274126177);
      return ((n ^ (n >>> 16)) >>> 0) / 4294967295;
    };
    const noise = (x, y) => {
      const ix = Math.floor(x),
        iy = Math.floor(y),
        fx = smooth(0, 1, x - ix),
        fy = smooth(0, 1, y - iy);
      return (
        (hash(ix, iy) * (1 - fx) + hash(ix + 1, iy) * fx) * (1 - fy) +
        (hash(ix, iy + 1) * (1 - fx) + hash(ix + 1, iy + 1) * fx) * fy
      );
    };
    const wave = (x, y) =>
      noise(x / 4, y / 4) * 0.6 + noise(x / 2, y / 2) * 0.3 + noise(x, y) * 0.1;
    for (let y = 0; y < size; y++)
      for (let x = 0; x < size; x++) {
        const nx = (wave(x + 1, y) - wave(x - 1, y)) * 1.9;
        const ny = (wave(x, y + 1) - wave(x, y - 1)) * 1.9;
        const n = new THREE.Vector3(nx, ny, 1).normalize(),
          i = (y * size + x) * 4;
        normalBytes.set(
          [(n.x + 1) * 127.5, (n.y + 1) * 127.5, (n.z + 1) * 127.5, 255],
          i,
        );
      }
    const normalMap = new THREE.DataTexture(
      normalBytes,
      size,
      size,
      THREE.RGBAFormat,
    );
    normalMap.wrapS = normalMap.wrapT = THREE.RepeatWrapping;
    normalMap.magFilter = THREE.LinearFilter;
    normalMap.minFilter = THREE.LinearMipmapLinearFilter;
    normalMap.generateMipmaps = true;
    normalMap.needsUpdate = true;
    textures.push(normalMap);
    // Use the filtered sky environment for stable, rough reflections at tower distance.
    // A planar reflection pass aliases the kilometre-scale shoreline at grazing angles.
    normalMap.repeat.set(3600, 3600);
    normalMap.anisotropy = 8;
    const water = new THREE.Mesh(
      new THREE.PlaneGeometry(180000, 180000),
      new THREE.MeshPhysicalMaterial({
        color: 0x426b72,
        roughness: 0.27,
        metalness: 0.36,
        normalMap,
        normalScale: new THREE.Vector2(0.23, 0.23),
        envMapIntensity: 1.15,
        clearcoat: 0.3,
        clearcoatRoughness: 0.23,
      }),
    );
    water.name = "San Francisco Bay · sky reflections";
    water.rotation.x = -Math.PI / 2;
    water.position.y = -0.35;
    group.add(water);
    info.reflections = "filtered sky environment";
    info.ready = true;
    return {
      group,
      terrain,
      water,
      update(seconds) {
        const time = Number.isFinite(seconds) ? seconds : 0;
        normalMap.offset.set(time * 0.002, time * 0.0009);
      },
      dispose,
    };
  } catch (error) {
    dispose();
    throw error;
  }
}
