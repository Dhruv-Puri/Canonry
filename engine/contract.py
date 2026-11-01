"""Canonry Finding Contract v2 (doc Section 9.7).

Every checker returns findings in this one shape. v2 adds a *locator* so a
finding can point at a PDF page and line, a DOCX paragraph, or an image region;
image findings keep a zero-length text span so every existing consumer still
works. `location_key` is the stable identity used for dedupe and for carrying a
decision forward across revisions.

The contract stays validated with pydantic before storage; the web mirrors the
shape in `web/src/lib/api.ts`.
"""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError

CONTRACT_VERSION = "finding@2"

Checker = Literal[
    "terminology", "readability", "claims", "tone", "confidential",
    "accessibility", "image", "compliance",
]
Tier = Literal["definite", "likely", "consider"]
Severity = Literal["high", "medium", "low"]

# category vocabulary (extensible; new checkers may add categories)
CATEGORIES = [
    "banned_term", "outdated_term", "terminology",
    "outdated_name", "contradicted_claim", "outdated_claim", "unsupported_claim",
    "readability", "missing_disclaimer", "missing_cta", "confidential_leak", "incomplete_citation",
    "tone", "messaging", "accessibility",
    # documents & images
    "logo_missing", "logo_outdated", "logo_too_small", "logo_clear_space",
    "off_brand_colour", "low_text_contrast", "missing_alt_text", "alt_text_quality",
    # India compliance pack
    "misleading_claim", "unsubstantiated_claim", "missing_disclosure",
    "bait_advertising", "surrogate_advertising", "free_claim",
    "children_directed", "comparative_advertising", "endorsement_disclosure",
]


class Span(BaseModel):
    start: int
    end: int
    text: str


class Locator(BaseModel):
    """Where a finding lives. Text findings fall back to the character span."""
    kind: Literal["text", "pdf", "docx", "image"] = "text"
    asset_id: Optional[str] = None
    page: Optional[int] = None
    line: Optional[int] = None
    paragraph: Optional[int] = None
    section: Optional[str] = None
    char_start: Optional[int] = None
    char_end: Optional[int] = None
    # image region in source pixels: (x, y, width, height)
    bbox: Optional[Tuple[int, int, int, int]] = None
    region: Optional[str] = None


class Citation(BaseModel):
    type: Literal["fact", "rule", "pack", "term"]
    id: str
    version: Optional[int] = None
    # facts may expire; rules may be superseded; citation check guards this
    active: bool = True
    excerpt: Optional[str] = None  # cited excerpt only for confidential facts
    # compliance-pack citations: the exact clause reference and source link
    ref: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None


class Suggestion(BaseModel):
    replace: Optional[str] = None
    operation: Literal["replace", "remove", "rewrite", "upload"] = "replace"


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
    citations: list[Citation] = Field(default_factory=list)
    explanation: str
    suggestion: Optional[Suggestion] = None
    # optional creator-supplied context when a finding came from a canned demo kit
    title: Optional[str] = None
    reason_if_disputed: Optional[str] = None
    status: Literal["open", "accepted", "edited", "disputed", "discarded"] = "open"
    provenance: Provenance
    locator: Optional[Locator] = None
    location_key: Optional[str] = None

    def key(self) -> str:
        if self.location_key:
            return self.location_key
        loc = self.locator
        if loc and loc.bbox:
            return f"{self.checker}|{self.category}|{loc.region or 'region'}:{','.join(map(str, loc.bbox))}"
        if loc and (loc.page or loc.paragraph):
            return f"{self.checker}|{self.category}|{loc.kind}:{loc.page or 0}:{loc.paragraph or 0}:{self.span.text}"
        return f"{self.checker}|{self.category}|{self.span.start}:{self.span.text}"


def finding_to_dict(f: Finding) -> Dict[str, Any]:
    return f.model_dump(exclude_none=False)


def location_key(finding: Dict[str, Any]) -> str:
    loc = finding.get("locator") or {}
    checker, category = finding.get("checker", ""), finding.get("category", "")
    if loc.get("bbox"):
        return f"{checker}|{category}|{loc.get('region') or 'region'}:{','.join(map(str, loc['bbox']))}"
    if loc.get("page") or loc.get("paragraph"):
        return f"{checker}|{category}|{loc.get('kind')}:{loc.get('page') or 0}:{loc.get('paragraph') or 0}:{finding.get('span', {}).get('text', '')}"
    span = finding.get("span") or {}
    return f"{checker}|{category}|{span.get('start')}:{span.get('text', '')}"


def conforms(finding: Dict[str, Any]) -> bool:
    """True when a checker's finding has the contract shape (checked before it is stored)."""
    try:
        Finding.model_validate(finding)
        return True
    except ValidationError:
        return False
