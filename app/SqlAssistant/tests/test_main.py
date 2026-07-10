"""Tests for the SqlAssistant @app.entrypoint (invoke).

Strategy: mock load_model, the MCP client, and Agent.stream_async so no real
LLM calls are made. The invoke function is an async generator, so we collect
its output via an async for loop.

Patch targets use `main.*` (not `strands.*` / `model.load.*`) because Python
resolves names in the module that *uses* them, not where they are defined.
"""
import types
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(session_id="test-session"):
    return types.SimpleNamespace(session_id=session_id)


async def _fake_stream(*events):
    """Async generator that yields the given events then stops."""
    for event in events:
        yield event


def _text_delta_event():
    return {"event": {"contentBlockDelta": {"delta": {"text": "SELECT 1"}}}}


def _empty_cbs_event():
    """contentBlockStart with falsy start — invoke should filter this out."""
    return {"event": {"contentBlockStart": {}}}


def _fresh_stream_factory(*events):
    """Return a side_effect callable that creates a new generator on each call."""
    def factory(*args, **kwargs):
        return _fake_stream(*events)
    return factory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_dependencies():
    """
    Patch load_model, the MCP client, and Agent before each test.

    Targets are `main.*` so the names already bound in main's namespace are
    replaced, not the originals in their source modules.
    """
    mock_model = MagicMock()
    mock_agent = MagicMock()
    # Use side_effect so each call to stream_async gets a *fresh* generator.
    mock_agent.stream_async = MagicMock(side_effect=_fresh_stream_factory())

    with (
        patch("main.load_model", return_value=mock_model),
        patch("main.get_streamable_http_mcp_client", return_value=None),
        patch("main.Agent", return_value=mock_agent),
    ):
        import main as m
        # Reset module-level MCP client cache so each test starts clean.
        m._mcp_clients = None
        # Fresh agent factory so the in-process session cache is empty.
        m.get_or_create_agent = m.agent_factory()
        yield mock_agent


# ---------------------------------------------------------------------------
# _extract_prompt
# ---------------------------------------------------------------------------

class TestExtractPrompt:
    def test_plain_prompt_string(self):
        import main as m
        assert m._extract_prompt({"prompt": "SELECT 1"}) == "SELECT 1"

    def test_messages_payload(self):
        import main as m
        msgs = [{"role": "user", "content": "hello"}]
        assert m._extract_prompt({"messages": msgs}) == msgs

    def test_tool_results_payload(self):
        import main as m
        tool_results = [{"toolUseId": "abc", "status": "success", "content": [{"text": "ok"}]}]
        result = m._extract_prompt({"tool_results": tool_results})
        assert isinstance(result, list)
        block = result[0]["content"][0]["toolResult"]
        assert block["toolUseId"] == "abc"
        assert block["status"] == "success"

    def test_empty_payload_returns_empty_string(self):
        import main as m
        assert m._extract_prompt({}) == ""


# ---------------------------------------------------------------------------
# invoke entrypoint
# ---------------------------------------------------------------------------

class TestInvoke:
    async def test_yields_valid_events(self, mock_dependencies):
        mock_agent = mock_dependencies
        good_event = _text_delta_event()
        mock_agent.stream_async = MagicMock(side_effect=_fresh_stream_factory(good_event))

        import main as m
        events = [e async for e in m.invoke({"prompt": "write a query"}, _make_context())]

        assert events == [good_event]

    async def test_filters_non_dict_events(self, mock_dependencies):
        mock_agent = mock_dependencies
        mock_agent.stream_async = MagicMock(
            side_effect=_fresh_stream_factory("not-a-dict", 42, _text_delta_event())
        )

        import main as m
        events = [e async for e in m.invoke({"prompt": "hi"}, _make_context())]

        assert len(events) == 1
        assert "event" in events[0]

    async def test_filters_events_without_event_key(self, mock_dependencies):
        mock_agent = mock_dependencies
        mock_agent.stream_async = MagicMock(
            side_effect=_fresh_stream_factory({"notEvent": True}, _text_delta_event())
        )

        import main as m
        events = [e async for e in m.invoke({"prompt": "hi"}, _make_context())]

        assert len(events) == 1

    async def test_filters_empty_content_block_start(self, mock_dependencies):
        mock_agent = mock_dependencies
        mock_agent.stream_async = MagicMock(
            side_effect=_fresh_stream_factory(_empty_cbs_event(), _text_delta_event())
        )

        import main as m
        events = [e async for e in m.invoke({"prompt": "hi"}, _make_context())]

        assert len(events) == 1
        assert "contentBlockDelta" in events[0]["event"]

    async def test_same_session_reuses_agent(self, mock_dependencies):
        mock_agent = mock_dependencies
        mock_agent.stream_async = MagicMock(side_effect=_fresh_stream_factory())

        import main as m
        ctx = _make_context(session_id="session-42")
        [e async for e in m.invoke({"prompt": "first"}, ctx)]
        [e async for e in m.invoke({"prompt": "second"}, ctx)]

        # Same session → same cached agent → stream_async called twice, Agent() once.
        assert mock_agent.stream_async.call_count == 2
        assert m.Agent.call_count == 1

    async def test_different_sessions_create_separate_agents(self, mock_dependencies):
        import main as m

        ctx_a = _make_context(session_id="session-A")
        ctx_b = _make_context(session_id="session-B")

        [e async for e in m.invoke({"prompt": "hi"}, ctx_a)]
        [e async for e in m.invoke({"prompt": "hi"}, ctx_b)]

        # Two distinct sessions → Agent() instantiated twice.
        assert m.Agent.call_count == 2

    async def test_messages_payload_passed_to_agent(self, mock_dependencies):
        mock_agent = mock_dependencies
        mock_agent.stream_async = MagicMock(side_effect=_fresh_stream_factory())

        import main as m
        messages = [{"role": "user", "content": "explain this query"}]
        [e async for e in m.invoke({"messages": messages}, _make_context())]

        mock_agent.stream_async.assert_called_once_with(messages)

    async def test_no_events_yields_nothing(self, mock_dependencies):
        import main as m
        events = [e async for e in m.invoke({"prompt": "hi"}, _make_context())]
        assert events == []
