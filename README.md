# Uita

A working SFO research simulation: inspect moving traffic, inject disruptions, independently verify reservations, replay checkpoints, and run matched bounded-observation experiments. **Research only; not operational ATC.**

## Run locally

Python 3.11 and Node 22 are local/deployment targets. Default execution needs no model credentials.

```sh
python3.11 -m venv .venv-agent
.venv-agent/bin/pip install -r requirements.lock
npm --prefix frontend ci
PYTHONPATH=backend .venv-agent/bin/uvicorn uita.app:app --host 127.0.0.1 --port 8001
```

In a second terminal:

```sh
npm --prefix frontend run dev -- --host 127.0.0.1
```

Open [Uita](http://localhost:5173). The Vite proxy targets 8001. `bash scripts/dev.sh` starts both services. State persists in ignored local `uita.db`.

## Try the workflow

1. Play at 10× or step. Select an aircraft and inspect its route, evidence or table row.
2. Pause, propose with the static policy, verify and commit. Admitted trajectories remain stable.
3. Inject demand, a closure, lower visibility or gate delay. Inspect changed reservations and pass/fail/unresolved evidence. Stale plans cannot commit.
4. Run a fixture experiment. Inspect candidate lineage and matched metrics. Rejection is a valid result; no winner is predetermined.
5. Compare the same checkpoint, scrub recorded history, and export evidence. Rollback restores the prior accepted observation policy.

## Verify

```sh
PYTHONPATH=backend .venv-agent/bin/pytest -q
npm --prefix frontend run build
PYTHONPATH=backend .venv-agent/bin/python scripts/evaluate_agent.py
PYTHONPATH=backend .venv-agent/bin/python scripts/export_schema.py
```

[API documentation](http://localhost:8001/docs), [shared schema](docs/api.openapi.json), [actual fixture report](docs/evaluation/fixture-result.md), [live Nemotron result](docs/evaluation/live-program-reevaluation.md), [browser and performance verification](docs/BROWSER_VERIFICATION.md), [three-minute demonstration](docs/DEMO.md).

## Live NVIDIA Nemotron

Crusoe is the only adapter. Runtime discovery pins `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, the exact account-discovered ID. Supply `CRUSOE_API_KEY` through server environment, configure a finite authorized `CRUSOE_MAX_SPEND_USD`, and select Crusoe in the UI. Learning uses the native Crusoe Pydantic AI agent: typed investigation tools, development feedback, one default revision, a persisted freeze, then independent validation. Default bounds include six model requests, twelve tool calls, four development evaluations, 120 seconds and a $0.02 per-job reservation ceiling within the existing aggregate approval. Cancellation terminates its isolated worker. Movement proposals consume accepted policies without new inference. The full live tool loop is **not yet verified**: bounded tool-output probes truncated, and native structured output skipped the requested function tool. The [live capability report](docs/agent-upgrade/live-evaluation.md) records these failures and exact known/unknown billing; fixtures do not establish model learning. A persistent aggregate ledger reserves worst-case cost; no paid POST is retried. `CRUSOE_BUDGET_DB` sets its path. Never place keys in frontend variables, source, screenshots or exports.

## Deployment preparation

The Dockerfile builds the frontend into FastAPI. Compose provides PostgreSQL 17 and one Uita process. Set a strong `UITA_API_TOKEN`, allowed origins and production database credentials before remote use. Containers/PostgreSQL are prepared, not claimed deployed or production validated. Use one API worker. Never expose sample database credentials publicly.

Read [architecture and limitations](docs/ARCHITECTURE.md), [primary sources](docs/research/SOURCES.md), [acceptance contract](docs/PRODUCT_CONTRACT.md) and [operational validation](docs/OPERATIONAL_VALIDATION.md). Existing context is preserved under `context/`.

The [agent architecture and limits](docs/agent-upgrade/ARCHITECTURE.md), [capacity audit](docs/agent-upgrade/CAPACITY_AUDIT.md), [matched fixture evaluation](docs/agent-upgrade/fixture-evaluation.md), and [actual browser verification](docs/agent-upgrade/BROWSER_VERIFICATION.md) document the upgrade. Historical evaluations remain available unchanged.
