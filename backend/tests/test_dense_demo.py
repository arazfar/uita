import gzip
import json
from pathlib import Path

from uita.research.data import digest
from uita.research.presentation import validate_recording, install_recording
from uita.research.database import Base, Database, Artifact
from uita.research.data import save_artifact

ASSETS = Path(__file__).parents[1] / "uita/research/assets"


def test_dense_pack_integrity_density_and_independent_comparison(tmp_path):
    pack = json.loads(gzip.decompress((ASSETS / "dense_demo.json.gz").read_bytes()))
    recording = json.loads(
        gzip.decompress((ASSETS / "recordings/dense-demo-v1.json.gz").read_bytes())
    )
    assert pack["checksum"] == digest(pack["artifacts"])
    manifest = validate_recording(recording)
    assert manifest.coverage["fraction_6_to_10"] >= 0.8
    assert manifest.coverage["airborne_min"] >= 6
    assert manifest.provenance == "fixture" and manifest.model_responses == 0
    assert (
        recording["comparison"]["results"][0]["state_hash"]
        == recording["comparison"]["results"][1]["state_hash"]
    )
    assert recording["comparison"]["results"][0]["metrics"]["violations"] == 0
    assert manifest.end - manifest.recommended_start == 1200
    assert manifest.event_tape[0]["clock"] == manifest.recommended_start + 90
    for a, b in zip(recording["frames"], recording["baseline_frames"]):
        assert a["aircraft"] == b["aircraft"] and a["metrics"] == b["metrics"]
    database = Database(f"sqlite:///{tmp_path}/empty.db")
    Base.metadata.create_all(database.engine)
    for _ in range(2):
        with database.transaction() as db:
            for artifact in pack["artifacts"]:
                assert artifact["checksum"] == digest(artifact["payload"])
                save_artifact(db, artifact["id"], artifact["kind"], artifact["payload"])
            install_recording(db, recording)
    with database.sessions() as db:
        assert db.get(Artifact, manifest.id).checksum == digest(recording)
