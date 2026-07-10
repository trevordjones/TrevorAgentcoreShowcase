"""Pytest wrapper for the SqlAssistant evaluation suite.

Each test case becomes its own pytest item so failures are reported per-case.
Requires AWS credentials and LITELLM_API_KEY in the environment (or .env).

Run:
    pytest evals/test_sql_assistant_evals.py -v
"""

from collections import defaultdict

import pytest
from sql_assistant_evals import CASES, build_experiment, _make_task


@pytest.fixture(scope="module")
def eval_results():
    """Run the experiment once and return a {case_name -> [(evaluator, passed, reason)]} map."""
    experiment = build_experiment()
    report = experiment.run_evaluations(task=_make_task())

    by_case: dict[str, list[dict]] = defaultdict(list)
    for case_row, passed, score, reason in zip(
        report.cases, report.test_passes, report.scores, report.reasons
    ):
        name = case_row.get("name") or "unknown"
        by_case[name].append(
            {
                "evaluator": case_row.get("evaluator", "unknown"),
                "passed": passed,
                "score": score,
                "reason": reason,
            }
        )

    return by_case


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_case_passes_all_evaluators(case, eval_results):
    rows = eval_results.get(case.name, [])
    assert rows, f"No eval results found for case '{case.name}'"

    failures = [
        f"{r['evaluator']} (score={r['score']:.2f}): {r['reason']}"
        for r in rows
        if not r["passed"]
    ]
    assert not failures, f"Case '{case.name}' failed:\n" + "\n".join(failures)
