"""运行中的 agent run 登记表，用于支持中止。

旧的 /cancel 端点只是 `return {"success": True}`，用户点了停止其实什么也没发生。
这里让每个 run 在注册表里留一个可被外部置位的取消信号。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

#: 超过这个时长的 run 视为泄漏，注册新 run 时顺手清掉。
_STALE_RUN_SECONDS = 60 * 60


@dataclass
class AgentRunHandle:
    run_id: str
    user_id: Optional[int]
    started_at: float = field(default_factory=time.time)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_reason: str = ""

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def cancel(self, reason: str = "") -> None:
        self.cancel_reason = reason or "cancelled by user"
        self.cancel_event.set()


class AgentRunRegistry:
    def __init__(self) -> None:
        self._runs: Dict[str, AgentRunHandle] = {}

    def register(self, run_id: str, user_id: Optional[int] = None) -> AgentRunHandle:
        self._prune()
        handle = AgentRunHandle(run_id=run_id, user_id=user_id)
        self._runs[run_id] = handle
        return handle

    def get(self, run_id: str) -> Optional[AgentRunHandle]:
        return self._runs.get(run_id)

    def cancel(self, run_id: str, user_id: Optional[int] = None, reason: str = "") -> bool:
        handle = self._runs.get(run_id)
        if handle is None:
            return False
        if user_id is not None and handle.user_id is not None and handle.user_id != user_id:
            return False
        handle.cancel(reason)
        return True

    def release(self, run_id: str) -> None:
        self._runs.pop(run_id, None)

    def active_count(self) -> int:
        return len(self._runs)

    def _prune(self) -> None:
        if not self._runs:
            return
        deadline = time.time() - _STALE_RUN_SECONDS
        for run_id in [key for key, handle in self._runs.items() if handle.started_at < deadline]:
            self._runs.pop(run_id, None)


#: 进程内共享。
agent_run_registry = AgentRunRegistry()
