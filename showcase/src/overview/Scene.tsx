import { useEffect, useRef } from "react";
import * as THREE from "three180";
import { OrbitControls } from "three180/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three180/addons/loaders/GLTFLoader.js";
import { Sky } from "three180/addons/objects/Sky.js";
import { createTerrain } from "./terrain";
import { createAirport } from "./airport";
import { createRegionalGround } from "./regional";
import type { DisplayTarget } from "./traffic";

type Props = {
  targets: DisplayTarget[];
  cameraRevision: number;
  time: number;
  cameraPreset: "overview" | "approach" | "tower" | "region" | "follow";
  showTracks: boolean;
  showLabels: boolean;
  quality: "high" | "balanced";
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onStatus: (s: { ready: boolean; error?: string; fps: number }) => void;
};
const cameras = {
  overview: { eye: [2400, 1900, 3000], target: [-650, 80, -650] },
  approach: { eye: [2600, 380, 4500], target: [100, 65, -600] },
  tower: { eye: [-100, 110, 60], target: [1900, 20, -600] },
  region: { eye: [13000, 26000, 30000], target: [0, 0, -7000] },
};
function makeWater() {
  const material = new THREE.ShaderMaterial({
    uniforms: {
      uTime: { value: 0 },
      uSun: { value: new THREE.Vector3(-0.6, 0.6, 0.3).normalize() },
    },
    vertexShader: `#include <common>
 #include <logdepthbuf_pars_vertex>
 varying vec3 vWorld; void main(){vec4 world=modelMatrix*vec4(position,1.);vWorld=world.xyz;gl_Position=projectionMatrix*viewMatrix*world;
 #include <logdepthbuf_vertex>
 }`,
    fragmentShader: `uniform float uTime; uniform vec3 uSun; varying vec3 vWorld;
 #include <logdepthbuf_pars_fragment>
 float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
 float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(hash(i),hash(i+vec2(1.,0.)),f.x),mix(hash(i+vec2(0.,1.)),hash(i+1.),f.x),f.y);}
 float waves(vec2 p,float t){return noise(p*.012+vec2(t,-t*.3))*.55+noise(p*.031-vec2(t*.4,t*.8))*.3+noise(p*.08+vec2(t*.3,t*.2))*.15;}
 void main(){vec2 p=vWorld.xz; float t=uTime*.035;
 #include <logdepthbuf_fragment>
 float h=waves(p,t);vec3 n=normalize(vec3((h-waves(p+vec2(3.,0.),t))*.85,1.,(h-waves(p+vec2(0.,3.),t))*.85));
 vec3 v=normalize(cameraPosition-vWorld);float fres=pow(1.-max(dot(v,n),0.),4.);
 float shade=noise(p*.0006);
 vec3 deep=mix(vec3(.075,.17,.16),vec3(.12,.24,.22),shade);
 vec3 col=mix(deep,vec3(.58,.67,.66),fres*.8);
 float spec=pow(max(dot(reflect(-uSun,n),v),0.),180.); col+=vec3(1.,.88,.65)*spec*.35;
 float dist=length(cameraPosition-vWorld);col=mix(col,vec3(.68,.72,.69),smoothstep(18000.,65000.,dist));
 gl_FragColor=vec4(col,1.);
 #include <tonemapping_fragment>
 #include <colorspace_fragment>
 }`,
  });
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(600000, 600000),
    material,
  );
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = 0;
  mesh.name = "San Francisco Bay";
  return { mesh, material };
}
export function Scene(props: Props) {
  const container = useRef<HTMLDivElement>(null),
    current = useRef(props);
  current.current = props;
  useEffect(() => {
    const host = container.current!;
    let disposed = false,
      frame = 0,
      ready = false,
      contextLost = false,
      landscapeReady = false,
      landscapeFailed = false;
    type LandscapePart = { group: THREE.Group; dispose: () => void };
    const landscapeParts: LandscapePart[] = [];
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        logarithmicDepthBuffer: true,
        powerPreference: "high-performance",
      });
    } catch {
      props.onStatus({
        ready: false,
        error: "3D graphics unavailable. Traffic records remain accessible.",
        fps: 0,
      });
      return;
    }
    renderer.setPixelRatio(
      Math.min(devicePixelRatio, props.quality === "high" ? 1.75 : 1),
    );
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.84;
    renderer.shadowMap.enabled = props.quality === "high";
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.domElement.setAttribute(
      "aria-label",
      "Interactive SFO landscape. Drag to orbit, scroll to zoom. Use camera buttons for keyboard access.",
    );
    renderer.domElement.style.cssText =
      "display:block;width:100%;height:100%;touch-action:none";
    host.prepend(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#c3cabc");
    scene.fog = new THREE.Fog("#bac4b5", 24000, 75000);
    const camera = new THREE.PerspectiveCamera(42, 1, 2, 500000);
    camera.position.fromArray(cameras.overview.eye);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.fromArray(cameras.overview.target);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = 100;
    controls.maxDistance = 300000;
    controls.maxPolarAngle = Math.PI * 0.485;
    controls.zoomToCursor = true;
    controls.update();
    scene.add(new THREE.HemisphereLight("#dce5e0", "#656043", 0.65));
    const sun = new THREE.DirectionalLight("#fff0d2", 2.7);
    sun.position.set(-4500, 3600, -3000);
    sun.target.position.set(0, 0, 0);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, {
      left: -4200,
      right: 4200,
      top: 4200,
      bottom: -4200,
      near: 100,
      far: 16000,
    });
    sun.shadow.normalBias = 3;
    sun.shadow.bias = -0.0002;
    scene.add(sun, sun.target);
    const sky = new Sky();
    sky.scale.setScalar(100000);
    sky.material.uniforms.turbidity.value = 3;
    sky.material.uniforms.rayleigh.value = 1.4;
    sky.material.uniforms.mieCoefficient.value = 0.003;
    sky.material.uniforms.mieDirectionalG.value = 0.8;
    sky.material.uniforms.sunPosition.value.copy(sun.position);
    scene.add(sky);
    const pmrem = new THREE.PMREMGenerator(renderer);
    const skyScene = new THREE.Scene();
    skyScene.add(sky.clone());
    const env = pmrem.fromScene(skyScene, 0.04);
    scene.environment = env.texture;
    scene.environmentIntensity = 0.22;
    pmrem.dispose();
    const water = makeWater();
    scene.add(water.mesh);
    const regional = createRegionalGround();
    scene.add(regional.group);
    landscapeParts.push(regional);
    const aircraftGroup = new THREE.Group();
    scene.add(aircraftGroup);
    const aircraft = new Map<string, THREE.Group>();
    const trails = new Map<string, THREE.Line>();
    const labels = new Map<string, HTMLButtonElement>();
    const trailKeys = new Map<string, string>();
    const beaconGeometry = new THREE.SphereGeometry(7, 8, 6);
    const beaconMaterial = new THREE.MeshBasicMaterial({ color: "#e8e3d5" });
    let model: THREE.Group | null = null;
    let shownTargets: DisplayTarget[] | null = null;
    const labelLayer = document.createElement("div");
    labelLayer.style.cssText =
      "position:absolute;inset:0;pointer-events:none;overflow:hidden";
    host.append(labelLayer);
    // Window changes replace the active targets; GPU resources remain bounded to that window.
    function syncTargets(targets: DisplayTarget[]) {
      const ids = new Set(targets.map((target) => target.id));
      for (const [id, group] of aircraft) {
        if (ids.has(id)) continue;
        group.removeFromParent();
        aircraft.delete(id);
        const line = trails.get(id)!;
        line.removeFromParent();
        line.geometry.dispose();
        (line.material as THREE.Material).dispose();
        trails.delete(id);
        trailKeys.delete(id);
        labels.get(id)?.remove();
        labels.delete(id);
      }
      for (const target of targets) {
        let group = aircraft.get(target.id);
        if (!group) {
          group = new THREE.Group();
          group.userData.targetId = target.id;
          group.add(new THREE.Mesh(beaconGeometry, beaconMaterial));
          if (model) group.add(model.clone(true));
          aircraftGroup.add(group);
          aircraft.set(target.id, group);
          const line = new THREE.Line(
            new THREE.BufferGeometry(),
            new THREE.LineDashedMaterial({
              color: "#a8d5a3",
              transparent: true,
              opacity: 0.45,
              dashSize: 50,
              gapSize: 25,
            }),
          );
          scene.add(line);
          trails.set(target.id, line);
          const button = document.createElement("button");
          button.className = "aircraft-label";
          button.style.pointerEvents = "auto";
          button.onclick = () => current.current.onSelect(target.id);
          labelLayer.append(button);
          labels.set(target.id, button);
        }
        const label = labels.get(target.id)!;
        label.textContent = target.callsign;
        label.setAttribute("aria-label", `Select ${target.callsign}`);
        const key = `${target.trail[0]?.t}:${target.trail.at(-1)?.t}:${target.trail.length}`;
        if (trailKeys.get(target.id) !== key) {
          const line = trails.get(target.id)!;
          line.geometry.dispose();
          line.geometry = new THREE.BufferGeometry().setFromPoints(
            target.trail.map(
              (point) =>
                new THREE.Vector3(point.x, Math.max(8, point.y + 6), point.z),
            ),
          );
          line.computeLineDistances();
          trailKeys.set(target.id, key);
        }
      }
      shownTargets = targets;
    }
    function disposeModel(object: THREE.Object3D) {
      const geometries = new Set<THREE.BufferGeometry>();
      const materials = new Set<THREE.Material>();
      const textures = new Set<THREE.Texture>();
      object.traverse((child) => {
        if (!(child instanceof THREE.Mesh)) return;
        geometries.add(child.geometry);
        for (const material of Array.isArray(child.material)
          ? child.material
          : [child.material]) {
          materials.add(material);
          Object.values(material).forEach((value) => {
            if (value instanceof THREE.Texture) textures.add(value);
          });
        }
      });
      geometries.forEach((geometry) => geometry.dispose());
      materials.forEach((material) => material.dispose());
      textures.forEach((texture) => texture.dispose());
    }
    new GLTFLoader()
      .loadAsync("/candidates/assets/overview/uita-airliner.glb")
      .then((gltf) => {
        if (disposed) {
          disposeModel(gltf.scene);
          return;
        }
        const size = new THREE.Box3()
          .setFromObject(gltf.scene)
          .getSize(new THREE.Vector3());
        gltf.scene.scale.setScalar(42 / Math.max(size.x, size.y, size.z));
        gltf.scene.rotation.y = Math.PI;
        gltf.scene.traverse((object) => {
          if (object instanceof THREE.Mesh) {
            object.castShadow = true;
            object.receiveShadow = true;
          }
        });
        model = gltf.scene;
        for (const group of aircraft.values()) group.add(model.clone(true));
      })
      .catch(() => {});
    const retainPart = (part: LandscapePart) => {
      if (disposed || landscapeFailed) part.dispose();
      else landscapeParts.push(part);
      return part;
    };
    Promise.all([
      createTerrain().then(retainPart),
      createAirport().then(retainPart),
    ])
      .then((parts) => {
        if (disposed) return;
        parts.forEach((p) => scene.add(p.group));
        landscapeReady = true;
        ready = !contextLost;
        if (ready) current.current.onStatus({ ready: true, fps: 0 });
      })
      .catch((error) => {
        landscapeFailed = true;
        landscapeParts.splice(0).forEach((p) => {
          p.group.removeFromParent();
          p.dispose();
        });
        if (!disposed)
          current.current.onStatus({
            ready: false,
            error: `Landscape could not finish loading: ${error.message}. Traffic records remain available.`,
            fps: 0,
          });
      });
    const resize = () => {
      const w = host.clientWidth,
        h = host.clientHeight;
      if (w && h) {
        renderer.setSize(w, h, false);
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
      }
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();
    let cameraRevision = current.current.cameraRevision;
    let preset = current.current.cameraPreset,
      lastQuality = current.current.quality;
    let transition: { eye: THREE.Vector3; target: THREE.Vector3 } | null = null;
    let followActive = false;
    controls.addEventListener("start", () => {
      transition = null;
      followActive = false;
    });
    let documentHidden = document.hidden;
    let shellHidden = false;
    const visibility = () => {
      documentHidden = document.hidden;
    };
    const shellMessage = (event: MessageEvent) => {
      if (event.origin !== location.origin || event.source !== window.parent)
        return;
      if (event.data?.skyflow === "pause") shellHidden = true;
      if (event.data?.skyflow === "resume") shellHidden = false;
    };
    document.addEventListener("visibilitychange", visibility);
    window.addEventListener("message", shellMessage);
    const raycaster = new THREE.Raycaster();
    let press: { x: number; y: number } | null = null;
    const pointerDown = (event: PointerEvent) => {
      press = { x: event.clientX, y: event.clientY };
    };
    const pointerUp = (event: PointerEvent) => {
      if (
        !press ||
        Math.hypot(event.clientX - press.x, event.clientY - press.y) > 5
      )
        return;
      press = null;
      const rect = renderer.domElement.getBoundingClientRect();
      raycaster.setFromCamera(
        new THREE.Vector2(
          ((event.clientX - rect.left) / rect.width) * 2 - 1,
          1 - ((event.clientY - rect.top) / rect.height) * 2,
        ),
        camera,
      );
      const hits = raycaster.intersectObjects(
        [...aircraft.values()].filter((group) => group.visible),
        true,
      );
      let hit: THREE.Object3D | null = hits[0]?.object ?? null;
      while (hit && !hit.userData.targetId) hit = hit.parent;
      if (hit) current.current.onSelect(hit.userData.targetId);
    };
    renderer.domElement.addEventListener("pointerdown", pointerDown);
    renderer.domElement.addEventListener("pointerup", pointerUp);
    let count = 0,
      stamp = performance.now();
    const v = new THREE.Vector3();
    function render(now: number) {
      if (disposed) return;
      const p = current.current;
      if (documentHidden || shellHidden) {
        frame = requestAnimationFrame(render);
        return;
      }
      if (p.targets !== shownTargets) syncTargets(p.targets);
      if (p.quality !== lastQuality) {
        lastQuality = p.quality;
        renderer.setPixelRatio(
          Math.min(devicePixelRatio, p.quality === "high" ? 1.75 : 1),
        );
        renderer.shadowMap.enabled = p.quality === "high";
        resize();
      }
      if (p.cameraPreset !== preset || p.cameraRevision !== cameraRevision) {
        cameraRevision = p.cameraRevision;
        preset = p.cameraPreset;
        followActive = preset === "follow";
        if (preset !== "follow") {
          const c = cameras[preset];
          transition = {
            eye: new THREE.Vector3().fromArray(c.eye),
            target: new THREE.Vector3().fromArray(c.target),
          };
          if (preset === "region" && p.targets.length) {
            const bounds = new THREE.Box3().expandByPoint(new THREE.Vector3());
            p.targets.forEach(({ state }) => {
              if (state.y !== null)
                bounds.expandByPoint(
                  new THREE.Vector3(state.x, state.y, state.z),
                );
            });
            const target = bounds.getCenter(new THREE.Vector3());
            const radius = Math.max(
              10000,
              bounds.getSize(new THREE.Vector3()).length() / 2,
            );
            const field =
              (Math.min(camera.fov, camera.fov * camera.aspect) * Math.PI) /
              180;
            const distance = Math.min(
              280000,
              (radius / Math.sin(field / 2)) * 1.1,
            );
            transition = {
              target,
              eye: target
                .clone()
                .add(new THREE.Vector3(0, distance * 0.92, distance * 0.4)),
            };
          }
        }
      }
      if (followActive) {
        const selected = p.targets.find(
          (target) => target.id === p.selectedId,
        )?.state;
        if (selected?.y != null) {
          const target = new THREE.Vector3(
            selected.x,
            Math.max(18, selected.y + 6),
            selected.z,
          );
          transition = {
            target,
            eye: target.clone().add(new THREE.Vector3(1100, 750, 1500)),
          };
        }
      }
      if (transition) {
        const rate = matchMedia("(prefers-reduced-motion: reduce)").matches
          ? 1
          : 0.075;
        camera.position.lerp(transition.eye, rate);
        controls.target.lerp(transition.target, rate);
        if (camera.position.distanceTo(transition.eye) < 1) transition = null;
      }
      controls.update();
      // Local haze stays subtle when a regional camera has to frame distant observations.
      const distance = camera.position.distanceTo(controls.target);
      (scene.fog as THREE.Fog).near = Math.max(24000, distance * 1.1);
      (scene.fog as THREE.Fog).far = Math.max(75000, distance * 3.5);
      // Relative time avoids float precision loss from UTC epochs in the water shader.
      water.material.uniforms.uTime.value = matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches
        ? 0
        : p.time % 86400;
      const occupied: Array<{ x: number; y: number; width: number }> = [];
      const hostRect = host.getBoundingClientRect();
      const panels = Array.from(
        host
          .closest(".scene-container")
          ?.querySelectorAll(
            ".scene-caption, .scene-help, .data-loading, .data-connection-error",
          ) ?? [],
      ).map((panel) => panel.getBoundingClientRect());
      for (const target of [...p.targets].sort(
        (a, b) => Number(b.id === p.selectedId) - Number(a.id === p.selectedId),
      )) {
        const group = aircraft.get(target.id)!,
          label = labels.get(target.id)!,
          line = trails.get(target.id)!;
        const state = target.state;
        const visible = state.y !== null;
        group.visible = visible;
        line.visible = p.showTracks && visible && target.trail.length > 1;
        (line.material as THREE.LineDashedMaterial).opacity =
          p.selectedId === target.id ? 0.9 : 0.32;
        if (!visible) {
          label.style.display = "none";
          continue;
        }
        group.position.set(state.x, Math.max(8, state.y! + 6), state.z);
        group.rotation.y = (-(state.heading ?? 0) * Math.PI) / 180;
        // Ground observations can be vehicles; unknown headings must not imply an aircraft orientation.
        if (group.children[1])
          group.children[1].visible =
            state.onGround !== true && state.heading !== null;
        group.scale.setScalar(2);
        v.copy(group.position).project(camera);
        const inView =
          v.z >= -1 && v.z <= 1 && Math.abs(v.x) < 1.1 && Math.abs(v.y) < 1.1;
        const lx = (v.x * 0.5 + 0.5) * host.clientWidth,
          ly = (-v.y * 0.5 + 0.5) * host.clientHeight;
        const width = Math.max(44, target.callsign.length * 8 + 16);
        const collision = occupied.some(
          (other) =>
            Math.abs(other.x - lx) < (other.width + width) / 2 + 8 &&
            Math.abs(other.y - ly) < 44,
        );
        // The 44px target is translated above its aircraft. Keep the complete hit
        // area inside the map and clear of actual panel bounds at every viewport.
        const labelBox = {
          left: hostRect.left + lx - width / 2,
          right: hostRect.left + lx + width / 2,
          top: hostRect.top + ly - 62,
          bottom: hostRect.top + ly - 18,
        };
        const behindInstrument = panels.some(
          (panel) =>
            labelBox.left < panel.right + 4 &&
            labelBox.right > panel.left - 4 &&
            labelBox.top < panel.bottom + 4 &&
            labelBox.bottom > panel.top - 4,
        );
        const inside =
          lx >= width / 2 + 4 &&
          lx <= host.clientWidth - width / 2 - 4 &&
          ly >= 66 &&
          ly <= host.clientHeight;
        const show =
          p.showLabels && inView && inside && !collision && !behindInstrument;
        if (show) occupied.push({ x: lx, y: ly, width });
        label.style.display = show ? "block" : "none";
        label.style.left = `${lx}px`;
        label.style.top = `${ly}px`;
        label.classList.toggle("selected", p.selectedId === target.id);
        label.setAttribute("aria-pressed", String(p.selectedId === target.id));
      }
      renderer.render(scene, camera);
      count++;
      if (now - stamp > 1200) {
        const fps = Math.round((count * 1000) / (now - stamp));
        count = 0;
        stamp = now;
        if (ready) current.current.onStatus({ ready: true, fps });
      }
      frame = requestAnimationFrame(render);
    }
    frame = requestAnimationFrame(render);
    const lost = (e: Event) => {
      e.preventDefault();
      contextLost = true;
      ready = false;
      current.current.onStatus({
        ready: false,
        error:
          "Graphics context lost. Reload the view; traffic records remain available.",
        fps: 0,
      });
    };
    const restored = () => {
      contextLost = false;
      ready = landscapeReady;
      if (!landscapeFailed) current.current.onStatus({ ready, fps: 0 });
    };
    renderer.domElement.addEventListener("webglcontextlost", lost);
    renderer.domElement.addEventListener("webglcontextrestored", restored);
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      document.removeEventListener("visibilitychange", visibility);
      window.removeEventListener("message", shellMessage);
      renderer.domElement.removeEventListener("pointerdown", pointerDown);
      renderer.domElement.removeEventListener("pointerup", pointerUp);
      controls.dispose();
      renderer.domElement.removeEventListener("webglcontextlost", lost);
      renderer.domElement.removeEventListener("webglcontextrestored", restored);
      labelLayer.remove();
      env.dispose();
      if (model) disposeModel(model);
      beaconGeometry.dispose();
      beaconMaterial.dispose();
      landscapeParts.splice(0).forEach((p) => {
        p.group.removeFromParent();
        p.dispose();
      });
      const geometries = new Set<THREE.BufferGeometry>(),
        materials = new Set<THREE.Material>();
      scene.traverse((o) => {
        if (o instanceof THREE.Mesh || o instanceof THREE.Line) {
          geometries.add(o.geometry);
          (Array.isArray(o.material) ? o.material : [o.material]).forEach((m) =>
            materials.add(m),
          );
        }
      });
      geometries.forEach((g) => g.dispose());
      materials.forEach((m) => m.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);
  return (
    <div
      className="scene-canvas"
      ref={container}
      style={{ position: "absolute", inset: 0 }}
    />
  );
}
