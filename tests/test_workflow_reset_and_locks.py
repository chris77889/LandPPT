"""Regression tests for workflow reset, outline invalidation and slide locks."""

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "landppt"


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


class TestExplicitClearMethodsExist:
    """`save_project_outline(None)` and `save_project_slides("", [])` are no-ops."""

    def test_db_service_exposes_clear_methods(self):
        methods = _class_methods(SRC / "database" / "service.py", "DatabaseService")
        assert "clear_project_outline" in methods
        assert "clear_project_slides" in methods

    def test_manager_exposes_clear_methods(self):
        methods = _class_methods(
            SRC / "services" / "db_project_manager.py", "DatabaseProjectManager"
        )
        assert "clear_project_outline" in methods
        assert "clear_project_slides" in methods

    def test_save_project_outline_still_refuses_empty_payloads(self):
        """The guard protects a good outline from being wiped by a failed run."""
        source = (SRC / "database" / "service.py").read_text(encoding="utf-8")
        marker = "async def save_project_outline"
        body = source[source.index(marker) :][:1200]
        assert "if not outline:" in body
        assert "return False" in body

    def test_clear_project_slides_deletes_rows(self):
        source = (SRC / "database" / "service.py").read_text(encoding="utf-8")
        marker = "async def clear_project_slides"
        body = source[source.index(marker) :][:1200]
        assert "delete_slides_by_project_id" in body, (
            "clearing slides must delete the rows, not just blank slides_html"
        )


class TestResetStagesUsesClearMethods:
    def test_reset_no_longer_calls_the_no_op_saves(self):
        source = (
            SRC / "services" / "project_workflow_stage_service.py"
        ).read_text(encoding="utf-8")
        marker = "async def reset_stages_from"
        body = source[source.index(marker) :]
        body = body[: body.index("async def start_workflow_from_stage")]

        assert "save_project_outline(project_id, None)" not in body
        assert 'save_project_slides(project_id, "", [])' not in body
        assert "clear_project_slides(project_id)" in body
        assert "clear_project_outline(project_id)" in body

    def test_reset_cancels_inflight_generation_first(self):
        source = (
            SRC / "services" / "project_workflow_stage_service.py"
        ).read_text(encoding="utf-8")
        marker = "async def reset_stages_from"
        body = source[source.index(marker) :]
        body = body[: body.index("async def start_workflow_from_stage")]
        assert "request_cancel_slides_generation" in body

    def test_reset_reports_failure_when_clearing_fails(self):
        source = (
            SRC / "services" / "project_workflow_stage_service.py"
        ).read_text(encoding="utf-8")
        marker = "if not await db_manager.clear_project_slides(project_id):"
        assert marker in source
        body = source[source.index(marker) :][:600]
        assert "return False" in body


class TestOutlineChangeInvalidatesSlides:
    def test_signature_detects_plan_changes(self):
        source = (
            SRC / "services" / "outline" / "project_outline_repair_service.py"
        ).read_text(encoding="utf-8")
        assert "_outline_signature" in source
        assert "_invalidate_slides_for_new_outline" in source

        from typing import Any, Dict, Optional

        namespace = {"Optional": Optional, "Dict": Dict, "Any": Any}
        tree = ast.parse(source)
        signature_fn = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_outline_signature":
                signature_fn = node
                break
        assert signature_fn is not None

        # Re-evaluate the helper standalone to check its semantics.
        module = ast.Module(body=[signature_fn], type_ignores=[])
        # Drop the @staticmethod decorator for standalone evaluation.
        signature_fn.decorator_list = []
        exec(compile(ast.fix_missing_locations(module), "<sig>", "exec"), namespace)
        sig = namespace["_outline_signature"]

        a = {"slides": [{"title": "A"}, {"title": "B"}]}
        b = {"slides": [{"title": "A"}, {"title": "B"}]}
        c = {"slides": [{"title": "A"}, {"title": "C"}]}
        d = {"slides": [{"title": "A"}]}

        assert sig(a) == sig(b), "identical plans must compare equal"
        assert sig(a) != sig(c), "renamed slide must invalidate"
        assert sig(a) != sig(d), "different slide count must invalidate"
        assert sig(None) is None
        assert sig({"title": "no slides"}) is None

    def test_invalidation_resets_ppt_creation_stage(self):
        source = (
            SRC / "services" / "outline" / "project_outline_repair_service.py"
        ).read_text(encoding="utf-8")
        marker = "async def _invalidate_slides_for_new_outline"
        body = source[source.index(marker) :][:1500]
        assert "clear_project_slides" in body
        assert "'ppt_creation'" in body
        assert "'pending'" in body

    def test_reused_outline_does_not_wipe_slides(self):
        """Signature comparison must gate the wipe, not run unconditionally."""
        source = (
            SRC / "services" / "outline" / "project_outline_repair_service.py"
        ).read_text(encoding="utf-8")
        assert "if outline_plan_changed:" in source
        assert "outline_plan_changed = (" in source


class TestSlideLocksArePersisted:
    def test_lock_helpers_reach_the_database(self):
        source = (
            SRC / "services" / "slide" / "slide_streaming_service.py"
        ).read_text(encoding="utf-8")
        marker = "async def _set_slide_lock"
        assert marker in source
        body = source[source.index(marker) :][:900]
        assert "set_slide_locked" in body
        assert "placeholder" not in body.lower()

    def test_placeholder_comment_is_gone(self):
        source = (
            SRC / "services" / "slide" / "slide_streaming_service.py"
        ).read_text(encoding="utf-8")
        assert "For now, return True as placeholder" not in source

    def test_db_layer_stores_lock_in_metadata(self):
        methods = _class_methods(SRC / "database" / "service.py", "DatabaseService")
        assert "set_slide_locked" in methods
        assert "get_locked_slide_indices" in methods

    def test_lock_query_is_forwarded_through_facades(self):
        enhanced = _class_methods(
            SRC / "services" / "enhanced_ppt_service.py", "EnhancedPPTService"
        )
        authoring = _class_methods(
            SRC / "services" / "slide" / "slide_authoring_service.py",
            "SlideAuthoringService",
        )
        assert "get_locked_slide_indices" in enhanced
        assert "get_locked_slide_indices" in authoring

    def test_batch_regenerate_skips_locked_slides(self):
        source = (
            SRC / "web" / "route_modules" / "slide_routes.py"
        ).read_text(encoding="utf-8")
        assert "get_locked_slide_indices(project_id)" in source
        marker = "locked_indices = await user_ppt_service.get_locked_slide_indices"
        body = source[source.index(marker) :][:1400]
        assert "skipped_locked" in body
        # Locked slides must be dropped before the credit check, not after.
        assert body.index("target_indices = [i for i in target_indices") < body.index(
            "check_credits_for_operation"
        )
