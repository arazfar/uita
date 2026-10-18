"""Build a dependency-free, evidence-linked model leaderboard.

The report never fills missing measurements or treats an incomplete run as a score.
The JSON input is the published record; all table and chart values derive from it.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

SCHEMA_VERSION = "uita-model-leaderboard-v1"
METRIC_KEYS = (
    "spawned", "completed", "backlog", "executed_violations",
    "unresolved_decisions", "mean_added_delay_seconds_all_demand",
    "p95_added_delay_seconds_all_demand", "penalized_added_delay_seconds",
    "decisions", "fallback_decisions", "controller_failures", "rejected_proposals",
)


def display_name(model: str) -> str:
    """Retain checkpoint identity while removing API namespace formatting."""
    name = model.rsplit("/", 1)[-1]
    name = re.sub(r"^NVIDIA-", "", name, flags=re.IGNORECASE)
    name = name.replace("-", " ")
    name = re.sub(r"\bgemma\b", "Gemma", name, flags=re.IGNORECASE)
    name = re.sub(r"\b(\d+(?:\.\d+)?)[bB]\b", r"\1B", name)
    name = re.sub(r"\bit\b", "IT", name, flags=re.IGNORECASE)
    return name


def _number(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number or null")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return value


def _url(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value)
    parts = urlsplit(text)
    if parts.scheme and parts.scheme not in {"http", "https"}:
        raise ValueError("Audit links must use relative paths or HTTP(S)")
    if parts.netloc and not parts.scheme:
        raise ValueError("Protocol-relative audit links are not allowed")
    return text


def normalize(document: dict[str, Any]) -> dict[str, Any]:
    """Validate records and derive presentation fields from measured aggregates.

    Entries use the closed-loop summary metric names. The optional ``usage``
    mapping accepts its existing ``ai_usage`` keys. Only exact complete, verified
    records with a complete safety/efficiency vector can enter the ranking.
    """
    if not isinstance(document, dict) or not isinstance(document.get("entries"), list):
        raise ValueError("Report input requires an entries array")
    result = dict(document)
    result["schema_version"] = SCHEMA_VERSION
    result.setdefault("title", "Arrival sequencing model leaderboard")
    result.setdefault("date_range", "Dates not recorded")
    result.setdefault("generated_at", "Not recorded")
    result.setdefault("harness_version", "Not recorded")
    result.setdefault("coverage", {})
    if result.get("failure_analysis_url"):
        result["failure_analysis_url"] = _url(result["failure_analysis_url"])
    rows = []
    seen = set()
    for index, original in enumerate(document["entries"]):
        row = dict(original)
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ValueError("Every entry requires a unique, nonempty id")
        seen.add(identifier)
        row.setdefault("model", identifier)
        row["display_name"] = row.get("display_name") or display_name(row["model"])
        row.setdefault("provider", "Not recorded")
        row.setdefault("reasoning", "n/a")
        if row["reasoning"] not in {"on", "off", "n/a", "unsupported"}:
            raise ValueError(f"Unknown reasoning state for {identifier}")
        row.setdefault("kind", "model")
        if row["kind"] not in {"model", "reference", "context"}:
            raise ValueError(f"Unknown entry kind for {identifier}")
        row.setdefault("status", "pending")
        if row["status"] not in {"completed", "running", "pending", "failed", "unsupported"}:
            raise ValueError(f"Unknown run status for {identifier}")
        row.setdefault("experiment_index", index + 1 if row["kind"] == "model" else None)
        if row["kind"] == "model" and (isinstance(row["experiment_index"], bool) or not isinstance(row["experiment_index"], int) or row["experiment_index"] < 1):
            raise ValueError(f"{identifier}.experiment_index must be a positive integer")
        row.setdefault("date", result["generated_at"][:10])
        row.setdefault("harness_version", result["harness_version"])
        metrics = dict(row.get("metrics") or {})
        for key in METRIC_KEYS:
            metrics[key] = _number(metrics.get(key), f"{identifier}.{key}")
        for key in ("spawned", "completed", "backlog", "executed_violations", "unresolved_decisions", "decisions", "fallback_decisions"):
            if metrics[key] is not None and int(metrics[key]) != metrics[key]:
                raise ValueError(f"{identifier}.{key} must be an integer")
        if metrics["spawned"] is not None and metrics["completed"] is not None:
            if metrics["completed"] > metrics["spawned"]:
                raise ValueError(f"{identifier} completes more arrivals than supplied")
            if metrics["backlog"] is not None and metrics["completed"] + metrics["backlog"] != metrics["spawned"]:
                raise ValueError(f"{identifier} completion and backlog do not match demand")
        usage = dict(row.get("usage") or row.get("ai_usage") or {})
        if "latency_seconds_p95" not in usage and "p95" in usage:
            usage["latency_seconds_p95"] = usage["p95"]
        for key in ("calls", "successful_calls", "reported_cost_usd", "unknown_cost_requests", "latency_seconds_mean", "latency_seconds_p95"):
            usage[key] = _number(usage.get(key), f"{identifier}.usage.{key}")
        if usage["successful_calls"] is not None and usage["calls"] is not None and usage["successful_calls"] > usage["calls"]:
            raise ValueError(f"{identifier} successful calls exceed total calls")
        decisions = metrics["decisions"]
        if decisions is not None and metrics["fallback_decisions"] is not None and metrics["fallback_decisions"] > decisions:
            raise ValueError(f"{identifier} fallback count exceeds decisions")
        row["metrics"], row["usage"] = metrics, usage
        row["audit_url"] = _url(row.get("audit_url"))
        row["verified"] = (row.get("verification") or {}).get("passed") is True
        required = ("spawned", "completed", "backlog", "executed_violations", "unresolved_decisions", "penalized_added_delay_seconds")
        row["rankable"] = (
            row["kind"] != "context" and row["status"] == "completed" and row["verified"]
            and all(metrics[key] is not None for key in required) and metrics["spawned"] > 0
        )
        row["eligible"] = bool(row["rankable"] and metrics["executed_violations"] == 0 and metrics["unresolved_decisions"] == 0)
        row["completion_percent"] = 100 * metrics["completed"] / metrics["spawned"] if metrics["spawned"] else None
        row["fallback_percent"] = 100 * metrics["fallback_decisions"] / decisions if decisions and metrics["fallback_decisions"] is not None else None
        row["usable_response_percent"] = 100 * usage["successful_calls"] / usage["calls"] if usage["calls"] and usage["successful_calls"] is not None else None
        row["rank"] = None
        rows.append(row)
    # The objective is lexicographic: delay cannot compensate for less service.
    ranked = sorted((r for r in rows if r["eligible"] and r["kind"] == "model"), key=ranking_key)
    previous_score = None
    previous_rank = None
    for rank, row in enumerate(ranked, 1):
        score = ranking_key(row)[:2]
        row["rank"] = previous_rank if score == previous_score else rank
        previous_score, previous_rank = score, row["rank"]
    references = [r for r in rows if r["kind"] == "reference"]
    demand = {r["metrics"]["spawned"] for r in rows if r["rankable"]}
    if len(demand) > 1:
        raise ValueError("Matched leaderboard entries must have the same arrival demand")
    result["entries"] = rows
    result["best_history"] = best_history(rows)
    result["ranked_configurations"] = len(ranked)
    result["matched_references"] = len(references)
    result["comparison_verdict"] = comparison_verdict(rows)
    return result


def ranking_key(row: dict[str, Any]) -> tuple[float, float, str]:
    metrics = row["metrics"]
    return metrics["backlog"], metrics["penalized_added_delay_seconds"], row["id"]


def comparison_verdict(rows: list[dict[str, Any]]) -> dict[str, Any]:
    models = [r for r in rows if r["kind"] == "model"]
    references = [r for r in rows if r["kind"] == "reference"]
    pending = {
        "status": "pending",
        "text": "Model-to-reference comparison pending. All configurations and matched references need complete, independently verified results. Model rank compares model configurations only.",
    }
    if not models or not references or any(not r["rankable"] for r in models + references):
        return pending
    eligible_models = [r for r in models if r["eligible"]]
    eligible_references = [r for r in references if r["eligible"]]
    if not eligible_models or not eligible_references:
        return {
            "status": "ineligible",
            "text": "No eligible model-to-reference comparison is available. At least one side has no configuration with zero executed violations and unresolved decisions.",
        }
    model = min(eligible_models, key=ranking_key)
    reference = min(eligible_references, key=ranking_key)
    model_key, reference_key = ranking_key(model)[:2], ranking_key(reference)[:2]
    relation = "better" if model_key < reference_key else "worse" if model_key > reference_key else "tied"
    m, r = model["metrics"], reference["metrics"]
    wording = {
        "better": "It outperforms",
        "worse": "It does not outperform",
        "tied": "It ties",
    }[relation]
    return {
        "status": "completed", "relation": relation,
        "best_model_id": model["id"], "best_reference_id": reference["id"],
        "text": (
            f"Best eligible model: {model['display_name']} (reasoning {model['reasoning'].upper()}). "
            f"It completes {int(m['completed']):,}/{int(m['spawned']):,} arrivals. "
            f"{wording} the matched {reference['display_name']} reference on the benchmark objective "
            f"({int(r['completed']):,}/{int(r['spawned']):,} arrivals). "
            "The objective compares unfinished arrivals first, then penalized delay. Model rank compares model configurations only."
        ),
    }


def best_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best = None
    history = []
    for row in sorted((r for r in rows if r["kind"] == "model"), key=lambda r: r["experiment_index"]):
        if row["eligible"] and (best is None or ranking_key(row) < ranking_key(best)):
            best = row
        history.append({
            "experiment": row["experiment_index"], "candidate": row["id"],
            "best_id": best["id"] if best else None,
            "best_model": best["display_name"] if best else None,
            "best_model_id": best["model"] if best else None,
            "reasoning": best["reasoning"] if best else None,
            "completion_percent": best["completion_percent"] if best else None,
            "backlog": best["metrics"]["backlog"] if best else None,
            "penalized_added_delay_seconds": best["metrics"]["penalized_added_delay_seconds"] if best else None,
        })
    return history


def _svg_bars(rows: list[dict[str, Any]], metric: str, title: str, unit: str, reference_rows: list[dict[str, Any]]) -> str:
    plotted = [r for r in rows if r["status"] == "completed" and r["rankable"] and r["metrics"].get(metric) is not None]
    if metric == "completion_percent":
        plotted = [r for r in rows if r["rankable"]]
    def value(row: dict[str, Any]) -> float:
        return row["completion_percent"] if metric == "completion_percent" else row["metrics"][metric]
    refs = [r for r in reference_rows if r["rankable"] and (metric == "completion_percent" or r["metrics"].get(metric) is not None)]
    height = max(180, 100 + len(plotted) * 42)
    width, left, right, top = 1100, 330, 120, 70
    plot_width = width - left - right
    maximum = 100 if metric == "completion_percent" else max([value(r) for r in plotted + refs] or [1]) * 1.12
    maximum = maximum or 1
    esc = html.escape
    pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(title)}"><style>text{{font-family:Arial,sans-serif;fill:#25231e}} .muted{{fill:#625d53}}</style><rect width="100%" height="100%" fill="#f6f2e8"/><text x="24" y="31" font-size="20" font-weight="600">{esc(title)}</text>']
    for step in range(5):
        amount = maximum * step / 4
        x = left + plot_width * step / 4
        pieces.extend([f'<line x1="{x}" y1="{top-14}" x2="{x}" y2="{height-30}" stroke="#ddd7ca"/>', f'<text x="{x}" y="{top-24}" text-anchor="middle" font-size="12" class="muted">{amount:,.0f}{unit}</text>'])
    for i, row in enumerate(plotted):
        y = top + 42 * i
        bar = value(row) / maximum * plot_width
        fill = "#216058" if row["reasoning"] == "on" else "#628b87"
        pieces.extend([f'<text x="{left-16}" y="{y+18}" text-anchor="end" font-size="13"><title>{esc(row["model"])}</title>{esc(row["display_name"])} · {esc(row["reasoning"].upper())}</text>', f'<rect x="{left}" y="{y}" width="{bar:.2f}" height="26" rx="2" fill="{fill}"/>', f'<text x="{left+bar+9:.2f}" y="{y+18}" font-size="13">{value(row):,.1f}{unit}</text>'])
    for i, row in enumerate(refs):
        x = left + value(row) / maximum * plot_width
        dash = "5 4" if i % 2 else "2 3"
        pieces.append(f'<line x1="{x:.2f}" y1="{top-12}" x2="{x:.2f}" y2="{height-30}" stroke="#39382f" stroke-dasharray="{dash}" stroke-width="1.5"><title>{esc(row["model"])}: {value(row):,.2f}{unit}</title></line>')
    if not plotted:
        pieces.append('<text x="24" y="100" font-size="15" class="muted">No complete, independently verified results are available.</text>')
    pieces.append('</svg>')
    return ''.join(pieces)


def write_report(document: dict[str, Any], out: str | Path) -> dict[str, str]:
    """Write HTML, normalized JSON, CSV and two standalone SVG chart artifacts."""
    report = normalize(document)
    destination = Path(out)
    destination.mkdir(parents=True, exist_ok=True)
    json_path, csv_path = destination / "leaderboard.json", destination / "leaderboard.csv"
    json_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    columns = ["id", "rank", "model", "display_name", "provider", "reasoning", "kind", "status", "verified", "eligible", "harness_version", "date", "completion_percent", *METRIC_KEYS, "usable_response_percent", "fallback_percent", "calls", "successful_calls", "reported_cost_usd", "unknown_cost_requests", "latency_seconds_mean", "latency_seconds_p95", "audit_url"]
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
        writer.writeheader()
        for row in report["entries"]:
            flat = {**row, **row["metrics"], **row["usage"]}
            writer.writerow({key: flat.get(key) for key in columns})
    references = [r for r in report["entries"] if r["kind"] == "reference"]
    models = [r for r in report["entries"] if r["kind"] == "model"]
    for filename, metric, title, unit in (
        ("completion.svg", "completion_percent", "Completed arrivals · higher is better", "%"),
        ("delay.svg", "mean_added_delay_seconds_all_demand", "All-demand added delay · seconds, lower is better", "s"),
    ):
        (destination / filename).write_text(_svg_bars(models, metric, title, unit, references))
    payload = json.dumps(report, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c").replace("&", "\\u0026")
    page = HTML_TEMPLATE.replace("__TITLE__", html.escape(str(report["title"]))).replace("__DATA__", payload)
    (destination / "index.html").write_text(page)
    return {name: str(destination / name) for name in ("index.html", "leaderboard.json", "leaderboard.csv", "completion.svg", "delay.svg")}


HTML_TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>__TITLE__</title>
<style>
:root{--paper:#f6f2e8;--sheet:#fffdf7;--ink:#25231e;--muted:#625d53;--rule:#d9d3c6;--panel:#e6dfce;--green:#216058;--green-light:#e6f0e9;--cyan:#356b7d;--red:#9b3429;--amber:#835b16;--radius:3px;font-family:"Helvetica Neue",Arial,sans-serif;font-size:15px;color:var(--ink);background:var(--paper);font-synthesis:none}*{box-sizing:border-box}body{margin:0}button,input,select{font:inherit}button,a,input,select{accent-color:var(--green)}a{color:var(--green);text-underline-offset:3px}button,select{min-height:44px;border:1px solid #a8a293;border-radius:var(--radius);background:var(--sheet);color:var(--ink);padding:8px 12px}button{cursor:pointer}button:hover{background:#eae5d8}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--cyan);outline-offset:3px}header{background:var(--panel);border-bottom:1px solid #bcb5a5;padding:26px max(24px,calc((100vw - 1600px)/2)) 24px}.brand{font:600 12px "Courier New",monospace;text-transform:uppercase;letter-spacing:.14em;color:var(--muted);margin-bottom:18px}.brand span{margin-left:18px;font-weight:400;letter-spacing:.04em}h1{font-size:clamp(28px,3vw,42px);font-weight:550;letter-spacing:-.035em;margin:0 0 12px;line-height:1.1}.intro{font-size:17px;line-height:1.55;max-width:1050px;margin:0}main{max-width:1648px;margin:auto;padding:25px 24px 55px}.meta{display:flex;gap:28px;flex-wrap:wrap;padding-bottom:22px;border-bottom:1px solid var(--rule);font-size:13px}.meta dt{color:var(--muted);margin-bottom:5px}.meta dd{margin:0;font-weight:550;font-variant-numeric:tabular-nums}.explain{display:grid;grid-template-columns:1.1fr 1fr;gap:32px;padding:23px 0;border-bottom:1px solid var(--rule)}h2{font-size:20px;font-weight:550;letter-spacing:-.02em;margin:0 0 10px}p{line-height:1.6;margin:0 0 10px}.explain p{font-size:14px;max-width:800px}.objective{font-family:"Courier New",monospace;font-size:12px;padding:12px 14px;border:1px solid var(--rule);background:var(--sheet);line-height:1.7}.subtle{color:var(--muted)}.toolbar{display:flex;align-items:end;gap:10px;flex-wrap:wrap;margin:24px 0 14px}.toolbar label{display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--muted)}.toolbar .search{min-width:240px;flex:1;max-width:380px}.toolbar input[type=search]{min-height:44px;background:var(--sheet);border:1px solid #a8a293;border-radius:var(--radius);padding:8px 12px;color:var(--ink);width:100%}.toolbar button:first-of-type{background:var(--green);border-color:var(--green);color:white}.toolbar .spacer{flex:1}.toolbar a{font-size:13px;white-space:nowrap;padding:13px 5px}.table-wrap{overflow:auto;border:1px solid #c5beae;border-radius:4px;background:var(--sheet)}table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}th{background:#eee9dc;border-bottom:1px solid #c5beae;text-align:right;color:var(--muted);font-size:10px;letter-spacing:.07em;text-transform:uppercase;font-weight:600;height:54px;position:sticky;top:0;z-index:1}th button{border:0;background:transparent!important;padding:10px;color:inherit!important;font:inherit;letter-spacing:inherit;text-transform:inherit;min-height:44px;white-space:nowrap}th:first-child{width:46px}th:nth-child(2){width:40px}th.model-col{text-align:left;min-width:270px}td{padding:15px 11px;text-align:right;border-bottom:1px solid #e3ded2;font-variant-numeric:tabular-nums}tr:last-child td{border-bottom:0}td.model-cell{text-align:left;white-space:normal;min-width:270px}td.model-cell strong{font-size:15px;font-weight:550;display:block;margin-bottom:5px}td.model-cell small{font-size:11px;display:block;color:var(--muted);line-height:1.5}td input{width:17px;height:17px;margin:0}.score{font-weight:650;font-size:19px;letter-spacing:-.025em}.mini-bar{height:3px;background:#e2e7dc;max-width:110px;margin:7px 0 0 auto;overflow:hidden;border-radius:3px}.mini-bar span{height:100%;display:block;background:var(--green)}tr[data-selected=true]{background:var(--green-light)}.reasoning{font-size:10px;font-weight:600;border:1px solid #c3c9bc;border-radius:3px;padding:3px 5px;display:inline-block;margin-right:5px}.status{font-size:11px}.status.fail{color:var(--red)}.status.pending{color:var(--amber)}.empty{text-align:left;padding:30px 20px;color:var(--muted)}.table-note{display:flex;justify-content:space-between;gap:15px;flex-wrap:wrap;margin:9px 0 24px;font-size:12px;color:var(--muted);line-height:1.6}.section-label{display:flex;align-items:baseline;justify-content:space-between;gap:20px;margin:26px 0 12px}.section-label p{font-size:12px;color:var(--muted);margin:0}.reference td{background:#ece8dc}.reference .score{font-size:16px}.charts{display:grid;grid-template-columns:1fr 1fr;gap:18px}.chart{border:1px solid #c5beae;border-radius:3px;background:var(--sheet);padding:18px 16px;min-width:0}.chart h3{font-size:15px;font-weight:550;margin:0 0 6px}.chart p{font-size:12px;color:var(--muted);margin:0 0 12px}.chart svg{width:100%;height:auto;display:block;overflow:visible}.chart .legend{display:flex;gap:16px;flex-wrap:wrap;font-size:11px;margin-top:12px}.legend span::before{content:"";width:18px;display:inline-block;vertical-align:middle;margin-right:6px;border-top:2px solid var(--green)}.legend span.off::before{border-color:#628b87}.legend span.ref::before{border-color:#39382f;border-top-style:dashed}.legend span.second::before{border-top-style:dotted}.chart .chart-empty{font-size:13px;min-height:140px;display:flex;align-items:center;justify-content:center;color:var(--muted)}.footnotes{display:grid;grid-template-columns:1fr 1fr;gap:25px;border-top:1px solid var(--rule);margin-top:28px;padding-top:20px}.footnotes p{font-size:12px;color:var(--muted)}details{margin-top:18px;border-top:1px solid var(--rule);padding-top:16px}summary{cursor:pointer;font-weight:550;min-height:35px}.failure-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:15px}.failure-item{font-size:12px;border:1px solid var(--rule);padding:12px}.failure-item p{margin:4px 0;font-size:12px}.progress-table{margin-top:10px;overflow:auto}.progress-table table{font-size:12px;white-space:normal}.progress-table th{text-transform:none;letter-spacing:0;padding:10px}.progress-table td{padding:10px}.progress-table td:nth-child(2){text-align:left}.context{padding:14px 16px;border:1px solid var(--rule);font-size:12px;background:#ede9df}.context strong{display:block;margin-bottom:5px}.context p{font-size:12px;margin:0}.download-links{margin-top:12px;display:flex;gap:16px;font-size:12px}noscript{display:block;padding:16px;border:1px solid var(--rule);background:white}footer{font-size:11px;color:var(--muted);margin-top:25px;line-height:1.6}@media(max-width:900px){.explain,.charts,.footnotes{grid-template-columns:1fr}.brand span{display:block;margin:8px 0 0}.toolbar .spacer{display:none}.meta{gap:18px}.section-label{display:block}.section-label p{margin-top:5px}.charts{gap:14px}.chart{padding:15px 10px}}@media(max-width:480px){header{padding:20px 16px}main{padding:20px 14px}.toolbar{gap:8px}.toolbar .search{min-width:100%;max-width:none}.toolbar select{max-width:145px}.toolbar a{padding:10px 3px}.intro{font-size:15px}.explain{gap:15px}.meta{font-size:12px;gap:16px}.score{font-size:17px}}@media print{header{background:white}body{background:white}main{padding:15px}.toolbar{display:none}.charts{grid-template-columns:1fr}th{position:static}.table-wrap{overflow:visible}.chart{break-inside:avoid}details{display:block}a{color:inherit}.download-links{display:none}}
</style></head><body>
<header><div class="brand">UITA / EVALUATION <span>Historical traffic · Closed-loop simulation</span></div><h1>__TITLE__</h1><p class="intro">Models repeatedly order arriving aircraft as traffic becomes known. We measure completed arrivals, added waiting, and violations within a fixed approach simulation.</p></header>
<main><dl class="meta" id="meta"></dl><p id="provenance" class="context" hidden></p>
<section class="explain" aria-label="Benchmark scope"><div><h2>What does the score measure?</h2><p>Each model chooses an arrival order. A common scheduler turns that order into landing reservations. The simulator executes checked plans, then asks again as traffic changes.</p><p class="subtle">All models receive the same traffic, public state, safety checks, and fallback policy. This evaluates the model and its counted fallbacks together.</p></div><div><h2>Safety first. Then service. Then delay.</h2><p>Only complete, independently verified runs with zero executed violations and zero unresolved decisions enter the ranking. Fewer unfinished arrivals wins. Delay breaks ties.</p><div class="objective">Penalized delay = total accrued added delay<br>+ 3,600 seconds × unfinished arrivals</div></div></section>
<p id="verdict" class="context" role="status"></p>
<div class="toolbar"><label class="search">Find a model<input type="search" id="search" placeholder="Model or provider" aria-label="Find a model"></label><label>Reasoning<select id="reasoning"><option value="all">All settings</option><option value="on">Reasoning ON</option><option value="off">Reasoning OFF</option></select></label><label>Show<select id="status"><option value="all">All configurations</option><option value="completed">Completed only</option><option value="eligible">Ranking eligible</option><option value="incomplete">Incomplete</option></select></label><button id="compare" aria-pressed="false">Compare selected</button><button id="clear">Clear selection</button><span class="spacer"></span><a href="leaderboard.csv" download>Download CSV</a><a href="leaderboard.json" download>JSON</a></div>
<div class="table-wrap"><table aria-label="Model leaderboard"><thead><tr><th><input type="checkbox" id="select-all" aria-label="Select all visible model configurations"></th><th><button data-sort="rank">#</button></th><th class="model-col"><button data-sort="display_name">Model / reasoning</button></th><th><button data-sort="completion_percent">Completed %</button></th><th><button data-sort="mean_added_delay_seconds_all_demand">Mean delay, s</button></th><th><button data-sort="p95_added_delay_seconds_all_demand">P95 delay, s</button></th><th><button data-sort="backlog">Backlog</button></th><th><button data-sort="executed_violations">Violations</button></th><th><button data-sort="usable_response_percent">Usable %</button></th><th><button data-sort="fallback_percent">Fallback %</button></th><th><button data-sort="latency_seconds_mean">Latency, s</button></th><th><button data-sort="reported_cost_usd">Known cost, $</button></th><th>Audit / date</th></tr></thead><tbody id="rows"></tbody></table></div>
<div class="table-note"><span id="row-count"></span><span>Rank follows the full objective. Column sorting does not change rank.</span></div>
<section><div class="section-label"><h2>Matched reference controllers</h2><p>Same date range, traffic, simulator, and safety envelope.</p></div><div class="table-wrap"><table aria-label="Matched reference controller results"><thead><tr><th class="model-col">Controller</th><th>Completed</th><th>Mean delay, s</th><th>P95 delay, s</th><th>Backlog</th><th>Violations</th><th>Status / evidence</th></tr></thead><tbody id="references"></tbody></table></div></section>
<div class="section-label"><h2>Compare outcomes</h2><p id="chart-scope">Complete verified model configurations. Reference lines show matched controllers.</p></div>
<div class="charts"><section class="chart"><h3>Completed arrivals</h3><p>Higher is better. Unfinished demand remains visible in the table.</p><div id="completion-chart"></div><div class="legend" id="completion-legend"></div></section><section class="chart"><h3>All-demand added delay</h3><p>Lower is better, after completion. Includes accrued waiting for unfinished arrivals.</p><div id="delay-chart"></div><div class="legend" id="delay-legend"></div></section><section class="chart"><h3>What changes when reasoning is ON?</h3><p>Paired differences: ON minus OFF. Positive delay means reasoning ON added more waiting.</p><div id="paired-chart"></div></section><section class="chart"><h3>Best eligible result in registered experiment order</h3><p>Experiments run concurrently. This follows registered order, not a learning curve. A delay rise may accompany a completion gain.</p><div id="history-chart"></div><div class="progress-table" id="history-table"></div></section></div>
<div class="download-links"><a href="completion.svg" download>Completion chart SVG</a><a href="delay.svg" download>Delay chart SVG</a></div>
<details><summary>Model responses and API failures</summary><p class="subtle">A usable response satisfies the action contract. A fallback is a checked replacement, not a successful model response.</p><div class="failure-grid" id="failures"></div></details>
<section id="context-section" hidden><div class="section-label"><h2>Earlier results — separate context</h2></div><div class="context" id="context"></div></section>
<div class="footnotes"><div><p><strong>Delay scope.</strong> Added delay is modeled waiting before admission to a fixed approach. It is not measured historical airline delay or airborne holding. Waiting after the common horizon is unknown.</p><p><strong>Safety scope.</strong> The verifier checks executed fixed-approach motion and modeled runway resources. The feeder and upstream waiting queue remain outside the safety model. Zero checked violations does not establish operational safety.</p></div><div><p><strong>Comparison scope.</strong> Controllers do not choose headings, altitudes, speeds, radio commands, or unrestricted routes. This benchmark does not measure performance against authentic human ATC decisions.</p><p><strong>Time and cost.</strong> Simulation time pauses during model computation. API latency is shown separately. Known cost excludes requests whose cost the provider did not report; those requests remain explicit.</p><p id="limits"></p></div></div>
<noscript>Interactive controls need JavaScript. Download leaderboard.csv or leaderboard.json for the full results. Standalone SVG charts remain available above.</noscript><footer id="footer"></footer><p id="failure-analysis-link" hidden></p></main>
<script type="application/json" id="report-data">__DATA__</script><script>
'use strict';
const D=JSON.parse(document.getElementById('report-data').textContent), $=id=>document.getElementById(id), esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=(n,d=0)=>n==null?'—':Number(n).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const get=(r,k)=>r[k]??r.metrics[k]??r.usage[k]??null;
const refs=D.entries.filter(r=>r.kind==='reference'), models=D.entries.filter(r=>r.kind==='model');let selected=new Set(), compare=false, sort='rank', descending=false;
const status=r=>r.status!=='completed'?r.status:r.kind==='context'?'Earlier context':!r.verified?'Verification pending':!r.rankable?'Metrics incomplete':!r.eligible?'Not eligible':'Verified';
const audit=r=>r.audit_url?`<a href="${esc(r.audit_url)}">Audit ↗</a>`:'No audit link';
const small=s=>`<span class="subtle">${s}</span>`;
const cov=D.coverage||{};let meta=[['Traffic dates',Array.isArray(D.date_range)?D.date_range.join(' – '):D.date_range],['Coverage',`${fmt(cov.episodes)} windows · ${fmt(cov.arrivals)} arrivals`],['Model configurations',`${models.filter(r=>r.status==='completed').length}/${models.length} complete`],['Harness',D.harness_version],['Published',D.generated_at]];
$('meta').innerHTML=meta.map(([k,v])=>`<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('');
const provenance=D.provenance_note||cov.provenance_note||cov.source_label;if(provenance){$('provenance').hidden=false;$('provenance').textContent=provenance}$('verdict').textContent=D.comparison_verdict.text;$('limits').textContent=(D.limits||[]).join(' ');$('footer').textContent=`Source: ${cov.source_label||'See linked protocol and audit records'}. Built from the published JSON record. Missing measurements remain missing.`;if(D.failure_analysis_url){$('failure-analysis-link').hidden=false;$('failure-analysis-link').innerHTML=`<a href="${esc(D.failure_analysis_url)}">Read model mistakes and API failure analysis ↗</a>`;}
function visible(){const query=$('search').value.toLowerCase(),reason=$('reasoning').value,state=$('status').value;return models.filter(r=>(`${r.model} ${r.display_name} ${r.provider}`.toLowerCase().includes(query))&&(reason==='all'||r.reasoning===reason)&&(state==='all'||(state==='completed'&&r.status==='completed')||(state==='eligible'&&r.eligible)||(state==='incomplete'&&r.status!=='completed'))&&(!compare||selected.has(r.id))).sort((a,b)=>{let av=get(a,sort),bv=get(b,sort);if(av==null)return bv==null?0:1;if(bv==null)return-1;let n=typeof av==='string'?av.localeCompare(bv):av-bv;return descending?-n:n;});}
function metric(r,key,dec=0){return r.status==='completed'?fmt(get(r,key),dec):'—';}
function render(){const rows=visible();$('rows').innerHTML=rows.length?rows.map(r=>{const done=r.status==='completed',m=r.metrics,u=r.usage;return `<tr data-selected="${selected.has(r.id)}"><td><input type="checkbox" data-id="${esc(r.id)}" aria-label="Compare ${esc(r.model)} reasoning ${esc(r.reasoning)}" ${selected.has(r.id)?'checked':''}></td><td>${fmt(r.rank)}</td><td class="model-cell"><strong title="${esc(r.model)}">${esc(r.display_name)}</strong><small><span class="reasoning">${esc(r.reasoning==='n/a'?'N/A':`REASONING ${r.reasoning.toUpperCase()}`)}</span>${esc(r.provider)} · ${esc(r.harness_version)}</small><small class="status ${!done?'pending':!r.eligible?'fail':''}">${esc(status(r))}${r.status_detail?' · '+esc(r.status_detail):''}</small></td><td><span class="score">${metric(r,'completion_percent',2)}</span>${done?`<div class="mini-bar"><span style="width:${r.completion_percent||0}%"></span></div><small>${fmt(m.completed)}/${fmt(m.spawned)}</small>`:''}</td><td>${metric(r,'mean_added_delay_seconds_all_demand',1)}</td><td>${metric(r,'p95_added_delay_seconds_all_demand',1)}</td><td>${metric(r,'backlog')}</td><td>${metric(r,'executed_violations')}${done&&m.unresolved_decisions?`<br><small class="status fail">${fmt(m.unresolved_decisions)} unresolved</small>`:''}</td><td>${metric(r,'usable_response_percent',1)}</td><td>${metric(r,'fallback_percent',1)}${done?`<br><small>${fmt(m.fallback_decisions)}/${fmt(m.decisions)}</small>`:''}</td><td title="Mean API wall latency; P95 ${fmt(u.latency_seconds_p95,1)} s">${fmt(u.latency_seconds_mean,1)}</td><td>${fmt(u.reported_cost_usd,4)}${u.unknown_cost_requests?`<br><small>${fmt(u.unknown_cost_requests)} unknown</small>`:''}</td><td>${audit(r)}<br><small class="subtle">${esc(r.date)}</small></td></tr>`}).join(''):'<tr><td colspan="13" class="empty">No configurations match these filters. Clear the filters or selection.</td></tr>';$('row-count').textContent=`${rows.length} configuration${rows.length===1?'':'s'} shown · ${models.filter(r=>r.eligible).length} ranking eligible. Unverified and incomplete results have no rank.`;$('select-all').checked=rows.length>0&&rows.every(r=>selected.has(r.id));$('select-all').indeterminate=rows.some(r=>selected.has(r.id))&&!$('select-all').checked;document.querySelectorAll('th button[data-sort]').forEach(b=>{b.setAttribute('aria-label',`Sort by ${b.textContent.trim()}`);b.parentElement.setAttribute('aria-sort',b.dataset.sort===sort?(descending?'descending':'ascending'):'none')});const chartRows=rows.filter(r=>r.rankable);$('chart-scope').textContent=compare?'Selected complete verified configurations. References use the same traffic.':'Complete verified configurations under the active filters. References use the same traffic.';barChart('completion-chart',chartRows,'completion_percent',true);barChart('delay-chart',chartRows,'mean_added_delay_seconds_all_demand',false);pairedChart(chartRows);}
function legend(target){$(target).innerHTML='<span>Reasoning ON</span><span class="off">Reasoning OFF</span>'+refs.filter(r=>r.rankable).map((r,i)=>`<span class="ref ${i?'second':''}">${esc(r.display_name)}</span>`).join('')}
function barChart(target,rows,key,percent){const valid=rows.filter(r=>get(r,key)!=null),reference=refs.filter(r=>r.rankable&&get(r,key)!=null);legend(target.replace('chart','legend'));if(!valid.length){$(target).innerHTML='<div class="chart-empty">No complete verified results in this view.</div>';return}const W=700,L=225,R=60,T=30,H=60+valid.length*37,P=W-L-R,max=percent?100:Math.max(...valid.concat(reference).map(r=>get(r,key)),1)*1.1;let s=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${percent?'Completed arrival percentage':'Mean all-demand added delay in seconds'}"><g font-family="Arial,sans-serif" fill="#25231e">`;for(let i=0;i<5;i++){let x=L+i*P/4;s+=`<line x1="${x}" y1="${T-5}" x2="${x}" y2="${H-15}" stroke="#e2ddcf"/><text x="${x}" y="15" text-anchor="middle" font-size="10" fill="#625d53">${fmt(i*max/4)}${percent?'%':'s'}</text>`}valid.forEach((r,i)=>{let y=T+i*37,v=get(r,key),b=v/max*P,label=r.display_name;s+=`<text x="${L-10}" y="${y+16}" text-anchor="end" font-size="11"><title>${esc(r.model)} · ${esc(r.reasoning)}</title>${esc(label)} · ${r.reasoning.toUpperCase()}</text><rect x="${L}" y="${y}" width="${b}" height="24" rx="1" fill="${r.reasoning==='on'?'#216058':'#628b87'}"><title>${esc(r.model)}: ${fmt(v,2)}${percent?'%':' s'}; ${fmt(r.metrics.backlog)} unfinished; ${fmt(r.fallback_percent,1)}% fallback</title></rect><text x="${L+b+6}" y="${y+16}" font-size="10">${fmt(v,1)}</text>`});reference.forEach((r,i)=>{let x=L+get(r,key)/max*P;s+=`<line x1="${x}" y1="${T-5}" x2="${x}" y2="${H-15}" stroke="#39382f" stroke-dasharray="${i?'2 3':'5 4'}" stroke-width="1.5"><title>${esc(r.model)}: ${fmt(get(r,key),2)}${percent?'%':' s'}</title></line>`});$(target).innerHTML=s+'</g></svg>'}
function pairedChart(rows){const groups=new Map();rows.forEach(r=>{let k=`${r.provider}|${r.model}`;if(!groups.has(k))groups.set(k,{});groups.get(k)[r.reasoning]=r});const pairs=[...groups.values()].filter(p=>p.on&&p.off&&p.on.metrics.mean_added_delay_seconds_all_demand!=null&&p.off.metrics.mean_added_delay_seconds_all_demand!=null);if(!pairs.length){$('paired-chart').innerHTML='<div class="chart-empty">A complete ON/OFF pair is required.</div>';return}const W=700,L=225,R=80,T=34,H=60+pairs.length*61,P=W-L-R,Z=L+P/2,max=Math.max(...pairs.map(p=>Math.abs(p.on.metrics.mean_added_delay_seconds_all_demand-p.off.metrics.mean_added_delay_seconds_all_demand)),1);let s=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Reasoning ON minus OFF mean delay and completion differences"><g font-family="Arial,sans-serif" fill="#25231e"><line x1="${Z}" y1="20" x2="${Z}" y2="${H-20}" stroke="#a39e92"/><text x="${Z}" y="12" text-anchor="middle" font-size="10">0 s</text>`;pairs.forEach((p,i)=>{const v=p.on.metrics.mean_added_delay_seconds_all_demand-p.off.metrics.mean_added_delay_seconds_all_demand,b=Math.abs(v)/max*(P/2-12),y=T+i*61,x=v<0?Z-b:Z,label=p.on.display_name,dc=p.on.metrics.completed-p.off.metrics.completed;s+=`<text x="${L-10}" y="${y+15}" text-anchor="end" font-size="11"><title>${esc(p.on.model)}</title>${esc(label)}</text><rect x="${x}" y="${y}" width="${b}" height="23" fill="${v<=0?'#216058':'#74817c'}"/><text x="${v<0?x-7:x+b+7}" y="${y+16}" text-anchor="${v<0?'end':'start'}" font-size="10">${v>0?'+':''}${fmt(v,1)} s</text><text x="${L}" y="${y+42}" font-size="10" fill="#625d53">Completion change: ${dc>0?'+':''}${fmt(dc)} arrivals · ON fallback ${fmt(p.on.fallback_percent,1)}% / OFF ${fmt(p.off.fallback_percent,1)}%${p.on.eligible&&p.off.eligible?'':' · Contains ineligible result'}</text>`});$('paired-chart').innerHTML=s+'</g></svg>'}
function history(){const h=D.best_history,valid=h.filter(p=>p.best_id);if(!valid.length){$('history-chart').innerHTML='<div class="chart-empty">No eligible completed experiment yet.</div>';return}const W=700,L=45,R=20,T=25,H=155,P=W-L-R,step=P/Math.max(h.length-1,1),max=100;let path='',lastY=null;h.forEach((p,i)=>{if(p.completion_percent==null)return;let x=L+i*step,y=T+(100-p.completion_percent)/100*(H-T-25);path+=lastY==null?`M${x} ${y}`:`H${x}V${y}`;lastY=y});let s=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Completion percentage of the best eligible configuration after each experiment"><g font-family="Arial,sans-serif" fill="#625d53">`;[0,50,100].forEach(v=>{let y=T+(100-v)/100*(H-T-25);s+=`<line x1="${L}" y1="${y}" x2="${W-R}" y2="${y}" stroke="#e2ddcf"/><text x="${L-8}" y="${y+3}" text-anchor="end" font-size="10">${v}%</text>`});s+=`<path d="${path}" stroke="#216058" stroke-width="2" fill="none"/>`;h.forEach((p,i)=>{let x=L+i*step;s+=`<text x="${x}" y="${H-5}" text-anchor="middle" font-size="10">${p.experiment}</text>`;if(p.completion_percent!=null){let y=T+(100-p.completion_percent)/100*(H-T-25);s+=`<circle cx="${x}" cy="${y}" r="3" fill="#216058"><title>Experiment ${p.experiment}: ${esc(p.best_model)} ${esc(p.reasoning)}; ${fmt(p.completion_percent,2)}%; penalized delay ${fmt(p.penalized_added_delay_seconds,1)} s</title></circle>`}});$('history-chart').innerHTML=s+'</g></svg>';$('history-table').innerHTML='<table aria-label="Best eligible experiment history"><thead><tr><th>After</th><th>Retained configuration</th><th>Completed %</th><th>Penalized delay, s</th></tr></thead><tbody>'+h.map(p=>`<tr><td>${p.experiment}</td><td>${p.best_model?esc(p.best_model)+' · '+esc(p.reasoning.toUpperCase()):'None eligible'}</td><td>${fmt(p.completion_percent,2)}</td><td>${fmt(p.penalized_added_delay_seconds,1)}</td></tr>`).join('')+'</tbody></table>'}
$('references').innerHTML=refs.length?refs.map(r=>`<tr class="reference"><td class="model-cell"><strong title="${esc(r.model)}">${esc(r.display_name)}</strong><small>Reference controller · ${esc(r.harness_version)}</small></td><td><span class="score">${metric(r,'completion_percent',2)}%</span><br><small>${fmt(r.metrics.completed)}/${fmt(r.metrics.spawned)}</small></td><td>${metric(r,'mean_added_delay_seconds_all_demand',1)}</td><td>${metric(r,'p95_added_delay_seconds_all_demand',1)}</td><td>${metric(r,'backlog')}</td><td>${metric(r,'executed_violations')}</td><td>${esc(status(r))}<br>${audit(r)}</td></tr>`).join(''):'<tr><td colspan="7" class="empty">Matched reference results are not available.</td></tr>';
$('failures').innerHTML=models.map(r=>{const u=r.usage,states=u.statuses||{},breakdown=u.failure_categories||u.failure_breakdown||r.failure_breakdown||{};return `<div class="failure-item"><strong title="${esc(r.model)}">${esc(r.display_name)} · ${esc(r.reasoning.toUpperCase())}</strong><p>${fmt(u.successful_calls)} usable / ${fmt(u.calls)} calls. ${fmt(r.metrics.fallback_decisions)} fallbacks.</p>${Object.entries(states).map(([k,v])=>`<p>${esc(k.replaceAll('_',' '))}: ${fmt(v)}</p>`).join('')}${Object.keys(u.finish_reasons||{}).length?'<p><strong>Finish reasons</strong></p>'+Object.entries(u.finish_reasons).map(([k,v])=>`<p>${esc(k)}: ${fmt(v)}</p>`).join(''):''}${Object.keys(breakdown).length?'<p><strong>Failure detail</strong></p>'+Object.entries(breakdown).map(([k,v])=>`<p>${esc(k.replaceAll('_',' '))}: ${typeof v==='number'?fmt(v):esc(v)}</p>`).join(''):''}<p>Known cost: $${fmt(u.reported_cost_usd,4)}. Cost unknown for ${fmt(u.unknown_cost_requests)} requests.</p></div>`}).join('');
const context=D.entries.filter(r=>r.kind==='context');if(context.length){$('context-section').hidden=false;$('context').innerHTML=context.map(r=>`<strong title="${esc(r.model)}">${esc(r.display_name)} · ${esc(r.date)}</strong><p>${esc(r.context_note||'Different traffic or protocol. Excluded from this leaderboard and matched charts.')} ${audit(r)}</p>`).join('')}
$('rows').addEventListener('change',e=>{const id=e.target.dataset.id;if(id){e.target.checked?selected.add(id):selected.delete(id);render()}});$('select-all').addEventListener('change',e=>{visible().forEach(r=>e.target.checked?selected.add(r.id):selected.delete(r.id));render()});['search','reasoning','status'].forEach(id=>$(id).addEventListener(id==='search'?'input':'change',render));$('compare').addEventListener('click',()=>{compare=!compare;$('compare').setAttribute('aria-pressed',String(compare));$('compare').textContent=compare?'Show all configurations':'Compare selected';render()});$('clear').addEventListener('click',()=>{selected.clear();compare=false;$('compare').setAttribute('aria-pressed','false');$('compare').textContent='Compare selected';render()});document.querySelectorAll('[data-sort]').forEach(b=>b.addEventListener('click',()=>{if(sort===b.dataset.sort)descending=!descending;else{sort=b.dataset.sort;descending=['completion_percent','usable_response_percent'].includes(sort)}render()}));render();history();
</script></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Frozen leaderboard input JSON")
    parser.add_argument("--out", type=Path, required=True, help="Output report directory")
    arguments = parser.parse_args()
    outputs = write_report(json.loads(arguments.input.read_text()), arguments.out)
    print(json.dumps(outputs, indent=2))


if __name__ == "__main__":
    main()
