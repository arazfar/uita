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
