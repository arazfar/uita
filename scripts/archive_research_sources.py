"""Archive official public source bytes and SHA256; never label current HTML historical."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from uita.research.standards import PACK, RULES

root = Path("output/research-sources")
root.mkdir(parents=True, exist_ok=True)
sources = []
with httpx.Client(timeout=30, follow_redirects=True) as client:
    for url in sorted({r["source"] for r in RULES}):
        response = client.get(url)
        response.raise_for_status()
        name = hashlib.sha256(url.encode()).hexdigest()[:16] + ".html"
        (root / name).write_bytes(response.content)
        sources.append(
            {
                "url": url,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "sha256": hashlib.sha256(response.content).hexdigest(),
                "file": name,
                "applicability": "Current reference HTML; historical effective version requires separate verification",
            }
        )
(root / "manifest.json").write_text(
    json.dumps({"sources": sources, "rule_pack": PACK.model_dump()}, indent=2) + "\n"
)
print(f"Archived {len(sources)} sources in {root}")
