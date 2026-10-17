"""Export source-controlled shared boundary schema without touching the live DB."""
import json, os
from pathlib import Path
os.environ['DATABASE_URL']='sqlite:///:memory:'
from uita.app import app
target=Path(__file__).resolve().parents[1]/'docs'/'api.openapi.json'
target.write_text(json.dumps(app.openapi(),indent=2)+'\n')
print(target)
