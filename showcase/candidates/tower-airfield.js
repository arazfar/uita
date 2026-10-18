/** Visual detail aligned to the OSM runway axes. This is scenery, not surveyed infrastructure. */
export function createTowerAirfield(THREE, { runways, parent }) {
  const group = new THREE.Group();
  group.name = 'runway-surface-detail';
  parent.add(group);
  const asphalt = new THREE.MeshStandardMaterial({ color: 0x34383a, roughness: .97, metalness: 0 });
  const shoulder = new THREE.MeshStandardMaterial({ color: 0x77786e, roughness: 1 });
  const paint = new THREE.MeshStandardMaterial({ color: 0xe7e4d8, roughness: .94 });
  const rubber = new THREE.MeshBasicMaterial({ color: 0x1b2021, transparent: true, opacity: .25, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -1 });
  const parts = [];
  const mark = (root, x, z, width, length, material = paint, height = .09) => {
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(width, length), material);
    mesh.rotation.x = -Math.PI / 2; mesh.position.set(x, height, z); root.add(mesh); parts.push(mesh);
    mesh.receiveShadow = true;
    return mesh;
  };
  for (const [name, runway] of Object.entries(runways)) {
    const dx = runway.W[0] - runway.E[0], dz = runway.W[1] - runway.E[1], length = Math.hypot(dx, dz);
    const root = new THREE.Group(); root.position.set(runway.E[0], 0, runway.E[1]);
    // Local +Z follows the inbound runway axis, and local +X is its right-hand side.
    root.rotation.y = Math.atan2(dx, dz); group.add(root);
    mark(root, 0, length / 2, 68, length, shoulder, .025);
    mark(root, 0, length / 2, 61, length, asphalt, .045);
    for (const x of [-29, 29]) mark(root, x, length / 2, .9, length - 6);
    for (let z = 200; z < length - 160; z += 60) mark(root, 0, z, .9, 30);
    for (const end of [0, length]) {
      const sign = end === 0 ? 1 : -1;
      for (let x = -24; x <= 24; x += 4) if (Math.abs(x) > 2) mark(root, x, end + sign * 28, 1.8, 30);
      for (const x of [-13, 13]) mark(root, x, end + sign * 305, 5.5, 45);
      for (const z of [150, 450, 600, 750, 900]) for (const side of [-1, 1]) {
        for (let stripe = 0; stripe < (z < 600 ? 3 : 2); stripe++) mark(root, side * (9 + stripe * 3), end + sign * z, 1.8, 23);
      }
      // Rubber deposits are fixed runway wear, not a live landing indication.
      for (let i = 0; i < 9; i++) mark(root, (i - 4) * 1.6, end + sign * (380 + (i % 3) * 30), .8 + (i % 2) * .4, 240 + (i % 4) * 32, rubber, .10);
      const canvas = document.createElement('canvas'); canvas.width = 256; canvas.height = 512;
      const ctx = canvas.getContext('2d'); ctx.fillStyle = '#e7e4d8'; ctx.textAlign = 'center'; ctx.font = 'bold 180px sans-serif';
      const label = end === 0 ? name : name === '28L' ? '10R' : '10L';
      ctx.fillText(label.slice(0, 2), 128, 235); ctx.font = 'bold 130px sans-serif'; ctx.fillText(label.slice(2), 128, 390);
      const tex = new THREE.CanvasTexture(canvas); tex.colorSpace = THREE.SRGBColorSpace;
      const number = mark(root, 0, end + sign * 105, 20, 55, new THREE.MeshStandardMaterial({ map: tex, transparent: true, depthWrite: false, roughness: 1 }), .11);
      // Planes viewed from above read toward their threshold.
      number.rotation.z = end === 0 ? Math.PI : 0;
    }
  }
  // Cheap ground contact cues avoid a kilometre-wide shadow map that blurs the cab shadows.
  const canvas = document.createElement('canvas'); canvas.width = canvas.height = 64;
  const ctx = canvas.getContext('2d'), gradient = ctx.createRadialGradient(32, 32, 2, 32, 32, 32);
  gradient.addColorStop(0, 'rgba(0,0,0,.5)'); gradient.addColorStop(.55, 'rgba(0,0,0,.25)'); gradient.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = gradient; ctx.fillRect(0, 0, 64, 64);
  const contactTexture = new THREE.CanvasTexture(canvas), contacts = new Map();
  const contactGroup = new THREE.Group(); contactGroup.name = 'aircraft-contact-shadows'; parent.add(contactGroup);
  function update(actors, groundY) {
    const current = new Set();
    for (const actor of actors) {
      const height = actor.pos.y - groundY;
      if (!actor.vis || height > 100 || height < -10) continue;
      current.add(actor.cs);
      let shadow = contacts.get(actor.cs);
      if (!shadow) {
        shadow = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: contactTexture, transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -3 }));
        shadow.rotation.x = -Math.PI / 2; contactGroup.add(shadow); contacts.set(actor.cs, shadow);
      }
      shadow.visible = true; shadow.position.set(actor.pos.x, .15, actor.pos.z);
      const span = actor.kind === '747' ? 64 : actor.kind === 'evtol' ? 14 : 36;
      shadow.scale.set(span * (1 + Math.max(0, height) / 120), span * 1.1, 1);
      shadow.rotation.z = -Math.atan2(actor.dir.x, -actor.dir.z);
      shadow.material.opacity = .6 * (1 - Math.max(0, height) / 100);
    }
    for (const [id, shadow] of contacts) if (!current.has(id)) shadow.visible = false;
  }
  function dispose() {
    group.removeFromParent(); contactGroup.removeFromParent();
    for (const root of [group, contactGroup]) root.traverse(mesh => { if (mesh.isMesh) mesh.geometry.dispose(); });
    const materials = new Set(parts.map(mesh => mesh.material));
    for (const material of materials) { material.map?.dispose(); material.dispose(); }
    for (const shadow of contacts.values()) shadow.material.dispose();
    contactTexture.dispose(); contacts.clear();
  }
  return { group, update, dispose };
}
