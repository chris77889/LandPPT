"""
Shared helpers for the unattended (无人值守) pipeline.

Holds the config resolution, task dispatch, and the creation-form glue used by both
project creation entry points, so `unattended_routes` and the lifecycle/requirements
routes stay thin.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from ...core.config import app_config
from ...services.unattended_service import (
    STAGE_SPECS,
    TEMPLATE_MODES,
    UNATTENDED_TASK_TYPE,
    build_config,
    clear_cancel,
    load_config_defaults,
    normalize_stop_after,
    planned_stage_ids,
    run_unattended_pipeline,
)
from .support import logger

TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}


def require_unattended_admin(user: Any, *, enabled: bool = True) -> None:
    if enabled and not getattr(user, "is_admin", False):
        raise HTTPException(status_code=403, detail="无权限")


def parse_bool_form_value(value: Any, default: bool = False) -> bool:
    """Parse a checkbox-ish form value. FastAPI already coerces `bool` params, but the
    creation form also posts these as strings from FormData."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


async def resolve_unattended_config(
    *,
    user_id: int,
    overrides: Optional[Dict[str, Any]] = None,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge the user's saved defaults with per-run overrides."""
    merged: Dict[str, Any] = await load_config_defaults(user_id)
    if language:
        merged["language"] = language
    for key, value in (overrides or {}).items():
        if value is not None:
            merged[key] = value
    return build_config(merged)


async def submit_unattended_run(
    *,
    project_id: str,
    project_topic: str,
    user_id: int,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Create the background task, dispatching to the queue when it is enabled.

    Returns the standard task envelope. Safe to call from a route handler.
    """
    from ...services.background_tasks import get_task_manager

    task_manager = get_task_manager()
    metadata = {
        "project_id": project_id,
        "project_topic": project_topic,
        "user_id": user_id,
        "stop_after": config["stop_after"],
        "language": config["language"],
        "config": config,
        "progress_message": "无人值守任务已创建，等待执行…",
    }

    existing = await task_manager.find_active_task_async(
        task_type=UNATTENDED_TASK_TYPE,
        metadata_filter={"project_id": project_id, "user_id": user_id},
    )
    if existing:
        return {
            "status": "already_processing",
            "task_id": existing.task_id,
            "message": "该项目已有正在运行的无人值守任务",
            "polling_endpoint": f"/api/landppt/tasks/{existing.task_id}",
        }

    # A cancel flag left behind by a crashed run would abort the new one instantly.
    # Clearing here (rather than inside the runner) keeps a cancel requested *after*
    # submission — while the job waits for a worker — effective.
    await clear_cancel(project_id)

    task_id = task_manager.create_task(UNATTENDED_TASK_TYPE, metadata)
    # Persist before the pipeline can start: the template stage rewrites
    # project_metadata, and a later write from here would race it and drop the
    # selected template id. This ordering matters for the queue path too, where a
    # worker can pick the job up the instant it is enqueued.
    await _remember_task_id(project_id, task_id, user_id)

    if str(app_config.task_execution_mode or "inline").lower() == "queue":
        from ...services.background_tasks import TaskStatus
        from ...tasks.queue import enqueue_task

        try:
            await enqueue_task(task_id, UNATTENDED_TASK_TYPE)
        except Exception as exc:  # noqa: BLE001
            # The task record already exists. Leaving it PENDING would make
            # find_active_task_async report the project as busy forever (the
            # local-memory branch has no staleness release), locking the user out of
            # both unattended and manual generation. Settle it before surfacing.
            logger.error("Failed to enqueue unattended task %s: %s", task_id, exc)
            await task_manager.update_task_status_async(
                task_id, TaskStatus.FAILED, error=f"任务入队失败：{exc}"
            )
            raise

        return {
            "status": "queued",
            "task_id": task_id,
            "message": "无人值守任务已排队",
            "polling_endpoint": f"/api/landppt/tasks/{task_id}",
        }

    async def _pipeline_task():
        from ...services.background_tasks import TaskStatus

        async def _on_progress(progress: float, snapshot: Dict[str, Any]) -> None:
            await task_manager.update_task_status_async(
                task_id,
                TaskStatus.RUNNING,
                progress=max(0.0, min(99.0, float(progress))),
                result=snapshot,
            )

        return await run_unattended_pipeline(
            project_id=project_id,
            user_id=user_id,
            config=config,
            task_id=task_id,
            progress_callback=_on_progress,
        )

    async_task = asyncio.create_task(task_manager.execute_task(task_id, _pipeline_task))
    task_manager.running_tasks[task_id] = async_task

    return {
        "status": "processing",
        "task_id": task_id,
        "message": "无人值守任务已在后台启动",
        "polling_endpoint": f"/api/landppt/tasks/{task_id}",
    }


async def has_active_unattended_run(project_id: str, user_id: int) -> bool:
    """True while an unattended pipeline owns this project's generation stages.

    The workspace uses this to stand down its own auto-start logic; without it the
    board would launch a second, competing outline stream on page load.
    """
    try:
        from ...services.background_tasks import get_task_manager

        task = await get_task_manager().find_active_task_async(
            task_type=UNATTENDED_TASK_TYPE,
            metadata_filter={"project_id": project_id, "user_id": user_id},
        )
        return task is not None
    except Exception as exc:  # noqa: BLE001
        # Fail open: a lookup outage must not permanently lock a user out of manual
        # generation. The cost is that during a total cache+DB outage the page may
        # start its own outline stream alongside a live run.
        logger.warning("Could not resolve unattended state for project %s: %s", project_id, exc)
        return False


def default_stage_snapshot(stop_after: str) -> List[Dict[str, Any]]:
    """Placeholder stage list shown before the runner has published anything."""
    planned = planned_stage_ids(stop_after)
    return [
        {
            "id": spec.id,
            "name": spec.name,
            "status": "pending" if spec.id in planned else "skipped",
            "progress": 0.0,
            "message": "" if spec.id in planned else "未选择该阶段",
            "error": None,
            "detail": {},
        }
        for spec in STAGE_SPECS
    ]


async def maybe_start_unattended_run(
    *,
    project_id: str,
    project_topic: str,
    user_id: int,
    confirmed_requirements: Dict[str, Any],
    language: str = "zh",
) -> Optional[Dict[str, Any]]:
    """Start the pipeline when the creation form asked for unattended mode.

    Returns the task envelope, or None when unattended mode is off. Never raises:
    the project already exists and must remain usable even if dispatch fails.
    """
    settings = confirmed_requirements.get("unattended") or {}
    if not settings.get("enabled"):
        return None

    try:
        config = await resolve_unattended_config(
            user_id=user_id,
            overrides={
                "stop_after": settings.get("stop_after"),
                "notify_in_app": settings.get("notify_in_app"),
                "notify_email": settings.get("notify_email"),
                "template_mode": settings.get("template_mode"),
                "template_id": settings.get("template_id"),
            },
            language=language,
        )
        envelope = await submit_unattended_run(
            project_id=project_id,
            project_topic=project_topic,
            user_id=user_id,
            config=config,
        )
        return {**envelope, "config": config}
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to auto-start unattended run for project %s: %s", project_id, exc)
        return {"status": "error", "task_id": None, "message": str(exc)}


async def _remember_task_id(project_id: str, task_id: Optional[str], user_id: int) -> None:
    """Record the task id on the project so the status endpoint can find a finished
    run once it has aged out of the active-task index."""
    if not task_id:
        return
    try:
        from ...services.db_project_manager import DatabaseProjectManager

        manager = DatabaseProjectManager()
        project = await manager.get_project(project_id, user_id=user_id)
        if not project:
            return
        metadata = dict(project.project_metadata or {})
        metadata["unattended_task_id"] = task_id
        await manager.update_project_metadata(project_id, metadata, user_id=user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not record unattended task id on project %s: %s", project_id, exc)


def build_unattended_requirements(
    *,
    enabled: bool,
    stop_at_stage: Optional[str],
    notify_in_app: bool,
    notify_email: bool,
    template_mode: Optional[str] = None,
    template_id: Optional[str] = None,
) -> Dict[str, Any]:
    """The `unattended` block stored inside confirmed_requirements."""
    mode = (template_mode or "auto").strip().lower()
    if mode not in TEMPLATE_MODES:
        mode = "auto"
    try:
        resolved_id = int(template_id) if str(template_id or "").strip() else None
    except (TypeError, ValueError):
        resolved_id = None

    return {
        "enabled": bool(enabled),
        "stop_after": normalize_stop_after(stop_at_stage),
        "notify_in_app": bool(notify_in_app),
        "notify_email": bool(notify_email),
        "template_mode": mode,
        "template_id": resolved_id if mode == "global" else None,
    }
