import gzip
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from uita.research.api import create_app
from uita.research.budget import BudgetExhausted, reserve_capture
from uita.research.contracts import RunCreate
from uita.research.data import digest, save_artifact
from uita.research.database import Base, Budget, Database
from uita.research.presentation import install_recording


def test_fresh_demo_pack_without_source_or_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("UITA_ACCESS_MODE", "public_demo")
    monkeypatch.setenv("UITA_HISTORY_LOCAL", "1")
    database = Database("sqlite:///" + str(tmp_path / "demo.db"))
    Base.metadata.create_all(database.engine)
    assets = Path("backend/uita/research/assets")
    with database.transaction() as db:
        for a in json.loads((assets / "demo_bundle.json").read_text())["artifacts"]:
            save_artifact(db, a["id"], a["kind"], a["payload"])
        for name in ("showcase_data.json.gz", "dense_demo.json.gz"):
            pack = json.loads(gzip.decompress((assets / name).read_bytes()))
            assert digest(pack["artifacts"]) == pack["checksum"]
            for a in pack["artifacts"]:
                assert digest(a["payload"]) == a["checksum"]
                save_artifact(db, a["id"], a["kind"], a["payload"])
                save_artifact(db, a["id"], a["kind"], a["payload"])
        from uita.research.sandbox import scenario_from

        sandbox_scenario = scenario_from(pack["artifacts"][0]["payload"])
        save_artifact(db, sandbox_scenario["id"], "scenario", sandbox_scenario)
        for p in (assets / "recordings").glob("*.json.gz"):
            install_recording(db, json.loads(gzip.decompress(p.read_bytes())))
    app = create_app(database, False)
    assert {"/api/history/catalog", "/uita/api/history/catalog"} <= {
        r.path for r in app.routes
    }
    with TestClient(app) as c:
        assert c.get("/health/demo").status_code == 200
        cat = c.get("/api/v2/history/catalog").json()[0]
        w = c.get(
            f"/api/v2/history/{cat['id']}/window",
            params={"clock": cat["recommended_start"]},
        ).json()
        assert len(w["frames"]) <= 122
        assert w["frames"][0]["aircraft"]
        assert any(a["altitude_ft"] is None for f in w["frames"] for a in f["aircraft"])
        assert (
            c.get(
                f"/api/v2/history/{cat['id']}/window", params={"clock": cat["end"] + 1}
            ).status_code
            == 422
        )
        recordings = c.get("/api/v2/recordings").json()
        assert any(r["id"] == "nemotron-immersive-episode-1" for r in recordings)
        r = recordings[0]
        result = c.get(
            f"/api/v2/recordings/{r['id']}/window",
            params={"clock": r["recommended_start"]},
        ).json()
        assert result["frames"][0]["aircraft"]


def test_capture_budget_is_atomic_and_not_public(tmp_path):
    db = Database("sqlite:///" + str(tmp_path / "budget.db"))
    Base.metadata.create_all(db.engine)
    with db.transaction() as s:
        s.add(Budget(id="capture:immersive-capture-v1", cap=10, reserved=0))

    def attempt(_):
        try:
            with db.transaction() as s:
                reserve_capture(s, "same-run", 1.2, "immersive-capture-v1")
            return True
        except BudgetExhausted:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(attempt, range(2))) == 1
    with pytest.raises(ValueError):
        RunCreate(
            scenario_id="fixture-august-v2",
            idempotency_key="test",
            capture_campaign="immersive-capture-v1",
        )
    with db.transaction() as s:
        s.get(Budget, "capture:immersive-capture-v1").reserved = 9.5
    with pytest.raises(BudgetExhausted), db.transaction() as s:
        reserve_capture(s, "another", 0.6, "immersive-capture-v1")
    db.close()


def test_history_interpolates_only_supported_observation_pairs(tmp_path, monkeypatch):
    monkeypatch.setenv("UITA_ACCESS_MODE", "public_demo")
    database = Database("sqlite:///" + str(tmp_path / "history.db"))
    Base.metadata.create_all(database.engine)

    def point(t, lon, altitude, segment=1):
        return {
            "t": t,
            "lon": lon,
            "lat": 37.6,
            "altitude_ft": altitude,
            "track_deg_true": 350 if t == 100 else 10,
            "segment_id": segment,
        }

    with database.transaction() as db:
        save_artifact(
            db,
            "test-history",
            "history_window",
            {
                "start": 100,
                "end": 200,
                "provenance": {"kind": "observed"},
                "tracks": [
                    {
                        "id": "known",
                        "points": [point(100, -122.3, 1000), point(110, -122.2, 2000)],
                    },
                    {
                        "id": "unknown",
                        "points": [point(100, -122.3, None), point(110, -122.2, 2000)],
                    },
                    {
                        "id": "gap",
                        "points": [
                            point(100, -122.3, 1000),
                            point(110, -122.2, 2000, 2),
                        ],
                    },
                ],
            },
        )
    with TestClient(create_app(database, False)) as client:
        result = client.get(
            "/api/v2/history/test-history/window?clock=105&seconds=1"
        ).json()
        aircraft = {a["id"]: a for a in result["frames"][0]["aircraft"]}
        assert aircraft["known"]["longitude"] == pytest.approx(-122.25)
        assert aircraft["known"]["altitude_ft"] == 1500
        assert aircraft["known"]["track_deg_true"] == 0
        assert aircraft["known"]["source_time"] == 100
        assert aircraft["unknown"]["altitude_ft"] is None
        assert aircraft["unknown"]["longitude"] == -122.3
        assert aircraft["gap"]["longitude"] == -122.3
