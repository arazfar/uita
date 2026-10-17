"""Causal context adapters. Missing publication timestamps remain unresolved."""

import copy
from datetime import datetime, timezone

from .data import advisory_status, causal_forecasts, causal_weather, digest


def utc_seconds(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("Timestamp lacks an explicit UTC offset")
    return value.timestamp()


def normalize_metar(row):
    observed = utc_seconds(row["t_utc"])
    ceiling = [
        row["skyl" + str(i)]
        for i in range(1, 5)
        if row.get("skyc" + str(i)) in ("BKN", "OVC", "VV")
        and row.get("skyl" + str(i)) is not None
    ]
    return {
        "observed_at": observed,
        "available_at": observed + 300,
        "visibility_sm": row.get("vsby"),
        "ceiling_ft": min(ceiling) if ceiling else None,
        "wind_from_deg_true": row.get("drct"),
        "wind_speed_kt": row.get("sknt"),
        "raw": row.get("metar"),
        "provenance": {
            "kind": "derived",
            "source": "atc_sfo_w35.metar",
            "availability": "Assumed five-minute reporting delay; receipt time absent",
        },
    }


def normalize_forecast(row):
    return {
        "issued_at": utc_seconds(row["utc_taf_issue"]),
        "valid_from": utc_seconds(row["utc_valid"]),
        "valid_until": utc_seconds(row.get("utc_end_valid") or row["utc_taf_expire"]),
        "product_id": row["product_id"],
        "raw": row["raw"],
        "is_tempo": row["is_tempo"],
        "is_amendment": row["is_amendment"],
        "wind_from_deg_true": row.get("drct"),
        "wind_speed_kt": row.get("sknt"),
        "visibility_sm": row.get("visibility"),
        "provenance": {
            "kind": "observed",
            "source": "atc_sfo_w35.taf",
            "availability": "Source issue time; receipt latency unavailable",
        },
    }


def normalize_advisory(row):
    raw = row["title"] + "\n" + row["text"]
    return {
        "id": digest([str(row["date"]), row["advzy"], raw])[:24],
        "source_identifier": str(row["advzy"]),
        "available_at": None,
        "start": utc_seconds(row["start_utc"]) if row["start_utc"] else None,
        "end": utc_seconds(row["end_utc"]) if row["end_utc"] else None,
        "state": advisory_status(raw),
        "text": raw,
        "provenance": {
            "kind": "observed",
            "source": "atc_sfo_w35.advisories",
            "limitation": "Publication clock absent; withheld from controller. ADL time is not issue time.",
        },
    }


def released_advisories(rows, clock):
    released = []
    for row in rows:
        if row.get("available_at") is None or row["available_at"] > clock:
            continue
        item = copy.deepcopy(row)
        if (
            item.get("end") is not None
            and item["end"] <= clock
            and item["state"] != "cancelled"
        ):
            item["state"] = "expired"
        elif (
            item.get("start") is not None
            and item["start"] > clock
            and item["state"] == "active"
        ):
            item["state"] = "proposed"
        released.append(item)
    return released


def available_context(scenario, clock):
    return {
        "weather": causal_weather(scenario.get("weather", []), clock),
        "forecasts": causal_forecasts(scenario.get("forecasts", []), clock),
        "advisories": released_advisories(scenario.get("advisories", []), clock),
    }


def august_configuration():
    return {
        "valid_from": datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp(),
        "valid_until": datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp(),
        "runways": {
            "01L": {"landing": False, "takeoff": False, "taxi": True},
            "01R": {"landing": False, "takeoff": False, "taxi": False},
            "28L": {"landing": True, "takeoff": True, "taxi": True},
            "28R": {"landing": True, "takeoff": True, "taxi": True},
        },
        "source": "https://www.flysfo.com/fil/node/15803",
        "classification": "announcement_based_assumption",
        "limitation": "Not interval-verified NOTAM or local authorization",
    }
