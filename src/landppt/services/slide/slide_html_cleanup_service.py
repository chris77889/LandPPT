import logging
import re
from typing import TYPE_CHECKING


logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from .slide_html_service import SlideHtmlService


class SlideHtmlCleanupService:
    """HTML response cleanup extracted from SlideHtmlService."""

    def __init__(self, service: "SlideHtmlService"):
        self._service = service

    def __getattr__(self, name: str):
        return getattr(self._service, name)

    def _clean_html_response(self, raw_content: str) -> str:
        """Clean and extract HTML content from AI responses."""
        # Imported here, absolutely, so this method still resolves its helpers when
        # loaded standalone from source (see the modularization tests).
        from landppt.services.slide.html_extraction import (
            looks_like_markup,
            pick_best_document,
        )

        raw_content = self._strip_think_tags(raw_content)

        if not raw_content:
            logger.warning("Received empty response from AI")
            return ""

        content = raw_content.strip()
        logger.debug("Raw AI response length: %s, preview: %s...", len(content), content[:200])
        content_lower = content.lower()

        if len(content) < 100:
            logger.warning("AI response is very short (%s chars), might be incomplete", len(content))
        has_error_indicators = any(
            error_indicator in content_lower for error_indicator in ["error", "sorry", "cannot", "unable"]
        )

        candidates = [
            match.group(1)
            for match in re.finditer(r"```(?:html|HTML)?[ \t]*\r?\n(.*?)```", content, re.DOTALL)
        ]
        candidates += [
            match.group(0)
            for match in re.finditer(r"<!DOCTYPE html.*?</html>", content, re.DOTALL | re.IGNORECASE)
        ]
        candidates += [
            match.group(0)
            for match in re.finditer(r"<html.*?</html>", content, re.DOTALL | re.IGNORECASE)
        ]

        best = pick_best_document(candidates)
        if best:
            logger.debug("Extracted HTML from %s candidate block(s)", len(candidates))
            return best

        prefixes_to_remove = [
            "这是生成的HTML代码：",
            "以下是HTML代码：",
            "HTML代码如下：",
            "生成的完整HTML页面：",
            "Here's the HTML code:",
            "The HTML code is:",
            "```html",
            "```",
        ]
        for prefix in prefixes_to_remove:
            if content.startswith(prefix):
                content = content[len(prefix):].strip()

        if content.endswith("```"):
            content = content[:-3].strip()

        # Assemble a document that never closed. Commentary lines are skipped only
        # BEFORE it starts: applying that filter inside the document deleted CSS
        # "#id {" selector lines and blank lines, corrupting the stylesheet.
        html_lines = []
        in_html = False
        for line in content.split("\n"):
            line_stripped = line.strip()
            line_lower = line_stripped.lower()

            if not in_html:
                if not line_stripped or line_stripped.startswith(("#", "//")):
                    continue
                if line_lower.startswith("<!doctype") or line_lower.startswith("<html"):
                    in_html = True
                    html_lines.append(line)
                continue

            html_lines.append(line)
            if line_lower.endswith("</html>"):
                break

        if html_lines:
            logger.debug("Found HTML using line-by-line extraction")
            return "\n".join(html_lines)

        # Last resort. Previously ANY content containing '<' and '>' was accepted,
        # so AI refusals shipped as slides.
        if looks_like_markup(content):
            logger.warning("Could not extract HTML using strict patterns, returning cleaned content")
            return content

        if has_error_indicators:
            logger.warning("AI response appears to be an error message instead of HTML")

        logger.error("Failed to extract HTML from AI response")
        return ""
