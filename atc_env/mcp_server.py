"""Dependency-free MCP stdio server (newline-delimited JSON-RPC 2.0).

python -m atc_env.mcp_server --split validation
"""
from __future__ import annotations

import argparse
import json
import sys

from . import ENV_ID
from .env import SFOArrivalEnv

ORDER_SCHEMA = {"type": "object", "properties": {"order": {"type": "array", "items": {"type": "string"},
                "description": "Every pending aircraft id exactly once, in landing order."}}, "required": ["order"]}
TOOLS = [
    {"name": "list_tasks", "description": "List available tasks (frozen train/validation windows).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "reset", "description": "Start a task and return the first situation.",
     "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}},
    {"name": "get_situation", "description": "Current decision point (or final grade when done).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "check_plan", "description": "Dry-run an order through the verifier (limited checks per decision).",
     "inputSchema": ORDER_SCHEMA},
    {"name": "submit_plan", "description": "Commit an order and advance to the next decision point.",
     "inputSchema": ORDER_SCHEMA},
]


def call_tool(env, name, args):
    if name == "list_tasks":
        return env.list_tasks()
    if name == "reset":
        return env.reset(args.get("task_id"))
    if name == "get_situation":
        return env.get_situation()
    if name in ("check_plan", "submit_plan"):
        return getattr(env, name)({"order": args.get("order")})
    raise KeyError(name)


def handle(env, msg):
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:  # notification
        return None
    if method == "initialize":
        result = {"protocolVersion": (msg.get("params") or {}).get("protocolVersion", "2024-11-05"),
                  "capabilities": {"tools": {}}, "serverInfo": {"name": ENV_ID, "version": "1.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = msg.get("params") or {}
        try:
            payload = call_tool(env, params.get("name"), params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(payload)}],
                      "isError": isinstance(payload, dict) and "error" in payload}
        except KeyError:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {params.get('name')!r}"}}
        except Exception as exc:  # never crash the server
            result = {"content": [{"type": "text", "text": json.dumps({"error": f"{type(exc).__name__}: {exc}"})}], "isError": True}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--split", default="validation", choices=["train", "validation"])
    a = p.parse_args(argv)
    env = SFOArrivalEnv(splits=(a.split,))
    print(f"{ENV_ID} MCP server ready ({a.split})", file=sys.stderr, flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            reply = handle(env, json.loads(line))
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
