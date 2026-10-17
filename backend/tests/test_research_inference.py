import httpx
import pytest
from sqlalchemy import select
from uita.provider import MODEL
from uita.research.data import frozen_fixture
from uita.research.database import Base, Budget, Database, Reservation
from uita.research.dynamics import initial_state
from uita.research.inference import InferenceFailure, generate


@pytest.mark.parametrize(
    "case,reason",
    [
        ("budget", "budget_exhausted"),
        ("timeout", "provider_timeout"),
        ("malformed", "invalid_model_response"),
        ("unavailable", "provider_unavailable"),
    ],
)
def test_paid_failures_are_bounded_and_explained(tmp_path, monkeypatch, case, reason):
    database = Database("sqlite:///" + str(tmp_path / "inference.db"))
    Base.metadata.create_all(database.engine)
    with database.transaction() as db:
        db.add(Budget(id="validation-v2", cap=5, reserved=5 if case == "budget" else 0))
    calls = []
    client_type = httpx.Client

    def handler(request):
        calls.append(request.method)
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        if case == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        if case == "unavailable":
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
                "choices": [
                    {"finish_reason": "stop", "message": {"content": "{malformed"}}
                ],
            },
        )

    monkeypatch.setenv("CRUSOE_API_KEY", "synthetic-fixture-key")
    monkeypatch.setattr(
        "uita.research.inference._pricing", lambda _: (0.000001, 0.000001)
    )
    monkeypatch.setattr(
        "uita.research.inference.httpx.Client",
        lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(handler)),
    )
    state = initial_state(frozen_fixture(), 42, "crusoe")
    state["spend_cap_usd"] = 0.5
    with pytest.raises(InferenceFailure) as error:
        generate(database, "test-run", "test-team", state)
    assert error.value.reason == reason
    assert calls.count("POST") == (0 if case == "budget" else 1)
    with database.sessions() as db:
        reservations = list(db.scalars(select(Reservation)))
        assert len(reservations) == (0 if case == "budget" else 1)
        if case == "malformed":
            assert reservations[0].actual > 0
            assert (
                reservations[0].metadata_json["response"]["message"]["content"]
                == "{malformed"
            )
        elif case != "budget":
            assert reservations[0].actual is None
    database.close()
