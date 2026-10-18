/**
 * A clear-afternoon lighting preset, not a measured weather or solar ephemeris.
 * Coordinates: metres, +Y up, north = -Z. Azimuth is clockwise from north.
 * Replace the old sky/global lights before creating this; keep cab point lights.
 * Pass the existing eight window meshes and live screen records. Call update()
 * after camera/cab transforms, before render. dispose() restores owned changes.
 */
export function createTowerAtmosphere(
  THREE,
  {
    scene,
    cab,
    camera,
    renderer,
    glassPanes = [],
    screens = {},
    sunElevation = 28,
    sunAzimuth = 245,
    hazeDensity = 0.000024,
    exposure = 0.85,
    shadows = true,
  },
) {
  const clamp = THREE.MathUtils.clamp;
  const oldFog = scene.fog;
  const oldEnvironment = scene.environment;
  const oldEnvironmentIntensity = scene.environmentIntensity;
  let environmentTarget = null;
  const oldExposure = renderer.toneMappingExposure;
  const oldShadowEnabled = renderer.shadowMap.enabled;
  const oldShadowType = renderer.shadowMap.type;
  const group = new THREE.Group();
  group.name = "tower-daylight";
  scene.add(group);
  const fog = new THREE.FogExp2(0xbacbd3, hazeDensity);
  scene.fog = fog;
  const sunDirection = new THREE.Vector3();
  const skyMaterial = new THREE.ShaderMaterial({
    side: THREE.BackSide,
    depthWrite: false,
    depthTest: false,
    fog: false,
    uniforms: {
      sunDirection: { value: sunDirection },
      horizon: { value: fog.color },
      warmth: { value: 0 },
    },
    vertexShader: `varying vec3 skyDirection;
      void main() { skyDirection = position; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `varying vec3 skyDirection; uniform vec3 sunDirection; uniform vec3 horizon; uniform float warmth;
      void main() {
        vec3 ray = normalize(skyDirection);
        float altitude = max(ray.y, 0.0);
        vec3 zenith = vec3(0.09, 0.25, 0.46);
        vec3 color = mix(horizon, zenith, pow(altitude, 0.34));
        float towardSun = max(dot(ray, sunDirection), 0.0);
        color += vec3(1.0, 0.77, 0.45) * pow(towardSun, 24.0) * (0.065 + warmth * 0.08);
        // The solar disk subtends about half a degree; the wider halo is atmospheric scattering.
        float disk = smoothstep(cos(0.0052), cos(0.0042), towardSun);
        color += vec3(4.0, 3.5, 2.7) * disk;
        color = mix(color, horizon * 0.72, smoothstep(0.0, 0.12, -ray.y));
        gl_FragColor = vec4(color, 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
  const sky = new THREE.Mesh(
    new THREE.SphereGeometry(80000, 32, 16),
    skyMaterial,
  );
  sky.name = "afternoon-sky";
  sky.renderOrder = -100;
  sky.frustumCulled = false;
  group.add(sky);
  const fill = new THREE.HemisphereLight(0xc5dcec, 0x655e50, 0.65);
  const sun = new THREE.DirectionalLight(0xffefd4, 2.1);
  const bounce = new THREE.AmbientLight(0x798995, 0.13);
  group.add(fill, sun, sun.target, bounce);
  const shadowObjects = [];
  if (shadows) {
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, {
      left: -5,
      right: 5,
      top: 5,
      bottom: -5,
      near: 0.5,
      far: 40,
    });
    sun.shadow.camera.updateProjectionMatrix();
    sun.shadow.normalBias = 0.012;
    sun.shadow.bias = -0.00015;
    const screenMeshes = new Set(
      Object.values(screens).map((screen) => screen.mesh),
    );
    const panes = new Set(glassPanes);
    cab.traverse((mesh) => {
      if (!mesh.isMesh || panes.has(mesh) || screenMeshes.has(mesh)) return;
      shadowObjects.push([mesh, mesh.castShadow, mesh.receiveShadow]);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
    });
  }

  // Reflect actual instrument canvases by intersecting the reflected eye ray with
  // their planes. No scene-copy pass, duplicated display data, or moving fake glare.
  const reflectedScreens = Object.values(screens)
    .filter((screen) => screen.mesh && screen.tex)
    .slice(0, 5);
  const glassUniforms = {
    cabInverse: { value: new THREE.Matrix4() },
    eyeCab: { value: new THREE.Vector3() },
    reflectionStrength: { value: 0.55 },
  };
  reflectedScreens.forEach((screen, i) => {
    glassUniforms[`screenMap${i}`] = { value: screen.tex };
    glassUniforms[`screenInverse${i}`] = { value: new THREE.Matrix4() };
    const { width, height } = screen.mesh.geometry.parameters;
    glassUniforms[`screenSize${i}`] = {
      value: new THREE.Vector2(width, height),
    };
  });
  const declarations = reflectedScreens
    .map(
      (_, i) =>
        `uniform sampler2D screenMap${i}; uniform mat4 screenInverse${i}; uniform vec2 screenSize${i};`,
    )
    .join("\n");
  const samples = reflectedScreens
    .map(
      (_, i) =>
        `reflected += readScreen(screenMap${i}, screenInverse${i}, screenSize${i}, reflectedRay);`,
    )
    .join("\n");
  const glassMaterial = new THREE.ShaderMaterial({
    name: "cab-fresnel-glass",
    transparent: true,
    depthWrite: false,
    forceSinglePass: true,
    side: THREE.DoubleSide,
    uniforms: glassUniforms,
    vertexShader: `#include <common>
      #include <logdepthbuf_pars_vertex>
      uniform mat4 cabInverse; varying vec3 panePosition; varying vec3 paneNormal; varying vec2 paneUv;
      void main() {
        mat4 paneToCab = cabInverse * modelMatrix;
        panePosition = (paneToCab * vec4(position, 1.0)).xyz;
        paneNormal = normalize(mat3(paneToCab) * normal);
        paneUv = uv;
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        gl_Position = projectionMatrix * mvPosition;
        #include <logdepthbuf_vertex>
      }`,
    fragmentShader: `#include <common>
      #include <logdepthbuf_pars_fragment>
      uniform vec3 eyeCab; uniform float reflectionStrength;
      varying vec3 panePosition; varying vec3 paneNormal; varying vec2 paneUv;
      ${declarations}
      vec3 readScreen(sampler2D image, mat4 toScreen, vec2 size, vec3 ray) {
        vec3 origin = (toScreen * vec4(panePosition, 1.0)).xyz;
        vec3 direction = (toScreen * vec4(ray, 0.0)).xyz;
        // Screen fronts point along local +Z; reject back-face reflections.
        if (direction.z >= -0.0001 || origin.z <= 0.0) return vec3(0.0);
        float distanceToScreen = -origin.z / direction.z;
        vec2 uv = (origin.xy + direction.xy * distanceToScreen) / size + 0.5;
        if (min(uv.x, uv.y) < 0.0 || max(uv.x, uv.y) > 1.0) return vec3(0.0);
        vec2 edge = min(uv, 1.0 - uv);
        return texture2D(image, uv).rgb * smoothstep(0.0, 0.008, min(edge.x, edge.y));
      }
      void main() {
        #include <logdepthbuf_fragment>
        vec3 incident = normalize(panePosition - eyeCab);
        vec3 normal = normalize(paneNormal);
        float cosTheta = abs(dot(-incident, normal));
        // Schlick approximation for glass (IOR ~1.5); cap grazing opacity for visibility.
        float fresnel = 0.04 + 0.96 * pow(1.0 - cosTheta, 5.0);
        vec3 reflectedRay = reflect(incident, normal);
        vec3 reflected = vec3(0.025, 0.032, 0.035);
        ${samples}
        vec2 edge = min(paneUv, 1.0 - paneUv);
        float edgeTint = 1.0 - smoothstep(0.0, 0.012, min(edge.x, edge.y));
        vec3 color = mix(reflected, vec3(0.05, 0.15, 0.14), edgeTint * 0.35);
        float alpha = clamp(fresnel * reflectionStrength + 0.008 + edgeTint * 0.025, 0.0, 0.24);
        gl_FragColor = vec4(color, alpha);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
  const originals = glassPanes.map((mesh) => [mesh, mesh.material]);
  glassPanes.forEach((mesh) => {
    mesh.material = glassMaterial;
  });
  let disposed = false;
  const settings = {};
  const target = new THREE.Vector3();
  function configure(options = {}) {
    if (disposed) return;
    const next = { ...settings, ...options };
    for (const key of [
      "sunElevation",
      "sunAzimuth",
      "hazeDensity",
      "exposure",
    ]) {
      if (!Number.isFinite(next[key]))
        throw new TypeError(`Tower atmosphere ${key} must be finite.`);
    }
    Object.assign(settings, next);
    const elevation = (clamp(settings.sunElevation, 5, 85) * Math.PI) / 180;
    const azimuth = (settings.sunAzimuth * Math.PI) / 180;
    sunDirection.set(
      Math.sin(azimuth) * Math.cos(elevation),
      Math.sin(elevation),
      -Math.cos(azimuth) * Math.cos(elevation),
    );
    const warmth = 1 - clamp((settings.sunElevation - 5) / 25, 0, 1);
    skyMaterial.uniforms.warmth.value = warmth;
    sun.color.setHex(0xffefd4).lerp(new THREE.Color(0xffc88e), warmth * 0.65);
    sun.intensity = 1.6 - warmth * 0.45;
    fog.density = clamp(settings.hazeDensity, 0, 0.00015);
    renderer.toneMappingExposure = clamp(settings.exposure, 0.5, 1.5);
  }
  function update() {
    if (disposed) return;
    cab.updateWorldMatrix(true, true);
    glassUniforms.cabInverse.value.copy(cab.matrixWorld).invert();
    camera
      .getWorldPosition(glassUniforms.eyeCab.value)
      .applyMatrix4(glassUniforms.cabInverse.value);
    reflectedScreens.forEach((screen, i) => {
      glassUniforms[`screenInverse${i}`].value
        .copy(screen.mesh.matrixWorld)
        .invert()
        .multiply(cab.matrixWorld);
    });
    target.set(0, 1.8, 0).applyMatrix4(cab.matrixWorld);
    sun.target.position.copy(target);
    sun.position.copy(target).addScaledVector(sunDirection, 20);
    sun.target.updateMatrixWorld();
    // Recenter only the distant sky; its direction and sunlight remain world-fixed.
    camera.getWorldPosition(sky.position);
  }
  function dispose() {
    if (disposed) return;
    disposed = true;
    originals.forEach(([mesh, material]) => {
      mesh.material = material;
    });
    shadowObjects.forEach(([mesh, castShadow, receiveShadow]) => {
      mesh.castShadow = castShadow;
      mesh.receiveShadow = receiveShadow;
    });
    group.removeFromParent();
    sky.geometry.dispose();
    skyMaterial.dispose();
    if (scene.environment === environmentTarget?.texture) { scene.environment = oldEnvironment; scene.environmentIntensity = oldEnvironmentIntensity; }
    environmentTarget?.dispose();
    glassMaterial.dispose();
    sun.dispose();
    if (scene.fog === fog) scene.fog = oldFog;
    renderer.toneMappingExposure = oldExposure;
    renderer.shadowMap.enabled = oldShadowEnabled;
    renderer.shadowMap.type = oldShadowType;
  }
  configure({ sunElevation, sunAzimuth, hazeDensity, exposure });
  // The same directional sky lights polished paint and metal. Generate once, not per frame.
  const environmentScene = new THREE.Scene();
  const environmentSky = sky.clone();
  environmentSky.position.set(0, 0, 0);
  environmentSky.material = skyMaterial.clone();
  environmentSky.material.toneMapped = false;
  environmentScene.add(environmentSky);
  const generator = new THREE.PMREMGenerator(renderer);
  environmentTarget = generator.fromScene(environmentScene, .035, 1, 100000);
  scene.environment = environmentTarget.texture;
  scene.environmentIntensity = .48;
  environmentSky.material.dispose();
  generator.dispose();
  update();
  return {
    update,
    configure,
    dispose,
    sky,
    sun,
    glassMaterial,
    get settings() {
      return { ...settings };
    },
  };
}
