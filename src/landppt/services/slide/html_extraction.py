"""Heuristics for pulling a slide document out of a raw model response.

Kept separate from ``SlideHtmlCleanupService`` so the rules are independently
testable and the service file stays small.
"""

from __future__ import annotations

from typing import Iterable, List

# Container tags that mark real slide markup, as opposed to prose that merely
# happens to contain angle brackets.
STRUCTURAL_TAGS = (
    "html", "body", "div", "section", "main", "header", "article", "table",
)


def looks_like_markup(text: str) -> bool:
    """Whether ``text`` is plausibly slide markup rather than an AI message.

    Guards against a refusal such as ``"Sorry, I cannot do that. <br>"`` being
    saved as a slide just because it contains a tag.
    """
    lowered = (text or "").lower()
    if not lowered:
        return False
    if "<!doctype html" in lowered or "<html" in lowered:
        return True
    # A fragment counts only when a structural container both opens and closes.
    return any(
        f"<{tag}" in lowered and f"</{tag}>" in lowered for tag in STRUCTURAL_TAGS
    )


def pick_best_document(candidates: Iterable[str]) -> str:
    """Choose the most complete document among overlapping candidates.

    Repair prompts echo the ORIGINAL html in a ```html fence, so the FIRST match is
    the unrepaired input: prefer complete documents and, among those, the last one.
    Candidates contained within another are dropped, because the fence / DOCTYPE /
    ``<html>`` patterns all match the same document at different extents (and a
    fence cut short by an inner ``` is a substring of the full document).
    """
    documents: List[str] = []
    fragments: List[str] = []

    for candidate in candidates:
        candidate = (candidate or "").strip()
        if not candidate:
            continue
        lowered = candidate.lower()
        if "<!doctype html" in lowered or "<html" in lowered:
            documents.append(candidate)
        elif looks_like_markup(candidate):
            fragments.append(candidate)

    pool = [doc for doc in documents if "</html>" in doc.lower()] or documents
    if not pool:
        return fragments[-1] if fragments else ""

    maximal = [doc for doc in pool if not any(doc != other and doc in other for other in pool)]
    return (maximal or pool)[-1]
