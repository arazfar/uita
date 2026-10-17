"""Small frozen contracts. Source identities and outcomes never enter prompts."""
from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

VERSION = "historical-arrival-sequence-v1"
DATA_DIR = Path(__file__).resolve().parent / "data"
RULES = {
    "medium_leader_spacing_seconds": 90,
    "heavy_leader_spacing_seconds": 150,
    "completion_horizon_seconds": 3600,
    "unfinished_penalty_seconds": 3600,
}
SYSTEM_PROMPT = (
    "You sequence arrivals from a causal snapshot of last-known aircraft observations. "
    "Predict the order in which these aircraft next appear in the recorded arrival-operation roster. "
    "This is a historical-order prediction task, not an authentic ATC clearance task. "
    "Aircraft IDs are arbitrary local aliases. Positions can be stale; age_seconds states their age. "
    "free_flow_seconds is a simple direct-to-airport estimate adjusted for observation age; "
    "it does not reveal actual arrival times. Use only the supplied input. "
    "Return exactly one JSON object with the key order and every supplied aircraft ID exactly once, "
    'for example {"order":["A2","A1"]}. Do not include explanations or extra keys.'
)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def validate_input(state):
    """Reject unexpected fields before any public state crosses a model boundary."""
    if set(state) != {"task", "runway", "rules", "aircraft"}:
        raise ValueError("Unexpected public state fields")
    if state["task"] != "sequence_arrivals_v1" or state["rules"] != RULES:
        raise ValueError("Unknown task or changed frozen rules")
    if set(state["runway"]) != {"resource", "available_in_seconds"}:
        raise ValueError("Unexpected runway fields")
    if state["runway"]["resource"] != "shared_arrival_runway":
        raise ValueError("Unknown runway resource")
    fields = {"id", "distance_nm", "bearing_deg_true", "altitude_ft", "groundspeed_kt",
              "track_deg_true", "wake_category", "free_flow_seconds", "position_source", "altitude_source", "age_seconds"}
    aircraft = state["aircraft"]
    if not isinstance(aircraft, list) or not 2 <= len(aircraft) <= 6:
        raise ValueError("An encounter needs 2–6 arrivals")
    ids = [a.get("id") for a in aircraft]
    if set(ids) != {f"A{i+1}" for i in range(len(aircraft))} or len(set(ids)) != len(ids):
        raise ValueError("Local aliases must form A1..An")
    for a in aircraft:
        if set(a) != fields or a["position_source"] != "observed_entry":
            raise ValueError("Only allowlisted observed entry features are permitted")
        if a["altitude_source"] not in ("beacon_reported", "unknown"):
            raise ValueError("Unknown altitude provenance")
        if a["altitude_source"] == "unknown":
            if a["altitude_ft"] is not None:
                raise ValueError("Unknown actual altitude must be null")
        elif isinstance(a["altitude_ft"], bool) or not isinstance(a["altitude_ft"], (int, float)) or not math.isfinite(a["altitude_ft"]):
            raise ValueError("Beacon altitude must be finite")
        if a["wake_category"] not in ("medium", "heavy"):
            raise ValueError("Unknown simplified wake category")
        for key in fields - {"id", "wake_category", "position_source", "altitude_source", "altitude_ft"}:
            value = a[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Non-finite public feature: {key}")
        if not 0 <= a["age_seconds"] <= 300 or not 0 <= a["free_flow_seconds"] <= 3600:
            raise ValueError("Observation too stale or free-flow time out of range")
        if not 90 <= a["groundspeed_kt"] <= 550 or not 8 <= a["distance_nm"] <= 81:
            raise ValueError("Observed entry outside frozen feature bounds")
    available = state["runway"]["available_in_seconds"]
    if isinstance(available, bool) or not isinstance(available, (int, float)) or not math.isfinite(available) or available < 0:
        raise ValueError("Invalid runway availability")
    return state


def model_messages(case):
    state = validate_input(case["input"])
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": canonical(state)}]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def parse_action(raw, state):
    validate_input(state)
    if not isinstance(raw, str):
        raise ValueError("Provider action must be raw JSON text")
    try:
        action = json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("Action is not a JSON object") from exc
    if not isinstance(action, dict) or set(action) != {"order"}:
        raise ValueError("Action requires exactly the order field")
    order = action["order"]
    if not isinstance(order, list) or not all(isinstance(x, str) for x in order):
        raise ValueError("Order must contain string IDs")
    expected = {a["id"] for a in state["aircraft"]}
    if len(order) != len(expected) or set(order) != expected:
        raise ValueError("Order is not an exact permutation of active aircraft")
    return action


def scripted_action(state):
    validate_input(state)
    return {"order": [a["id"] for a in sorted(state["aircraft"], key=lambda a: (a["free_flow_seconds"], a["id"]))]}


def schedule_action(state, action):
    action = parse_action(canonical(action), state)
    by_id = {a["id"]: a for a in state["aircraft"]}
    schedule = []
    previous = None
    for aircraft_id in action["order"]:
        a = by_id[aircraft_id]
        earliest = max(a["free_flow_seconds"], state["runway"]["available_in_seconds"])
        if previous is not None:
            spacing = RULES[f"{by_id[previous['id']]['wake_category']}_leader_spacing_seconds"]
            earliest = max(earliest, previous["time_seconds"] + spacing)
        previous = {"id": aircraft_id, "time_seconds": earliest}
        schedule.append(previous)
    return schedule


def check_schedule(state, schedule):
    """Recompute constraints and metrics independently from scheduling choices."""
    validate_input(state)
    by_id = {a["id"]: a for a in state["aircraft"]}
    ids = [s.get("id") for s in schedule]
    if len(ids) != len(by_id) or set(ids) != set(by_id):
        raise ValueError("Checker rejected missing, duplicate or unknown aircraft")
    previous = None
    delays = []
    completed = 0
    for slot in schedule:
        if set(slot) != {"id", "time_seconds"}:
            raise ValueError("Checker rejected malformed slot")
        aircraft = by_id[slot["id"]]
        t = slot["time_seconds"]
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t):
            raise ValueError("Checker rejected non-finite slot")
        if t < aircraft["free_flow_seconds"] or t < state["runway"]["available_in_seconds"]:
            raise ValueError("Checker rejected slot before release")
        if previous is not None:
            previous_aircraft = by_id[previous["id"]]
            required = 150 if previous_aircraft["wake_category"] == "heavy" else 90
            if t - previous["time_seconds"] < required - 1e-9:
                raise ValueError("Checker rejected wake-spacing violation")
        completed += t <= RULES["completion_horizon_seconds"]
        delays.append(max(0, t - aircraft["free_flow_seconds"]))
        previous = slot
    backlog = len(by_id) - completed
    return {"completed": completed, "backlog": backlog, "constraint_violations": 0,
            "delay_seconds_sum": round(sum(delays), 3),
            "max_delay_seconds": round(max(delays), 3),
            "penalized_delay_seconds": round(sum(delays) + backlog * RULES["unfinished_penalty_seconds"], 3)}


def teacher_action(state):
    """Synthetic scheduling oracle. This is not the primary historical target."""
    validate_input(state)
    ids = sorted(a["id"] for a in state["aircraft"])
    candidates = []
    for order in itertools.permutations(ids):
        action = {"order": list(order)}
        metrics = check_schedule(state, schedule_action(state, action))
        candidates.append(((metrics["backlog"], metrics["delay_seconds_sum"], metrics["max_delay_seconds"], order), action))
    return min(candidates, key=lambda item: item[0])[1]


def evaluate_action(case, action):
    state = case["input"]
    action = parse_action(canonical(action), state)
    metrics = check_schedule(state, schedule_action(state, action))
    reference = case["private"]["historical_order"]
    if len(reference) != len(action["order"]) or set(reference) != set(action["order"]):
        raise ValueError("Historical label is not a complete permutation")
    rank = {aircraft_id: i for i, aircraft_id in enumerate(reference)}
    pairs = list(itertools.combinations(action["order"], 2))
    correct = sum(rank[a] < rank[b] for a, b in pairs)
    metrics.update(next_arrival_correct=action["order"][0] == reference[0],
                   exact_sequence_correct=action["order"] == reference,
                   pairwise_correct=correct, pairwise_total=len(pairs),
                   pairwise_agreement=correct / len(pairs))
    return metrics


def failed_metrics(case):
    n = len(case["input"]["aircraft"])
    return {"completed": 0, "backlog": n, "constraint_violations": 0,
            "delay_seconds_sum": 0, "max_delay_seconds": 0,
            "penalized_delay_seconds": n * RULES["unfinished_penalty_seconds"],
            "next_arrival_correct": False, "exact_sequence_correct": False,
            "pairwise_correct": 0, "pairwise_total": n * (n - 1) // 2, "pairwise_agreement": 0}


def load_cases(split, directory=DATA_DIR):
    if split not in ("train", "validation"):
        raise ValueError("Only train and validation are available; final test stays sealed")
    cases = [json.loads(line) for line in (Path(directory) / f"{split}.jsonl").read_text().splitlines() if line.strip()]
    ids = set()
    for case in cases:
        validate_input(case["input"])
        if case["split"] != split or case["case_id"] in ids:
            raise ValueError("Split mismatch or duplicate case")
        ids.add(case["case_id"])
    return cases
