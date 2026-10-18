# Model and API failure analysis

Status: **complete_verified**. Completed model windows: 420/420.

Failure attribution for recorded calls only; scheduling quality remains measured by the closed-loop leaderboard.

All recorded attempts include unfinished jobs. Selected decisions include completed model-window outcomes only. Preflights are separate and unscored.

A model response mistake requires a complete final response that violates the action contract. Transport and HTTP failures are separate. Truncation measures reliability under the frozen output budget. A valid action does not establish a good schedule.

The table includes all recorded attempts, including unfinished jobs. It cannot rank model performance.

| Configuration | Calls | Usable | Model contract | API transport | API HTTP | Token/finish boundary | Other | Known $ | Unknown cost | P95 latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| nemotron-3.5-super-vl-off | 566 | 539 | 17 | 10 | 0 | 0 | 0 | 0.10883 | 10 | 15.98s |
| nemotron-3.5-super-vl-on | 566 | 223 | 7 | 330 | 5 | 1 | 0 | 0.28250 | 335 | 60.13s |
| nemotron-3.5-lightning-off | 570 | 364 | 200 | 6 | 0 | 0 | 0 | 0.05594 | 6 | 4.62s |
| nemotron-3.5-lightning-on | 566 | 56 | 0 | 51 | 0 | 459 | 0 | 0.83465 | 51 | 60.05s |
| nemotron-3-nano-off | 569 | 334 | 230 | 5 | 0 | 0 | 0 | 0.05592 | 5 | 4.73s |
| nemotron-3-nano-on | 566 | 73 | 4 | 52 | 0 | 437 | 0 | 0.80436 | 52 | 60.05s |
| qwen-3.8-27b-off | 566 | 542 | 21 | 2 | 0 | 1 | 0 | 0.36699 | 2 | 4.52s |
| qwen-3.8-27b-on | 566 | 184 | 0 | 33 | 0 | 349 | 0 | 7.40283 | 33 | 60.04s |
| gemma-4-31b-off | 566 | 547 | 5 | 14 | 0 | 0 | 0 | 0.14812 | 14 | 8.17s |
| gemma-4-31b-on | 566 | 94 | 0 | 472 | 0 | 0 | 0 | 0.09079 | 472 | 60.14s |

Known charges exclude unknown charges. Unknown requests retain their full reservation in the shared spending cap.

## Reasoning controls

| Configuration | Evaluation responses with reasoning | Evaluation responses with empty/missing reasoning | Preflight with reasoning | Unexpected OFF reasoning |
|---|---:|---:|---:|---:|
| nemotron-3.5-super-vl-off | 0 | 556 | 0 | 0 |
| nemotron-3.5-super-vl-on | 231 | 0 | 1 | 0 |
| nemotron-3.5-lightning-off | 0 | 564 | 0 | 0 |
| nemotron-3.5-lightning-on | 515 | 0 | 1 | 0 |
| nemotron-3-nano-off | 0 | 564 | 0 | 0 |
| nemotron-3-nano-on | 514 | 0 | 1 | 0 |
| qwen-3.8-27b-off | 0 | 564 | 0 | 0 |
| qwen-3.8-27b-on | 533 | 0 | 1 | 0 |
| gemma-4-31b-off | 0 | 552 | 0 | 0 |
| gemma-4-31b-on | 94 | 0 | 1 | 0 |

Counts describe returned API fields. Missing reasoning fields alone cannot prove that internal reasoning was disabled.

## Example cases

First request by lexical ID for each observed failure group/detail/HTTP status, at most ten; no invented examples.

### gemma-4-31b-off: response_not_received_no_retry

Episode `2026-08-24-1200`, clock 3300.0s. Pending aircraft: A009, A011, A012, A013, A014, A015, A016, A017, A018, A019, A020, A021, A022, A023, A024, A025, A026, A027, A028, A029 (22 total).

HTTP None; finish reason `None`; latency 26.31s.

The client did not receive a complete response. This does not establish a scheduling or reasoning mistake.

No final-answer text was available to inspect.

### gemma-4-31b-off: unknown_aircraft_ids

Episode `2026-08-26-0900`, clock 2700.0s. Pending aircraft: A001, A006, A009, A010, A011, A012, A013, A014, A015, A016, A017, A018, A019, A020, A021, A022, A023, A024, A025, A026 (21 total).

HTTP 200; finish reason `stop`; latency 1.26s.

A complete final response violated the exact pending-ID action contract. This is a model response mistake.

Unexpected IDs: ["A007"].

Reported output tokens: 114.

Final-answer excerpt (maximum 400 characters; JSON escaping preserves literal text):

```json
"{\"order\":[\"A001\",\"A006\",\"A009\",\"A010\",\"A017\",\"A011\",\"A019\",\"A015\",\"A014\",\"A012\",\"A013\",\"A021\",\"A023\",\"A007\",\"A016\",\"A018\",\"A020\",\"A025\",\"A024\",\"A027\",\"A022\",\"A026\"]}"
```

### nemotron-3-nano-off: missing_aircraft_ids

Episode `2026-08-24-0900`, clock 3300.0s. Pending aircraft: A004, A005, A006, A011, A012, A013, A014, A015, A016, A017, A018, A019, A020, A021, A022, A023, A024, A025, A026, A027 (20 total).

HTTP 200; finish reason `stop`; latency 4.97s.

A complete final response violated the exact pending-ID action contract. This is a model response mistake.

Missing pending IDs: A006.

Reported output tokens: 101.

Final-answer excerpt (maximum 400 characters; JSON escaping preserves literal text):

```json
"{\"order\":[\"A004\",\"A005\",\"A011\",\"A012\",\"A013\",\"A014\",\"A015\",\"A016\",\"A017\",\"A018\",\"A019\",\"A020\",\"A021\",\"A022\",\"A023\",\"A024\",\"A025\",\"A026\",\"A027\"]}"
```

### nemotron-3-nano-off: duplicate_aircraft_ids

Episode `2026-08-24-1200`, clock 4200.0s. Pending aircraft: A011, A012, A014, A015, A016, A017, A018, A019, A020, A021, A022, A023, A024, A025, A026, A027, A028, A030, A031 (19 total).

HTTP 200; finish reason `stop`; latency 4.44s.

A complete final response violated the exact pending-ID action contract. This is a model response mistake.

Unexpected IDs: ["A013", "A029"].

Reported output tokens: 116.

Final-answer excerpt (maximum 400 characters; JSON escaping preserves literal text):

```json
"{\"order\":[\"A011\",\"A014\",\"A017\",\"A021\",\"A027\",\"A023\",\"A025\",\"A026\",\"A030\",\"A031\",\"A015\",\"A016\",\"A020\",\"A024\",\"A018\",\"A019\",\"A012\",\"A013\",\"A028\",\"A022\",\"A019\",\"A029\"]}"
```

### nemotron-3-nano-on: output_token_limit

Episode `2026-08-24-0600`, clock 2400.0s. Pending aircraft: A002, A003, A004, A005, A006 (5 total).

HTTP 200; finish reason `length`; latency 35.87s.

The configured generation boundary prevented a completed action. This measures reliability under the frozen budget, not unrestricted reasoning ability.

Reported output tokens: 8192.

No final-answer text was available to inspect.

### nemotron-3-nano-on: extra_or_missing_action_fields

Episode `2026-08-28-0600`, clock 3600.0s. Pending aircraft: A006 (1 total).

HTTP 200; finish reason `stop`; latency 4.42s.

A complete final response violated the exact pending-ID action contract. This is a model response mistake.

Reported output tokens: 887.

Final-answer excerpt (maximum 400 characters; JSON escaping preserves literal text):

```json
"{ \"order \": [ \"A006\" ] }"
```

### nemotron-3.5-super-vl-on: provider_http_5xx

Episode `2026-08-24-1800`, clock 2100.0s. Pending aircraft: A002, A003, A007, A008, A009, A010, A012, A013, A014, A015, A016, A017 (12 total).

HTTP 500; finish reason `None`; latency 6.29s.

The API returned an HTTP error. Provider or request handling failed before a usable model action; HTTP status alone cannot establish model quality.

No final-answer text was available to inspect.

## Limits

- A valid action is not evidence of an optimal schedule.
- Timeouts do not establish whether the provider generated an answer or incurred a charge.
- Token-limit failures measure this output budget and cannot prove unrestricted model inability.
- Returned reasoning is an observation, not proof of every internal computation. Missing reasoning fields alone cannot prove OFF.
- Examples contain at most 400 final-answer characters and never copy reasoning bodies or HTTP error bodies.
- All compared model actions use the same checked decoder and counted fallback policy. August 8–9 remain held out.
