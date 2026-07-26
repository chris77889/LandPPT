"""HTML5-aware structural checks for generated slides.

The previous implementation validated slides with ``lxml.etree.HTMLParser(recover=False)``.
libxml2 only knows HTML 4.0, so it rejected ``<header>``, ``<section>``, ``<svg>``,
``<canvas>`` and friends — i.e. nearly every slide the generation prompts ask for —
while happily accepting documents truncated mid-sentence. This module inverts that:
unknown-but-well-formed tags are fine, and truncation is an error.

Built on ``html.parser`` from the stdlib, so it has no tag whitelist and validation
behaves identically whether or not the optional native parsers are installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import List, Optional, Set

# Elements that never have an end tag.
VOID_ELEMENTS: Set[str] = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

# Elements whose end tag may be omitted per the HTML5 spec, so an unclosed one
# at EOF is not evidence of truncation.
OPTIONAL_END_TAG_ELEMENTS: Set[str] = {
    "body", "colgroup", "dd", "dt", "head", "html", "li", "optgroup",
    "option", "p", "rp", "rt", "tbody", "td", "tfoot", "th", "thead", "tr",
}

# Start tags that implicitly close a currently-open element of the same or a
# related type (the subset that actually shows up in slide markup).
IMPLIED_CLOSE_RULES = {
    "li": {"li"},
    "dt": {"dt", "dd"},
    "dd": {"dt", "dd"},
    "option": {"option"},
    "optgroup": {"option", "optgroup"},
    "tr": {"td", "th", "tr"},
    "td": {"td", "th"},
    "th": {"td", "th"},
    "thead": {"td", "th", "tr"},
    "tbody": {"td", "th", "tr", "thead"},
    "tfoot": {"td", "th", "tr", "thead", "tbody"},
    "p": {"p"},
}

# A <p> is closed implicitly by any of these block-level start tags.
P_CLOSING_BLOCKS: Set[str] = {
    "address", "article", "aside", "blockquote", "details", "div", "dl",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hgroup", "hr", "main", "menu", "nav", "ol",
    "p", "pre", "section", "table", "ul",
}


@dataclass
class HtmlStructureReport:
    """Outcome of a structural pass over a slide document."""

    unclosed_tags: List[str] = field(default_factory=list)
    stray_end_tags: List[str] = field(default_factory=list)
    saw_html_start: bool = False
    saw_html_end: bool = False
    saw_body_start: bool = False
    saw_body_end: bool = False
    parse_error: Optional[str] = None
    trailing_fragment: Optional[str] = None

    @property
    def is_truncated(self) -> bool:
        """True when the document stops before its structure is complete."""
        if self.trailing_fragment:
            return True
        if self.saw_html_start and not self.saw_html_end:
            return True
        if self.saw_body_start and not (self.saw_body_end or self.saw_html_end):
            return True
        return bool(self.unclosed_tags)

    @property
    def is_well_formed(self) -> bool:
        return (
            not self.unclosed_tags
            and not self.stray_end_tags
            and self.parse_error is None
            and not self.trailing_fragment
        )


class _StructureParser(HTMLParser):
    def __init__(self) -> None:
        # convert_charrefs=False keeps entity text intact; we only care about tags.
        super().__init__(convert_charrefs=False)
        self.stack: List[str] = []
        self.report = HtmlStructureReport()

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: D102
        tag = tag.lower()
        if tag == "html":
            self.report.saw_html_start = True
        elif tag == "body":
            self.report.saw_body_start = True

        if tag in VOID_ELEMENTS:
            return

        self._apply_implied_closes(tag)
        self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs) -> None:  # noqa: D102
        # Explicit self-closing form (<br/>, <svg .../>): nothing to track.
        return

    def handle_endtag(self, tag: str) -> None:  # noqa: D102
        tag = tag.lower()
        if tag == "html":
            self.report.saw_html_end = True
        elif tag == "body":
            self.report.saw_body_end = True

        if tag in VOID_ELEMENTS:
            return

        if tag not in self.stack:
            # A stray end tag for an optional-end-tag element is harmless noise.
            if tag not in OPTIONAL_END_TAG_ELEMENTS:
                self.report.stray_end_tags.append(tag)
            return

        # Pop down to the matching open tag. Anything above it was left unclosed;
        # that is only a defect for elements whose end tag is mandatory.
        while self.stack:
            open_tag = self.stack.pop()
            if open_tag == tag:
                break
            if open_tag not in OPTIONAL_END_TAG_ELEMENTS:
                self.report.unclosed_tags.append(open_tag)

    def _apply_implied_closes(self, tag: str) -> None:
        closes = set(IMPLIED_CLOSE_RULES.get(tag, ()))
        if tag in P_CLOSING_BLOCKS:
            closes.add("p")
        if not closes:
            return
        while self.stack and self.stack[-1] in closes:
            self.stack.pop()

    def finish(self) -> HtmlStructureReport:
        # Whatever remains open at EOF and needs an end tag indicates truncation.
        for open_tag in reversed(self.stack):
            if open_tag not in OPTIONAL_END_TAG_ELEMENTS:
                self.report.unclosed_tags.append(open_tag)
        self.stack.clear()
        return self.report


def _trailing_fragment(html_content: str) -> Optional[str]:
    """Detect a document that ends inside an unterminated tag."""
    last_open = html_content.rfind("<")
    if last_open == -1:
        return None
    if ">" in html_content[last_open:]:
        return None
    fragment = html_content[last_open:].strip()
    return fragment[:60] if fragment else None


def analyze_html_structure(html_content: str) -> HtmlStructureReport:
    """Structurally inspect a slide document without rejecting HTML5 tags."""
    parser = _StructureParser()
    parser.report.trailing_fragment = _trailing_fragment(html_content or "")
    try:
        parser.feed(html_content or "")
        parser.close()
    except Exception as exc:  # pragma: no cover - html.parser is very tolerant
        parser.report.parse_error = str(exc)
    return parser.finish()


def describe_structure_errors(report: HtmlStructureReport) -> List[str]:
    """Human-readable error strings for a report, empty when the HTML is sound."""
    errors: List[str] = []

    if report.parse_error:
        errors.append(f"HTML解析失败: {report.parse_error}")

    if report.trailing_fragment:
        errors.append(f"HTML在标签中间被截断: ...{report.trailing_fragment}")

    if report.unclosed_tags:
        # De-duplicate while keeping order so the message stays short.
        seen: List[str] = []
        for tag in report.unclosed_tags:
            if tag not in seen:
                seen.append(tag)
        errors.append(f"存在未闭合的标签: {', '.join(f'<{tag}>' for tag in seen)}")

    if report.stray_end_tags:
        seen_end: List[str] = []
        for tag in report.stray_end_tags:
            if tag not in seen_end:
                seen_end.append(tag)
        errors.append(
            f"存在多余的结束标签: {', '.join(f'</{tag}>' for tag in seen_end)}"
        )

    if report.saw_html_start and not report.saw_html_end and not report.trailing_fragment:
        errors.append("HTML文档不完整：缺少 </html> 结束标签")

    return errors
