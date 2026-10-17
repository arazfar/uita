"""Generate v2 schema without opening or migrating the production database."""

import json
from pathlib import Path

from uita.research.api import create_app
from uita.research.database import Database

target = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "research"
    / "v2"
    / "api.openapi.json"
)
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(
    json.dumps(create_app(Database("sqlite:///:memory:")).openapi(), indent=2) + "\n"
)
print(target)
