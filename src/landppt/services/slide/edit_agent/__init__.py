"""Slide edit agent：单页幻灯片的工具驱动编辑循环。

模块划分：

- ``html_safety``  HTML 清洗 / 校验 / 哈希
- ``draft``        可增量编辑的草稿（持久 DOM 树 + 引用表 + 撤销栈）
- ``tools``        工具规格与实现（native schema 与文本协议清单同源）
- ``protocol``     native tool_calls / JSON 文本协议适配器与能力表
- ``prompt``       系统提示词与首轮上下文
- ``loop``         唯一的 agent 循环
- ``runs``         运行中 run 的登记表，支撑中止
- ``events``       SSE 事件协议
"""

from .draft import DraftRefError, ElementSummary, SlideDraft
from .events import (
    BILLABLE_EVENT_TYPES,
    DRAFT_UPDATED,
    ERROR,
    PROTOCOL_CHANGED,
    RUN_FINISHED,
    RUN_STARTED,
    THINKING,
    TOOL_FINISHED,
    TOOL_STARTED,
    TURN_STARTED,
    VALIDATION,
    AgentEventEmitter,
)
from .html_safety import (
    SlideEditValidationResult,
    compute_slide_html_hash,
    css_declaration_error,
    sanitize_slide_html,
    strip_agent_ids,
    validate_slide_html,
)
from .loop import SlideEditAgentRun, SlideEditAgentService
from .protocol import (
    AgentTurn,
    ToolCall,
    ToolProtocol,
    ToolProtocolRegistry,
    is_structured_agent_action,
    is_tool_parameter_rejection,
    tool_protocol_registry,
)
from .runs import AgentRunHandle, AgentRunRegistry, agent_run_registry
from .schema import (
    AGENT_DEFAULT_ITERATIONS,
    AGENT_MAX_ITERATIONS,
    AGENT_MIN_ITERATIONS,
    SlideEditAgentApplyRequest,
    SlideEditAgentCancelRequest,
    SlideEditAgentContext,
    SlideEditAgentRequest,
    SlideEditProposal,
    SlideEditRunResult,
    coerce_agent_max_iterations,
)
from .tools import TOOL_SPECS, SlideEditToolbox, ToolResult, ToolSpec

__all__ = [
    "AGENT_DEFAULT_ITERATIONS",
    "AGENT_MAX_ITERATIONS",
    "AGENT_MIN_ITERATIONS",
    "AgentEventEmitter",
    "AgentRunHandle",
    "AgentRunRegistry",
    "AgentTurn",
    "BILLABLE_EVENT_TYPES",
    "DRAFT_UPDATED",
    "DraftRefError",
    "ERROR",
    "ElementSummary",
    "PROTOCOL_CHANGED",
    "RUN_FINISHED",
    "RUN_STARTED",
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
    "THINKING",
    "TOOL_FINISHED",
    "TOOL_SPECS",
    "TOOL_STARTED",
    "TURN_STARTED",
    "ToolCall",
    "ToolProtocol",
    "ToolProtocolRegistry",
    "ToolResult",
    "ToolSpec",
    "VALIDATION",
    "agent_run_registry",
    "coerce_agent_max_iterations",
    "compute_slide_html_hash",
    "css_declaration_error",
    "is_structured_agent_action",
    "is_tool_parameter_rejection",
    "sanitize_slide_html",
    "strip_agent_ids",
    "tool_protocol_registry",
    "validate_slide_html",
]
