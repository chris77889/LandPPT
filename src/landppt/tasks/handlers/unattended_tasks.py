"""Worker handler for the unattended generation pipeline."""

from __future__ import annotations

import logging
from typing import Any, Dict

from ...services.background_tasks import TaskStatus, get_task_manager
from ...services.unattended_service import UNATTENDED_TASK_TYPE, run_unattended_pipeline
from ..registry import task_handler

logger = logging.getLogger(__name__)


def _config_from_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    config = metadata.get("config")
    return dict(config) if isinstance(config, dict) else {}


@task_handler(UNATTENDED_TASK_TYPE)
async def run_unattended(task) -> dict:
    """Drive the full unattended pipeline for one project.

    Everything the pipeline needs comes from ``task.metadata`` so the job survives
    the round trip through Valkey and the ``async_tasks`` row.
    """
    metadata = task.metadata if isinstance(task.metadata, dict) else {}
    project_id = str(metadata.get("project_id") or "").strip()
    raw_user_id = metadata.get("user_id")
    if not project_id or raw_user_id is None:
        return {"success": False, "error": "Unattended task metadata is missing project_id or user_id"}

    task_manager = get_task_manager()

    async def _on_progress(progress: float, snapshot: Dict[str, Any]) -> None:
        # Mirror the live snapshot into the task record so GET /api/landppt/tasks/{id}
        # and the workspace monitor panel can poll it while the run is in flight.
        await task_manager.update_task_status_async(
            task.task_id,
            TaskStatus.RUNNING,
            progress=max(0.0, min(99.0, float(progress))),
            result=snapshot,
        )

    return await run_unattended_pipeline(
        project_id=project_id,
        user_id=int(raw_user_id),
        config=_config_from_metadata(metadata),
        task_id=task.task_id,
        progress_callback=_on_progress,
    )
