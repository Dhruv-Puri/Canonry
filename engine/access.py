"""What each role may see. One place, so every endpoint applies the same rules.

Roles are self-chosen (no login), so the engine, not the UI, enforces them:
- confidential fact text is for reviewers and admins only;
- agency partners see only the submissions they created.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

CONFIDENTIAL_PLACEHOLDER = "[Confidential — visible to reviewers and admins]"


def can_see_confidential(user) -> bool:
    return user["role"] in ("reviewer", "admin")


def can_see_submission(user, sub) -> bool:
    return user["role"] != "agency" or sub["created_by"] == user["email"]


def submission_scope(user, alias: str = "s") -> Tuple[str, Tuple[Any, ...]]:
    """SQL condition (and its parameters) limiting a query over `submissions <alias>`
    to the submissions this user may see. Every cross-submission read uses it."""
    if user["role"] == "agency":
        return f"{alias}.created_by = ?", (user["email"],)
    return "1=1", ()


def filter_visible(conn, user, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep the items (dicts carrying a submission_id) this user may see."""
    if user["role"] != "agency":
        return items
    own = {r[0] for r in conn.execute("SELECT id FROM submissions WHERE created_by = ?", (user["email"],))}
    return [i for i in items if i.get("submission_id") in own]


def redact_fact(d: Dict[str, Any], user) -> Dict[str, Any]:
    """A fact (or fact snapshot) as this user may see it."""
    if d.get("confidential") and not can_see_confidential(user):
        d = {**d, "text": CONFIDENTIAL_PLACEHOLDER}
    return d
