"""Slide edit agent 的公开入口。

实现拆分到 ``edit_agent`` 包里；这里只保留一个稳定的导入面，
让路由和测试不必关心内部模块划分。
"""

from __future__ import annotations

from .edit_agent import (
    AGENT_DEFAULT_ITERATIONS,
    AGENT_MAX_ITERATIONS,
    AGENT_MIN_ITERATIONS,
    AgentRunHandle,
    AgentRunRegistry,
    DraftRefError,
    SlideDraft,
    SlideEditAgentApplyRequest,
    SlideEditAgentCancelRequest,
    SlideEditAgentContext,
    SlideEditAgentRequest,
    SlideEditAgentRun,
    SlideEditAgentService,
    SlideEditProposal,
    SlideEditRunResult,
    SlideEditToolbox,
    SlideEditValidationResult,
    ToolProtocol,
    ToolProtocolRegistry,
    agent_run_registry,
    coerce_agent_max_iterations,
    compute_slide_html_hash,
    sanitize_slide_html,
    strip_agent_ids,
    tool_protocol_registry,
    validate_slide_html,
)

__all__ = [
    "AGENT_DEFAULT_ITERATIONS",
    "AGENT_MAX_ITERATIONS",
    "AGENT_MIN_ITERATIONS",
    "AgentRunHandle",
    "AgentRunRegistry",
    "DraftRefError",
    "SlideDraft",
    "SlideEditAgentApplyRequest",
    "SlideEditAgentCancelRequest",
    "SlideEditAgentContext",
    "SlideEditAgentRequest",
    "SlideEditAgentRun",
    "SlideEditAgentService",
    "SlideEditProposal",
    "SlideEditRunResult",
    "SlideEditToolbox",
    "SlideEditValidationResult",
    "ToolProtocol",
    "ToolProtocolRegistry",
    "agent_run_registry",
    "coerce_agent_max_iterations",
    "compute_slide_html_hash",
    "sanitize_slide_html",
    "strip_agent_ids",
    "tool_protocol_registry",
    "validate_slide_html",
]
