# Arrival sequencing benchmark v1

The primary task predicts recorded arrival order from observed entry snapshots. A secondary scheduling surrogate measures the consequences of a chosen sequence under fixed synthetic rules. Neither task measures human controller performance. The historical sequence is the order of recorded arrival-operation timestamps, not authentic command labels.

## Frozen interfaces

`benchmark/core.py` exports:

- `SYSTEM_PROMPT`: exact prompt shared by inference and supervised training.
- `model_messages(case) -> [{role, content}, ...]`: only `case["input"]` enters model messages.
- `parse_action(raw, input) -> dict`: strict JSON, exact permutation of active local aircraft IDs, no extra fields.
- `evaluate_action(case, action) -> dict`: independent schedule checker and historical agreement metrics.
- `scripted_action(input) -> {"order": [...]}`: earliest free-flow-arrival order; ID breaks ties.
- `teacher_action(input) -> {"order": [...]}`: exact enumeration minimizes total modeled delay, then maximum modeled delay, then lexicographic IDs.
- `load_cases(split, directory=...)`: accepts only `train` or `validation`; final test is inaccessible.

Provider returns raw model text. Runners parse with `parse_action`; malformed output is a failed decision with every encounter aircraft counted as backlog. Do not repair output or quietly replace it with a scripted action.

Cases: `benchmark/data/train.jsonl` and `benchmark/data/validation.jsonl`. One JSON object per line:

```json
{
  "case_id": "opaque stable identifier",
  "split": "train",
  "encounter_id": "opaque stable identifier",
  "local_date": "2026-08-03",
  "input": {
    "task": "sequence_arrivals_v1",
    "runway": {"resource": "shared_arrival_runway", "available_in_seconds": 0},
    "rules": {
      "medium_leader_spacing_seconds": 90,
      "heavy_leader_spacing_seconds": 150,
      "completion_horizon_seconds": 3600,
      "unfinished_penalty_seconds": 3600
    },
    "aircraft": [{
      "id": "A1",
      "distance_nm": 22.1,
      "bearing_deg_true": 114.0,
      "altitude_ft": 7000,
      "groundspeed_kt": 240,
      "track_deg_true": 290,
      "wake_category": "medium",
      "free_flow_seconds": 331.5,
      "position_source": "observed_entry",
      "altitude_source": "beacon_reported",
      "age_seconds": 30
    }]
  },
  "private": {
    "historical_order": ["A1"],
    "source_flight_ids": ["private provenance only"],
    "alias_to_source": {"A1": "private provenance only"},
    "source_entry_times": {"A1": 1779999970},
    "snapshot_time": 1780000000,
    "source_position_stratum": "observed_only"
  }
}
```

The frozen pilot uses **pairs**, with 488 training and 141 validation encounters. The contract accepts 2–6 aircraft for later separately versioned datasets. Aircraft never repeat between encounters. IDs are shuffled local aliases, independent of historical order. Candidate-list order is shuffled separately.

Model inputs contain no callsigns, source IDs, dates, historical timestamps, future paths/weather, assigned historical runway, template IDs or historical sequence. Positions are the last-known observed entry positions, with their ages stated. No interpolation or synthetic position projection occurs. `free_flow_seconds = max(0, distance_nm / groundspeed_kt * 3600 - age_seconds)` is a disclosed direct-to-airport estimate, not a recovered ATC ETA. Only beacon-reported actual heights are retained; all inferred heights become `altitude_ft: null, altitude_source: "unknown"`. The snapshot clock is the latest member's entry time. No future recorded trajectory is used.

## Fixed scheduler and checker

The action is exactly `{"order":["A1","A2",...]}` and schedules the complete encounter. One shared synthetic runway resource models both arrival runways conservatively. For each aircraft, the scheduler sets its slot to the maximum of its free-flow arrival time, runway availability, and the previous slot plus the previous aircraft's wake spacing. A medium leader requires 90 seconds; a heavy leader requires 150 seconds. These are deliberately simplified rules, not complete FAA minima. No runway choice, headings, altitude, communication, occupancy or continuous separation is scored.

The independent checker verifies permutation, release times, wake spacing and finite slots. It computes completion, backlog at 3,600 seconds, total modeled delay and a 3,600-second backlog penalty. This is an action-to-schedule evaluation. A single generated complete sequence is **not a closed-loop full-ATC rollout**. Do not label it as one.

Historical metrics: next-arrival accuracy, exact-sequence accuracy and pairwise agreement with recorded operation order. For pairs, these three measures are identical per encounter. Historical-order mismatch is not evidence of unsafe or inferior control. Synthetic entry positions are excluded completely because their spawn times are inferred from recorded operation times.

## Split and exposure

Train: August 3–6. Validation: August 7. August 8–9 remain sealed. The builder queries only permitted dates from the source DuckDB tables; it never opens test scenario files or emits test data. Aircraft appear in at most one encounter. Duplicate snapshots are forbidden. The manifest records source query, code/data hashes, encounter counts and dates. Training and validation outputs are distinct and must never be concatenated for fitting.

**Primary fine-tuning targets use recorded operation order**, matching the untuned baseline task. They are independently audited historical labels, not human-reviewed ATC commands. `teacher_action` optimizes the synthetic scheduler using public input only and supplies a separate secondary oracle. Never substitute this oracle's labels for historical targets while claiming improvement on the same primary task.
