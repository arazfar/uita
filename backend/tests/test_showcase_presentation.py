import copy

import pytest
from fastapi.testclient import TestClient
from uita.research.api import create_app
from uita.research.contracts import PresentationFrame
from uita.research.data import digest, frozen_fixture, save_artifact
from uita.research.database import Base, Budget, Database
from uita.research.dynamics import initial_state, step
from uita.research.geometry import geographic, local
from uita.research.presentation import frame, validate_recording
from uita.research.security import add_user


def test_coordinates_and_null_altitude():
    state = initial_state(frozen_fixture(), 42, "static")
    step(state, frozen_fixture())
    a = state["aircraft"][0]
    a["altitude_ft"] = None
    result = frame(state, "test", 1)
    assert result.aircraft[0].altitude_ft is None
    assert local(
        result.aircraft[0].longitude, result.aircraft[0].latitude
    ) == pytest.approx((a["x_nm"], a["y_nm"]))
    assert geographic(0, 0) == (-122.375, 37.619)
    assert "spawn_cursor" not in result.model_dump()


def test_private_showcase_and_read_only_frames(tmp_path, monkeypatch):
    monkeypatch.setenv("UITA_SHOWCASE", "1")
    db = Database("sqlite:///" + str(tmp_path / "test.db"))
    Base.metadata.create_all(db.engine)
    with db.transaction() as s:
        scenario = frozen_fixture()
        save_artifact(s, scenario["id"], "scenario", scenario)
        s.add(Budget(id="validation-v2", cap=5, reserved=0))
        add_user(s, "tester", "test-password-long", "one", "operator")
        add_user(s, "other", "test-password-long", "two", "viewer")
    with TestClient(create_app(db, False)) as client:
        assert client.get("/candidates/app.html").status_code == 401
        assert client.get("/api/v2/recordings").status_code == 401
        assert client.get("/api/maps-key").status_code == 401
        client.post(
            "/api/v2/login",
            json={"username": "tester", "password": "test-password-long"},
        )
        shell = client.get("/")
        assert "Traffic, decisions, evidence" in shell.text
        assert shell.headers["x-frame-options"] == "SAMEORIGIN"
        assert (
            client.post(
                "/api/v2/runs", headers={"origin": "https://evil.example"}, json={}
            ).status_code
            == 403
        )
        r = client.post(
            "/api/v2/runs",
            json={"scenario_id": scenario["id"], "idempotency_key": "create-test"},
        ).json()
        path = "/api/v2/runs/" + r["id"] + "/presentation"
        a = client.get(path)
        assert a.status_code == 200
        assert PresentationFrame.model_validate(a.json())
        assert a.json() == client.get(path).json()
        assert client.get("/uita/api/history/other").status_code == 404
        assert client.get("/uita/api/history/window?start=1").status_code == 422
        client.post(
            "/api/v2/login",
            json={"username": "other", "password": "test-password-long"},
        )
        assert client.get(path).status_code == 404


def test_bundled_recording_checksums():
    import gzip
    import json
    from pathlib import Path

    path = Path("backend/uita/research/assets/showcase_recording.json.gz")
    assert path.exists(), "Authentic recording must be packaged"
    payload = json.loads(gzip.decompress(path.read_bytes()))
    manifest = validate_recording(payload)
    assert manifest.model_responses > 0
    assert len(manifest.event_tape) == 1
    assert manifest.event_tape[0]["clock"] == manifest.start + 90
    assert payload["comparison"]["scenario_hash"] == manifest.scenario_checksum
    assert (
        payload["comparison"]["results"][0]["clock"]
        == payload["comparison"]["results"][1]["clock"]
    )
    damaged = copy.deepcopy(payload)
    damaged["frames"][0]["clock"] += 1
    with pytest.raises(ValueError, match="checksum"):
        validate_recording(damaged)


def test_recording_window_is_bounded_and_keeps_fallback_context(tmp_path):
    import gzip
    import json
    from pathlib import Path

    from uita.research.presentation import install_recording

    database = Database("sqlite:///" + str(tmp_path / "recording.db"))
    Base.metadata.create_all(database.engine)
    bundle = json.loads(
        Path("backend/uita/research/assets/demo_bundle.json").read_text()
    )
    payload = json.loads(
        gzip.decompress(
            Path("backend/uita/research/assets/showcase_recording.json.gz").read_bytes()
        )
    )
    with database.transaction() as db:
        for a in bundle["artifacts"]:
            save_artifact(db, a["id"], a["kind"], a["payload"])
        install_recording(db, payload)
        add_user(db, "tester", "test-password-long", "one", "viewer")
        db.add(Budget(id="validation-v2", cap=5, reserved=0))
    with TestClient(create_app(database, False)) as client:
        client.post(
            "/api/v2/login",
            json={"username": "tester", "password": "test-password-long"},
        )
        manifest = payload["manifest"]
        url = f"/api/v2/recordings/{manifest['id']}/window"
        assert client.get(url, params={"clock": manifest["end"] + 1}).status_code == 422
        assert (
            client.get(
                url, params={"clock": manifest["start"], "seconds": 121}
            ).status_code
            == 422
        )
        response = client.get(url, params={"clock": manifest["end"], "seconds": 30})
        assert response.status_code == 200
        window = response.json()
        assert len(window["frames"]) == 1
        assert any(e["kind"] == "controller_fallback" for e in window["events"])
        assert window["frames"][0]["clock"] == window["baseline_frames"][0]["clock"]
        exported = client.get(f"/api/v2/recordings/{manifest['id']}/export").json()
        assert exported == payload
        assert client.get("/api/v2/recordings").json()[0]["model_responses"] == 1
    broken = copy.deepcopy(payload)
    broken["frames"][0]["simulator_version"] = "unrelated-simulator"
    broken["manifest"]["checksums"]["frames"] = digest(broken["frames"])
    with pytest.raises(ValueError, match="Incompatible"):
        validate_recording(broken)
