"""Daily AI allowance: how many AI-assisted checks a person and a workspace may run.

Free API keys run out without warning, so AI-assisted checks are rationed. One
check run counts as one try once an AI provider has answered at least once in
it; a run whose provider calls all failed costs nothing. Out of tries, the check
still runs every rule-based checker and records why the AI part was skipped.
Limits are set by environment variable and reset at 00:00 UTC.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

DEFAULT_PER_USER = 5
DEFAULT_PER_WORKSPACE = 50


def _limit(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    if not raw.isdigit():
        raise RuntimeError(f"{name} must be a whole number of AI-assisted checks per day.")
    return int(raw)


def limits() -> Dict[str, int]:
    return {"per_user": _limit("CANONRY_AI_DAILY_PER_USER", DEFAULT_PER_USER),
            "per_workspace": _limit("CANONRY_AI_DAILY_PER_WORKSPACE", DEFAULT_PER_WORKSPACE)}


def today() -> str:
    """The current allowance day (UTC), as YYYY-MM-DD."""
    return datetime.now(timezone.utc).date().isoformat()


def _used(conn: sqlite3.Connection, ws: str, user: Optional[str]) -> int:
    sql = ("SELECT COUNT(*) FROM check_runs cr JOIN revisions r ON r.id = cr.revision_id "
           "JOIN submissions s ON s.id = r.submission_id "
           "WHERE s.workspace_id = ? AND cr.started_at >= ? AND cr.ai_calls > 0")
    args: tuple = (ws, today())
    if user is not None:
        sql += " AND cr.by_user = ?"
        args += (user,)
    return conn.execute(sql, args).fetchone()[0]


def usage(conn: sqlite3.Connection, ws: str, user: Optional[str]) -> Dict[str, Any]:
    lim = limits()
    resets = datetime.combine(date.fromisoformat(today()) + timedelta(days=1), datetime.min.time(), timezone.utc)
    return {"used": _used(conn, ws, user) if user else 0, "limit": lim["per_user"],
            "workspace_used": _used(conn, ws, None), "workspace_limit": lim["per_workspace"],
            "resets_at": resets.isoformat()}


def blocked(conn: sqlite3.Connection, ws: str, user: Optional[str]) -> Optional[str]:
    """Why this check may not use AI ("user_quota" / "workspace_quota"), or None."""
    u = usage(conn, ws, user)
    if user and u["used"] >= u["limit"]:
        return "user_quota"
    if u["workspace_used"] >= u["workspace_limit"]:
        return "workspace_quota"
    return None
