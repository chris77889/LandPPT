import sys
import types

import pytest

from landppt.ai.base import AIMessage, MessageRole
from landppt.ai.providers import AnthropicProvider
from landppt.services.db_config_service import _build_user_ai_provider_config


@pytest.mark.asyncio
async def test_anthropic_reasoning_effort_reaches_messages_request(monkeypatch):
    calls = []

    class FakeMessages:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                model=kwargs["model"],
                content=[types.SimpleNamespace(type="text", text="ok")],
                stop_reason="end_turn",
                usage=types.SimpleNamespace(input_tokens=1, output_tokens=1),
            )

    class FakeAsyncAnthropic:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        types.SimpleNamespace(AsyncAnthropic=FakeAsyncAnthropic),
    )

    config = _build_user_ai_provider_config(
        {
            "default_ai_provider": "anthropic",
            "anthropic_api_key": "test-key",
            "anthropic_base_url": "https://api.anthropic.com",
            "anthropic_model": "claude-opus-4-6",
            "anthropic_enable_reasoning": True,
            "anthropic_reasoning_effort": "max",
        }
    )
    config.pop("provider_name")
    provider = AnthropicProvider(config)

    await provider.chat_completion(
        [AIMessage(role=MessageRole.USER, content="hello")],
        tools=[{"name": "noop", "input_schema": {"type": "object"}}],
    )

    assert AnthropicProvider.SUPPORTED_REASONING_EFFORTS == {
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    }
    assert calls[0]["output_config"] == {"effort": "max"}
