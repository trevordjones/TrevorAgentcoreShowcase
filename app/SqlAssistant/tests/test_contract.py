"""Contract tests for the SqlAssistant HTTP interface.

These tests drive the real Starlette routing (POST /invocations, GET /ping)
through starlette.testclient.TestClient, mocking only the Agent so no LLM
calls are made.  They verify the observable HTTP contract that the
BedrockAgentCore control plane and any client depends on:

  - /invocations accepts JSON and streams SSE events
  - Each SSE chunk is valid JSON
  - Session ID header is forwarded to the agent
  - /ping reports Healthy / HealthyBusy status
  - Malformed requests return the expected error codes
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
REQUEST_ID_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Request-Id"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _fake_stream(*events):
    for event in events:
        yield event


def _fresh_stream_factory(*events):
    def factory(*args, **kwargs):
        return _fake_stream(*events)
    return factory


def _text_delta_event():
    return {"event": {"contentBlockDelta": {"delta": {"text": "SELECT 1"}}}}


def _parse_sse(raw: bytes) -> list[dict]:
    """Parse raw SSE body into a list of decoded JSON objects."""
    chunks = []
    for line in raw.decode().split("\n\n"):
        line = line.strip()
        if line.startswith("data:"):
            data = line[len("data:"):].strip()
            chunks.append(json.loads(data))
    return chunks


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_agent():
    mock_model = MagicMock()
    agent = MagicMock()
    agent.stream_async = MagicMock(side_effect=_fresh_stream_factory())

    with (
        patch("main.load_model", return_value=mock_model),
        patch("main.get_streamable_http_mcp_client", return_value=None),
        patch("main.Agent", return_value=agent),
    ):
        import main as m
        m._mcp_clients = None
        m.get_or_create_agent = m.agent_factory()
        yield agent


@pytest.fixture()
def client(mock_agent):
    import main as m
    with TestClient(m.app, raise_server_exceptions=True) as c:
        yield c


# ---------------------------------------------------------------------------
# /ping
# ---------------------------------------------------------------------------

class TestPing:
    def test_returns_200(self, client):
        resp = client.get("/ping")
        assert resp.status_code == 200

    def test_returns_healthy_status(self, client):
        body = client.get("/ping").json()
        assert body["status"] == "Healthy"

    def test_returns_timestamp(self, client):
        body = client.get("/ping").json()
        assert "time_of_last_update" in body
        assert isinstance(body["time_of_last_update"], int)


# ---------------------------------------------------------------------------
# /invocations — happy path
# ---------------------------------------------------------------------------

class TestInvocations:
    def test_returns_200(self, client, mock_agent):
        mock_agent.stream_async = MagicMock(side_effect=_fresh_stream_factory(_text_delta_event()))
        resp = client.post("/invocations", json={"prompt": "SELECT 1"})
        assert resp.status_code == 200

    def test_content_type_is_sse(self, client, mock_agent):
        mock_agent.stream_async = MagicMock(side_effect=_fresh_stream_factory())
        resp = client.post("/invocations", json={"prompt": "hi"})
        assert "text/event-stream" in resp.headers["content-type"]

    def test_events_are_valid_json(self, client, mock_agent):
        good = _text_delta_event()
        mock_agent.stream_async = MagicMock(side_effect=_fresh_stream_factory(good))
        resp = client.post("/invocations", json={"prompt": "SELECT 1"})
        events = _parse_sse(resp.content)
        assert len(events) == 1
        assert events[0] == good

    def test_multiple_events_all_streamed(self, client, mock_agent):
        events_in = [_text_delta_event(), _text_delta_event(), _text_delta_event()]
        mock_agent.stream_async = MagicMock(side_effect=_fresh_stream_factory(*events_in))
        resp = client.post("/invocations", json={"prompt": "SELECT 1"})
        events_out = _parse_sse(resp.content)
        assert events_out == events_in

    def test_empty_stream_returns_200_with_no_data(self, client, mock_agent):
        mock_agent.stream_async = MagicMock(side_effect=_fresh_stream_factory())
        resp = client.post("/invocations", json={"prompt": "hi"})
        assert resp.status_code == 200
        assert _parse_sse(resp.content) == []

    def test_messages_payload_accepted(self, client, mock_agent):
        mock_agent.stream_async = MagicMock(side_effect=_fresh_stream_factory(_text_delta_event()))
        payload = {"messages": [{"role": "user", "content": "explain this query"}]}
        resp = client.post("/invocations", json=payload)
        assert resp.status_code == 200
        mock_agent.stream_async.assert_called_once_with(payload["messages"])

    def test_session_header_used_for_agent_routing(self, client, mock_agent):
        """Requests with the same session ID reuse the same agent instance."""
        mock_agent.stream_async = MagicMock(side_effect=_fresh_stream_factory())
        headers = {SESSION_HEADER: "session-abc"}
        client.post("/invocations", json={"prompt": "first"}, headers=headers)
        client.post("/invocations", json={"prompt": "second"}, headers=headers)
        # Same session → Agent() constructed once, stream_async called twice.
        import main as m
        assert m.Agent.call_count == 1
        assert mock_agent.stream_async.call_count == 2

    def test_different_session_headers_create_separate_agents(self, client, mock_agent):
        mock_agent.stream_async = MagicMock(side_effect=_fresh_stream_factory())
        client.post("/invocations", json={"prompt": "hi"}, headers={SESSION_HEADER: "sess-1"})
        client.post("/invocations", json={"prompt": "hi"}, headers={SESSION_HEADER: "sess-2"})
        import main as m
        assert m.Agent.call_count == 2


# ---------------------------------------------------------------------------
# /invocations — error cases
# ---------------------------------------------------------------------------

class TestInvocationsErrors:
    def test_invalid_json_returns_400(self, client):
        resp = client.post(
            "/invocations",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    def test_400_body_describes_error(self, client):
        resp = client.post(
            "/invocations",
            content=b"{bad",
            headers={"content-type": "application/json"},
        )
        body = resp.json()
        assert "error" in body
