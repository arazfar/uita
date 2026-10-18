import * as THREE from "three180";
import counties from "../bay-geometry.json";

type Ring = number[][];
type Polygon = Ring[];
type County = {
  properties: { name: string };
  geometry:
    | { type: "Polygon"; coordinates: Polygon }
    | { type: "MultiPolygon"; coordinates: Polygon[] };
};

const ORIGIN_LON = -122.3826;
const ORIGIN_LAT = 37.6164;
const METRES_LON = 88288.08474587766;
const METRES_LAT = 110989.20390546018;

// This exclusion matches the measured coastline asset's full geographic bounds.
// Only the detailed terrain owns land and water within that rectangle.
const LOCAL_BOUNDS = new THREE.Vector4(
  (-122.65 - ORIGIN_LON) * METRES_LON,
  (-122.0 - ORIGIN_LON) * METRES_LON,
  -(38.05 - ORIGIN_LAT) * METRES_LAT,
  -(37.45 - ORIGIN_LAT) * METRES_LAT,
);

function projectedRing(ring: Ring): THREE.Vector2[] {
  // ShapeGeometry lies in XY before rotation; positive Y becomes northward -Z.
  const points = ring.map(
    ([lon, lat]) =>
      new THREE.Vector2(
        (lon - ORIGIN_LON) * METRES_LON,
        (lat - ORIGIN_LAT) * METRES_LAT,
      ),
  );
  if (points.length > 1 && points[0].equals(points[points.length - 1]))
    points.pop();
  return points;
}

/** Flat regional context from the existing coarse county map, not a terrain DEM. */
export function createRegionalGround(): {
  group: THREE.Group;
  dispose: () => void;
} {
  const group = new THREE.Group();
  group.name = "Bay Area regional ground · simplified county map";
  group.userData.provenance =
    "US Atlas counties-10m: simplified US Census cartographic county boundaries, 2017 edition. Flat regional context only, with approximate shorelines and no measured elevation.";
  group.userData.source = "https://github.com/topojson/us-atlas";
  group.userData.lonLatBounds = [-123.53482, 36.89739, -121.20896, 38.86464];

  const material = new THREE.MeshStandardMaterial({
    color: "#858774",
    roughness: 1,
    metalness: 0,
  });
  material.onBeforeCompile = (shader) => {
    shader.uniforms.localGroundBounds = { value: LOCAL_BOUNDS };
    shader.vertexShader = shader.vertexShader
      .replace(
        "#include <common>",
        "#include <common>\nvarying vec2 vRegionalXZ;",
      )
      .replace(
        "#include <begin_vertex>",
        "#include <begin_vertex>\nvRegionalXZ = (modelMatrix * vec4(transformed, 1.0)).xz;",
      );
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        "#include <common>\nvarying vec2 vRegionalXZ;\nuniform vec4 localGroundBounds;",
      )
      .replace(
        "#include <clipping_planes_fragment>",
        `#include <clipping_planes_fragment>
        if (vRegionalXZ.x >= localGroundBounds.x &&
            vRegionalXZ.x <= localGroundBounds.y &&
            vRegionalXZ.y >= localGroundBounds.z &&
            vRegionalXZ.y <= localGroundBounds.w) discard;`,
      );
  };
  material.customProgramCacheKey = () => "uita-regional-ground-local-exclusion-v1";

  const geometries: THREE.BufferGeometry[] = [];
  for (const county of counties.features as County[]) {
    const polygons =
      county.geometry.type === "Polygon"
        ? [county.geometry.coordinates]
        : county.geometry.coordinates;
    for (const polygon of polygons) {
      const outer = projectedRing(polygon[0] ?? []);
      // The bundled map includes a collapsed, two-point San Francisco island.
      if (outer.length < 3 || Math.abs(THREE.ShapeUtils.area(outer)) < 1) continue;
      const shape = new THREE.Shape(outer);
      for (const ring of polygon.slice(1)) {
        const hole = projectedRing(ring);
        if (hole.length >= 3 && Math.abs(THREE.ShapeUtils.area(hole)) >= 1)
          shape.holes.push(new THREE.Path(hole));
      }
      const geometry = new THREE.ShapeGeometry(shape);
      geometry.rotateX(-Math.PI / 2);
      geometry.translate(0, 1, 0);
      geometry.computeBoundingSphere();
      geometries.push(geometry);
      const mesh = new THREE.Mesh(geometry, material);
      mesh.name = `${county.properties.name} · flat regional context`;
      group.add(mesh);
    }
  }
  return {
    group,
    dispose() {
      for (const geometry of geometries) geometry.dispose();
      material.dispose();
      group.clear();
    },
  };
}
