"""Canonry Finding Contract v1 (doc Section 9.7).

Every checker, now and in future, returns findings in this one shape.
It is the contract between the analysis engine and the web app, defined
first and versioned, so the two services can be built in parallel and new
checkers plug in without UI changes. Validated with JSON Schema on both sides
(server side here via pydantic; web side via data-contract.ts).
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

CONTRACT_VERSION = "finding@1"

Checker = Literal["terminology", "readability", "claims", "tone", "confidential", "accessibility", "image"]
Tier = Literal["definite", "likely", "consider"]
Severity = Literal["high", "medium", "low"]

# category vocabulary (extensible; new checkers may add categories)
CATEGORIES = [
    "banned_term", "outdated_term", "terminology",
    "outdated_name", "contradicted_claim", "outdated_claim", "unsupported_claim",
    "readability", "missing_disclaimer", "missing_cta", "confidential_leak", "incomplete_citation",
    "tone", "messaging", "accessibility",
]


class Span(BaseModel):
    start: int
    end: int
    text: str


class Citation(BaseModel):
    type: Literal["fact", "rule", "pack", "term"]
    id: str
    version: Optional[int] = None
    # facts may expire; rules may be superseded; citation check guards this
    active: bool = True
    excerpt: Optional[str] = None  # cited excerpt only for confidential facts


class Suggestion(BaseModel):
    replace: Optional[str] = None
    operation: Literal["replace", "remove", "rewrite"] = "replace"


class Provenance(BaseModel):
    model: Optional[str] = None
    prompt_version: str
    knowledge_version: int


class Finding(BaseModel):
    id: str
    revision_id: str
    checker: Checker
    category: str
    span: Span
    tier: Tier
    severity: Severity
    citations: List[Citation] = Field(default_factory=list)
    explanation: str
    suggestion: Optional[Suggestion] = None
    # optional creator-supplied context when a finding came from a canned demo kit
    title: Optional[str] = None
    reason_if_disputed: Optional[str] = None
    status: Literal["open", "accepted", "edited", "disputed", "discarded"] = "open"
    provenance: Provenance


def finding_to_dict(f: Finding) -> Dict[str, Any]:
    return f.model_dump(exclude_none=False)


def conforms(finding: Dict[str, Any]) -> bool:
    """True when a checker's finding has the contract shape (checked before it is stored)."""
    try:
        Finding.model_validate(finding)
        return True
    except ValidationError:
        return False
