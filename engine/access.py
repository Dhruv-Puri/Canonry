"""What each role may see. One place, so every endpoint applies the same rules.

Roles are self-chosen (no login), so the engine, not the UI, enforces them:
- confidential fact text is for reviewers and admins only;
- agency partners see only the submissions they created.
"""
from __future__ import annotations

from typing import Any, Dict

CONFIDENTIAL_PLACEHOLDER = "[Confidential — visible to reviewers and admins]"


def can_see_confidential(user) -> bool:
    return user["role"] in ("reviewer", "admin")


def can_see_submission(user, sub) -> bool:
    return user["role"] != "agency" or sub["created_by"] == user["email"]


def redact_fact(d: Dict[str, Any], user) -> Dict[str, Any]:
    """A fact (or fact snapshot) as this user may see it."""
    if d.get("confidential") and not can_see_confidential(user):
        d = {**d, "text": CONFIDENTIAL_PLACEHOLDER}
    return d
