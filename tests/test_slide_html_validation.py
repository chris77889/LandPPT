"""Regression tests for slide HTML validation, extraction and auto-repair.

The pre-fix validator used lxml's strict (HTML 4.0) parser, which rejected modern
HTML5 slides while accepting truncated documents, and the "auto fix" step declared
success whenever the output string differed from the input.
"""

import ast
import logging
from pathlib import Path

import pytest

from landppt.services.slide.html_structure import (
    analyze_html_structure,
    describe_structure_errors,
)
from landppt.services.slide.slide_html_cleanup_service import SlideHtmlCleanupService

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "landppt"

VALID_HTML5_SLIDE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>#wrap{display:flex}</style></head>
<body>
  <header><h1>Title</h1></header>
  <main><section>
    <ul><li>first<li>second</ul>
    <svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>
    <canvas id="chart"></canvas>
    <figure><img src="a.png"><figcaption>caption</figcaption></figure>
  </section></main>
  <footer><p>note<p>second note</footer>
</body></html>"""


class TestHtml5TagsAreAccepted:
    @pytest.mark.parametrize(
        "tag",
        ["header", "main", "section", "nav", "article", "aside", "figure", "footer"],
    )
    def test_semantic_html5_tags_are_well_formed(self, tag):
        html = f"<!DOCTYPE html><html><head></head><body><{tag}>x</{tag}></body></html>"
        report = analyze_html_structure(html)
        assert report.is_well_formed, describe_structure_errors(report)

    def test_full_modern_slide_passes(self):
        report = analyze_html_structure(VALID_HTML5_SLIDE)
        assert report.is_well_formed, describe_structure_errors(report)
        assert not report.is_truncated

    def test_svg_and_canvas_pass(self):
        html = (
            '<!DOCTYPE html><html><head></head><body>'
            '<svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid"></svg>'
            '<canvas id="c"></canvas><video src="v.mp4"></video>'
            "</body></html>"
        )
        report = analyze_html_structure(html)
        assert report.is_well_formed, describe_structure_errors(report)

    def test_script_with_comparison_operator_passes(self):
        html = (
            "<!DOCTYPE html><html><head><script>if(a<b){c()}</script></head>"
            "<body><div>ok</div></body></html>"
        )
        report = analyze_html_structure(html)
        assert report.is_well_formed, describe_structure_errors(report)

    def test_implied_end_tags_pass(self):
        html = (
            "<!DOCTYPE html><html><head></head><body>"
            "<table><thead><tr><th>a<th>b</thead><tbody><tr><td>1<td>2</tbody></table>"
            "<ul><li>a<li>b</ul><p>x<p>y"
            "</body></html>"
        )
        report = analyze_html_structure(html)
        assert report.is_well_formed, describe_structure_errors(report)


class TestTruncationIsDetected:
    def test_truncated_mid_text_is_an_error(self):
        html = '<!DOCTYPE html><html><head></head><body><div class="wrap"><h1>Ti'
        report = analyze_html_structure(html)
        assert report.is_truncated
        assert not report.is_well_formed
        assert describe_structure_errors(report)

    def test_truncated_mid_tag_is_an_error(self):
        html = '<!DOCTYPE html><html><head></head><body><div><span>hi</span><div class="a'
        report = analyze_html_structure(html)
        assert report.is_truncated
        assert report.trailing_fragment

    def test_unclosed_div_is_an_error(self):
        html = "<!DOCTYPE html><html><head></head><body><div><p>hi</p></body></html>"
        report = analyze_html_structure(html)
        assert "div" in report.unclosed_tags
        assert not report.is_well_formed

    def test_stray_end_tag_is_an_error(self):
        html = "<!DOCTYPE html><html><head></head><body><div>x</div></span></body></html>"
        report = analyze_html_structure(html)
        assert "span" in report.stray_end_tags
        assert not report.is_well_formed


class TestAutoFixIsVerified:
    def test_validator_no_longer_uses_strict_lxml(self):
        source = (
            SRC / "services" / "slide" / "slide_html_inspection_service.py"
        ).read_text(encoding="utf-8")
        assert "recover=False" not in source, (
            "libxml2's strict HTML 4.0 parser rejects valid HTML5 slides"
        )

    def test_auto_fix_no_longer_reserialises_through_lxml(self):
        source = (
            SRC / "services" / "slide" / "slide_html_inspection_service.py"
        ).read_text(encoding="utf-8")
        assert "pretty_print=True" not in source, (
            "re-serialising lowercases viewBox and re-flows whitespace"
        )

    def test_recovery_revalidates_after_parser_fix(self):
        source = (
            SRC / "services" / "slide" / "slide_html_recovery_service.py"
        ).read_text(encoding="utf-8")
        marker = "parser_fixed_html = self._auto_fix_html_with_parser(html_content)"
        assert marker in source
        body = source[source.index(marker) :][:1400]
        assert "_validate_html_completeness(parser_fixed_html)" in body, (
            "a changed string is not evidence of a successful repair"
        )

    def test_layout_repair_revalidates_before_replacing_a_slide(self):
        source = (
            SRC / "services" / "slide" / "layout_repair_service.py"
        ).read_text(encoding="utf-8")
        marker = "repaired_html = self._clean_html_response(repair_content)"
        assert marker in source
        body = source[source.index(marker) :][:1600]
        assert "_validate_html_completeness(repaired_html)" in body


class TestSeverityGate:
    @staticmethod
    def _load_skip_fn():
        source = (
            SRC / "services" / "slide" / "layout_repair_service.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_should_skip_layout_repair"
            ):
                node.decorator_list = []
                namespace = {}
                module = ast.Module(body=[node], type_ignores=[])
                exec(compile(ast.fix_missing_locations(module), "<sev>", "exec"), namespace)
                return namespace["_should_skip_layout_repair"]
        raise AssertionError("_should_skip_layout_repair not found")

    @pytest.mark.parametrize(
        "report,expected_skip",
        [
            ("- severity: low\nConsider highlighting the key metric", True),
            ("- severity: low\nIncrease medium-gray contrast slightly", True),
            ("- severity: low\nMinor kerning nit", True),
            ("- severity: high\nText overflows the container", False),
            ("- severity: medium\nSpacing is tight", False),
            ("- severity: low\n- severity: high\n", False),
            ("Overall the contrast is high and text overflows", False),
            ("", False),
        ],
    )
    def test_only_structured_severity_decides(self, report, expected_skip):
        skip_fn = self._load_skip_fn()
        assert skip_fn(report) is expected_skip


class _CleanupStub(SlideHtmlCleanupService):
    def __init__(self):  # bypass the facade wiring
        pass

    def _strip_think_tags(self, value):
        return value


DOC_NEW = '<!DOCTYPE html><html><head></head><body><div class="a">NEW</div></body></html>'
DOC_OLD = '<!DOCTYPE html><html><head></head><body><div class="a">OLD</div></body></html>'


class TestHtmlExtraction:
    @pytest.fixture(autouse=True)
    def _quiet_logs(self):
        logging.disable(logging.CRITICAL)
        yield
        logging.disable(logging.NOTSET)

    @pytest.fixture
    def cleaner(self):
        return _CleanupStub()

    def test_repair_echo_picks_the_repaired_document(self, cleaner):
        """Repair prompts embed the original in a ```html fence."""
        raw = f"原始HTML:\n```html\n{DOC_OLD}\n```\n修复后:\n```html\n{DOC_NEW}\n```"
        out = cleaner._clean_html_response(raw)
        assert "NEW" in out and "OLD" not in out

    def test_trailing_snippet_does_not_win_over_full_document(self, cleaner):
        raw = (
            f"```html\n{DOC_OLD}\n```\n改后:\n```html\n{DOC_NEW}\n```\n"
            "说明:\n```html\n<div>片段</div>\n```"
        )
        out = cleaner._clean_html_response(raw)
        assert "NEW" in out and "OLD" not in out

    def test_two_plain_documents_pick_the_last(self, cleaner):
        out = cleaner._clean_html_response(f"{DOC_OLD}\n\n{DOC_NEW}")
        assert "NEW" in out and "OLD" not in out

    def test_refusal_is_rejected(self, cleaner):
        raw = "Sorry, I cannot generate this slide right now. Please try again. <br>"
        assert cleaner._clean_html_response(raw) == ""

    def test_error_prose_is_rejected(self, cleaner):
        raw = "Error: unable to process the request at this time."
        assert cleaner._clean_html_response(raw) == ""

    def test_embedded_fence_does_not_truncate_the_document(self, cleaner):
        raw = (
            "```html\n<!DOCTYPE html><html><body><pre>```\nnested\n```</pre>"
            "<div>tail</div></body></html>\n```"
        )
        out = cleaner._clean_html_response(raw)
        assert "tail" in out, "document truncated at the embedded fence"

    def test_css_id_selector_lines_survive(self, cleaner):
        raw = (
            "<!DOCTYPE html>\n<html>\n<head>\n<style>\n#container {\n"
            "display:flex;\n}\n</style>\n</head>\n<body>\n<div>x</div>"
        )
        out = cleaner._clean_html_response(raw)
        assert "#container" in out
        assert "display:flex" in out

    def test_structural_fragment_is_accepted(self, cleaner):
        raw = '<div class="slide"><h1>hi</h1></div>'
        assert cleaner._clean_html_response(raw) == raw

    def test_plain_fenced_document(self, cleaner):
        assert "NEW" in cleaner._clean_html_response(f"```html\n{DOC_NEW}\n```")
