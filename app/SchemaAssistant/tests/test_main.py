"""Tests for the SchemaAssistant @app.entrypoint (invoke).

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
    for event in events:
        yield event


def _text_delta_event():
    return {"event": {"contentBlockDelta": {"delta": {"text": "CREATE TABLE foo (id INT NOT NULL);"}}}}


def _empty_cbs_event():
    return {"event": {"contentBlockStart": {}}}


def _fresh_stream_factory(*events):
    def factory(*args, **kwargs):
        return _fake_stream(*events)
    return factory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_dependencies():
    mock_model = MagicMock()
    mock_agent = MagicMock()
    mock_agent.stream_async = MagicMock(side_effect=_fresh_stream_factory())

    with (
        patch("main.load_model", return_value=mock_model),
        patch("main.get_streamable_http_mcp_client", return_value=None),
        patch("main.Agent", return_value=mock_agent),
    ):
        import main as m
        m._mcp_clients = None
        m.get_or_create_agent = m.agent_factory()
        yield mock_agent


# ---------------------------------------------------------------------------
# _extract_prompt
# ---------------------------------------------------------------------------

class TestExtractPrompt:
    def test_plain_prompt_string(self):
        import main as m
        assert m._extract_prompt({"prompt": "design a users table"}) == "design a users table"

    def test_messages_payload(self):
        import main as m
        msgs = [{"role": "user", "content": "describe this schema"}]
        assert m._extract_prompt({"messages": msgs}) == msgs

    def test_tool_results_payload(self):
        import main as m
        tool_results = [{"toolUseId": "xyz", "status": "success", "content": []}]
        result = m._extract_prompt({"tool_results": tool_results})
        assert isinstance(result, list)
        block = result[0]["content"][0]["toolResult"]
        assert block["toolUseId"] == "xyz"

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
        events = [e async for e in m.invoke({"prompt": "design a schema"}, _make_context())]

        assert events == [good_event]

    async def test_filters_non_dict_events(self, mock_dependencies):
        mock_agent = mock_dependencies
        mock_agent.stream_async = MagicMock(
            side_effect=_fresh_stream_factory("not-a-dict", None, _text_delta_event())
        )

        import main as m
        events = [e async for e in m.invoke({"prompt": "hi"}, _make_context())]

        assert len(events) == 1
        assert "event" in events[0]

    async def test_filters_events_without_event_key(self, mock_dependencies):
        mock_agent = mock_dependencies
        mock_agent.stream_async = MagicMock(
            side_effect=_fresh_stream_factory({"metadata": "only"}, _text_delta_event())
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
        ctx = _make_context(session_id="schema-session-1")
        [e async for e in m.invoke({"prompt": "hi"}, ctx)]
        [e async for e in m.invoke({"prompt": "again"}, ctx)]

        assert mock_agent.stream_async.call_count == 2
        assert m.Agent.call_count == 1

    async def test_different_sessions_create_separate_agents(self, mock_dependencies):
        import main as m

        ctx_a = _make_context(session_id="schema-A")
        ctx_b = _make_context(session_id="schema-B")

        [e async for e in m.invoke({"prompt": "hi"}, ctx_a)]
        [e async for e in m.invoke({"prompt": "hi"}, ctx_b)]

        assert m.Agent.call_count == 2

    async def test_messages_payload_passed_to_agent(self, mock_dependencies):
        mock_agent = mock_dependencies
        mock_agent.stream_async = MagicMock(side_effect=_fresh_stream_factory())

        import main as m
        messages = [{"role": "user", "content": "suggest indexes for this table"}]
        [e async for e in m.invoke({"messages": messages}, _make_context())]

        mock_agent.stream_async.assert_called_once_with(messages)

    async def test_no_events_yields_nothing(self, mock_dependencies):
        import main as m
        events = [e async for e in m.invoke({"prompt": "hi"}, _make_context())]
        assert events == []
