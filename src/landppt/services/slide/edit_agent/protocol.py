"""工具调用协议适配层。

循环只有一套。协议在这里被抽象成「怎么把 tools 发出去、怎么把结果写回消息里」，
它只影响消息的编解码，不影响控制流：

- NATIVE：走 provider 原生 tool_calls。
- TEXT：provider 不认 tools 参数时，用 JSON action 文本协议顶上。

选哪个由开局的能力表决定（见 ToolProtocolRegistry），不是在循环中间靠异常
字符串猜出来的。异常路径只保留一次性的兜底降级，且只允许发生在第一次模型调用、
任何工具执行之前。
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

ChatFn = Callable[..., Awaitable[Any]]

#: provider 参数被拒绝的典型报错片段。只用于一次性兜底降级。
_TOOL_PARAM_REJECTION_MARKERS = (
    "tools",
    "tool_choice",
    "tool_calls",
    "function calling",
    "functions",
)
_TOOL_PARAM_REJECTION_CONTEXT = (
    "unsupported parameter",
    "unknown parameter",
    "unrecognized request argument",
    "unsupported value",
    "invalid_request_error",
    "does not support",
    "not supported",
)


class ToolProtocol(str, Enum):
    NATIVE = "native"
    TEXT = "text"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class AgentTurn:
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    raw_tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    #: 文本协议下模型没按 JSON action 格式回复。
    malformed: bool = False
    #: NATIVE 下模型明显没看到工具定义（自己编了 JSON action），需要降级。
    looks_tool_blind: bool = False


def extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1).strip()

    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    object_match = re.search(r"\{[\s\S]*\}", cleaned)
    if object_match:
        try:
            parsed = json.loads(object_match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None

    return None


def is_structured_agent_action(content: str) -> bool:
    payload = extract_json_payload(content or "")
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("action") or payload.get("tool"))


def is_tool_parameter_rejection(error: Exception) -> bool:
    """只在报错同时提到「tools 这类参数」和「不支持/无法识别」时才算降级信号。"""
    message = (str(error) or error.__class__.__name__).lower()
    has_marker = any(marker in message for marker in _TOOL_PARAM_REJECTION_MARKERS)
    has_context = any(marker in message for marker in _TOOL_PARAM_REJECTION_CONTEXT)
    return has_marker and has_context


class ToolProtocolRegistry:
    """进程级的协议能力表。

    默认所有 provider 都支持 native tool_calls（OpenAI / Azure / Anthropic /
    Google / Ollama 适配器都实现了）。真正的风险来自第三方 OpenAI 兼容网关，
    因此一旦某个 provider+model 组合被证实不认 tools，就把它记下来，
    后续请求直接从 TEXT 协议起步，不再每次都白花一轮调用。
    """

    def __init__(self) -> None:
        self._text_only: Dict[str, str] = {}

    @staticmethod
    def key_for(provider_name: Optional[str], model: Optional[str]) -> str:
        return f"{(provider_name or 'unknown').strip().lower()}::{(model or '').strip().lower()}"

    def preferred(self, key: str) -> ToolProtocol:
        return ToolProtocol.TEXT if key in self._text_only else ToolProtocol.NATIVE

    def downgrade_reason(self, key: str) -> str:
        return self._text_only.get(key, "")

    def mark_text_only(self, key: str, reason: str) -> None:
        self._text_only.setdefault(key, reason or "provider ignored native tool schemas")

    def reset(self) -> None:
        self._text_only.clear()


#: 进程内共享。测试可调用 reset()。
tool_protocol_registry = ToolProtocolRegistry()


class ProtocolAdapter(ABC):
    protocol: ToolProtocol

    def __init__(self, chat: ChatFn, messages: List[Any]):
        self._chat = chat
        self.messages: List[Any] = list(messages)

    @abstractmethod
    async def next_turn(self) -> AgentTurn:
        ...

    @abstractmethod
    def record_turn(self, turn: AgentTurn) -> None:
        ...

    @abstractmethod
    def record_tool_result(self, call: ToolCall, observation: Dict[str, Any]) -> None:
        ...

    def record_correction(self, message: str) -> None:
        self.messages.append(_message("user", message))


class NativeToolProtocolAdapter(ProtocolAdapter):
    protocol = ToolProtocol.NATIVE

    def __init__(self, chat: ChatFn, messages: List[Any], tools: List[Dict[str, Any]]):
        super().__init__(chat, messages)
        self._tools = tools
        self._turns = 0

    async def next_turn(self) -> AgentTurn:
        response = await self._chat(
            messages=self.messages,
            tools=self._tools,
            tool_choice="auto",
            parallel_tool_calls=False,
        )
        self._turns += 1
        text = str(getattr(response, "content", "") or "")
        raw_calls = list(getattr(response, "tool_calls", None) or [])
        calls = [_to_tool_call(raw, index) for index, raw in enumerate(raw_calls, start=1)]
        return AgentTurn(
            text=text,
            tool_calls=[call for call in calls if call.name],
            raw_tool_calls=raw_calls,
            looks_tool_blind=(
                self._turns == 1 and not raw_calls and is_structured_agent_action(text)
            ),
        )

    def record_turn(self, turn: AgentTurn) -> None:
        self.messages.append(
            _message("assistant", turn.text, tool_calls=turn.raw_tool_calls or None)
        )

    def record_tool_result(self, call: ToolCall, observation: Dict[str, Any]) -> None:
        self.messages.append(
            _message(
                "tool",
                json.dumps(observation, ensure_ascii=False),
                tool_call_id=call.id,
            )
        )


class TextToolProtocolAdapter(ProtocolAdapter):
    protocol = ToolProtocol.TEXT

    def __init__(self, chat: ChatFn, messages: List[Any]):
        super().__init__(chat, messages)
        self._call_index = 0

    async def next_turn(self) -> AgentTurn:
        response = await self._chat(messages=self.messages)
        content = str(getattr(response, "content", "") or "")
        payload = extract_json_payload(content)

        if not isinstance(payload, dict) or not (payload.get("action") or payload.get("tool")):
            return AgentTurn(text=content, malformed=True)

        action = str(payload.get("action") or payload.get("tool") or "").strip()
        normalized = action.lower().replace("-", "_")
        thought = str(payload.get("thought") or payload.get("reasoning") or "").strip()
        raw_input = payload.get("action_input") or payload.get("input") or {}
        arguments = raw_input if isinstance(raw_input, dict) else {"value": raw_input}

        if normalized in {"final", "finish", "done"}:
            summary = str(arguments.get("summary") or thought or content).strip()
            return AgentTurn(text=summary)

        self._call_index += 1
        return AgentTurn(
            text=thought,
            tool_calls=[ToolCall(id=f"text-{self._call_index}", name=normalized, arguments=arguments)],
            raw_tool_calls=[{"id": f"text-{self._call_index}", "raw": content}],
        )

    def record_turn(self, turn: AgentTurn) -> None:
        payload = turn.raw_tool_calls[0].get("raw") if turn.raw_tool_calls else turn.text
        self.messages.append(_message("assistant", str(payload or turn.text)))

    def record_tool_result(self, call: ToolCall, observation: Dict[str, Any]) -> None:
        self.messages.append(
            _message(
                "user",
                "Tool result:\n" + json.dumps(observation, ensure_ascii=False),
            )
        )


def _to_tool_call(raw: Dict[str, Any], index: int) -> ToolCall:
    function = raw.get("function") if isinstance(raw, dict) else {}
    function = function if isinstance(function, dict) else {}
    name = str(function.get("name") or raw.get("name") or "").strip()
    raw_arguments = function.get("arguments") if "arguments" in function else raw.get("arguments")

    if isinstance(raw_arguments, dict):
        arguments: Dict[str, Any] = raw_arguments
    else:
        try:
            parsed = json.loads(str(raw_arguments or "{}"))
        except json.JSONDecodeError:
            parsed = {}
        arguments = parsed if isinstance(parsed, dict) else {}

    return ToolCall(
        id=str(raw.get("id") or f"call-{index}"),
        name=name.lower().replace("-", "_"),
        arguments=arguments,
    )


def _message(
    role: str,
    content: Any,
    *,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    tool_call_id: Optional[str] = None,
):
    from ....ai import AIMessage, MessageRole

    role_map = {
        "system": MessageRole.SYSTEM,
        "user": MessageRole.USER,
        "assistant": MessageRole.ASSISTANT,
        "tool": MessageRole.TOOL,
    }
    return AIMessage(
        role=role_map.get(role, MessageRole.USER),
        content=content,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
    )
