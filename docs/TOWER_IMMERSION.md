# Tower immersion

The cab in `showcase/candidates/19-tower-cab-interior.html` shares the existing tower shell and controls. It starts at a seated first-person viewpoint. Cinematic movement remains available through the existing CINE button. Backend traffic remains authoritative in connected mode: no synthetic flights, taxi routes, or invented aircraft configuration are added to recorded tracks.

## Camera

Drag or use arrow keys to look. Hold Q/E to lean left/right by up to 22 cm. Wheel zoom, binoculars, aircraft picking, and all six presets remain available. Movement stays inside the console bay. Focused controls retain native keyboard behavior. Blur, hidden tabs, and pointer cancellation release held input. Reduced-motion preference removes preset animation and cinematic FOV breathing.

A bounded controller extends the existing camera rather than replacing it with pointer-lock navigation. This keeps the current presets, touch dragging, picking, and keyboard controls together without requiring pointer lock.

## Glass and daylight

A clear-afternoon preset uses a directional sun, sky fill, matching distance haze, and cab shadows. It is not a measured solar position or live weather condition. Ground imagery uses a daylight tint. Window reflection strength increases toward grazing angles and reflects the actual monitor textures. The windows retain transparency so aircraft remain visible.

The glass shader intersects reflected rays with monitor planes. It avoids an additional scene render needed by full screen-space or transmission effects. This keeps cost predictable, but only the monitors contribute detailed reflections. The shadow map covers the cab, not the airport. The [realism update](TOWER_REALISM.md) adds local Blender equipment, runway detail, and aircraft contact cues.

## Sound

The existing sound button or M shortcut enables quiet ventilation and up to six nearby aircraft sound sources. Connected mode retains the remote shell's hidden sound button; focus the cab and press M. Sound starts only after a user gesture. It pauses when playback pauses, the cab is hidden, or the document loses visibility. The replay shell now sends its zero-rate playhead immediately on Pause; previously that message waited for a render tick that no longer ran.

Aircraft sounds follow their existing world positions. Direction and distance affect each source; a low-pass filter approximates closed tower glass. Local simulated thrust controls engine intensity. Backend aircraft without thrust data use a quiet generic sound instead. These are procedural effects, not recordings or a calibrated acoustic model. Radio behavior remains separate.

## Landing to taxi

Aircraft sample their precomputed trajectory using elapsed visible playback time. Slow rendering does not slow aircraft motion. Camera smoothing still caps large frame deltas.

The standalone AAL173 scenario follows the existing force-based approach and touchdown, slows for runway exit E, follows taxiway B, and holds clear. The path uses connected bundled OpenStreetMap vertices, with curved turns and speed limits. It rejects routes across other runways. The route is not operational guidance. See `TOWER_FLIGHT_MODEL.md` for model limits.

## Browser verification

Serve the current showcase and a bootstrapped local research backend on port 5188. Use the repository's documented backend setup; recorded playback requires no paid inference.

```sh
cd web
npx e2e run --config e2e.tower.config.ts tests/tower-physics.e2e.ts tests/tower-immersion.e2e.ts
```

The browser suite checks camera movement, return from lean, preserved presets and buttons, actual Web Audio output after a gesture, mute/pause behavior, aircraft continuity and landing phases, and saved backend traffic in the connected tower. Output waveform checks establish signal generation, not subjective sound quality. The scene still uses the remote branch's Three.js WebGL renderer; this pass does not introduce a separate WebGPU renderer.
