"""Which workspace rule each built-in check enforces (rule bindings).

A built-in check never cites a rule id written into the code. It asks for the
rule bound to its key ("claims.statistic", "voice.hard_sell", ...) in the
workspace it is checking. A workspace keeps its own rule ids (the Quillmark
demo binds CLM-01, VOICE-3.2, ...); a workspace without a matching rule gets the
check's baseline rule installed, versioned like any other rule. Retiring a bound
rule switches its check off: the check finds nothing rather than producing
findings the citation check would throw away.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, Mapping, Optional

from db import _now, next_knowledge_version


@dataclass(frozen=True)
class Check:
    key: str
    baseline_id: str
    category: str
    statement: str
    severity: str
    do_example: Optional[str] = None
    dont_example: Optional[str] = None


_CHECKS = (
    Check("claims.statistic", "BASE-01", "Claims",
          "Every statistic in public content must trace to an approved fact in the Fact Library.", "high",
          "Trusted by 2,300+ teams (approved fact).", "Trusted by 5,000+ teams (no source)."),
    Check("claims.superlative", "BASE-02", "Claims",
          "Superlatives (\"#1\", \"best\", \"leading\") need an approved source behind them.", "high",
          "An analytics platform trusted by 2,300+ teams.", "The #1 analytics platform."),
    Check("claims.certification", "BASE-03", "Claims",
          "Certifications (ISO, SOC 2) may only be claimed while the certificate is current.", "high",
          "Certified to ISO 27001 (renewal filed).", "Fully ISO 27001 certified."),
    Check("voice.sentence_length", "BASE-04", "Voice",
          "Keep sentences short on average: aim under 20 words per sentence.", "low"),
    Check("voice.hard_sell", "BASE-05", "Voice",
          "Tone is confident, never pushy; no hard-sell phrases.", "medium",
          "Analytics your team can trust.", "Grab it NOW before it's gone!!"),
    Check("voice.tone", "BASE-05", "Voice",
          "Tone is confident, never pushy; no hard-sell phrases.", "medium"),
    Check("voice.exclamation", "BASE-06", "Voice",
          "At most one exclamation mark per post.", "low", "That's it.", "Amazing!! Incredible!!!"),
    Check("social.length", "BASE-07", "Social",
          "Social posts stay under 200 words.", "low"),
    Check("messaging.cta", "BASE-08", "Messaging",
          "Sales posts end with a clear call to action.", "low",
          "Start a 14-day trial.", "Great product, see you around."),
)

CHECKS: Dict[str, Check] = {c.key: c for c in _CHECKS}


def bindings(conn: sqlite3.Connection, ws: str) -> Dict[str, str]:
    return {r["check_key"]: r["rule_id"] for r in conn.execute(
        "SELECT check_key, rule_id FROM rule_bindings WHERE workspace_id = ?", (ws,)).fetchall()}


def rule_for(conn: sqlite3.Connection, ws: str, key: str) -> Optional[str]:
    """The approved rule this check cites here, or None when the check is off."""
    row = conn.execute(
        "SELECT r.id FROM rule_bindings b JOIN rules r ON r.id = b.rule_id AND r.workspace_id = b.workspace_id "
        "WHERE b.workspace_id = ? AND b.check_key = ? AND r.status = 'approved'", (ws, key)).fetchone()
    return row["id"] if row else None


def ensure_bindings(conn: sqlite3.Connection, ws: str, prefer: Optional[Mapping[str, str]] = None) -> None:
    """Bind every unbound check: to the rule named in `prefer` when the workspace
    has it, otherwise to the check's baseline rule (installed if missing).
    Idempotent; existing bindings are never changed."""
    import knowledge  # local import: knowledge imports db, which this module also needs first

    bound = bindings(conn, ws)
    installed = []
    for check in _CHECKS:
        if check.key in bound:
            continue
        rule_id = (prefer or {}).get(check.key)
        if not rule_id or not conn.execute(
                "SELECT 1 FROM rules WHERE id = ? AND workspace_id = ?", (rule_id, ws)).fetchone():
            rule_id = check.baseline_id
            if not conn.execute("SELECT 1 FROM rules WHERE id = ? AND workspace_id = ?", (rule_id, ws)).fetchone():
                conn.execute(
                    "INSERT INTO rules (id, workspace_id, version, category, statement, do_example, dont_example, "
                    "severity, status, created_at) VALUES (?,?,1,?,?,?,?,?,'approved',?)",
                    (rule_id, ws, check.category, check.statement, check.do_example, check.dont_example,
                     check.severity, _now()),
                )
                installed.append(rule_id)
        conn.execute("INSERT INTO rule_bindings (workspace_id, check_key, rule_id) VALUES (?,?,?)",
                     (ws, check.key, rule_id))
    if installed:
        kv = next_knowledge_version(conn)
        for rule_id in installed:
            knowledge.record_version(conn, ws, "rule", rule_id, 1, "baseline",
                                     "Baseline rule for a built-in check", "system", kv)
