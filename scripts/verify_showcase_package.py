"""Fail packaging if a shipped page, model, or vendor entrypoint is absent."""

import re
from pathlib import Path

root = Path(__file__).resolve().parents[1] / "showcase"
required = [
    "candidates/app.html",
    "candidates/research-shell.js",
    "candidates/research-client.js",
    "candidates/research-renderer.js",
    "candidates/research-scene-controls.js",
    "candidates/research-decision.js",
    "candidates/research-arrivals.js",
    "candidates/research-windows.js",
    "candidates/research-login.html",
    "node_modules/three186/build/three.module.js",
    "node_modules/cesium/Build/Cesium/Cesium.js",
]
for name in required:
    if not (root / name).is_file():
        raise SystemExit("Missing packaged asset: " + name)
for name in ["11-photoreal-sfo.html", "19-tower-cab-interior.html"]:
    for ref in re.findall(
        r"""(?:src|href)=["']([^"']+)""", (root / "candidates" / name).read_text()
    ):
        ref = ref.split("?")[0]
        if ref.startswith(("http", "/", "#")):
            continue
        if not (root / "candidates" / ref).is_file():
            raise SystemExit("Missing local page asset: " + ref)
print("Shipped showcase pages, local dependencies and vendor entrypoints are present")

for name in ("dense_demo.json.gz", "recordings/dense-demo-v1.json.gz"):
    if not (root.parent / "backend/uita/research/assets" / name).is_file():
        raise SystemExit("Missing dense demo asset: " + name)
