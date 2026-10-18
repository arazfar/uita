/** Articulated, type-class geometry. Metres; +Z forward, +Y up, +X left wing.
 * Main wheel contact is the pitch pivot; surfaces follow flight configuration.
 * This is an original representative model, not an exact manufacturer CAD model.
 */
export function makeAirliner(THREE, profile) {
  const g = new THREE.Group(),
    heavy = profile.span > 50,
    jumbo = heavy && profile.upperDeck !== false;
  const length = profile.length,
    radius = heavy ? 3.05 : 1.98,
    belly = heavy ? 3.5 : 2.3;
  const center = belly + radius,
    span = profile.span;
  const paint = new THREE.MeshStandardMaterial({
    color: 0xe3e6e3,
    roughness: 0.38,
    metalness: 0.25,
  });
  const blue = new THREE.MeshStandardMaterial({
    color: 0x234a71,
    roughness: 0.4,
    metalness: 0.2,
  });
  const dark = new THREE.MeshStandardMaterial({
    color: 0x111b22,
    roughness: 0.6,
  });
  const metal = new THREE.MeshStandardMaterial({
    color: 0x66727d,
    roughness: 0.24,
    metalness: 0.8,
  });
  const rubber = new THREE.MeshStandardMaterial({
    color: 0x121415,
    roughness: 0.9,
  });
  const mesh = (geometry, material, parent = g) => {
    const m = new THREE.Mesh(geometry, material);
    m.castShadow = true;
    m.receiveShadow = true;
    parent.add(m);
    return m;
  };
  const points = [
    [0, -0.5],
    [0.3, -0.46],
    [0.75, -0.35],
    [1, -0.23],
    [1, 0.32],
    [0.94, 0.4],
    [0.7, 0.46],
    [0.25, 0.495],
    [0, 0.5],
  ];
  const fuselage = mesh(
    new THREE.LatheGeometry(
      points.map(([r, z]) => new THREE.Vector2(r * radius, z * length)),
      32,
    ),
    paint,
  );
  fuselage.rotation.x = Math.PI / 2;
  fuselage.position.y = center;
  // The 747's upper-deck shape remains recognizable at tower distances.
  if (jumbo) {
    const hump = mesh(new THREE.SphereGeometry(1, 24, 12), paint);
    hump.scale.set(2.25, 1.8, 12);
    hump.position.set(0, center + 2.15, 14);
  }
  function plate(points, thickness, material) {
    const shape = new THREE.Shape();
    points.forEach(([x, z], i) =>
      i ? shape.lineTo(x, z) : shape.moveTo(x, z),
    );
    shape.closePath();
    const m = mesh(
      new THREE.ExtrudeGeometry(shape, {
        depth: thickness,
        bevelEnabled: false,
      }),
      material,
    );
    m.rotation.x = Math.PI / 2;
    m.position.y = belly + radius * 0.6;
    return m;
  }
  const flaps = [],
    spoilers = [],
    gears = [],
    wheels = [];
  for (const side of [-1, 1]) {
    plate(
      [
        [side * radius, 7],
        [side * span * 0.5, -length * 0.14],
        [side * span * 0.5, -length * 0.18],
        [side * radius, -length * 0.15],
      ],
      heavy ? 0.65 : 0.35,
      paint,
    );
    plate(
      [
        [side * radius, -length * 0.34],
        [side * span * 0.21, -length * 0.45],
        [side * span * 0.21, -length * 0.49],
        [0, -length * 0.44],
      ],
      0.2,
      paint,
    );
    const winglet = mesh(
      new THREE.BoxGeometry(0.18, heavy ? 2.4 : 1.4, 1.7),
      blue,
    );
    winglet.position.set(
      side * span * 0.49,
      belly + radius * 0.6 + 0.7,
      -length * 0.16,
    );
    winglet.rotation.z = side * 0.2;
    for (let k = 0; k < 2; k++) {
      const flap = new THREE.Group();
      flap.position.set(
        side * span * (0.13 + k * 0.09),
        belly + radius * 0.6,
        -length * (0.075 + k * 0.025),
      );
      const m = mesh(
        new THREE.BoxGeometry(span * 0.085, 0.16, heavy ? 3.5 : 2),
        paint,
        flap,
      );
      m.position.z = -1;
      g.add(flap);
      flaps.push(flap);
      const spoiler = new THREE.Group();
      spoiler.position.copy(flap.position);
      spoiler.position.z += 1;
      spoiler.position.y += 0.15;
      const sm = mesh(
        new THREE.BoxGeometry(span * 0.075, 0.12, 1.1),
        metal,
        spoiler,
      );
      sm.position.z = -0.5;
      g.add(spoiler);
      spoilers.push(spoiler);
    }
    const engineCount = jumbo ? 2 : 1;
    for (let k = 0; k < engineCount; k++) {
      const x = side * span * (0.19 + k * 0.12),
        z = length * (0.065 - k * 0.07),
        er = heavy ? 1.25 : 1;
      const cowl = mesh(
        new THREE.CylinderGeometry(
          er,
          er * 0.88,
          heavy ? 4.7 : 3.4,
          24,
          1,
          true,
        ),
        paint,
      );
      cowl.rotation.x = Math.PI / 2;
      cowl.position.set(x, belly * 0.75, z);
      const inlet = mesh(
        new THREE.TorusGeometry(er * 0.92, 0.12, 8, 24),
        metal,
      );
      inlet.position.set(x, belly * 0.75, z + (heavy ? 2.36 : 1.71));
      const fan = mesh(new THREE.CircleGeometry(er * 0.87, 24), dark);
      fan.position.set(x, belly * 0.75, z + (heavy ? 2.2 : 1.5));
      const spinner = mesh(new THREE.ConeGeometry(er * 0.24, 0.7, 12), metal);
      spinner.rotation.x = Math.PI / 2;
      spinner.position.copy(fan.position);
      spinner.position.z += 0.3;
      const pylon = mesh(new THREE.BoxGeometry(0.4, 1.5, 2.5), metal);
      pylon.position.set(x, belly + 1, z - 0.5);
    }
    // Repeated windows share one draw call per side, even with many visible aircraft.
    const windowPositions = [];
    for (let z = -length * 0.29; z < length * 0.34; z += heavy ? 1.05 : 0.85)
      windowPositions.push(z);
    const windows = new THREE.InstancedMesh(
      new THREE.PlaneGeometry(0.28, 0.37),
      dark,
      windowPositions.length,
    );
    const windowPose = new THREE.Object3D();
    windowPose.rotation.y = (side * Math.PI) / 2;
    windowPositions.forEach((z, i) => {
      windowPose.position.set(side * radius * 0.98, center + 0.4, z);
      windowPose.updateMatrix();
      windows.setMatrixAt(i, windowPose.matrix);
    });
    g.add(windows);
    // Angled cockpit glazing stays flush with the tapered forward fuselage.
    for (let panel = 0; panel < 3; panel++) {
      const cockpit = mesh(
        new THREE.PlaneGeometry(radius * 0.32, radius * 0.25),
        dark,
      );
      cockpit.position.set(
        side * radius * (0.38 + panel * 0.19),
        center + radius * (0.35 - panel * 0.08),
        length * (0.468 - panel * 0.014),
      );
      cockpit.rotation.set(-0.34, side * (0.4 + panel * 0.3), 0);
    }
    for (const z of [-0.29, 0.31]) {
      const door = mesh(new THREE.BoxGeometry(0.04, 1.6, 0.85), metal);
      door.position.set(side * radius * 0.995, center - 0.3, z * length);
    }
    const nav = mesh(
      new THREE.SphereGeometry(0.13, 8, 6),
      new THREE.MeshBasicMaterial({ color: side > 0 ? 0xff2514 : 0x27ff7b }),
    );
    nav.position.set(side * span * 0.5, belly + radius * 0.6, -length * 0.16);
  }
  const tailShape = new THREE.Shape();
  tailShape.moveTo(0, 0);
  tailShape.lineTo(length * 0.1, length * 0.18);
  tailShape.lineTo(length * 0.17, length * 0.2);
  tailShape.lineTo(length * 0.19, 0);
  tailShape.closePath();
  const tail = mesh(
    new THREE.ExtrudeGeometry(tailShape, { depth: 0.25, bevelEnabled: false }),
    blue,
  );
  tail.rotation.y = Math.PI / 2;
  tail.position.set(-0.125, center, -length * 0.3);
  // Gear legs retract as whole assemblies; tyre rotation derives from ground speed.
  for (const [x, z] of [
    [-radius * 0.85, 0],
    [radius * 0.85, 0],
    [0, length * 0.34],
    ...(heavy
      ? [
          [-radius * 1.65, -3],
          [radius * 1.65, -3],
        ]
      : []),
  ]) {
    const pivot = new THREE.Group();
    pivot.position.set(x, belly, z);
    g.add(pivot);
    gears.push(pivot);
    const leg = mesh(
      new THREE.CylinderGeometry(0.1, 0.13, belly - 0.45, 8),
      metal,
      pivot,
    );
    leg.position.y = -(belly - 0.45) / 2;
    for (const side of [-1, 1])
      for (const axle of heavy && x !== 0 ? [-0.55, 0.55] : [0]) {
        const wheel = mesh(
          new THREE.CylinderGeometry(0.45, 0.45, 0.3, 12),
          rubber,
          pivot,
        );
        wheel.geometry.rotateZ(Math.PI / 2);
        wheel.position.set(side * 0.25, -belly + 0.45, axle);
        wheels.push(wheel);
      }
  }
  g.userData.profile = profile.name;
  g.userData.configurationBasis = "representative articulated geometry";
  g.userData.updateFlight = (s) => {
    const gear = Number.isFinite(s.gear) ? s.gear : 1;
    const flap = Number.isFinite(s.flap) ? s.flap : 0;
    const spoiler = Number.isFinite(s.spoilers) ? s.spoilers : 0;
    // The dynamics height measures the lowest deployed wheel, including rotation.
    // A four-bogie widebody pivots on its rear gear rather than sinking into asphalt.
    const pitch = Number.isFinite(s.pitch) ? s.pitch : 0;
    const contactZ = pitch >= 0 ? (heavy ? -3.55 : 0) : length * 0.34;
    g.position.y =
      gear > 0.99
        ? Math.max(0, 0.45 * (1 - Math.cos(pitch)) - contactZ * Math.sin(pitch))
        : 0;
    for (const p of gears)
      p.rotation.z = ((p.position.x < 0 ? -1 : 1) * (1 - gear) * Math.PI) / 2;
    for (const f of flaps) f.rotation.x = -flap * 0.52;
    for (const sp of spoilers) sp.rotation.x = spoiler * 0.95;
    for (const w of wheels) w.rotation.x = -(s.wheelAngle || 0);
  };
  return g;
}
