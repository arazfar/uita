# Tower desk equipment

Original procedural assets created through Blender MCP on October 17, 2026.
Blender 5.2.1 ran in background mode. No external models, paid generation,
textures, or third-party asset licenses are required.

## Runtime contract

Load `candidates/assets/tower-realism/cab-equipment.glb` and attach its scene to
the tower cab group. Do not rescale, rotate, or translate it.

- GLB is Y-up and uses metres. +X is right; -Z points toward the windows.
- Desk top is Y=0.77 m. The asset leaves the central live displays unobstructed.
- Left: communications panel, headset with coiled cable, gooseneck microphone.
- Right: physical flight strip tray with blank ruled papers and a pencil.
- Labels describe equipment. They do not contain invented flights or clearances.
- Nine material meshes, 14,363 triangles, approximately 568 KiB.
- Standard glTF metallic/roughness materials, with emissive indicator details.
- No textures, Draco dependency, animations, lights, or cameras in the export.

`cab-equipment-preview.png` is a headless Blender render inspected through the
MCP `look` tool. The central empty area is intentional: the existing tower
displays and controls occupy it at runtime.

## Reproduce

Run `Blender --background --python build_cab_equipment.py` from any directory.
The source resolves the showcase asset directory from its own location.
The script creates a new scene and preserves existing scenes. It exports only
the new scene's selected equipment meshes. Preview camera and lights are added
after export. Call `bpy.ops.render.render(write_still=True)` to save the preview.

For headless MCP, start `Blender --background --python headless_mcp.py` using
the installed `blender_mcp` addon. Its local server uses port 9876. The launcher
supplies the main-thread command loop that normally runs through Blender's UI.
It keeps the addon's command validation and MCP safe mode unchanged.

When executing the generator through MCP safe mode, pass its source directly
as `execute_blender_code.code`; replace the initial `Path` output setup with
the absolute output-directory string and omit the final file-size lookup.
Safe mode allows Blender exports but does not allow reading arbitrary files.

The installed addon reports protocol 7 while the MCP server expects protocol
13. Generation, export, render, and image inspection work through its supported
fallbacks. No addon preferences were changed.


## Airport scenery (October 21, 2026)

`build_airport_detail.py` imports the bundled OSM building massing into a new
Blender scene. It preserves those footprints and heights. Original authored
geometry adds curtain-wall frames, canopies, 103 rooftop equipment clusters,
17 generic jet bridges and nearby service equipment. These details are
illustrative. Gate locations, building elevations and vehicles are not surveyed.
The original tower mass is omitted because the runtime already contains its cab.
Distant city massing stays in the original asset.

The generated `airport-detail.glb` uses metres and Y-up coordinates. It is 509 KiB
with Draco compression. The runtime uses its existing local Draco decoder.
The GLB contains geometry and materials; it contains no external textures,
cameras or lights. Runtime roof shaders add seams and mild weathering.
`airport-detail-preview.png` is a headless Cycles render, separate from the
browser screenshots. Blender MCP generated and rendered the asset in background
mode. No Blender window or addon preference change is required.

Reproduce from the repository root:

```sh
/Applications/Blender.app/Contents/MacOS/Blender --background --python showcase/assets/source/tower-realism/build_airport_detail.py
uv run --with pillow showcase/assets/source/tower-realism/fetch_terrain.py
npm --prefix showcase run build:tower
```

For MCP safe mode, replace the `PATH_SETUP_BEGIN` / `PATH_SETUP_END` block with
the three absolute asset paths and the numeric `APRON_RINGS` list. Pass the
remaining source to `execute_blender_code`. Render with
`bpy.ops.render.render(write_still=True)`; inspect the saved path with `look`.
The generator exports only its new active scene and preserves existing scenes.

### Terrain and surface provenance

`fetch_terrain.py` samples 25 public Mapzen Terrarium elevation tiles at zoom 11.
The committed grid contains 401 × 401 signed little-endian metre samples over
58 × 61.5 km. The manifest records each source URL and SHA-256, the output hash,
coordinate frame, sampling method, access date and attribution links.

- Terrain: Mapzen and USGS; ocean bathymetry: NOAA.
- Format: <https://github.com/tilezen/joerd/blob/master/docs/formats.md>.
- Attribution: <https://github.com/tilezen/joerd/blob/master/docs/attribution.md>.
- Hosting: <https://registry.opendata.aws/terrain-tiles/>.
- Shoreline: existing US Census polygons; imagery: existing USGS NAIP pack.
- Buildings, aprons and taxiway axes: existing OpenStreetMap package.

The renderer subtracts the existing 4 m local datum, keeps airport operations
flat, and blends heights near the airport and shoreline. It does not exaggerate
inland elevation. Vegetation is deterministic illustration. Terrain does not
change aircraft altitude, runway contact, or recorded position evidence.

The tower and overview share `src/overview/terrain.ts`. `build:tower` emits its
browser JavaScript with the tower's Three.js import; the overview retains its
existing default terrain settings. Run the generator after editing this source.

Apron and taxiway textures are original deterministic Canvas textures. Water
uses original normal data and filtered sky reflections. Clouds and sunlight are
an illustrative afternoon preset, independent of the recorded weather. Water
motion follows playback pause and respects reduced motion. A missing terrain or
building asset falls back to the original imagery and visibly labels base scenery.

### Limits

This improves depth, surface detail and aircraft finish within the existing
browser renderer. It is not a photogrammetry reconstruction or a surveyed
airport simulator. Bundled aerial imagery limits ground detail at close range.
Aircraft remain representative type classes; facades, roof equipment, clouds,
vegetation, service vehicles and jet bridges are authored scenery. Reflections
include the sky environment, not real-time aircraft or building reflections.
