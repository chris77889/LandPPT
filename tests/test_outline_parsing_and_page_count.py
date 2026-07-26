"""Regression tests for outline JSON parsing, page-count control and prompts."""

import ast
import asyncio
import json
import logging
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "landppt"


def _read(relative: str) -> str:
    return (SRC / relative).read_text(encoding="utf-8")


def _load_class_helpers(relative: str, wanted: set, extra_globals=None):
    """Exec the static/class methods of a service class in isolation."""
    source = _read(relative)
    tree = ast.parse(source)
    class_node = next(node for node in tree.body if isinstance(node, ast.ClassDef))

    body = [m for m in class_node.body if isinstance(m, ast.Assign)]
    for member in class_node.body:
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if wanted and member.name not in wanted:
                continue
            decorators = {d.id for d in member.decorator_list if isinstance(d, ast.Name)}
            if wanted or decorators & {"staticmethod", "classmethod"}:
                body.append(member)

    holder = ast.ClassDef(name="Holder", bases=[], keywords=[], body=body, decorator_list=[])
    module = ast.Module(
        body=[
            ast.Import(names=[ast.alias(name="re", asname=None)]),
            ast.Import(names=[ast.alias(name="json", asname=None)]),
            ast.ImportFrom(
                module="typing",
                names=[ast.alias(name=n, asname=None) for n in ("Any", "Dict", "List", "Optional")],
                level=0,
            ),
            holder,
        ],
        type_ignores=[],
    )
    namespace = {"logger": logging.getLogger("test")}
    if extra_globals:
        namespace.update(extra_globals)
    exec(compile(ast.fix_missing_locations(module), f"<{relative}>", "exec"), namespace)
    return namespace["Holder"]


OUTLINE_JSON = (
    '{"title":"三体解析","slides":[{"page_number":1,"title":"封面",'
    '"content_points":["主题"]}]}'
)


class TestJsonCandidateSelection:
    @pytest.fixture(scope="class")
    def parser(self):
        return _load_class_helpers(
            "services/outline/project_outline_normalization_service.py", set()
        )

    def test_citation_marker_does_not_hijack_parsing(self, parser):
        """`[1]` parses as valid JSON, so first-block extraction returned it."""
        text = f"根据检索[1]，大纲如下：\n```json\n{OUTLINE_JSON}\n```"
        parsed = parser._parse_json_like_outline(text)
        assert isinstance(parsed, dict)
        assert parsed["title"] == "三体解析"
        assert len(parsed["slides"]) == 1

    def test_citation_marker_before_raw_json(self, parser):
        parsed = parser._parse_json_like_outline(f"参考[1][2]。{OUTLINE_JSON}")
        assert isinstance(parsed, dict) and "slides" in parsed

    def test_prose_around_outline(self, parser):
        parsed = parser._parse_json_like_outline(
            f"好的，我来生成。\n\n{OUTLINE_JSON}\n\n以上就是大纲。"
        )
        assert isinstance(parsed, dict) and parsed["title"] == "三体解析"

    def test_deeply_nested_chart_config_survives(self, parser):
        text = (
            '{"title":"X","slides":[{"page_number":1,"title":"a",'
            '"chart_config":{"type":"bar","opts":{"deep":{"x":1}}}}]}'
        )
        parsed = parser._parse_json_like_outline(text)
        assert parsed["slides"][0]["chart_config"]["opts"]["deep"]["x"] == 1

    def test_prefers_outline_shaped_object(self, parser):
        text = '{"note":"meta"}\n' + OUTLINE_JSON
        parsed = parser._parse_json_like_outline(text)
        assert "slides" in parsed

    def test_page_count_service_uses_shared_parser(self):
        source = _read("services/outline/project_outline_page_count_service.py")
        assert "_parse_json_like_outline(content)" in source
        # The depth-limited regex could not match an outline with 3+ nesting levels.
        assert "\\\\{[^{}]*(?:\\\\{[^{}]*\\\\}[^{}]*)*\\\\}" not in source
        assert "[^{}]*(?:" not in source


class TestSlideTypeClassification:
    @pytest.fixture(scope="class")
    def normalizer(self):
        return _load_class_helpers(
            "services/outline/project_outline_normalization_service.py",
            {"_normalize_slide_type", "_title_matches_keywords", "_position_allows_slide_type"},
        )

    @pytest.mark.parametrize(
        "title,page,total,expected",
        [
            ("QA体系与测试流程", 5, 12, "content"),
            ("Test Coverage Report", 6, 12, "content"),
            ("API Outline", 7, 12, "content"),
            ("Quality Assurance", 4, 12, "content"),
            ("封面", 1, 12, "title"),
            ("目录", 2, 12, "agenda"),
            ("谢谢观看", 12, 12, "thankyou"),
            ("Thank You", 12, 12, "thankyou"),
            ("总结与展望", 11, 12, "conclusion"),
            ("章节过渡", 5, 12, "transition"),
            ("普通内容页", 5, 12, "content"),
        ],
    )
    def test_classification(self, normalizer, title, page, total, expected):
        assert normalizer._normalize_slide_type(None, title, page, total) == expected

    def test_explicit_type_always_wins(self, normalizer):
        assert normalizer._normalize_slide_type("thankyou", "任意标题", 5, 12) == "thankyou"

    def test_word_boundary_matching(self, normalizer):
        assert normalizer._title_matches_keywords("test coverage", ("cover",)) is False
        assert normalizer._title_matches_keywords("cover page", ("cover",)) is True
        assert normalizer._title_matches_keywords("qa体系", ("qa",)) is False


class TestPageCountEnforcement:
    @pytest.fixture(scope="class")
    def service(self):
        holder = _load_class_helpers(
            "services/outline/project_outline_page_count_service.py",
            {"_condense_outline", "_force_page_count"},
        )
        return holder()

    @staticmethod
    def _outline(titles: int, contents: int, closings: int):
        slides = [{"slide_type": "title", "title": f"T{i}"} for i in range(titles)]
        slides += [{"slide_type": "content", "title": f"C{i}"} for i in range(contents)]
        slides += [{"slide_type": "thankyou", "title": f"E{i}"} for i in range(closings)]
        return {"slides": slides}

    @pytest.mark.parametrize(
        "titles,contents,closings,target",
        [(1, 8, 2, 4), (1, 8, 2, 2), (1, 8, 2, 3), (1, 0, 1, 2)],
    )
    def test_condense_reaches_target(self, service, titles, contents, closings, target):
        outline = self._outline(titles, contents, closings)
        result = asyncio.run(service._condense_outline(outline, target))
        assert len(result["slides"]) == target

    @pytest.mark.parametrize(
        "titles,contents,closings,target",
        [(1, 8, 2, 2), (1, 8, 2, 1), (1, 1, 1, 5), (1, 0, 1, 3), (1, 10, 1, 10)],
    )
    def test_force_hits_exact_target(self, service, titles, contents, closings, target):
        outline = self._outline(titles, contents, closings)
        result = asyncio.run(service._force_page_count(outline, target, {"topic": "X"}))
        assert len(result["slides"]) == target

    def test_page_numbers_are_renumbered(self, service):
        outline = self._outline(1, 8, 2)
        result = asyncio.run(service._force_page_count(outline, 5, {"topic": "X"}))
        numbers = [slide["page_number"] for slide in result["slides"]]
        assert numbers == [1, 2, 3, 4, 5]


class TestFixedPageCountMode:
    def test_fixed_mode_gets_its_own_branch(self):
        source = _read("services/outline/project_outline_page_count_service.py")
        assert "elif page_count_mode == 'fixed':" in source
        # Scope to the fixed branch only: the following else branch legitimately
        # contains the "let the model decide" wording.
        tail = source[source.index("elif page_count_mode == 'fixed':") :]
        body = tail[: tail.index("            else:")]
        assert "恰好" in body, "fixed mode must demand an exact page count"
        assert "'mode': 'fixed'" in body
        assert "自主决定" not in body

    def test_fixed_mode_is_enforced_after_generation(self):
        source = _read("services/outline/project_outline_page_count_service.py")
        assert "expected_page_count['mode'] in ('range', 'fixed')" in source

    def test_user_settings_are_not_overwritten_with_ai_decide(self):
        source = _read("services/outline/project_outline_page_count_service.py")
        assert (
            "outline_data['metadata']['page_count_settings'] = dict(page_count_settings)"
            in source
        )
        assert "outline_data['metadata']['resolved_page_count'] = expected_page_count" in source


class TestNonePageBoundsDoNotCrash:
    def test_validation_treats_none_bounds_as_defaults(self):
        source = _read("services/outline/project_outline_repair_service.py")
        assert "page_count_settings.get('min_pages') or 8" in source
        assert "page_count_settings.get('max_pages') or 15" in source
        assert "page_count_settings.get('fixed_pages') or 10" in source
        assert "get('min_pages', 8)" not in source

    def test_repair_prompt_handles_none_bounds(self):
        source = _read("services/prompts/repair_prompts.py")
        assert "page_count_settings.get('min_pages') or 8" in source


class TestRepairPromptUsesRealJson:
    def test_outline_is_json_serialised(self):
        source = _read("services/prompts/repair_prompts.py")
        assert "json.dumps(outline_data, ensure_ascii=False, indent=2)" in source
        assert "{outline_json}" in source
        assert "\n{outline_data}\n" not in source

    def test_generated_prompt_contains_valid_json(self):
        from landppt.services.prompts.repair_prompts import RepairPrompts

        outline = {
            "title": "测试",
            "slides": [{"page_number": 1, "title": "封面", "ok": True, "note": None}],
        }
        prompt = RepairPrompts.get_repair_prompt(outline, ["页数不足"], {"topic": "测试"})
        block = re.search(r"原始JSON数据：\s*```json\s*(.*?)```", prompt, re.DOTALL)
        assert block, "json block missing from prompt"
        # Must be parseable JSON, not a Python repr with True/None/single quotes.
        parsed = json.loads(block.group(1))
        assert parsed["slides"][0]["ok"] is True
        assert "'title'" not in block.group(1)
        assert "None" not in block.group(1)


class TestStreamingPromptRespectsLanguage:
    def test_prompt_accepts_a_language_parameter(self):
        from landppt.services.prompts.outline_prompts import OutlinePrompts

        prompt = OutlinePrompts.get_streaming_outline_prompt(
            topic="AI", target_audience="devs", ppt_style="general",
            page_count_instruction="", research_section="", language="en",
        )
        assert "English" in prompt

    def test_default_is_chinese(self):
        from landppt.services.prompts.outline_prompts import OutlinePrompts

        prompt = OutlinePrompts.get_streaming_outline_prompt(
            topic="AI", target_audience="devs", ppt_style="general",
            page_count_instruction="", research_section="",
        )
        assert "中文" in prompt

    def test_unknown_code_is_passed_through(self):
        from landppt.services.prompts.outline_prompts import OutlinePrompts

        prompt = OutlinePrompts.get_streaming_outline_prompt(
            topic="AI", target_audience="devs", ppt_style="general",
            page_count_instruction="", research_section="", language="ja",
        )
        assert "日本語" in prompt

    def test_call_site_passes_the_project_language(self):
        source = _read("services/outline/project_outline_streaming_service.py")
        assert "outline_language" in source
        assert "language=outline_language" in source


class TestHeadingParser:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2.1 Web 2.0 架构演进", "Web 2.0 架构演进"),
            ("## 第三章 总结", "第三章 总结"),
            ("4.2.1 性能优化", "性能优化"),
            ("7. 附录", "附录"),
            ("1. 引言", "引言"),
        ],
    )
    def test_clean_heading_preserves_inline_numbers(self, raw, expected):
        from landppt.services.outline.outline_workflow_support import _clean_heading_text

        assert _clean_heading_text(raw) == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("# 标题", True),
            ("2.1 架构", True),
            ("简短标题", True),
            ("- 这是一个要点", False),
            ("* item", False),
            ("• bullet point", False),
            ("这是一句完整的话。", False),
            ("A very long line that goes on and on and should not be a heading", False),
            ("", False),
        ],
    )
    def test_heading_detection(self, raw, expected):
        from landppt.services.outline.outline_workflow_support import _looks_like_heading

        assert _looks_like_heading(raw) is expected

    def test_bullet_document_does_not_explode_into_sections(self):
        from landppt.services.outline.outline_workflow_support import (
            create_outline_from_file_content,
        )
        from types import SimpleNamespace

        content = "# 项目概述\n- 要点一\n- 要点二\n- 要点三\n# 实施方案\n- 步骤一\n- 步骤二\n"
        outline = create_outline_from_file_content(
            content, SimpleNamespace(topic="测试", language="zh")
        )
        # Two headings -> a title page, agenda and two content sections, not one
        # pseudo-section per bullet.
        assert len(outline["slides"]) <= 5
