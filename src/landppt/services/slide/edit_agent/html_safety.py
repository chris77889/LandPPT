"""HTML 安全与校验原语。

这一层不关心 agent 循环，只负责回答两个问题：
1. 这段 HTML 能不能安全地写进幻灯片？
2. 清洗后的 HTML 是什么？
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

AGENT_ID_ATTRS = ("data-agent-id", "data-quick-ai-id")

_UNSAFE_CSS_MARKERS = (
    "expression(",
    "javascript:",
    "-moz-binding",
    "@import",
)
_CSS_PROPERTY_RE = re.compile(r"^-?[a-zA-Z][a-zA-Z0-9-]*$")
_CSS_URL_RE = re.compile(r"url\(\s*['\"]?([^'\")]*)", re.IGNORECASE)
_SAFE_URL_SCHEMES = ("http:", "https:", "data:image/", "/", "./", "../", "#")


@dataclass
class SlideEditValidationResult:
    valid: bool
    errors: List[str]
    warnings: List[str]
    sanitized_html: str


def compute_slide_html_hash(html: str) -> str:
    normalized = (html or "").strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def strip_agent_ids(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup.find_all(True):
        for attr in AGENT_ID_ATTRS:
            if attr in node.attrs:
                del node.attrs[attr]
    return str(soup).strip()


def _attribute_value_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value or "")


def _attribute_value_scheme_text(value: Any) -> str:
    return re.sub(r"[\x00-\x20]+", "", _attribute_value_text(value)).lower()


def _has_javascript_attribute_value(soup: BeautifulSoup) -> bool:
    for node in soup.find_all(True):
        for value in getattr(node, "attrs", {}).values():
            if "javascript:" in _attribute_value_scheme_text(value):
                return True
    return False


def _has_srcdoc_attribute(soup: BeautifulSoup) -> bool:
    return any(
        attr.lower() == "srcdoc"
        for tag in soup.find_all(True)
        for attr in getattr(tag, "attrs", {})
    )


def sanitize_slide_html(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")

    for script in soup.find_all("script"):
        script.decompose()

    for node in soup.find_all(True):
        for attr in list(getattr(node, "attrs", {}).keys()):
            attr_lower = (attr or "").lower()
            value = node.attrs.get(attr)
            if attr_lower.startswith("on"):
                del node.attrs[attr]
                continue
            if attr_lower == "srcdoc":
                del node.attrs[attr]
                continue
            if "javascript:" in _attribute_value_scheme_text(value):
                del node.attrs[attr]
                continue
            if attr_lower == "data-agent-id":
                del node.attrs[attr]

    return str(soup).strip()


class _SlideHtmlStructureParser(HTMLParser):
    _VOID_ELEMENTS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: List[str] = []
        self.errors: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag_name = tag.lower()
        if tag_name not in self._VOID_ELEMENTS:
            self.stack.append(tag_name)

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        return None

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name in self._VOID_ELEMENTS:
            return
        if not self.stack:
            self.errors.append("html is malformed")
            return
        if self.stack[-1] == tag_name:
            self.stack.pop()
            return
        self.errors.append("html is malformed")

    def close(self) -> None:
        super().close()
        if self.stack:
            self.errors.append("html is malformed")


def _find_html_structure_errors(html: str) -> List[str]:
    parser = _SlideHtmlStructureParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return ["html is malformed"]
    return list(dict.fromkeys(parser.errors))


def validate_slide_html(html: str) -> SlideEditValidationResult:
    errors: List[str] = []
    warnings: List[str] = []
    original = html or ""
    original_lower = original.lower()

    if not original.strip():
        errors.append("html content is required")
        return SlideEditValidationResult(False, errors, warnings, "")

    if "<script" in original_lower:
        errors.append("script tags are not allowed")

    original_soup = BeautifulSoup(original, "html.parser")
    if any(attr.lower().startswith("on") for tag in original_soup.find_all(True) for attr in tag.attrs):
        errors.append("inline event handlers are not allowed")

    if "javascript:" in original_lower or _has_javascript_attribute_value(original_soup):
        errors.append("javascript urls are not allowed")

    if _has_srcdoc_attribute(original_soup):
        errors.append("srcdoc attributes are not allowed")

    errors.extend(_find_html_structure_errors(original))

    sanitized = sanitize_slide_html(original)
    soup = BeautifulSoup(sanitized, "html.parser")
    if not soup.find(True):
        errors.append("html must contain at least one element")

    root_text = soup.get_text(" ", strip=True)
    has_media = bool(soup.find(["img", "svg", "canvas", "video", "picture"]))
    if not root_text and not has_media:
        warnings.append("slide has no visible text or media")

    return SlideEditValidationResult(
        valid=not errors,
        errors=list(dict.fromkeys(errors)),
        warnings=warnings,
        sanitized_html=sanitized,
    )


def is_safe_attribute(name: str, value: Any) -> bool:
    """属性级安全判断，供 set_attributes 工具使用。"""
    lowered = (name or "").strip().lower()
    if not lowered or not re.fullmatch(r"[a-zA-Z_:][-a-zA-Z0-9_:.]*", lowered):
        return False
    if lowered.startswith("on") or lowered in {"srcdoc", "data-agent-id"}:
        return False
    return "javascript:" not in _attribute_value_scheme_text(value)


def css_declaration_error(prop: str, value: str) -> Optional[str]:
    """返回不安全 CSS 声明的原因，安全则返回 None。

    这里用黑名单替代旧的属性白名单：白名单会挡掉 gap / flex /
    grid-template-columns 等大量正常排版属性，逼着模型改用整块 HTML 替换，
    反而放大了改动面。安全边界交给取值检查和最终 sanitize。
    """
    name = (prop or "").strip().lower()
    raw_value = (value or "").strip()

    if not name or not _CSS_PROPERTY_RE.fullmatch(name):
        return f"invalid css property: {prop}"
    if not raw_value:
        return f"empty css value for {name}"

    collapsed = re.sub(r"[\x00-\x20]+", "", raw_value).lower()
    for marker in _UNSAFE_CSS_MARKERS:
        if marker.replace(" ", "") in collapsed:
            return f"unsafe css value for {name}"

    for match in _CSS_URL_RE.finditer(raw_value):
        target = re.sub(r"[\x00-\x20]+", "", match.group(1)).lower()
        if target and not target.startswith(_SAFE_URL_SCHEMES):
            return f"unsafe css url in {name}"

    return None


def _split_style_declarations(style: str) -> List[str]:
    """Split on top-level ';' only.

    A plain ``style.split(";")`` cut inline ``url(data:image/svg+xml;base64,...)``
    values in half, so merging any unrelated property re-serialised the element
    with a broken background.
    """
    items: List[str] = []
    current: List[str] = []
    depth = 0
    quote: Optional[str] = None

    for char in style or "":
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            current.append(char)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == ";" and depth == 0:
            items.append("".join(current))
            current = []
            continue
        current.append(char)

    if current:
        items.append("".join(current))
    return items


def parse_style_declarations(style: str) -> Dict[str, str]:
    declarations: Dict[str, str] = {}
    for item in _split_style_declarations(style):
        if ":" not in item:
            continue
        prop, value = item.split(":", 1)
        prop = prop.strip().lower()
        value = value.strip()
        if prop and value:
            declarations[prop] = value
    return declarations


def serialize_style_declarations(declarations: Dict[str, str]) -> str:
    return "; ".join(f"{prop}: {value}" for prop, value in declarations.items())
