# Final implementation validation

Final command: `PYTHONPATH=backend .venv-agent/bin/pytest -q --tb=short`.

**232 tests passed in 18.97 seconds.** The sole warning is an upstream Starlette/AnyIO deprecated alias. [Exact output](final-test-result.txt). Independent validation covers 227 tests; the final five add native structured-output/framework/wire coverage and compact scene-poll evidence. [Independent methods and results](INDEPENDENT_VALIDATION.md).

The four native-mode tests verify typed JSON after a registered investigation tool, rejection of skipped inspection, strict rejection of extra fields, and the actual native Crusoe SDK request shape against a mock wire: `response_format=json_schema`, `tool_choice=auto`, `max_tokens`, and no provider strict-tool flag. They are network-free framework tests, not fresh model performance evidence. Ordinary tests block real network and live model requests.

The isolated process tests use real SIGKILL at three boundaries: before a response, after verified cost settles but before the response event persists, and after that event persists. Each retains its conservative reservation, preserves known actual cost where available, recovers explicitly as interrupted, and makes zero model calls on worker re-entry. Other checks cover cancellation during inference/evaluation, concurrent reservation/claim races, no SDK/transport/framework retries, strict budgets and schemas, injection/secret/validation isolation, durable freeze, test-only accepted ancestry, separate activation and rollback, historical program hashes and behavior, and compact state polling.

Exact pinned dependencies were installed into a separate clean Python 3.11.17 environment from `requirements.lock`: 54 packages installed, Pydantic AI 2.57.0 imported, and the application loaded with 21 routes against an in-memory database. `uv pip check` found no dependency conflicts. The repository's existing Python 3.9 environment was preserved. `scripts/dev.sh` prefers the new `.venv-agent` runtime and seeds pip when necessary. Docker's existing Python 3.11 image consumes the updated lock; `.venv-agent` is excluded from its build context.

Docker CLI is present, but its daemon socket is unavailable. A real Docker image build and PostgreSQL deployment were not run. This is a documented environment limitation, not a passing container/database deployment claim.

Source-controlled OpenAPI and generated TypeScript were regenerated together. `npm --prefix frontend run build` passed typechecking and the production build; the existing Rapier bundle-size warning remains. Real desktop/narrow browser results are in [browser verification](BROWSER_VERIFICATION.md). `git diff --check` passed. After the full run, the final compact policy-summary filter was verified with six targeted job-summary/API tests; full policy and job evidence remains available on demand.

The final fixture evaluation and replay completed with prompt `investigator-2`, zero provider calls and no promotions. [Matched raw/report](fixture-evaluation.md), [offline replay](replay-evaluation.md), and [live capability outcomes and exact billing limitations](live-evaluation.md) are separate. Historical research/evaluation artifacts remain unchanged. No push, merge, publication, provider fallback or spend-cap increase occurred.
