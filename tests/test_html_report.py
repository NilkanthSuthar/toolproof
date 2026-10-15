"""The HTML and Markdown reports, built from hand-made reports."""

import re

from toolproof.bench import BenchResult
from toolproof.checks import CheckResult
from toolproof.client import CallResult
from toolproof.evals import EvalCaseResult, EvalReport
from toolproof.fuzz import FuzzFinding, FuzzResult
from toolproof.html_report import render_html
from toolproof.reporters import render_markdown
from toolproof.runner import RunReport, TestResult

EVIL = '<script>alert("x")</script><img src=x onerror=alert(1)>'


def hostile_report() -> RunReport:
    """A report where everything the server controls contains HTML."""
    result = CallResult(
        tool="t", arguments={}, is_error=True, text=EVIL, structured=None, latency_ms=12
    )
    return RunReport(
        target=f"python {EVIL}",
        phases=["checks", "tests", "evals", "bench", "fuzz"],
        server_name=EVIL,
        tool_names=[EVIL],
        checks=[CheckResult("description", EVIL, "error", EVIL)],
        tests=[
            TestResult(
                name=EVIL,
                tool=EVIL,
                passed=False,
                failures=[EVIL],
                latency_ms=12,
                result=result,
                server_stderr=EVIL,
            )
        ],
        bench=[
            BenchResult(
                name=EVIL,
                tool=EVIL,
                calls=10,
                concurrency=2,
                errors=1,
                duration_s=0.5,
                p50_ms=1,
                p95_ms=2,
                p99_ms=3,
                mean_ms=1.5,
                max_ms=4,
                failures=[EVIL],
                first_error=EVIL,
            )
        ],
        fuzz=[
            FuzzResult(
                tool=EVIL, calls=3, findings=[FuzzFinding("crash", "valid", {EVIL: EVIL}, EVIL)]
            )
        ],
        fuzz_seed=7,
        evals=EvalReport(
            provider="command",
            model=EVIL,
            min_accuracy=1.0,
            cases=[
                EvalCaseResult(
                    name=EVIL,
                    prompt=EVIL,
                    expect_tool=EVIL,
                    expect_args={},
                    picked_tool=EVIL,
                    picked_args={EVIL: EVIL},
                    failures=[EVIL],
                )
            ],
        ),
    )


def test_server_text_is_escaped():
    page = render_html(hostile_report())
    assert "<script" not in page.lower()
    assert "<img" not in page  # only the escaped text, never a real tag
    assert "&lt;script&gt;" in page


def test_page_is_self_contained():
    page = render_html(hostile_report())
    # No external scripts, styles, fonts or images: it must work offline.
    assert not re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", page)
    assert "<link" not in page


def test_every_phase_has_a_section():
    page = render_html(hostile_report())
    for heading in ["Static checks", "Tests", "Benchmarks", "Fuzzing", "Tool-selection evals"]:
        assert heading in page


def test_only_phases_that_ran_are_shown():
    page = render_html(RunReport(target="x", phases=["tests"]))
    assert "Tests" in page
    assert "Benchmarks" not in page and "Fuzzing" not in page


def test_markdown_summary():
    md = render_markdown(hostile_report())
    assert md.startswith("## ❌ toolproof: Failed")
    for phase in ["Static checks", "Tests", "Evals", "Bench", "Fuzz"]:
        assert f"| {phase} |" in md
    # Pipes from the server can't break the table.
    report = RunReport(target="x", phases=["tests"])
    report.tests = [TestResult(name="a|b", tool="t", passed=False, failures=["c|d"])]
    assert "a\\|b" in render_markdown(report)
