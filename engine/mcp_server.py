"""Canon Connector (doc Section 5.4 'prevent') — an MCP (Model Context Protocol)
server so the AI tools creators already use can read the brand's approved facts
instead of inventing claims. Transport: stdio, JSON-RPC 2.0 (MCP wire format).
Agency users never receive confidential facts.

Wire-compatible with MCP Inspector (upgrade path: official MCP SDKs; doc 9.8).
Run: python engine/mcp_canon.py  (stdio)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from typing import Any, Dict

import claims
from db import connect, get_knowledge_version
from seed import seed

PROTOCOL_VERSION = "2024-11-05"


def tool_defs() -> Dict[str, Any]:
    return {
        "tools": [
            {
                "name": "look_up_fact",
                "description": "Look up an approved fact for the brand (e.g. pricing, customer count, certification status). Returns the fact text plus validity. Agency users never receive confidential facts.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "topic to look up"},
                        "include_confidential": {"type": "boolean", "default": False},
                        "as_source": {"type": "string", "enum": ["in-house", "agency", "ai-assisted"], "description": "caller role; agency never sees confidential"},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "check_claim",
                "description": "Check a draft claim against the brand's approved facts BEFORE publishing. Returns supported / contradicted / outdated / unsupported with the fact id behind it.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "as_source": {"type": "string", "enum": ["in-house", "agency", "ai-assisted"]},
                    },
                    "required": ["claim"],
                },
            },
            {
                "name": "get_channel_rules",
                "description": "Get the approved rules for a channel (blog, social, email, web, sales) so a draft starts on-brand.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "channel": {"type": "string", "enum": ["blog", "social", "email", "web", "sales"]},
                        "max_items": {"type": "integer", "default": 10},
                    },
                    "required": ["channel"],
                },
            },
        ]
    }


def look_up_fact(conn: sqlite3.Connection, args: Dict[str, Any], ws: str) -> str:
    query = args["query"]
    as_source = args.get("as_source", "in-house")
    include_conf = bool(args.get("include_confidential")) and as_source != "agency"
    facts = claims.visible_facts(conn, ws, include_conf)
    hits = claims.retrieve_facts(query, facts, limit=5)
    if not hits:
        return json.dumps({"results": [], "note": "No approved fact matches. Do not invent a figure — ask the brand owner to add one."})
    out = [
        {"id": f["id"], "text": f["text"], "valid_from": f["valid_from"],
         "valid_to": f["valid_to"], "confidential": bool(f["confidential"])}
        for f in hits
    ]
    return json.dumps({"results": out})


def check_claim(conn: sqlite3.Connection, args: Dict[str, Any], ws: str) -> str:
    snippet = args["claim"]
    as_source = args.get("as_source", "in-house")
    facts = claims.visible_facts(conn, ws, as_source != "agency")
    kind = "superlative" if any(p.search(snippet) for p in [
        __import__("re").compile(r"#\d+", re.I)]) else "count"
    retrieved = claims.retrieve_facts(snippet, facts)
    v = claims.classify_match(kind, snippet, retrieved)
    if v["verdict"] is None:
        if kind == "superlative":
            v = claims.superlative_verdict(snippet, retrieved)
        else:
            v = {"verdict": "unsupported", "fact_ids": [], "explanation": "No approved fact supports this claim.", "suggestion": None}
    v["as_source"] = as_source
    v["note"] = "Pre-check only; publish flow still requires approval through Canonry."
    return json.dumps(v)


def get_channel_rules(conn: sqlite3.Connection, args: Dict[str, Any], ws: str) -> str:
    channel = args["channel"].lower()
    channel_rule_ids = {
        "social": ("TERM-", "CLM-", "VOICE-", "SOC-", "CMP-"),
        "blog": ("TERM-", "CLM-", "VOICE-", "FMT-", "ACC-"),
        "email": ("TERM-", "CLM-", "VOICE-", "FMT-", "MSG-"),
        "web": ("TERM-", "CLM-", "FMT-", "PAGE-"),
        "sales": ("TERM-", "CLM-", "VOICE-", "MSG-"),
    }
    prefixes = channel_rule_ids.get(channel, ("TERM-", "CLM-", "VOICE-"))
    rows = conn.execute(
        "SELECT id, statement FROM rules WHERE workspace_id=? AND status='approved' ORDER BY id",
        (ws,),
    ).fetchall()
    picked = [r for r in rows if r["id"].startswith(prefixes)]
    limit = int(args.get("max_items", 10))
    return json.dumps({"channel": channel, "rules": [{"id": r["id"], "statement": r["statement"]} for r in picked[:limit]]})


def handle(conn: sqlite3.Connection, ws: str, msg: Dict[str, Any]) -> Dict[str, Any]:
    method = msg.get("method", "")
    mid = msg.get("id")
    resp: Dict[str, Any] = {"jsonrpc": "2.0", "id": mid}
    if method == "initialize":
        resp["result"] = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "canon-connector", "version": "1.0.0", "title": "Canon Connector"},
        }
    elif method == "tools/list":
        resp["result"] = tool_defs()
    elif method == "tools/call":
        name = msg["params"]["name"]
        args = msg["params"].get("arguments", {})
        try:
            if name == "look_up_fact":
                content = look_up_fact(conn, args, ws)
            elif name == "check_claim":
                content = check_claim(conn, args, ws)
            elif name == "get_channel_rules":
                content = get_channel_rules(conn, args, ws)
            else:
                raise ValueError(f"Unknown tool {name}")
            resp["result"] = {"content": [{"type": "text", "text": content}], "isError": False}
        except Exception as e:  # never crash the pipe; report to caller
            resp["result"] = {"content": [{"type": "text", "text": json.dumps({"error": str(e)})}], "isError": True}
    else:
        resp["error"] = {"code": -32601, "message": "Method not found"}
        return resp
    return resp


def main() -> None:
    seed()
    conn = connect()
    row = conn.execute("SELECT id FROM workspaces LIMIT 1").fetchone()
    ws = row["id"]
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if msg.get("method") == "ping":
            print(json.dumps({"jsonrpc": "2.0", "id": msg.get("id"), "result": {}}), flush=True)
            continue
        print(json.dumps(handle(conn, ws, msg)), flush=True)


if __name__ == "__main__":
    main()
