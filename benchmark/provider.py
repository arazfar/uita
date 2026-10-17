"""Bounded, auditable Crusoe inference. No generation occurs during import.

Each paid POST receives a persistent reservation before dispatch. Lost responses
retain their full reservation. Reusing a request ID never sends another POST.
Only explicitly approved model IDs and origins may receive credentials.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.request
from typing import Any


BASE_URL = "https://api.inference.crusoecloud.com/v1"
DEFAULT_MODEL = "nvidia/Nemotron-3.5-Lightning-30B-A3B"
PRICING_SOURCE = "https://www.crusoe.ai/cloud/pricing"
MODEL_POLICIES = {
    DEFAULT_MODEL: {
        "guidance_source": "https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16/blob/main/README.md",
        "reasoning_mode": "disabled", "generation_overrides": {"chat_template_kwargs": {"enable_thinking": False}},
    },
    "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B": {
        "guidance_source": "https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16/blob/main/README.md",
        "reasoning_mode": "disabled", "generation_overrides": {"chat_template_kwargs": {"enable_thinking": False}},
    },
    "nvidia/NVIDIA-Nemotron-3.5-Super-VL": {
        "guidance_source": "https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-BF16/blob/main/README.md",
        "reasoning_mode": "disabled", "generation_overrides": {"chat_template_kwargs": {"enable_thinking": False}},
    },
    "Qwen/Qwen3.8-27B": {
        "guidance_source": "https://huggingface.co/Qwen/Qwen3.8-27B",
        "reasoning_mode": "disabled", "generation_overrides": {"chat_template_kwargs": {"enable_thinking": False}},
    },
    "openai/gpt-oss-120b": {
        "guidance_source": "https://developers.openai.com/api/docs/models/gpt-oss-120b",
        "reasoning_mode": "low_not_disabled", "generation_overrides": {"reasoning_effort": "low"},
    },
}
USER_AGENT = "uita-historical-benchmark/1.0"


class ProviderError(RuntimeError):
    """A failed discovery, invalid configuration, or exhausted reservation."""


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def load_key(env_path: str | Path = ".env.local") -> str:
    """Read only the required credential without executing shell content."""
    key = os.environ.get("CRUSOE_API_KEY")
    if not key and Path(env_path).exists():
        for line in Path(env_path).read_text().splitlines():
            if line.strip().startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == "CRUSOE_API_KEY":
                key = value.strip().strip('"').strip("'")
                break
    if not key:
        raise ProviderError("CRUSOE_API_KEY is missing")
    return key


def discover(model_id: str = DEFAULT_MODEL, *, key: str | None = None) -> dict[str, Any]:
    """A read-only GET establishes model capacity, parameters, and token rates."""
    if model_id not in MODEL_POLICIES:
        raise ProviderError("No reviewed generation policy exists for this model")
    policy = MODEL_POLICIES[model_id]
    request = urllib.request.Request(
        BASE_URL + "/models",
        headers={"Authorization": "Bearer " + (key or load_key()), "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            catalog = json.load(response)
    except (urllib.error.URLError, ValueError, TimeoutError):
        raise ProviderError("Crusoe model discovery failed; credentials and bodies are not logged") from None
    models = catalog.get("data", catalog.get("models", []))
    model = next((item for item in models if item.get("id") == model_id), None)
    if model is None:
        raise ProviderError("The pinned model is absent from authenticated inference discovery")
    supported = model.get("supported_parameters")
    required = {"max_tokens", "temperature", "top_p", "seed", "response_format"} | set(policy["generation_overrides"])
    if not isinstance(supported, list) or not required.issubset(supported):
        raise ProviderError("The pinned model does not advertise the required bounded generation parameters")
    if model.get("is_billed_by_token") is not True:
        raise ProviderError("The pinned model does not advertise token billing")
    pricing = model.get("pricing", {})
    try:
        rates = [float(pricing[name]) for name in ("prompt", "completion")]
    except (TypeError, KeyError, ValueError):
        raise ProviderError("Model discovery lacks usable token pricing") from None
    if any(not math.isfinite(rate) or rate < 0 for rate in rates):
        raise ProviderError("Token prices must be finite and nonnegative")
    # The public pricing page explicitly denominates these discovery numbers per
    # million tokens. Cache discounts are excluded from the upper bound.
    return {
        "id": model_id,
        "context_length": model.get("context_length"),
        "quantization": model.get("quantization"),
        "supported_parameters": supported,
        "input_usd_per_million_tokens": rates[0],
        "output_usd_per_million_tokens": rates[1],
        "pricing_source": PRICING_SOURCE,
        **policy,
        "discovered_at_epoch": time.time(),
    }


class ReservationLedger:
    """SQLite transactions enforce the cap across restarts and concurrent jobs."""

    def __init__(self, path: str | Path, budget_id: str, cap_usd: float):
        if not isinstance(budget_id, str) or not budget_id or not math.isfinite(cap_usd) or cap_usd <= 0:
            raise ProviderError("A named, finite positive inference budget is required")
        self.path, self.budget_id, self.cap_usd = str(path), budget_id, cap_usd
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("CREATE TABLE IF NOT EXISTS benchmark_budgets (id TEXT PRIMARY KEY, cap_usd REAL NOT NULL)")
            db.execute("INSERT OR IGNORE INTO benchmark_budgets VALUES (?,?)", (budget_id, cap_usd))
            stored = db.execute("SELECT cap_usd FROM benchmark_budgets WHERE id=?", (budget_id,)).fetchone()[0]
            if stored != cap_usd:
                raise ProviderError("An existing budget cap cannot be silently changed")
            db.execute("""CREATE TABLE IF NOT EXISTS benchmark_reservations (
                budget_id TEXT NOT NULL, request_id TEXT NOT NULL, payload_sha256 TEXT NOT NULL,
                reserved_usd REAL NOT NULL, actual_usd REAL, status TEXT NOT NULL,
                created_at REAL NOT NULL, record_json TEXT, PRIMARY KEY(budget_id,request_id))""")
            db.execute("CREATE TABLE IF NOT EXISTS benchmark_model_dispatch (model_id TEXT PRIMARY KEY, next_start REAL NOT NULL)")

    def pace_model(self, model_id: str, interval_seconds: float = 2.2) -> None:
        """Reserve a dispatch time per model across processes sharing this ledger."""
        if not math.isfinite(interval_seconds) or not 2.2 <= interval_seconds <= 60:
            raise ProviderError("Dispatch spacing must be finite and between 2.2 and 60 seconds")
        now = time.time()
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT next_start FROM benchmark_model_dispatch WHERE model_id=?", (model_id,)).fetchone()
            start = max(now, row[0] if row else now)
            if start - now > 60:
                raise ProviderError("Model dispatch queue exceeds one minute; do not add concurrent same-model workers")
            db.execute("INSERT OR REPLACE INTO benchmark_model_dispatch VALUES (?,?)", (model_id, start + interval_seconds))
        if start > now:
            time.sleep(start - now)

    def reserve(self, request_id: str, payload_sha256: str, worst_usd: float) -> None:
        if not request_id or not math.isfinite(worst_usd) or worst_usd < 0:
            raise ProviderError("Invalid inference reservation")
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM benchmark_reservations WHERE budget_id=? AND request_id=?",
                          (self.budget_id, request_id)).fetchone():
                raise ProviderError("Request ID already reserved; paid requests are never automatically repeated")
            used = db.execute("SELECT COALESCE(SUM(reserved_usd),0) FROM benchmark_reservations WHERE budget_id=?",
                              (self.budget_id,)).fetchone()[0]
            if used + worst_usd > self.cap_usd:
                raise ProviderError("Approved inference budget exhausted")
            db.execute("INSERT INTO benchmark_reservations VALUES (?,?,?,?,NULL,'reserved',?,NULL)",
                       (self.budget_id, request_id, payload_sha256, worst_usd, time.time()))

    def finish(self, request_id: str, record: dict[str, Any]) -> None:
        actual = record.get("cost_usd")
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT reserved_usd,status FROM benchmark_reservations WHERE budget_id=? AND request_id=?",
                             (self.budget_id, request_id)).fetchone()
            if row is None or row[1] != "reserved":
                raise ProviderError("Only a pending reservation can receive a result")
            if actual is not None and (not math.isfinite(actual) or actual < 0 or actual > row[0]):
                raise ProviderError("Provider usage exceeded the reservation; result remains pending")
            db.execute("UPDATE benchmark_reservations SET actual_usd=?,status=?,record_json=? WHERE budget_id=? AND request_id=?",
                       (actual, record["status"], canonical(record), self.budget_id, request_id))

    def summary(self) -> dict[str, Any]:
        with sqlite3.connect(self.path, timeout=10) as db:
            count, reserved, actual, unknown = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(reserved_usd),0),COALESCE(SUM(actual_usd),0),"
                "COALESCE(SUM(CASE WHEN actual_usd IS NULL THEN 1 ELSE 0 END),0) "
                "FROM benchmark_reservations WHERE budget_id=?", (self.budget_id,)
            ).fetchone()
        return {"budget_id": self.budget_id, "cap_usd": self.cap_usd, "requests": count,
                "reserved_usd": reserved, "reported_cost_usd": actual, "unknown_cost_requests": unknown}

    def lookup(self, request_id: str) -> dict[str, Any] | None:
        """Recover completed audit data, never dispatching a pending reservation."""
        with sqlite3.connect(self.path, timeout=10) as db:
            row = db.execute("SELECT status,record_json FROM benchmark_reservations WHERE budget_id=? AND request_id=?",
                             (self.budget_id, request_id)).fetchone()
        if row is None:
            return None
        if row[1] is None:
            raise ProviderError("A request has an unresolved reservation; investigate it without retrying the POST")
        return json.loads(row[1])


def request_plan(messages: list[dict[str, str]], *, model: dict[str, Any], max_tokens: int = 1024,
                 seed: int = 17) -> dict[str, Any]:
    """Calculate exact dispatch bytes and worst-case cost without generation."""
    if type(max_tokens) is not int or not 1 <= max_tokens <= 2048:
        raise ProviderError("Output bound must be an integer from 1 to 2048")
    if not isinstance(messages, list) or len(messages) != 2:
        raise ProviderError("Benchmark requests contain one system and one user message")
    if [item.get("role") for item in messages] != ["system", "user"] or any(
        set(item) != {"role", "content"} or not isinstance(item["content"], str) for item in messages
    ):
        raise ProviderError("Unsupported benchmark message structure")
    payload = {
        "model": model["id"], "messages": messages, "temperature": 0, "top_p": 1,
        "seed": seed, "max_tokens": max_tokens, "stream": False,
        "response_format": {"type": "json_object"},
        **model["generation_overrides"],
    }
    encoded = canonical(payload).encode()
    if len(encoded) > 65536:
        raise ProviderError("Benchmark request exceeds the frozen 64 KiB prompt bound")
    # UTF-8 bytes cover byte-fallback tokenization. The additional factor and
    # framing allowance are deliberately conservative without a local tokenizer.
    input_bound = 2 * len(encoded) + 1024
    context = model.get("context_length")
    if not isinstance(context, int) or input_bound + max_tokens > context:
        raise ProviderError("Conservative input/output bounds exceed the model context")
    in_rate = model["input_usd_per_million_tokens"] / 1_000_000
    out_rate = model["output_usd_per_million_tokens"] / 1_000_000
    worst_usd = input_bound * in_rate + max_tokens * out_rate
    return {"payload": payload, "input_token_bound": input_bound, "reserved_usd": worst_usd}


def generate(
    messages: list[dict[str, str]], *, model: dict[str, Any], ledger: ReservationLedger,
    request_id: str, key: str | None = None, max_tokens: int = 1024, seed: int = 17,
) -> dict[str, Any]:
    """Send exactly one bounded POST, returning an audit record for every result.

    This function validates transport and JSON structure. The task-specific core
    independently validates the returned action. Invalid actions receive no repair
    call, and timeout or HTTP failures receive no retry.
    """
    planned = request_plan(messages, model=model, max_tokens=max_tokens, seed=seed)
    payload, input_bound, worst_usd = planned["payload"], planned["input_token_bound"], planned["reserved_usd"]
    encoded = canonical(payload).encode()
    in_rate = model["input_usd_per_million_tokens"] / 1_000_000
    out_rate = model["output_usd_per_million_tokens"] / 1_000_000
    record: dict[str, Any] = {
        "request_id": request_id, "payload_sha256": digest(payload), "request": payload,
        "model_discovery": model, "input_token_bound": input_bound,
        "reserved_usd": worst_usd, "cost_usd": None, "paid_retries": 0,
        "status": "ambiguous_failure", "started_at_epoch": time.time(),
    }
    credential = key or load_key()
    ledger.reserve(request_id, record["payload_sha256"], worst_usd)
    started = time.monotonic()
    request = urllib.request.Request(
        BASE_URL + "/chat/completions", data=encoded, method="POST",
        headers={"Authorization": "Bearer " + credential, "User-Agent": USER_AGENT,
                 "Content-Type": "application/json"},
    )
    try:
        # No SDK or urllib retry layer is installed. Redirects must not forward
        # an authenticated paid request to another origin.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args: Any, **kwargs: Any) -> None:
                return None
        opener = urllib.request.build_opener(NoRedirect())
        with opener.open(request, timeout=60) as response:
            record["http_status"] = response.status
            record["rate_limit_headers"] = {name: response.headers.get(name) for name in (
                "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens", "x-ratelimit-limit-requests",
                "x-ratelimit-remaining-requests", "retry-after") if response.headers.get(name) is not None}
            raw = response.read(1_048_577)
        if len(raw) > 1_048_576:
            record.update(status="invalid_response", failure="response_size_limit")
        else:
            result = json.loads(raw)
            record["response"] = result
            if not isinstance(result, dict):
                raise ValueError("Provider response is not an object")
            usage = result.get("usage") or {}
            if not isinstance(usage, dict):
                usage = {}
            prompt_tokens, completion_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
            if (type(prompt_tokens) is int and 0 <= prompt_tokens <= input_bound
                    and type(completion_tokens) is int and 0 <= completion_tokens <= max_tokens):
                record["cost_usd"] = prompt_tokens * in_rate + completion_tokens * out_rate
            else:
                record["usage_error"] = "missing_or_out_of_bounds_provider_usage"
            choice = result["choices"][0]
            content = choice["message"].get("content")
            record["finish_reason"] = choice.get("finish_reason")
            if choice.get("finish_reason") != "stop":
                record.update(status="invalid_response", failure="incomplete_generation")
            elif not isinstance(content, str):
                record.update(status="invalid_response", failure="missing_text_content")
            else:
                try:
                    action = json.loads(content)
                    if not isinstance(action, dict):
                        raise ValueError("non_object")
                    record.update(status="completed", action=action)
                except ValueError:
                    record.update(status="invalid_response", failure="invalid_json_object")
    except urllib.error.HTTPError as exc:
        record.update(status="http_failure", http_status=exc.code, failure="provider_http_error_no_retry")
        record["rate_limit_headers"] = {name: exc.headers.get(name) for name in (
            "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens", "x-ratelimit-limit-requests",
            "x-ratelimit-remaining-requests", "retry-after") if exc.headers.get(name) is not None}
    except (urllib.error.URLError, TimeoutError, OSError):
        record.update(status="ambiguous_failure", failure="transport_failure_no_retry")
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        record.update(status="invalid_response", failure="provider_response_contract")
    finally:
        record["latency_seconds"] = time.monotonic() - started
        ledger.finish(request_id, record)
    return record
