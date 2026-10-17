---
name: Uita
description: A precise aviation instrument for reproducible simulation and evidence inspection.
colors:
  canvas: "#101f2a"
  background: "#111f2a"
  panel: "#14232f"
  foreground: "#dbe8ed"
  muted: "#8fa7b5"
  line: "#2a3b48"
  cyan: "#8adadd"
  amber: "#e9b578"
  action: "#9ae1df"
  action-ink: "#102b35"
  action-hover: "#b5efec"
  secondary: "#213541"
  secondary-ink: "#bdd1db"
  secondary-hover: "#2c4655"
  field: "#1c3545"
  field-ink: "#d1e5ec"
  scene: "#1b3945"
  drawer: "#172d3a"
  pass: "#acf1da"
  pass-bg: "#244d44"
  fail: "#f0bd9e"
  fail-bg: "#563c34"
  unresolved: "#e9c591"
  unresolved-bg: "#453f33"
typography:
  display:
    fontFamily: "DM Sans Variable, sans-serif"
    fontSize: "32px"
    fontWeight: 450
    lineHeight: 1.2
    letterSpacing: "-0.035em"
  title:
    fontFamily: "DM Sans Variable, sans-serif"
    fontSize: "17px"
    fontWeight: 560
    letterSpacing: "-0.025em"
  body:
    fontFamily: "DM Sans Variable, sans-serif"
    fontSize: "11px"
    lineHeight: 1.75
  button:
    fontFamily: "DM Sans Variable, sans-serif"
    fontSize: "11px"
    fontWeight: 550
  data:
    fontFamily: "IBM Plex Mono, monospace"
    fontSize: "10px"
  clock:
    fontFamily: "IBM Plex Mono, monospace"
    fontSize: "19px"
    fontWeight: 400
    letterSpacing: "-0.02em"
rounded:
  tag: "3px"
  control: "5px"
  table: "8px"
  drawer: "10px"
  comparison: "12px"
spacing:
  tight: "5px"
  related: "8px"
  control: "10px"
  group: "16px"
  panel: "22px"
components:
  button-primary:
    backgroundColor: "{colors.action}"
    textColor: "{colors.action-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
  button-primary-hover:
    backgroundColor: "{colors.action-hover}"
    textColor: "{colors.action-ink}"
  button-secondary:
    backgroundColor: "{colors.secondary}"
    textColor: "{colors.secondary-ink}"
    typography: "{typography.button}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
  button-secondary-hover:
    backgroundColor: "{colors.secondary-hover}"
  field:
    backgroundColor: "{colors.field}"
    textColor: "{colors.field-ink}"
    rounded: "{rounded.control}"
    padding: "9px 10px"
  status-pass:
    backgroundColor: "{colors.pass-bg}"
    textColor: "{colors.pass}"
    rounded: "{rounded.tag}"
    padding: "5px 6px"
  evidence-drawer:
    backgroundColor: "{colors.drawer}"
    rounded: "{rounded.drawer}"
    padding: "23px"
    width: "352px"
---

# Design System: Uita

## Overview

**Creative North Star: "Precise aviation instrument"**

Uita uses the user-pinned precise aviation instrument direction: navy surfaces, restrained cyan actions, and amber attention. The recognizable SFO scene gives spatial context; compact controls and evidence support deliberate inspection. Density serves the simulation, with tables and explicit state text carrying information beyond the 3D view.

**Key Characteristics:**

- A large spatial scene with compact instrument chrome.
- Locally served proportional interface type and monospaced operational values.
- Tonal panels, fine dividers, and diffuse overlay shadows.

This scan documents `frontend/src/style.css`, `World.tsx`, `App.tsx`, `Comparison.tsx`, and `main.tsx`. Frontmatter records reusable values actually present in the build; the sidecar carries rendering examples and extensions. The earlier `frontend/DESIGN.md` is background context; this root document is the machine-readable system record.

## Colors

The palette is cool navy with pale, desaturated instrument accents. Frontmatter is normative for values; CSS custom properties remain the implementation source.

### Primary

Cyan identifies selected controls, highlighted flight paths, and the brand punctuation. The brighter action fill and dark action ink distinguish primary buttons from scene overlays.

### Secondary

Amber marks disruptions, priority, and unresolved evidence. Pass, fail, and unresolved badges use their own tonal foreground/background pairs and always include text.

### Neutral

Canvas and background are distinct existing navy values. Panel surfaces support the inspector; drawer surfaces lift temporary tools above it. Foreground, muted text, and line tokens establish information hierarchy. Scene blue is the world background and fog color.

**The Explicit State Rule.** Color accompanies a named state; it never substitutes for verification or connection text.

## Typography

DM Sans Variable is locally bundled for interface and display text; IBM Plex Mono regular is locally bundled for coordinates, timestamps, and evidence. Both arrive through npm font packages in `main.tsx`, with sans-serif and monospace fallbacks. Operational numbers use tabular numerals where the shared data selectors apply.

The default scene display is the frontmatter display role, changing to 40px at the wide breakpoint, 28px at 1200px, 25px at 900px, and 27px in the stacked layout. Inspector titles use the title role; body copy uses the body role. Flight identity uses 12px medium-weight text. The wordmark is a dedicated 37px, weight 660 treatment with tight tracking; it is not a general heading style. Code and measurements use the data role; the clock uses its larger monospaced role.

The existing build includes incidental 6–9px map, reservation, and status labels. These are documented as a legibility limitation, not a scale for new essential content.

## Layout

The current operational shell fills the viewport with a 70px header, flexible workspace, 121px transport strip, and 29px status strip, with a 660px minimum height. The scene takes remaining width beside a 332px inspector. Inspector width becomes 370px at 1600px and above, 306px at 1200px and below, and 288px at 900px and below. Content scrolls inside the inspector; divisions use fine rules rather than detached cards.

At 700px and below, the shell returns to document flow. A 60px header precedes the scene (56dvh, minimum 390px), inspector, wrapped transport, and status strip. The inspector is 420–650px high; its traffic list uses two columns. Drawers become fixed bottom panels with 12px side clearance and maximum 78dvh height. Paired comparison scenes switch from columns to rows.

The compact spacing vocabulary is intentionally contextual rather than a strict modular grid: 5–10px within controls, 16px between groups, and approximately 20–26px in panels. The current layout is a surface implementation, not a requirement that every future page use these exact tracks.

## Elevation & Depth

Permanent surfaces use tonal separation and thin navy rules. Temporary overlays use diffuse downward shadows: camera controls (`0 8px 24px #091d2738`), drawers (`0 18px 50px #06192588`), and comparison (`0 25px 90px #00121bcc`). The scene's top/bottom gradient preserves overlay readability; it is part of scene compositing.

World depth comes from fog, hemisphere and directional light, restrained material roughness, and a schematic Bay shoreline. World x points east and negative z north. Horizontal coordinates multiply nautical miles by 2.8; altitude multiplies feet by .0009 and is visually exaggerated. Runway endpoints come directly from backend state. Aircraft scale is exaggerated for selection and recognition. Rapier checks static camera clearance only.

**The Evidence Boundary Rule.** Scene depth and motion communicate location; backend state and evidence supply measurements and verification.

## Shapes

Controls have gently rounded corners, small status tags are tighter, and drawers/comparison overlays have broader corners. Tables use their own intermediate rounding. The round play button is the transport's distinctive primary control. Aircraft and runway labels are compact rectangular instruments, not decorative bubbles. Fine borders define controls and rows; avoid introducing ornamental geometry into evidence surfaces.

## Components

### Buttons

Primary and secondary variants share frontmatter padding, radius, and type, with a 36px minimum height. Secondary controls add a fine blue-gray border. Icon buttons use 30px square targets and descriptive accessible names. Hover changes color over .18s. Focus-visible uses a pale cyan 2px outline with 4px offset; disabled buttons use opacity .38 and a not-allowed cursor. Preserve visible focus for links, summaries, fields, and selects too.

### Inputs and navigation

Labeled inputs and native selects use the field surface, thin blue-gray outline, and control radius. Tabs form a flush inspector header: selected text brightens and a cyan 2px underline marks the active view. Camera controls form a compact floating segmented group. Native details/summary reveals evidence progressively.

### Status and evidence containers

Pass, fail, pending, and unresolved chips retain uppercase status text with their state palettes. Evidence is organized as ruled rows, summaries, and expandable data, with JSON loaded on request. The preview is capped at 20,000 characters with a complete JSON download. There is no generic card primitive in this build; drawers and the comparison overlay are the reusable raised containers.

### Scene, timeline, and replay

DOM buttons projected over the scene expose flight/runway selection. Label placement excludes the measured scene-heading rectangle with clearance. The compass follows the camera-projected world north direction. The traffic table offers essential flight data without relying on WebGL; scene failure explicitly directs users to it. Reservation lanes align to runway resources, with selected reservations linked to flight selection. Replay and paired comparison use backend checkpoint states at shared logical time; frontend interpolation does not generate metrics.

The renderer caps device pixel ratio at 1.7, uses 1024px directional shadow maps, caches GLB loading, clones loaded scene assets, and instances 160 background buildings. DOM label projection is throttled to .08 seconds. These are current resource controls, not a measured frame-rate guarantee; comparison renders two worlds.

Reduced motion disables CSS transitions/animations, copies aircraft and follow-camera positions directly, and disables orbit damping. The scene listens for preference changes during the session. Loading spinners otherwise rotate over 1.3 seconds. Keep motion functional and preserve server-authoritative positions.

## Do's and Don'ts

- Do preserve the navy, cyan, and amber hierarchy.
- Do pair state colors with readable status text and provide the traffic table alongside 3D inspection.
- Do show unavailable metrics as an em dash and keep simulation, replay, and provider states explicit.
- Do reuse local fonts, cached scene assets, and instanced repeated geometry.
- Don't turn the operational workspace into a wall of metric cards.
- Don't imply that schematic geometry, exaggerated altitude, or camera physics measures flight separation.
- Don't promote tiny incidental map or timeline text into a general interface typography standard.
