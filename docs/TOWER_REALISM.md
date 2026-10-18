# Tower realism and runway demonstration

The showcase keeps two distinct tower experiences. **Tower cab** displays the
selected research recording or historical source. **Runway demo** runs a separate,
explicitly simulated arrival on 28L and departure on 28R. Both use the same
Three.js airport and tower scene.

Open `/`, then choose **Runway demo**, or open
`/candidates/19-tower-cab-interior.html?mode=runway-demo` directly. The demonstration
does not require a database, inference calls, or a browser Maps key. It uses the
bundled airport imagery and weather snapshot.

## Playback

- **Watch takeoff** starts shortly before rotation and follows the departure.
- **Watch landing** starts on final approach and follows touchdown and rollout.
- **Tower desk** returns to the instrument desk. The existing camera presets,
  binoculars, zoom, and drag controls remain available.
- Play/pause, restart, a timeline, and 1×–10× speed control the finite sequence.
- The sequence ends visibly; restarting is explicit. It does not silently loop
  aircraft back onto a runway.

Entering Runway demo pauses saved research playback. Returning to Tower cab or
3D simulation restores that source and playhead. Research frames and decisions
never drive the demonstration, and its movements never alter research evidence.
An already-running server simulation retains its server-owned clock.

## Aircraft and scenery

The existing 60 Hz reduced-order flight model controls acceleration, rotation,
climb, approach, flare, touchdown, braking, runway exit, and taxi. Aircraft models
show gear, flaps, spoilers, wheel motion, and pitch from that state. Wheel-contact
compensation prevents the rotating model from penetrating the runway. See
[the flight model](TOWER_FLIGHT_MODEL.md) for its assumptions and limitations.

In connected mode, source position and status remain authoritative. Aircraft
attitude and mechanical configuration are visual estimates from nearby frames,
not measured ADS-B fields. Historical altitude anchors remain unchanged. A
recording without rollout or departure positions does not gain invented tracks.

The scene adds sky-based reflections, daylight-balanced aircraft lights, runway
markings and wear, and soft ground-contact cues. Runway detail follows bundled
OpenStreetMap axes; it is illustrative scenery, not surveyed airport engineering.
Contact shadows approximate grounding without a very large shadow map. The
lighting preset and weather snapshot are not current SFO conditions.

The Blender-generated equipment asset and its reproducible source live under
`showcase/candidates/assets/tower-realism/` and
`showcase/assets/source/tower-realism/`. The asset is generated through Blender
MCP in a background Blender process; no visible Blender window is required.

## Renderer choice

Improving the current Three.js renderer preserves the cab glass, imagery,
photoreal-tile option, camera controls, and existing playback. Migrating the whole
scene to WebGPU would require replacing its custom GLSL materials. We retain
WebGL and spend the rendering budget on materials, lighting, and aircraft
readability. Three.js documents the custom-material migration boundary in its
[WebGPU guide](https://threejs.org/manual/pages/webgpurenderer).

This remains a research demonstration with representative aircraft and locally
packaged scenery. It is not live traffic, a certified flight simulator, or a
claim of photographically accurate airport geometry. Optional Google photoreal
tiles retain their existing key and attribution requirements.

## Verification

Run the showcase gateway and a local research backend on the ports configured in
`web/e2e.tower.config.ts`, then run:

```sh
cd web
npx e2e run --headed --config e2e.tower.config.ts tests/tower-physics.e2e.ts tests/tower-immersion.e2e.ts tests/tower-realism.e2e.ts
```

Tests drive the real scene and controls, inspect aircraft configuration and
source continuity, and capture desktop and narrow layouts. These are integration
and plausibility checks, not comparison with instrumented aircraft telemetry.

An October 17, 2026 five-second sample at 1440 × 900 measured 120 frames/second
on an Apple M5 Pro through Chromium's ANGLE Metal backend (median frame interval
8.3 ms, 95th percentile 9.3 ms). The headless software-rendering backend measured
about 4 frames/second. These are local samples, not a guaranteed frame rate or a
before/after improvement claim. Use the actual GPU backend for demo rehearsal.
