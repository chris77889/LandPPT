"""
In-app notification routes.

Backs the nav bell: an unread badge, a recent list, and read acknowledgements.
Every endpoint is scoped to the authenticated user.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from ...auth.middleware import get_current_user_required
from ...database.database import AsyncSessionLocal
from ...database.models import User
from ...database.repositories import NotificationRepository
from ...services.notification_service import notification_to_dict
from .support import _apply_no_store_headers, logger

router = APIRouter()


@router.get("/api/notifications")
async def list_notifications(
    limit: int = 20,
    unread_only: bool = False,
    user: User = Depends(get_current_user_required),
):
    """List the current user's recent notifications, newest first."""
    try:
        async with AsyncSessionLocal() as session:
            repository = NotificationRepository(session)
            notifications = await repository.list_for_user(
                user.id, limit=limit, unread_only=unread_only
            )
            unread_count = await repository.count_unread(user.id)

        response = JSONResponse(
            {
                "success": True,
                "notifications": [notification_to_dict(item) for item in notifications],
                "unread_count": unread_count,
            }
        )
        return _apply_no_store_headers(response)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to list notifications for user %s: %s", user.id, exc)
        raise HTTPException(status_code=500, detail="Failed to load notifications")


@router.get("/api/notifications/unread-count")
async def get_unread_notification_count(user: User = Depends(get_current_user_required)):
    """Cheap poll target for the nav badge."""
    try:
        async with AsyncSessionLocal() as session:
            unread_count = await NotificationRepository(session).count_unread(user.id)
        return _apply_no_store_headers(JSONResponse({"success": True, "unread_count": unread_count}))
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to count notifications for user %s: %s", user.id, exc)
        raise HTTPException(status_code=500, detail="Failed to load notification count")


@router.post("/api/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    user: User = Depends(get_current_user_required),
):
    """Mark one notification read. Already-read ids are reported as updated=False."""
    try:
        async with AsyncSessionLocal() as session:
            repository = NotificationRepository(session)
            updated = await repository.mark_read(notification_id, user.id)
            unread_count = await repository.count_unread(user.id)
        return JSONResponse({"success": True, "updated": updated, "unread_count": unread_count})
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to mark notification %s read: %s", notification_id, exc)
        raise HTTPException(status_code=500, detail="Failed to update notification")


@router.post("/api/notifications/read-all")
async def mark_all_notifications_read(user: User = Depends(get_current_user_required)):
    """Mark every unread notification read."""
    try:
        async with AsyncSessionLocal() as session:
            updated = await NotificationRepository(session).mark_all_read(user.id)
        return JSONResponse({"success": True, "updated": updated, "unread_count": 0})
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to mark all notifications read for user %s: %s", user.id, exc)
        raise HTTPException(status_code=500, detail="Failed to update notifications")
