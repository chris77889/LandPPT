"""Regression tests for slide-generation cancellation and lock release."""

import ast
import asyncio
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "landppt"


def _class_methods(path: Path, class_name: str) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                m.name
                for m in node.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    raise AssertionError(f"class {class_name} not found in {path}")


def test_cancellation_check_is_reachable_from_generation_service():
    """SlideGenerationService delegates to EnhancedPPTService via __getattr__.

    EnhancedPPTService has no __getattr__ of its own, so the cancel check must be
    forwarded explicitly or the stop button becomes a silent no-op.
    """
    enhanced = _class_methods(
        SRC / "services" / "enhanced_ppt_service.py", "EnhancedPPTService"
    )
    assert "_is_slides_generation_cancelled" in enhanced
    assert "request_cancel_slides_generation" in enhanced
    assert "clear_cancel_slides_generation" in enhanced


def test_generation_loop_logs_cancellation_check_failures():
    """A broken cancel check must not be swallowed by a bare `except: pass`."""
    source = (
        SRC / "services" / "slide" / "slide_generation_service.py"
    ).read_text(encoding="utf-8")
    marker = "if await self._is_slides_generation_cancelled("
    assert marker in source
    tail = source[source.index(marker) :]
    handler = tail[: tail.index("batch_end = min(")]
    assert "except Exception:\n                        pass" not in handler
    assert "logger.error" in handler


def test_await_on_cancelled_task_needs_cancellederror_in_handler():
    """Guards the actual language behaviour the lock-release fix depends on."""

    async def scenario(handler_catches_cancelled: bool) -> bool:
        cleanup_ran = False

        async def renew():
            await asyncio.sleep(60)

        task = asyncio.create_task(renew())
        await asyncio.sleep(0)
        try:
            task.cancel()
            if handler_catches_cancelled:
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            else:
                try:
                    await task
                except Exception:
                    pass
            cleanup_ran = True
        except asyncio.CancelledError:
            pass
        return cleanup_ran

    assert asyncio.run(scenario(handler_catches_cancelled=True)) is True
    # Without CancelledError in the handler the cleanup is skipped entirely.
    assert asyncio.run(scenario(handler_catches_cancelled=False)) is False


def test_background_generate_slides_releases_lock_after_cancelling_renewer():
    source = (
        SRC / "services" / "slide" / "slide_streaming_service.py"
    ).read_text(encoding="utf-8")
    marker = "renew_task.cancel()"
    assert marker in source
    tail = source[source.index(marker) :]
    block = tail[: tail.index("_slides_generation_tasks.pop")]
    assert "asyncio.CancelledError" in block, (
        "awaiting the cancelled renew task must catch CancelledError, "
        "otherwise _release_slides_generation_lock is skipped"
    )
