"""Agent 事件协议。

前端只依赖这里列出的事件名与字段。每个事件都带 runId 和自增 seq，
方便前端做乱序保护、只取最新草稿、以及把事件归到正确的 run 上。
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

EventCallback = Callable[[Dict[str, Any]], Awaitable[None]]

RUN_STARTED = "run_started"
PROTOCOL_CHANGED = "protocol_changed"
TURN_STARTED = "turn_started"
THINKING = "thinking"
TOOL_STARTED = "tool_started"
TOOL_FINISHED = "tool_finished"
DRAFT_UPDATED = "draft_updated"
VALIDATION = "validation"
RUN_FINISHED = "run_finished"
ERROR = "error"

#: 计费判定用：run 真正产出结果的事件。
BILLABLE_EVENT_TYPES = frozenset({RUN_FINISHED})


class AgentEventEmitter:
    def __init__(self, run_id: str, callback: Optional[EventCallback] = None):
        self.run_id = run_id
        self._callback = callback
        self._seq = 0

    async def emit(self, event_type: str, **payload: Any) -> None:
        if self._callback is None:
            return
        self._seq += 1
        event: Dict[str, Any] = {
            "type": event_type,
            "runId": self.run_id,
            "seq": self._seq,
        }
        event.update({key: value for key, value in payload.items() if value is not None})
        await self._callback(event)

    async def emit_error(
        self,
        error: Exception,
        *,
        phase: str,
        iteration: Optional[int] = None,
        tool: Optional[str] = None,
    ) -> None:
        await self.emit(
            ERROR,
            phase=phase,
            message=str(error) or error.__class__.__name__,
            errorType=error.__class__.__name__,
            iteration=iteration,
            tool=tool,
        )
