"""
Strands Evaluations suite for SqlAssistant.

Evaluators used:
  - OutputEvaluator  (LLM-as-a-judge): scores the response against a rubric.
  - ToolCalled       (deterministic):  checks that validate_sql was invoked.

Run locally:
    cd <repo-root>
    python evals/sql_assistant_evals.py

    # or via pytest
    pytest evals/test_sql_assistant_evals.py -v
"""

import os
import subprocess
import sys

# Resolve agent root so we can import its modules directly.
_AGENT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "../app/SqlAssistant")
sys.path.insert(0, os.path.abspath(_AGENT_ROOT))

from dotenv import load_dotenv

load_dotenv()


def _load_sops_secrets():
    """Decrypt agentcore/secrets/dev.enc.yaml via the sops CLI and inject into os.environ."""
    if os.environ.get("LITELLM_API_KEY"):
        return
    secrets_file = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "../agentcore/secrets/dev.enc.yaml"
    )
    try:
        result = subprocess.run(
            ["sops", "-d", secrets_file],
            capture_output=True, text=True, check=True,
        )
        for line in result.stdout.splitlines():
            if ":" in line and not line.startswith("#"):
                key, _, value = line.partition(":")
                os.environ.setdefault(key.strip(), value.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # sops unavailable or KMS access denied — rely on env vars being set externally


_load_sops_secrets()

from strands import Agent, tool
from strands_evals import Case, Experiment
from strands_evals.evaluators.deterministic import ToolCalled
from strands_evals.evaluators.output_evaluator import OutputEvaluator

from model.load import load_model
from shared.sql_tools import validate_sql, format_sql


@tool
def explain_query(sql: str) -> str:
    """Return a plain-English description of what the SQL query does."""
    return f"Please explain the following SQL query in plain English:\n\n{sql}"


DEFAULT_SYSTEM_PROMPT = """
You are a senior data analyst assistant that helps users write, understand, and validate SQL queries.

Guidelines:
- Always use the validate_sql tool to check SQL syntax before answering.
- Prefer explicit column names over SELECT *.
- Write ANSI SQL unless the user specifies a dialect (e.g., BigQuery, Postgres, Snowflake).
- Use your tools sequentially: validate, then format, then explain.
"""


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

def _make_task():
    """Return a task function that runs the SqlAssistant and captures trajectory."""

    def task(case: Case) -> dict:
        seen_ids: set[str] = set()
        tools_called: list[str] = []

        def _track_callback(**kwargs):
            # current_tool_use fires multiple times per call (once per chunk);
            # deduplicate by toolUseId so each tool name appears only once.
            ctu = kwargs.get("current_tool_use")
            if isinstance(ctu, dict) and ctu.get("name"):
                uid = ctu.get("toolUseId", ctu["name"])
                if uid not in seen_ids:
                    seen_ids.add(uid)
                    tools_called.append(ctu["name"])

        agent = Agent(
            model=load_model(),
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            tools=[validate_sql, format_sql, explain_query],
            callback_handler=_track_callback,
        )

        result = agent(case.input)

        return {
            "output": str(result),
            "trajectory": tools_called,
        }

    return task


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

CASES: list[Case] = [
    Case(
        name="validate_valid_sql",
        input=(
            "Use the validate_sql tool to check this query, then tell me if it is valid: "
            "SELECT id, name FROM users WHERE active = 1"
        ),
        expected_output="The SQL is valid.",
        expected_trajectory=["validate_sql"],
    ),
    Case(
        name="detect_invalid_sql",
        input=(
            "Use the validate_sql tool to check this query, then report any errors: "
            "SELECT * FROM WHERE id = 5"
        ),
        expected_output="The SQL contains a syntax error and is invalid.",
        expected_trajectory=["validate_sql"],
    ),
    Case(
        name="format_sql_query",
        input=(
            "First use validate_sql to check this query, then use format_sql to prettify it "
            "and return the formatted result: "
            "select id,name,email from users where active=1 order by name"
        ),
        expected_output="A formatted SQL query with uppercase keywords and consistent indentation.",
        expected_trajectory=["validate_sql", "format_sql"],
    ),
    Case(
        name="explain_aggregate_query",
        input=(
            "First use validate_sql to check this SQL, then use explain_query to describe "
            "what it does in plain English: "
            "SELECT customer_id, COUNT(*) AS order_count FROM orders GROUP BY customer_id"
        ),
        expected_output=(
            "The query counts the number of orders per customer, "
            "grouping results by customer_id."
        ),
        expected_trajectory=["validate_sql", "explain_query"],
    ),
    Case(
        name="write_and_validate_filter_query",
        input=(
            "Write a SQL query to retrieve all orders placed in the last 30 days from a table "
            "called orders with a column created_at, then use validate_sql to confirm it is valid."
        ),
        expected_output=(
            "A valid SQL SELECT statement filtering orders by created_at for the last 30 days."
        ),
        expected_trajectory=["validate_sql"],
    ),
]


# ---------------------------------------------------------------------------
# Experiment
# ---------------------------------------------------------------------------

_OUTPUT_RUBRIC = (
    "The agent correctly answered the user's SQL question. "
    "Score 1.0 if the response is accurate, complete, and directly addresses the request. "
    "Score 0.0 if the response is incorrect, incomplete, or off-topic."
)


def build_experiment() -> Experiment:
    return Experiment(
        cases=CASES,
        evaluators=[
            OutputEvaluator(rubric=_OUTPUT_RUBRIC, model=load_model(), name="output_quality"),
            ToolCalled(tool_name="validate_sql", name="validate_sql_called"),
        ],
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run():
    experiment = build_experiment()
    report = experiment.run_evaluations(task=_make_task())
    report.display()
    return report


if __name__ == "__main__":
    run()
