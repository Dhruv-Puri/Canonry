"""Submission lifecycle: which actions each status allows. One place, so every
endpoint applies the same rules.

    Draft/Checked --submit--> In review --approve--> Signed
         ^                        |
         +--- Changes requested <-+ request_changes
    (clean email digest under an exemption policy --submit--> Exempt-approved)

Content changes only while the draft is with its creator. In review, the content
the router assessed is the content the reviewer decides on; signed and
exempt-approved content is what the seal and the audit trail describe, so it is
frozen. To change approved content, start a new submission.
"""
from __future__ import annotations

from typing import Dict, Optional

WITH_CREATOR = ("Draft", "Checked", "Changes requested")
IN_REVIEW = ("In review",)

ALLOWED = {
    "edit": WITH_CREATOR,          # resolve a finding, re-check
    "submit": WITH_CREATOR,        # send for review
    "approve": IN_REVIEW,
    "request_changes": IN_REVIEW,
    "override": IN_REVIEW,
}

_WHY = {
    "In review": "it is in review; the content stays as submitted until the reviewer approves or requests changes",
    "Signed": "it is signed; approved content never changes (start a new submission instead)",
    "Exempt-approved": "it was approved under an exemption policy; approved content never changes",
    "Approved": "it is approved; approved content never changes",
}


def blocked(status: str, action: str) -> Optional[str]:
    """Why `action` is not allowed in `status`, or None when it is."""
    if status in ALLOWED.get(action, (status,)):
        return None
    if action in ("approve", "request_changes", "override"):
        return (f"Only content that is In review can be decided; this item is {status}. "
                "The creator submits it for review first.")
    return f"This item can't be changed: {_WHY.get(status, f'it is {status}')}."


def allowed(status: str) -> Dict[str, bool]:
    """Every lifecycle action and whether this status allows it (for the UI)."""
    return {action: blocked(status, action) is None for action in ALLOWED}
