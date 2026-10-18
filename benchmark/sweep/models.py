"""Frozen model pairs and bounded Crusoe calls for historical admission ordering.

Only ``choose`` dispatches paid requests. It receives the same strict public
view and task prompt as the original benchmark. A configuration identifier binds
its engine request IDs, so two model settings cannot share an action cache.
"""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.request

from benchmark import provider
from benchmark.provider import BASE_URL, ProviderError, ReservationLedger, canonical, digest, load_key
from benchmark.closed_loop import ai as original_ai
from benchmark.closed_loop.ai import (
    SYSTEM_PROMPT, validate_view, parse_action, _append, _NoRedirect,
    _RATE_HEADERS, _bad_constant,
)

VERSION = "historical-admission-model-pairs-v1"
MAX_TOKENS = 8192
TIMEOUT_SECONDS = 60
PACING_SECONDS = 2.2
MAX_REQUEST_BYTES = 65536
MAX_RESPONSE_BYTES = 1_048_576
CATALOG_SOURCE = "https://docs.crusoecloud.com/serverless-inference/available-models/index.html"
RATE_SOURCE = "https://docs.crusoecloud.com/serverless-inference/rate-limits/index.html"
PRICING_SOURCE = "https://www.crusoe.ai/cloud/pricing"
MODEL_POLICIES = (
    {
        "id": "nemotron-3.5-super-vl", "model": "nvidia/NVIDIA-Nemotron-3.5-Super-VL",
        "display_name": "Nemotron 3.5 Super VL", "family": "NVIDIA Nemotron",
        "guidance_source": "https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Super-VL-120B-A12B-BF16/blob/main/README.md",
        "reasoning_on_extra": {"medium_effort": True},
        "reasoning_on_label": "on (medium effort)",
        "control_evidence": "Official model card documents enable_thinking true/false and medium_effort true; reasoning and final text share max_tokens.",
    },
    {
        "id": "nemotron-3.5-lightning", "model": "nvidia/Nemotron-3.5-Lightning-30B-A3B",
        "display_name": "Nemotron 3.5 Lightning 30B", "family": "NVIDIA Nemotron",
        "guidance_source": "https://huggingface.co/nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-BF16/blob/main/README.md",
        "reasoning_on_extra": {}, "reasoning_on_label": "on (default effort)",
        "control_evidence": "Official model card gives separate API examples with enable_thinking true and false. This is a different released checkpoint from Nemotron 3 Nano.",
    },
    {
        "id": "nemotron-3-nano", "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
        "display_name": "Nemotron 3 Nano 30B", "family": "NVIDIA Nemotron",
        "guidance_source": "https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16",
        "reasoning_on_extra": {}, "reasoning_on_label": "on (default effort)",
        "control_evidence": "Official model card documents chat_template_kwargs enable_thinking false and true by default. It is the Nemotron 3 checkpoint, not a Lightning alias.",
    },
    {
        "id": "qwen-3.8-27b", "model": "Qwen/Qwen3.8-27B",
        "display_name": "Qwen 3.8 27B", "family": "Qwen",
        "guidance_source": "https://huggingface.co/Qwen/Qwen3.8-27B",
        "reasoning_on_extra": {},
        "reasoning_on_label": "on (medium effort)",
        "control_evidence": "Official model card documents enable_thinking true/false and medium reasoning effort. Sampling stays fixed across the pair to isolate the reasoning setting, despite different suggested OFF sampling.",
    },
    {
        "id": "gemma-4-31b", "model": "google/gemma-4-31b-it",
        "display_name": "Gemma 4 31B", "family": "Google Gemma",
        "guidance_source": "https://huggingface.co/google/gemma-4-31B-it",
        "reasoning_on_extra": {}, "reasoning_on_label": "on (default effort)",
        "control_evidence": "Official model card documents apply_chat_template enable_thinking false/true. The template inserts a system thinking token when true; OFF can retain an empty thought block.",
    },
)


def discover_catalog():
    """Read model capacity and rates, excluding credentials and unneeded fields."""
    request = urllib.request.Request(BASE_URL + "/models", headers={
        "Authorization": "Bearer " + load_key(), "User-Agent": "uita-closed-loop-model-sweep/1.0",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("catalog_size")
        result = json.loads(raw)
        models = result.get("data", result.get("models", []))
        if not isinstance(models, list):
            raise ValueError("catalog_shape")
    except (urllib.error.URLError, ValueError, TypeError, TimeoutError, OSError):
        raise ProviderError("Crusoe read-only model discovery failed; credentials are not logged") from None
    selected = []
    for policy in MODEL_POLICIES:
        found = next((m for m in models if isinstance(m, dict) and m.get("id") == policy["model"]), None)
        if found is None:
            raise ProviderError("A selected model is absent from authenticated discovery: " + policy["model"])
        supported = found.get("supported_parameters")
        required = {"max_tokens", "temperature", "top_p", "seed", "response_format", "chat_template_kwargs"}
        if not isinstance(supported, list) or not required.issubset(supported):
            raise ProviderError("Selected model lacks bounded generation controls: " + policy["model"])
        if found.get("is_billed_by_token") is not True:
            raise ProviderError("Selected model does not advertise token billing")
        pricing = found.get("pricing", {})
        try:
            rates = [float(pricing[name]) for name in ("prompt", "completion")]
        except (TypeError, KeyError, ValueError):
            raise ProviderError("Selected model lacks usable token rates") from None
        if any(not math.isfinite(rate) or rate < 0 for rate in rates):
            raise ProviderError("Discovered token rates must be finite and nonnegative")
        context = found.get("context_length")
        if type(context) is not int or context <= MAX_TOKENS:
            raise ProviderError("Selected model lacks a usable context bound")
        selected.append({
            "id": policy["model"], "context_length": context,
            "quantization": found.get("quantization"), "supported_parameters": supported,
            "input_usd_per_million_tokens": rates[0], "output_usd_per_million_tokens": rates[1],
            "pricing_source": PRICING_SOURCE,
        })
    return {"schema_version": 1, "endpoint": BASE_URL + "/models", "catalog_source": CATALOG_SOURCE,
            "discovered_at_epoch": time.time(), "models": selected}


def configuration_matrix(catalog=None):
    """Return exactly five distinct authenticated base models and two real modes."""
    catalog = discover_catalog() if catalog is None else copy.deepcopy(catalog)
    models = catalog["models"]
    configs = []
    for policy in MODEL_POLICIES:
        discovery = next(m for m in models if m["id"] == policy["model"])
        for mode in ("off", "on"):
            template = {"enable_thinking": mode == "on"}
            if mode == "on":
                template.update(policy["reasoning_on_extra"])
            generation = {"temperature": 1.0, "top_p": .95, "seed": 17,
                          "max_tokens": MAX_TOKENS, "stream": False,
                          "response_format": {"type": "json_object"}, "chat_template_kwargs": template}
            if mode == "on" and policy["id"] == "qwen-3.8-27b":
                generation["reasoning_effort"] = "medium"
            configs.append({
                "id": policy["id"] + "-" + mode, "model": policy["model"],
                "display_name": policy["display_name"], "family": policy["family"],
                "reasoning": mode, "reasoning_label": policy["reasoning_on_label"] if mode == "on" else "off",
                "generation": generation, "discovery": discovery,
                "guidance_source": policy["guidance_source"], "reasoning_control_evidence": policy["control_evidence"],
                "catalog_source": CATALOG_SOURCE, "discovered_at_epoch": catalog["discovered_at_epoch"],
                "timeout_seconds": TIMEOUT_SECONDS, "minimum_per_model_dispatch_seconds": PACING_SECONDS,
                "sampling_policy": "Identical temperature, top_p, seed and total output-token ceiling in both modes; effort has model-specific meaning.",
            })
    return configs


def validate_configuration(configuration):
    if not isinstance(configuration, dict) or not isinstance(configuration.get("discovery"), dict):
        raise ProviderError("A frozen model configuration and discovery metadata are required")
    policy = next((p for p in MODEL_POLICIES if p["model"] == configuration.get("model")), None)
    if policy is None or configuration.get("reasoning") not in ("on", "off"):
        raise ProviderError("Unknown model or unsupported reasoning mode")
    mode = configuration["reasoning"]
    if configuration.get("id") != policy["id"] + "-" + mode:
        raise ProviderError("Configuration ID is not bound to the model and reasoning mode")
    template = {"enable_thinking": mode == "on"}
    if mode == "on":
        template.update(policy["reasoning_on_extra"])
    generation = {"temperature": 1.0, "top_p": .95, "seed": 17, "max_tokens": MAX_TOKENS,
                  "stream": False, "response_format": {"type": "json_object"}, "chat_template_kwargs": template}
    if mode == "on" and policy["id"] == "qwen-3.8-27b":
        generation["reasoning_effort"] = "medium"
    if configuration.get("generation") != generation:
        raise ProviderError("Frozen model generation settings changed")
    found = configuration["discovery"]
    if found.get("id") != configuration["model"]:
        raise ProviderError("Model discovery is not bound to its configuration")
    if configuration.get("timeout_seconds") != TIMEOUT_SECONDS or configuration.get("minimum_per_model_dispatch_seconds") != PACING_SECONDS:
        raise ProviderError("Frozen timeout or dispatch pacing changed")
    context = found.get("context_length")
    if type(context) is not int or context <= MAX_TOKENS:
        raise ProviderError("Model discovery lacks a context bound")
    for key in ("input_usd_per_million_tokens", "output_usd_per_million_tokens"):
        rate = found.get(key)
        if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate < 0:
            raise ProviderError("Model discovery lacks finite token rates")
    return configuration


class SweepLedger(ReservationLedger):
    """Cap known charges plus full unresolved reservations across all workers.

    A completed, reported charge releases unused headroom. A transport failure
    with unknown cost keeps the full request reservation until reconciled.
    """
    def reserve(self, request_id, payload_sha256, worst_usd):
        if not request_id or not math.isfinite(worst_usd) or worst_usd < 0:
            raise ProviderError("Invalid sweep inference reservation")
        with sqlite3.connect(self.path, timeout=30) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM benchmark_reservations WHERE budget_id=? AND request_id=?",
                          (self.budget_id, request_id)).fetchone():
                raise ProviderError("Sweep request ID already reserved; paid POSTs are not repeated")
            used = db.execute("SELECT COALESCE(SUM(COALESCE(actual_usd,reserved_usd)),0) FROM benchmark_reservations WHERE budget_id=?",
                              (self.budget_id,)).fetchone()[0]
            if used + worst_usd > self.cap_usd:
                raise ProviderError("Sweep spending cap reached; experiment remains incomplete")
            db.execute("INSERT INTO benchmark_reservations VALUES (?,?,?,?,NULL,'reserved',?,NULL)",
                       (self.budget_id, request_id, payload_sha256, worst_usd, time.time()))

    def summary(self):
        result = super().summary()
        with sqlite3.connect(self.path, timeout=30) as db:
            exposure = db.execute("SELECT COALESCE(SUM(COALESCE(actual_usd,reserved_usd)),0) FROM benchmark_reservations WHERE budget_id=?",
                                  (self.budget_id,)).fetchone()[0]
        result.update(budget_exposure_usd=exposure, remaining_exposure_usd=max(0., self.cap_usd - exposure),
                      reservation_policy="reported actual when known; full reservation when unknown")
        return result


class SweepController:
    def __init__(self, directory, configuration, *, ledger_path, budget_id, cap_usd):
        validate_configuration(configuration)
        if isinstance(cap_usd, bool) or not isinstance(cap_usd, (int, float)) or not math.isfinite(cap_usd) or not 0 < cap_usd <= 30:
            raise ProviderError("Sweep requires a finite positive inference cap of at most $30")
        self.configuration = copy.deepcopy(configuration)
        self.config_id, self.model = configuration["id"], configuration["model"]
        self.discovery = configuration["discovery"]
        self.generation = configuration["generation"]
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.directory / "calls.jsonl"
        self.ledger = SweepLedger(ledger_path, budget_id, float(cap_usd))
        self.key = load_key()
        self.calls, self._cache, self.cache_hits = [], {}, 0
        if self.audit_path.exists():
            for line in self.audit_path.read_text().splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                request_id = record["request_id"]
                if request_id in self._cache:
                    raise ProviderError("Duplicate sweep request audit records")
                self._cache[request_id] = record
                self.calls.append(record)
        self.plan = {
            "version": VERSION, "configuration": self.configuration, "config_id": self.config_id,
            "model": self.discovery, "generation": self.generation, "reasoning_mode": configuration["reasoning"],
            "system_prompt": SYSTEM_PROMPT, "prompt_sha256": digest(SYSTEM_PROMPT),
            "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "provider_source_sha256": hashlib.sha256(Path(provider.__file__).read_bytes()).hexdigest(),
            "contract_source_sha256": hashlib.sha256(Path(original_ai.__file__).read_bytes()).hexdigest(),
            "budget_id": budget_id, "cap_usd": float(cap_usd), "max_request_bytes": MAX_REQUEST_BYTES,
            "timeout_seconds": TIMEOUT_SECONDS, "minimum_per_model_dispatch_seconds": PACING_SECONDS,
            "paid_retries": 0, "request_id_policy": "config_id + ':' + engine_request_id",
            "scope": "Already-announced pending arrivals only; no future traffic or historical outcomes",
        }
        plan_path = self.directory / "ai-plan.json"
        if plan_path.exists() and json.loads(plan_path.read_text()) != self.plan:
            raise ProviderError("The frozen sweep controller plan changed")
        if not plan_path.exists():
            plan_path.write_text(json.dumps(self.plan, sort_keys=True, indent=2, allow_nan=False) + "\n")

    def _remember(self, record, *, finish=False):
        if finish:
            self.ledger.finish(record["request_id"], record)
        _append(self.audit_path, record)
        self._cache[record["request_id"]] = record
        self.calls.append(record)

    def choose(self, view, request_id):
        """Return a strict action or recorded API failure; spending blocks raise."""
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 256:
            raise ProviderError("A bounded unique engine request ID is required")
        engine_request_id = request_id
        request_id = self.config_id + ":" + engine_request_id
        try:
            public = copy.deepcopy(validate_view(view))
            payload = {"model": self.model, "messages": [
                {"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": canonical(public)},
            ], **self.generation}
            encoded, payload_hash = canonical(payload).encode(), digest(payload)
        except (ValueError, TypeError, KeyError):
            # Rejected fields cannot be copied to an audit or sent externally.
            raise ProviderError("Sweep public-view boundary rejected an invalid causal state") from None
        cached = self._cache.get(request_id)
        if cached is not None:
            if cached.get("payload_sha256") != payload_hash:
                raise ProviderError("A cached sweep request ID was reused with an altered payload")
            if cached.get("status") in ("budget_or_dispatch_blocked", "unresolved_reservation"):
                raise ProviderError("Prior sweep orchestration block requires review; job remains incomplete")
            self.cache_hits += 1
            return copy.deepcopy(cached.get("action")) if cached["status"] == "completed" else None
        record = {"request_id": request_id, "engine_request_id": engine_request_id, "config_id": self.config_id,
                  "payload_sha256": payload_hash, "request": payload, "status": "not_dispatched",
                  "reserved_usd": 0., "cost_usd": 0., "paid_retries": 0, "dispatched": False,
                  "started_at_epoch": time.time(), "latency_seconds": 0.}
        try:
            previous = self.ledger.lookup(request_id)
        except (ProviderError, sqlite3.Error):
            record.update(status="unresolved_reservation", failure="prior_paid_request_not_retried", cost_usd=None)
            self._remember(record)
            raise ProviderError("Prior sweep request has unresolved reservation; no repeated POST") from None
        if previous is not None:
            if previous.get("payload_sha256") != payload_hash:
                raise ProviderError("Persistent sweep request ID was reused with an altered payload")
            previous["reused_from_persistent_ledger"] = True
            self._remember(previous)
            self.cache_hits += 1
            return copy.deepcopy(previous.get("action")) if previous["status"] == "completed" else None
        input_bound = 2 * len(encoded) + 1024
        if len(encoded) > MAX_REQUEST_BYTES or input_bound + MAX_TOKENS > self.discovery["context_length"]:
            raise ProviderError("Sweep request exceeds the frozen input/output context bounds")
        input_rate = self.discovery["input_usd_per_million_tokens"] / 1_000_000
        output_rate = self.discovery["output_usd_per_million_tokens"] / 1_000_000
        worst = input_bound * input_rate + MAX_TOKENS * output_rate
        record.update(input_token_bound=input_bound, reserved_usd=worst)
        try:
            self.ledger.pace_model(self.model, PACING_SECONDS)
            self.ledger.reserve(request_id, payload_hash, worst)
        except (ProviderError, sqlite3.Error):
            record.update(status="budget_or_dispatch_blocked", failure="no_paid_dispatch", reserved_usd=0.)
            self._remember(record)
            raise ProviderError("Sweep budget or dispatch queue blocked; job remains incomplete") from None
        record.update(status="ambiguous_failure", cost_usd=None, dispatched=True, started_at_epoch=time.time())
        request = urllib.request.Request(BASE_URL + "/chat/completions", data=encoded, method="POST", headers={
            "Authorization": "Bearer " + self.key, "Content-Type": "application/json",
            "User-Agent": "uita-closed-loop-model-sweep/1.0",
        })
        started = time.monotonic()
        try:
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                record["http_status"] = response.status
                record["rate_limit_headers"] = {k: response.headers.get(k) for k in _RATE_HEADERS if response.headers.get(k) is not None}
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            record["response_sha256"] = hashlib.sha256(raw).hexdigest()
            if len(raw) > MAX_RESPONSE_BYTES:
                record.update(status="invalid_response", failure="response_size_limit")
            else:
                record["response_text"] = raw.decode("utf-8", errors="replace")
                response_data = json.loads(raw, parse_constant=_bad_constant)
                record["response"] = response_data
                if not isinstance(response_data, dict):
                    raise ValueError("Provider response is not an object")
                usage = response_data.get("usage")
                usage = usage if isinstance(usage, dict) else {}
                prompt_tokens, output_tokens = usage.get("prompt_tokens"), usage.get("completion_tokens")
                if (type(prompt_tokens) is int and 0 <= prompt_tokens <= input_bound
                        and type(output_tokens) is int and 0 <= output_tokens <= MAX_TOKENS):
                    record["cost_usd"] = prompt_tokens * input_rate + output_tokens * output_rate
                else:
                    record["usage_error"] = "missing_or_out_of_bounds_provider_usage"
                choice = response_data["choices"][0]
                record["finish_reason"] = choice.get("finish_reason")
                message = choice["message"]
                reasoning = message.get("reasoning_content", message.get("reasoning"))
                record["reasoning_content_characters"] = len(reasoning) if isinstance(reasoning, str) else 0
                if choice.get("finish_reason") != "stop":
                    record.update(status="invalid_response", failure="incomplete_generation")
                else:
                    action = parse_action(message.get("content"), public)
                    record.update(status="completed", action=action)
        except urllib.error.HTTPError as exc:
            record.update(status="http_failure", http_status=exc.code, failure="provider_http_error_no_retry")
            record["rate_limit_headers"] = {k: exc.headers.get(k) for k in _RATE_HEADERS if exc.headers.get(k) is not None}
            try:
                raw = exc.read(MAX_RESPONSE_BYTES + 1)
                record["response_sha256"] = hashlib.sha256(raw).hexdigest()
                record["response_truncated"] = len(raw) > MAX_RESPONSE_BYTES
                text = raw[:MAX_RESPONSE_BYTES].decode("utf-8", errors="replace")
                if self.key in text:
                    text = text.replace(self.key, "[credential redacted]")
                    record["response_redacted"] = True
                record["response_text"] = text
            except (OSError, TimeoutError):
                record["error_response_unavailable"] = True
        except (urllib.error.URLError, TimeoutError, OSError):
            record.update(status="ambiguous_failure", failure="transport_failure_no_retry")
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            record.update(status="invalid_response", failure="provider_or_action_contract")
        finally:
            record["latency_seconds"] = time.monotonic() - started
            self._remember(record, finish=True)
        return copy.deepcopy(record.get("action")) if record["status"] == "completed" else None

    def summary(self):
        def token(record, key):
            response = record.get("response")
            usage = response.get("usage") if isinstance(response, dict) else None
            value = usage.get(key) if isinstance(usage, dict) else None
            return value if type(value) is int and value >= 0 else 0
        return {"version": VERSION, "config_id": self.config_id, "model": self.model,
                "reasoning_mode": self.configuration["reasoning"], "calls": len(self.calls),
                "dispatched_calls": sum(r.get("dispatched", False) and not r.get("reused_from_persistent_ledger", False) for r in self.calls),
                "successful_calls": sum(r["status"] == "completed" for r in self.calls),
                "statuses": dict(Counter(r["status"] for r in self.calls)), "cache_hits": self.cache_hits,
                "nonempty_reasoning_calls": sum(r.get("reasoning_content_characters", 0) > 0 for r in self.calls),
                "usage": {k: sum(token(r, k) for r in self.calls) for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
                "reported_cost_usd": sum(r.get("cost_usd") or 0 for r in self.calls),
                "unknown_cost_requests": sum(r.get("cost_usd") is None for r in self.calls),
                "reserved_usd": sum(r["reserved_usd"] for r in self.calls), "paid_retries": 0,
                "budget": self.ledger.summary()}

    def usage_summary(self):
        return self.summary()
