"""Regression tests for the todo-board generation UI.

Static assertions over the template JS: these guard behaviours that were broken
(zombie polling, uncancellable concurrent streams, stale-outline "recovery",
permanent loading skeletons) and have no Python-side surface to test.
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TODO_BOARD_JS = (
    REPO
    / "src" / "landppt" / "web" / "templates" / "components" / "project"
    / "todo_board" / "extra_js_1.html"
)


@pytest.fixture(scope="module")
def js() -> str:
    return TODO_BOARD_JS.read_text(encoding="utf-8")


def _slice(source: str, marker: str, length: int = 1500) -> str:
    assert marker in source, f"marker not found: {marker}"
    return source[source.index(marker) :][:length]


class TestFileIntegrity:
    def test_no_control_characters(self, js):
        """A stray NUL would make the template unparseable as text."""
        assert "\x00" not in js
        for char in js:
            if ord(char) < 32 and char not in "\t\n\r":
                pytest.fail(f"unexpected control character {ord(char)!r}")


class TestZombiePollingIsGone:
    def test_no_unconditional_three_second_interval(self, js):
        assert "}, 3000); // Update every 3 seconds" not in js

    def test_poll_is_self_scheduling_and_stoppable(self, js):
        assert "function scheduleStageSync(" in js
        assert "function stopStageSync(" in js
        assert "clearTimeout(stageSyncTimer)" in js

    def test_poll_backs_off_on_error(self, js):
        body = _slice(js, "async function runStageSync(")
        assert "stageSyncBackoffMs" in body
        assert "STAGE_SYNC_MAX_BACKOFF_MS" in js

    def test_poll_pauses_while_hidden_and_stops_on_unload(self, js):
        assert "if (document.hidden)" in _slice(js, "async function runStageSync(")
        assert "window.addEventListener('pagehide', stopStageSync)" in js

    def test_poll_no_longer_targets_absent_dom_nodes(self, js):
        body = _slice(js, "async function runStageSync(", 2500)
        for absent in (
            ".overall-progress-bar",
            "[data-stage-id=",
            "connection-error",
            ".stage-status-icon",
        ):
            assert absent not in body, f"{absent} does not exist on this page"

    def test_poll_interval_is_no_longer_aggressive(self, js):
        match = re.search(r"const STAGE_SYNC_INTERVAL_MS = (\d+);", js)
        assert match
        assert int(match.group(1)) >= 10000


class TestStreamCancellation:
    def test_abort_controller_is_used(self, js):
        assert "new AbortController()" in js
        assert "signal: streamAbortController.signal" in js

    def test_new_run_aborts_the_previous_stream(self, js):
        assert "abortActiveOutlineStream('superseded by a new generation')" in js
        helper = _slice(js, "function abortActiveOutlineStream(")
        assert ".cancel(reason)" in helper
        assert ".abort(reason)" in helper

    def test_page_unload_aborts_the_stream(self, js):
        assert "window.addEventListener('pagehide', () => abortActiveOutlineStream(" in js

    def test_abort_is_not_treated_as_a_disconnect(self, js):
        assert "function isOutlineStreamAbortError(" in js
        body = _slice(js, "if (isOutlineStreamAbortError(error))")
        assert "return" in body
        # Must be checked BEFORE the disconnect classification.
        assert js.index("isOutlineStreamAbortError(error)") < js.index(
            "const isNetworkDisconnect = isOutlineStreamNetworkDisconnect(error)"
        )

    def test_handles_are_released_in_finally(self, js):
        assert "if (activeOutlineStreamController === streamAbortController)" in js


class TestDoubleSubmitGuards:
    def test_regenerate_has_an_in_flight_guard(self, js):
        body = _slice(js, "async function regenerateOutlineNew()")
        assert "if (outlineGenerationStarted)" in body
        assert "return" in body

    def test_json_view_does_not_expose_regenerate_mid_stream(self, js):
        body = _slice(js, "if (view === 'json')")
        assert "if (!outlineGenerationStarted)" in body
        # The un-dim and the button reveal must both sit inside that guard.
        guard_at = body.index("if (!outlineGenerationStarted)")
        assert body.index("toggleOutlineViewDuringRegeneration(false)") > guard_at
        assert body.index("actionsDiv.style.display = 'block'") > guard_at


class TestDisconnectRecoveryFreshness:
    def test_recovery_requires_a_fresh_outline(self, js):
        assert "requireFresh: true" in js
        assert "function isOutlineFresherThanRunStart(" in js
        assert "function computeOutlineSignature(" in js

    def test_signature_is_captured_when_a_run_starts(self, js):
        assert "outlineSignatureAtGenerationStart = computeOutlineSignature(" in js

    def test_fetch_helper_honours_the_flag(self, js):
        body = _slice(js, "async function fetchPersistedProjectOutline(")
        assert "requireFresh" in body
        assert "isOutlineFresherThanRunStart(outline)" in body


class TestStuckSkeletonIsFixed:
    def test_hydrate_handles_no_outline_and_no_resume(self, js):
        body = _slice(js, "function hydrateOutlineSectionFromProjectState()", 2200)
        assert "if (!shouldResumeOutlineGenerationOnLoad())" in body
        assert "setOutlineLoadingState(false)" in body
        assert "showOutlineGenerationError(" in body

    def test_failed_stage_gets_a_specific_message(self, js):
        body = _slice(js, "function hydrateOutlineSectionFromProjectState()", 2200)
        assert "initialOutlineStageStatus === 'failed'" in body


class TestDoneWithoutOutlineIsAFailure:
    def test_start_button_is_not_offered_without_slides(self, js):
        # The same condition also appears in applyCompletedOutlineToTodoBoard, so
        # anchor on the comment unique to the stream-completion path.
        marker = "// `done` without a usable outline is a failure."
        body = _slice(js, marker, 1200)
        assert "hideStartPPTButton()" in body
        assert "showOutlineGenerationError(" in body
        assert "return" in body


class TestHiddenTabDoesNotStallTheStream:
    def test_yield_helper_has_a_timeout_fallback(self, js):
        assert "function yieldToRenderer(" in js
        body = _slice(js, "function yieldToRenderer(")
        assert "setTimeout(finish" in body
        assert "!document.hidden" in body

    def test_read_loop_uses_the_helper(self, js):
        assert "await yieldToRenderer();" in js
        assert "await new Promise(resolve => requestAnimationFrame(() => resolve()));" not in js


class TestJumpButtonListenerIsNotLeaked:
    def test_listener_is_bound_once_at_module_scope(self, js):
        assert "let outlineStreamJumpListenerBound = false;" in js
        assert "function ensureOutlineStreamJumpListener(" in js
        body = _slice(js, "function ensureOutlineStreamJumpListener(")
        assert "if (outlineStreamJumpListenerBound)" in body

    def test_per_run_flag_is_gone(self, js):
        assert "streamPreviewJumpBindingInitialized" not in js

    def test_binding_retargets_the_current_handler(self, js):
        body = _slice(js, "function bindOutlineStreamJumpButton()")
        assert "currentOutlineStreamJumpToLatest = jumpOutlineStreamPreviewToLatest" in body

    def test_destroy_detaches_the_stale_handler(self, js):
        body = _slice(js, "function destroyOutlineStreamPreviewRenderers()")
        assert "currentOutlineStreamJumpToLatest = null" in body


class TestOutlineContentDetection:
    def test_structural_check_precedes_the_text_heuristic(self, js):
        body = _slice(js, "function looksLikePlaceholderOutlineText(", 1400)
        assert "JSON.parse(text)" in body
        assert "Array.isArray(parsed.slides)" in body
        assert body.index("JSON.parse(text)") < body.index("placeholderPhrases")

    def test_tips_phrase_is_no_longer_a_rejection_trigger(self, js):
        body = _slice(js, "function looksLikePlaceholderOutlineText(", 1400)
        assert "小贴士" not in body, (
            "a real outline mentioning 小贴士 was rejected as a placeholder"
        )

    def test_both_getters_share_the_guard(self, js):
        for marker in ("function getOutlineContent()", "function getOutlineContentNew()"):
            body = _slice(js, marker, 1600)
            assert "looksLikePlaceholderOutlineText(" in body, f"{marker} lacks the guard"


class TestSingleSlideSavePreservesFields:
    def test_slide_is_spread_from_the_original(self, js):
        body = _slice(js, "async function saveSingleSlideEdit(", 3000)
        assert "...originalSlide," in body, "whitelist rebuild dropped unknown fields"

    def test_missing_outline_is_reported_not_crashed(self, js):
        body = _slice(js, "async function saveSingleSlideEdit(", 3000)
        assert "if (!outlineContent)" in body
        assert body.index("if (!outlineContent)") < body.index("JSON.parse(outlineContent)")


class TestModelContentIsEscaped:
    def test_escape_helper_is_defined_before_use(self, js):
        assert "function escapeHtml(value)" in js
        assert js.index("function escapeHtml(value)") < js.index("escapeHtml(slide.title)")
