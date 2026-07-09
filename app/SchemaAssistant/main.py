from collections import OrderedDict
from strands import Agent, tool
from dotenv import load_dotenv
load_dotenv()
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model
from mcp_client.client import get_streamable_http_mcp_client
from shared.sql_tools import validate_sql, format_sql

app = BedrockAgentCoreApp()
log = app.logger

_mcp_clients = None

def _get_mcp_clients():
    global _mcp_clients
    if _mcp_clients is None:
        _mcp_clients = [get_streamable_http_mcp_client()]
    return _mcp_clients

DEFAULT_SYSTEM_PROMPT = """
You are a senior database architect assistant that helps users design, generate, and document SQL schemas.

Guidelines:
- Always validate DDL before returning it to the user.
- Use explicit NOT NULL constraints and appropriate data types.
- Write ANSI SQL unless the user specifies a dialect (e.g., BigQuery, Postgres, Snowflake).
- Use your tools sequentially: generate or describe, then validate, then format.
"""

tools = []

_INLINE_FUNCTION_NAMES = set()


@tool
def generate_create_table(description: str) -> str:
    """Signal the agent to generate a CREATE TABLE DDL statement from a plain-English description."""
    return f"Generate a CREATE TABLE DDL statement for the following entity:\n\n{description}"


@tool
def suggest_indexes(schema_ddl: str, query: str) -> str:
    """Signal the agent to suggest indexes given a schema DDL and a slow query."""
    return f"Given this schema:\n\n{schema_ddl}\n\nAnd this query:\n\n{query}\n\nSuggest appropriate CREATE INDEX statements with reasoning."


@tool
def describe_schema(ddl: str) -> str:
    """Signal the agent to describe a schema DDL in plain English."""
    return f"Describe the following SQL schema in plain English, covering tables, columns, and relationships:\n\n{ddl}"


tools.extend([validate_sql, format_sql, generate_create_table, suggest_indexes, describe_schema])


def _make_conversation_manager():
    return NullConversationManager()


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
            hooks=[],
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
    if not _INLINE_FUNCTION_NAMES or not isinstance(messages, list):
        return False
    for msg in messages:
        if msg.get("role") == "assistant":
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("toolUse", {}).get("name") in _INLINE_FUNCTION_NAMES:
                    return True
    return False


def _is_inline_function_call(event: dict) -> bool:
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

    async for event in agent.stream_async(prompt):
        if not isinstance(event, dict) or "event" not in event:
            continue
        cbs = event["event"].get("contentBlockStart")
        if cbs is not None and not cbs.get("start"):
            continue
        yield event


if __name__ == "__main__":
    app.run()
