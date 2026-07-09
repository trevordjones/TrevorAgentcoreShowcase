from typing import Any
from collections import OrderedDict
from strands import Agent, tool
import asyncio
from dotenv import load_dotenv
load_dotenv()
import sqlglot
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model
from mcp_client.client import get_streamable_http_mcp_client

app = BedrockAgentCoreApp()
log = app.logger

# MCP clients are initialized lazily on first agent creation to avoid
# blocking the runtime startup health check with a network call.
_mcp_clients = None

def _get_mcp_clients():
    global _mcp_clients
    if _mcp_clients is None:
        _mcp_clients = [get_streamable_http_mcp_client()]
    return _mcp_clients

DEFAULT_SYSTEM_PROMPT = """
You are a senior data analyst assistant that helps users write, understand, and validate SQL queries.

Guidelines:
- Always validate SQL before returning it to the user.
- Prefer explicit column names over SELECT *.
- Write ANSI SQL unless the user specifies a dialect (e.g., BigQuery, Postgres, Snowflake).
- Use your tools sequentially: validate, then format, then explain.
"""


# Define a collection of tools used by the model
tools = []

_INLINE_FUNCTION_NAMES = set()


@tool
def format_sql(sql: str) -> str:
    """Prettify a SQL string with consistent casing and indentation."""
    return sqlglot.transpile(sql, pretty=True)[0]


@tool
def validate_sql(sql: str, dialect: str = "") -> dict:
    """Validate SQL syntax. Returns a dict with 'valid' (bool) and 'errors' (list of strings)."""
    try:
        errors = sqlglot.parse(sql, dialect=dialect or None, error_level=sqlglot.ErrorLevel.RAISE)
        return {"valid": True, "errors": []}
    except sqlglot.errors.SqlglotError as e:
        return {"valid": False, "errors": [str(e)]}


@tool
def explain_query(sql: str) -> str:
    """Return a plain-English description of what the SQL query does."""
    # The agent reasons over the query using its own LLM capability.
    # This tool acts as a signal for the agent to produce an explanation;
    # the agent will call this tool and then generate the explanation in its response.
    return f"Please explain the following SQL query in plain English:\n\n{sql}"


tools.extend([format_sql, validate_sql, explain_query])


def _make_conversation_manager():
    return NullConversationManager()

# Reuses one Agent per session_id so each session keeps its own in-process
# conversation history (best-effort; resets on cold start). The cache is bounded
# to 128 sessions with LRU eviction (least-recently-used is dropped and its
# history reset) so a single process serving many sessions cannot leak history
# between them or grow without limit. For durable history, attach a session manager.
def agent_factory():
    cache = OrderedDict()
    def get_or_create_agent(session_id):
        if session_id in cache:
            cache.move_to_end(session_id)
            return cache[session_id]
        if len(cache) >= 128:
            cache.popitem(last=False)
        agent_tools = list(tools)
        for mcp_client in _get_mcp_clients():
            if mcp_client:
                agent_tools.append(mcp_client)
        cache[session_id] = Agent(
            model=load_model(),
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            tools=agent_tools,
            conversation_manager=_make_conversation_manager(),
            hooks=[
            ],
        )
        return cache[session_id]
    return get_or_create_agent
get_or_create_agent = agent_factory()


def _extract_prompt(payload: dict):
    """Accept harness-style messages[], tool_results[], or plain prompt string payloads."""
    if "messages" in payload:
        return payload["messages"]
    if "tool_results" in payload:
        return [{"role": "user", "content": [{"toolResult": {
            "toolUseId": tr["toolUseId"],
            "status": tr.get("status", "success"),
            "content": tr.get("content", []),
        }} for tr in payload["tool_results"]]}]
    return payload.get("prompt", "")


def _has_inline_function_call(messages) -> bool:
    """Return True if messages contains an assistant toolUse for an inline function tool."""
    if not _INLINE_FUNCTION_NAMES or not isinstance(messages, list):
        return False
    for msg in messages:
        if msg.get("role") == "assistant":
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("toolUse", {}).get("name") in _INLINE_FUNCTION_NAMES:
                    return True
    return False


def _is_inline_function_call(event: dict) -> bool:
    """Check if a contentBlockStart event is for an inline function tool."""
    if not _INLINE_FUNCTION_NAMES:
        return False
    cbs = event.get("contentBlockStart", {})
    start = cbs.get("start", {})
    tool_use = start.get("toolUse") if isinstance(start, dict) else None
    return tool_use is not None and tool_use.get("name") in _INLINE_FUNCTION_NAMES



@app.entrypoint
async def invoke(payload, context):
    log.info("Invoking Agent.....")


    session_id = getattr(context, 'session_id', 'default-session')
    agent = get_or_create_agent(session_id)

    prompt = _extract_prompt(payload)


    async for event in agent.stream_async(
        prompt,
    ):
        if not isinstance(event, dict) or "event" not in event:
            continue
        cbs = event["event"].get("contentBlockStart")
        if cbs is not None and not cbs.get("start"):
            continue
        yield event


if __name__ == "__main__":
    app.run()
