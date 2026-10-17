from datetime import datetime, timedelta, timezone

import pytest
from uita.research.context import (
    available_context,
    normalize_advisory,
    normalize_metar,
    utc_seconds,
)
from uita.research.data import digest
from uita.research.legs import normalize_legs


def position(
    t=0, identity="abc123", callsign="UAL123", near=False, ground=False, altitude=3000
):
    return {
        "icao24": identity,
        "callsign": callsign,
        "registration": "N123",
        "type_code": "A320",
        "t_utc": datetime(2026, 8, 24, tzinfo=timezone.utc) + timedelta(seconds=t),
        "lon": -122.375 if near else -122.175,
        "lat": 37.619,
        "alt_baro_ft": altitude,
        "gs_kt": 20 if ground else 200,
        "track_deg": 280,
        "on_ground": ground,
    }


def test_flight_identity_deduplication_and_airport_evidence():
    rows = [
        position(),
        position(),
        position(600, near=True, ground=True, altitude=13),
        position(780, near=True, ground=True, altitude=13),
        position(1000),
        position(1100, identity="def456"),
        position(1800, identity="def456", near=True, ground=True, altitude=13),
    ]
    legs = list(normalize_legs(rows))
    assert len(legs) == 3
    assert [leg["operation"] for leg in legs] == ["arrival", "departure", "arrival"]
    assert len(legs[0]["points"]) == 3
    assert len({leg["id"] for leg in legs}) == 3
    assert digest(legs) == digest(list(normalize_legs(rows)))


def test_gap_callsign_jump_and_null_height_preserved():
    rows = [
        position(0, altitude=None),
        position(1500),
        position(1600, callsign="UAL456"),
    ]
    legs = list(normalize_legs(rows))
    assert len(legs) == 3
    assert legs[0]["points"][0]["altitude_ft"] is None
    assert "null_pressure_altitude" in legs[0]["points"][0]["quality_flags"]
    assert all(leg["operation"] == "unresolved" for leg in legs)
    with pytest.raises(ValueError, match="chronologically"):
        list(normalize_legs([position(10), position(0)]))


def test_context_never_promotes_unknown_advisory_issue_time():
    start = datetime(2026, 8, 24, tzinfo=timezone.utc)
    advisory = normalize_advisory(
        {
            "date": start,
            "advzy": 1,
            "title": "PROPOSED PROGRAM",
            "text": "ADL TIME: 2357Z",
            "start_utc": start,
            "end_utc": start + timedelta(hours=1),
        }
    )
    report = normalize_metar({"t_utc": start, "metar": "fixture", "vsby": 10})
    scenario = {
        "weather": [report],
        "advisories": [advisory],
        "forecasts": [
            {
                "issued_at": start.timestamp() + 600,
                "valid_until": start.timestamp() + 3600,
            }
        ],
    }
    prior = available_context(scenario, start.timestamp() + 299)
    assert prior["weather"]["stale"]
    assert prior["forecasts"] == [] and prior["advisories"] == []
    released = available_context(scenario, start.timestamp() + 600)
    assert released["weather"]["visibility_sm"] == 10
    assert released["forecasts"] and released["advisories"] == []
    with pytest.raises(ValueError, match="UTC offset"):
        utc_seconds(datetime(2026, 8, 24))
