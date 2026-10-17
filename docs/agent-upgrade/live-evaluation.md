# Live bounded capability results

The new live agent loop was **not verified** against the current Crusoe endpoint. No live candidate reached development evaluation, freeze or promotion. This is a bounded capability failure, not evidence that Nemotron cannot improve a policy.

Authenticated discovery returned the pinned `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` and advertised tool and structured output parameters. Actual requests produced the following evidence:

| Experiment | Requests | Output mode | Observed result | Verified cost | Retained reserve |
|---|---:|---|---|---:|---:|
| Initial matched stateless/persistent study | 2 | Output tool, 1,000-token bound | Rejected response envelope; detailed finish metadata was not retained in this first attempt | Unknown | $0.00148730 |
| Minimal native tool/typed-output probe | 1 | Output tool, 1,500-token bound | `finish_reason=length`; no tool execution | $0.00031970 | $0.00044020 |
| Documented compatibility-profile probe | 1 | Output tool, 1,500-token bound; `max_tokens`, provider strict-tool flag omitted | `finish_reason=length`; no tool execution | $0.00031900 | $0.00043630 |
| Native JSON-schema probe | 1 | `NativeOutput`, 1,500-token bound | Valid typed JSON in 10 tokens, but requested function tool was skipped | $0.00001735 | $0.00043400 |

Each probe was an explicit new bounded capability experiment after a concrete integration change. No failed or ambiguous request was retried. Provider, model, safety rules, scenarios and promotion thresholds stayed fixed. The native JSON result verifies only the simple structured output used by that probe; it does not verify function calling or the full investigation loop.

New verified cost is **$0.00065605**, plus unknown actual billing for the first two requests. Their $0.00148730 reservation remains retained. Including the original historical calls, the shared ledger retains **$0.00344340** of its unchanged **$0.05** aggregate approval; total verified actual cost is $0.00071855. Conservative reserves are never released on successful, failed or ambiguous requests. No key, raw prompt, raw response or reasoning text was written to these artifacts.

The credential-free matched study completed both full agent loops and rejected both candidates. Its [fixture report](fixture-evaluation.md) exercises orchestration only. The [development capacity audit](CAPACITY_AUDIT.md) finds the original static policy already optimal over both bounded grammars, so this study cannot support a claim of model improvement. The historical single-proposal result remains unchanged and is only a migration reference.

Raw evidence: [initial matched study](live-attempt-1.json), [first capability probe](live-capability-check.json), [compatibility-profile probe](live-capability-profile-2.json), [native-output probe](live-capability-native-output.json). The first attempt's original report is preserved as [live-attempt-1.md](live-attempt-1.md); its zero verified subtotal and zero failure-latency fields should not be read as zero billing or zero elapsed time. The raw timestamps and this report provide the correction.

Further live runs require resolving actual tool-calling behavior within the configured budgets. No provider/model fallback, larger spend approval or automatic retry was used.
