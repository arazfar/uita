# SFO tower aircraft dynamics

The standalone tower's two civil airborne aircraft use a force-based, reduced-order simulation. Their callsigns are scenario labels. They are **not recorded flight tracks or live aircraft**. Connected mode (`?mode=connected`) continues to display only backend-provided aircraft. No synthetic physics actors are created there. The remote shell, buttons, historical replay, recorded observations, research backend, and UITA/eVTOL scenario are unchanged.

## Runtime contract

`showcase/candidates/tower-flight-dynamics.js` integrates at 60 Hz in SI units. The renderer samples that trajectory with interpolation. Frame rate and the compressed ATC narrative clock cannot speed up aircraft physics. Space pauses; R starts takeoff and approach from the beginning. Opening the view starts 38 seconds into the sequence so aircraft are already visible.

The departure follows SFO 28R. The arrival follows 28L. Both use the bundled OpenStreetMap runway centerlines in the same east/up/south coordinate frame as the airport imagery. Thresholds are the eastern ends of those centerlines. These are not surveyed threshold or runway-slope data. Runway 28 operations are a scenario choice, not a claim about today's active configuration.

The bundled KSFO METAR provides surface wind, temperature, and pressure. This is a **snapshot**, not live weather. Wind direction is true north, wind-from; knots become metres/second. The code resolves along-runway and crosswind components. Density uses pressure and temperature with an exponential altitude approximation. Missing wind falls back to calm conditions.

## Forces and guidance

- Dynamic pressure: `q = 0.5 * density * trueAirspeed²`.
- Lift: `q * wingArea * CL`; CL depends on angle of attack and flap setting, with a maximum.
- Drag: `q * wingArea * (CD0 + gear + flap + spoilers + k * CL² * groundEffect)`.
- Engine thrust has a 2.5-second spool response. Mass converts net force into acceleration.
- The ground reaction prevents downward runway penetration. Rolling resistance and brake force depend on wheel load.
- Takeoff: spool, release brakes, accelerate to reference equivalent airspeed, rate-limited rotation, lift exceeds weight, positive climb, then gear and flap retraction.
- Approach: a nominal 3° path and 50 ft threshold crossing height. Guidance requests vertical speed; lift and thrust determine the response.
- Flare begins below 12 m and reduces sink rate. Pitch is distinct from flight-path angle.
- Touchdown triggers spoiler deployment, delayed wheel braking, and reverse thrust. Reverse ends below 30 m/s.
- Crosswind compensation crabs the aircraft into the wind and removes the crab near touchdown. Lateral motion is constrained to the runway centerline; this is not a lateral dynamics solver.

There are no periodic runway teleports. The departure leaves the scene after 14 km. The arrival slows before exit E, follows the connected bundled taxiway B centerline, then holds clear of the runway. Circular corner fillets and a braking envelope limit turns. The route avoids other runway protected areas; no route means the existing runway stop remains. This route is a scenario assumption, not an actual clearance. Gate assignment, surface conflict avoidance, and continuous traffic scheduling remain unimplemented.

## Aircraft and rendering

The heavy profile represents a 747-400 class aircraft: 70.7 m length, 64.4 m span, 541 m² wing area. The medium profile represents an A320 class aircraft: 37.6 m length, 34.1 m span, 122.6 m² wing area. Assumed masses are 300,000 kg and 62,000 kg. Thrust, aerodynamic coefficients, V-speeds, braking friction, and controller gains are representative engineering assumptions, not flight-manual performance tables.

`tower-airliner.js` builds original articulated aircraft geometry at physical scale. It includes engines, window rows, winglets, tail surfaces, wheels, gear, flaps, spoilers, and navigation lights. Gear/configuration comes from the same flight state as movement. Models are type-class approximations, not exact manufacturer CAD or airline liveries. Existing static taxi aircraft keep their original assets.

## Accuracy boundary

This is more physically grounded than the previous constant-speed/descent animation. It is **not yet a high-fidelity aircraft simulator**. It does not implement six-degree-of-freedom rigid-body dynamics, engine-specific performance decks, fuel burn, stall/spin behavior, tire/suspension dynamics, turbulence, gusts, wind shear, wake vortices, wet-runway braking, or measured wind aloft. The existing eVTOL actors remain scripted. Aircraft dimensions and general flight phases have source references; profile coefficients and behavior have not been validated against instrumented real flights.

For higher fidelity, replace the representative profiles and reduced-order model with a validated flight-dynamics engine and licensed/type-specific aerodynamic data. Connect recorded tracks as a separate observation layer, retaining explicit distinction between observations and simulated states. ADS-B positions alone cannot establish aircraft mass, thrust, flap position, or wheel contact.

## Verification

Run the showcase on port 5188, then:

```sh
cd web
npx e2e run tests/tower-physics.e2e.ts --config e2e.tower.config.ts --headed
```

The browser checks the actual loaded aircraft model, progression through flare and landing roll, wheel contact, arrival-to-hold trajectory, gear/spoiler state, continuous trajectories, plausible pitch and speed bounds, wind sensitivity, pause/restart, and preservation of connected-mode camera controls and backend authority. These are plausibility and integration checks, not validation against real aircraft telemetry.

## References

- [FAA Airplane Flying Handbook](https://www.faa.gov/regulations_policies/handbooks_manuals/aviation/airplane_handbook): takeoff, approach, flare, landing, and ground effect concepts.
- [Boeing 747-400 airport planning](https://www.boeing.com/content/dam/boeing/v2/airports/acaps/747-400_Rev_F.pdf): physical aircraft characteristics; not the source of simulated coefficients.
- [EUROCONTROL BADA](https://www.eurocontrol.int/model/bada): validated aircraft performance modeling requires aircraft data; this code does not use or claim BADA licensing/validation.
- [SFO runway constraints and operations](https://www.flysfo.com/about/airport-operations/policies-regulations/runway-constraints): runway configurations depend on operating conditions.
