# Compare existing models on historical arrival ordering

Fine-tuning is deferred at the user's request on October 17, 2026. No training files were uploaded, training jobs submitted, or serving resources created by this work. `experiment-config.json` disables upload and training submission.

## What this benchmark measures

The task predicts which of two observed aircraft appears first in the recorded SFO arrival-operation roster. It uses the same 141 August 7 validation encounters for every model. August 8–9 remain sealed. The 488 August 3–6 encounters support development; they are not additional validation cases.

Each model receives the same system prompt and public aircraft observations. Arbitrary aircraft IDs hide callsigns and historical order. Dates, future paths, operation times, and recorded outcomes stay outside the prompt. The strict parser accepts one complete ordering only. A failed or malformed response remains a failed decision; there are no repair calls.

The primary score is agreement with recorded operation order. These records do not contain authentic controller commands. A mismatch cannot establish worse safety or decision quality than a human controller. Synthetic scheduling metrics describe the supplied simplified scheduler; they do not measure historical human delay or separation performance.

## Compare two evaluation approaches

| Approach | Benefit | Limit |
| --- | --- | --- |
| Same prompt and bounded generation settings | Directly compares models within one small deployment budget | Some models require internal reasoning and use different tokenizers |
| Each model's recommended reasoning and sampling settings | Measures each model in a preferred configuration | Changes compute, latency, and sampling alongside the model |

Use the first approach for the demo. Keep the second as a separately named later experiment. Do not mix their results into one ranking.

Freeze temperature, top-p, seed, maximum generated tokens, timeout, JSON output requirements, and case membership before measuring validation. Record model-specific reasoning controls separately. A seed does not promise identical outputs across model families or provider backends.

Use one model call per case. Report successful valid decisions, recorded-order agreement, failure counts, token use, estimated token cost, and observed latency. Keep incomplete generations visible. The same token limit gives a common deployment limit, not equal internal computation.

## Selected model scope

Authenticated Crusoe inference discovery on October 17 confirmed these five selected models. Prices are USD per million tokens, excluding cache discounts. Availability and prices can change. The experiment's saved catalog and API usage records govern actual results. Public units are documented on [Crusoe's pricing page](https://www.crusoe.ai/cloud/pricing).

| Model ID | Input | Output | Comparison role |
| --- | ---: | ---: | --- |
| `nvidia/Nemotron-3.5-Lightning-30B-A3B` | $0.05 | $0.20 | Initial Nemotron reference |
| `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` | $0.05 | $0.20 | Earlier Nemotron variant |
| `nvidia/NVIDIA-Nemotron-3.5-Super-VL` | $0.10 | $0.40 | Larger Nemotron model using text input only |
| `openai/gpt-oss-120b` | $0.05 | $0.25 | Different reasoning model family |
| `Qwen/Qwen3.8-27B` | $0.25 | $2.00 | Different model family with a similar nominal size |

All five runs completed with 141 attempted cases each. See [results](reports/2026-10-17/comparison.md) and [testing instructions](TESTING.md). The results separate failed API calls from valid decisions and disclose all denominators.

## Reasoning controls need model-specific handling

The catalog advertises supported API parameter names. That does not prove every chat-template option affects every model.

- Nemotron 3.5 Lightning documents `enable_thinking=False` in its chat template. Preserve the same option when the serving route supports it. See the [NVIDIA model card](https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16/blob/main/README.md).
- GPT-OSS documents low, medium, and high reasoning effort. Its card does not document a reasoning-off mode. Use an explicit supported effort and report it. See the [OpenAI model card](https://huggingface.co/openai/gpt-oss-120b/blob/main/README.md).
- Qwen 3.8 documents `chat_template_kwargs={"enable_thinking":false}` for non-thinking mode. Its recommended sampling settings differ from the common deterministic settings here. The result measures this shared configuration. See the [Qwen model card](https://huggingface.co/Qwen/Qwen3.8-27B/blob/main/README.md#instruct-or-non-thinking-mode).

For models that always reason, count reasoning tokens within the recorded generation allowance when the API includes them there. Record finish reason and usage details. Treat an exhausted allowance as a limitation of this bounded configuration, not evidence of the model's maximum capability.

## Interpret differences conservatively

Report each model's correct count out of 141 and percentage-point difference from the scripted reference. For model-to-model differences, compare outcomes on the same encounter IDs. Include counts where only model A is correct, only model B is correct, both are correct, or neither is correct.

All 141 validation encounters come from one historical day. They are separate aircraft encounters, but they do not establish performance across independent weather or operating days. Larger percentages can still reflect small absolute differences: one encounter changes the score by about 0.71 percentage points.

Keep latency and cost separate from accuracy. Provider load, execution order, caching, tokenization, and server configuration can affect those measurements. Record the execution schedule. Do not describe a one-pass timing difference as a controlled hardware speed comparison.

The final test stays untouched until the benchmark, prompts, model settings, and selection rule are frozen. Selecting a model using August 7 results makes August 7 a validation set, not a final unbiased test.
