"""Regression tests for the AI provider layer.

The streaming think-tag filter is on the critical path for outline streaming: a
marker split across chunks used to either leak reasoning into the parsed JSON or
silently swallow the entire remainder of the response.
"""

import asyncio
import json
from pathlib import Path

import pytest

from landppt.ai.providers import OpenAIProvider

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "landppt"


class _BareProvider(OpenAIProvider):
    """Skip __init__ so no API client is constructed."""

    def __init__(self):  # noqa: D107
        pass


def _filter(chunks) -> str:
    provider = _BareProvider()

    async def source():
        for chunk in chunks:
            yield chunk

    async def drain() -> str:
        out = ""
        async for piece in provider._filter_think_chunks(source()):
            out += piece
        return out

    return asyncio.run(drain())


class TestThinkFilterAcrossChunkBoundaries:
    @pytest.mark.parametrize(
        "chunks,expected",
        [
            (["hello ", "world"], "hello world"),
            (["<think>reasoning</think>ANSWER"], "ANSWER"),
            (["Hello<think>r</think>ANSWER"], "HelloANSWER"),
            (["<think>a</think>X<think>b</think>Y"], "XY"),
            (['<think type="x">sec</think>OK'], "OK"),
            (["＜think＞sec＜/think＞OK"], "OK"),
        ],
    )
    def test_basic_cases(self, chunks, expected):
        assert _filter(chunks) == expected

    def test_split_opening_marker_does_not_leak_reasoning(self):
        """Previously the partial "<thi" was emitted and the block leaked."""
        assert _filter(["abc<thi", "nk>secret</think>ANSWER"]) == "abcANSWER"

    def test_split_closing_marker_does_not_swallow_the_answer(self):
        """Previously in_think_tag stayed true forever and ANSWER was lost."""
        assert _filter(["<think>secret</thi", "nk>ANSWER"]) == "ANSWER"

    def test_both_markers_split(self):
        assert _filter(["pre<thi", "nk>sec", "ret</thi", "nk>ANSWER"]) == "preANSWER"

    def test_character_by_character_stream(self):
        assert _filter(list("A<think>zz</think>B")) == "AB"

    def test_text_before_think_in_same_chunk_is_kept(self):
        """Previously emit was discarded whenever the chunk entered a think block."""
        assert _filter(["KEEPME<think>drop"]) == "KEEPME"

    def test_lone_less_than_is_not_treated_as_a_marker(self):
        assert _filter(["if a < b then ok"]) == "if a < b then ok"

    def test_json_payload_survives_intact(self):
        payload = '{"slides":[{"t":"a<b"}]}'
        assert _filter([f"<think>plan</think>{payload}"]) == payload
        assert json.loads(_filter([f"<think>plan</think>{payload}"]))

    def test_trailing_partial_marker_is_flushed_not_dropped(self):
        assert _filter(["answer<thi"]) == "answer<thi"

    def test_unterminated_think_block_emits_nothing_after_it(self):
        assert _filter(["visible<think>never closed"]) == "visible"


class TestPartialMarkerHelper:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("abc<thi", 4),
            ("abc<", 1),
            ("abc", 0),
            ("", 0),
        ],
    )
    def test_suffix_length(self, text, expected):
        provider = _BareProvider()
        assert (
            provider._longest_partial_marker_suffix(text, ("<think", "＜think"))
            == expected
        )


class TestAiServiceFallbackExists:
    def test_ppt_fallback_targets_a_method_that_exists(self):
        from landppt.services.ai_service import AIService

        service = AIService()
        assert hasattr(service, "_generate_outline_response")
        source = (SRC / "services" / "ai_service.py").read_text(encoding="utf-8")
        assert "_generate_guidance_response" not in source, (
            "fallback referenced a method that was never defined"
        )

    def test_fallback_produces_an_outline(self):
        from landppt.services.ai_service import AIService

        service = AIService()
        result = asyncio.run(service._generate_fallback_ppt_response("关于人工智能的PPT"))
        assert result
        assert "大纲" in result or "Outline" in result


class TestAnthropicStreamingRequest:
    def test_streaming_body_includes_max_tokens(self):
        source = (SRC / "ai" / "providers.py").read_text(encoding="utf-8")
        marker = 'url = f"{base_url}/messages"'
        assert marker in source
        body_block = source[source.index(marker) :][:900]
        assert '"max_tokens"' in body_block, (
            "the Anthropic Messages API rejects requests without max_tokens"
        )

    def test_auth_fallback_uses_continue_not_break(self):
        source = (SRC / "ai" / "providers.py").read_text(encoding="utf-8")
        marker = "for index, (auth_name, auth_header) in enumerate(auth_methods):"
        assert marker in source, "auth loop should be indexed to detect the last method"
        loop_body = source[source.index(marker) :]
        loop_body = loop_body[: loop_body.index("raise Exception(f\"All authentication")]
        # `break` inside the non-loop `async with` blocks exited the auth loop,
        # so the second method was dead code.
        assert "break  # Exit inner loop" not in loop_body
        assert "continue" in loop_body
