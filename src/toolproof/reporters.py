"""Output formats for a run: rich console summary, JUnit XML and JSON."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from toolproof.runner import RunReport

# ---------- console ----------


def print_report(report: RunReport, console: Console | None = None) -> None:
    """Print checks, tests and a one-line summary."""
    console = console or Console()
    label = report.server_name or report.target
    if report.server_version:
        label += f" {report.server_version}"
    console.print(f"[bold]toolproof[/bold] - {label}\n")

    if report.checks:
        table = Table(title="Static checks", title_justify="left", show_lines=False)
        table.add_column("", width=4)
        table.add_column("Tool")
        table.add_column("Check")
        table.add_column("Problem")
        for check in report.checks:
            mark = (
                Text("FAIL", style="red")
                if check.severity == "error" or report.strict
                else Text("WARN", style="yellow")
            )
            table.add_row(mark, check.tool, check.check, check.message)
        console.print(table)
        console.print()

    if report.tests:
        table = Table(title="Tests", title_justify="left")
        table.add_column("", width=4)
        table.add_column("Test")
        table.add_column("Tool")
        table.add_column("Time", justify="right")
        table.add_column("Details")
        for test in report.tests:
            mark = Text("PASS", style="green") if test.passed else Text("FAIL", style="red")
            details = "\n".join(test.failures)
            if test.attempts > 1:
                details = (details + f"\n(after {test.attempts} attempts)").strip()
            table.add_row(mark, test.name, test.tool, f"{test.latency_ms:.0f}ms", details)
        console.print(table)
        console.print()

        for test in report.tests:
            if test.server_stderr:
                console.print(f"[red]Server stderr during '{test.name}':[/red]")
                console.print(test.server_stderr, markup=False, highlight=False)
                console.print()

    if report.evals is not None:
        _print_evals(report, console)
    if report.bench:
        _print_bench(report, console)
    if report.fuzz:
        _print_fuzz(report, console)

    if report.error:
        console.print(f"[red bold]Error:[/red bold] {report.error}", markup=True)

    console.print(_summary_line(report))


def _print_evals(report: RunReport, console: Console) -> None:
    ev = report.evals
    assert ev is not None
    who = " / ".join(x for x in (ev.provider, ev.model) if x)
    title = f"Tool-selection evals ({who})" if who else "Tool-selection evals"
    table = Table(title=title, title_justify="left")
    table.add_column("", width=4)
    table.add_column("Case")
    table.add_column("Expected")
    table.add_column("Picked")
    table.add_column("Details")
    for c in ev.cases:
        mark = Text("PASS", style="green") if c.passed else Text("MISS", style="red")
        picked = c.picked_tool or "(no tool)"
        if c.picked_args:
            picked += " " + _short_json(c.picked_args, 50)
        details = "\n".join(c.failures)
        if c.cached:
            details = (details + "\n(cached)").strip()
        table.add_row(mark, c.name, c.expect_tool or "(no tool)", picked, details)
    console.print(table)
    if ev.skipped_tools:
        names = ", ".join(ev.skipped_tools)
        console.print(f"[yellow]Left out (invalid input schema):[/yellow] {names}")
    if ev.cases:
        console.print(
            f"Accuracy {ev.accuracy:.0%} ({ev.correct}/{len(ev.cases)}), "
            f"minimum {ev.min_accuracy:.0%}\n"
        )


def _print_bench(report: RunReport, console: Console) -> None:
    table = Table(title="Bench", title_justify="left")
    table.add_column("", width=4)
    table.add_column("Target")
    table.add_column("Calls", justify="right")
    table.add_column("p50", justify="right")
    table.add_column("p95", justify="right")
    table.add_column("p99", justify="right")
    table.add_column("Calls/s", justify="right")
    table.add_column("Errors", justify="right")
    table.add_column("Details")
    for b in report.bench:
        mark = Text("PASS", style="green") if b.passed else Text("FAIL", style="red")
        details = "\n".join(b.failures)
        if b.first_error:
            details = (details + f"\nfirst error: {b.first_error}").strip()
        table.add_row(
            mark,
            b.name,
            f"{b.calls} x{b.concurrency}",
            f"{b.p50_ms:.1f}ms",
            f"{b.p95_ms:.1f}ms",
            f"{b.p99_ms:.1f}ms",
            f"{b.throughput:.1f}",
            f"{b.error_rate:.1%}",
            details,
        )
    console.print(table)
    console.print()


def _print_fuzz(report: RunReport, console: Console) -> None:
    table = Table(title=f"Fuzz (seed {report.fuzz_seed})", title_justify="left")
    table.add_column("", width=4)
    table.add_column("Tool")
    table.add_column("Calls", justify="right")
    table.add_column("Finding")
    table.add_column("Smallest input")
    table.add_column("Details")
    for f in report.fuzz:
        if f.skipped:
            table.add_row(Text("SKIP", style="yellow"), f.tool, str(f.calls), "", "", f.skipped)
            continue
        if not f.findings:
            table.add_row(Text("PASS", style="green"), f.tool, str(f.calls), "", "", "")
            continue
        for i, finding in enumerate(f.findings):
            table.add_row(
                Text("FAIL", style="red") if i == 0 else "",
                f.tool if i == 0 else "",
                str(f.calls) if i == 0 else "",
                f"{finding.kind} ({finding.mode})",
                _short_json(finding.input),
                finding.detail.splitlines()[0] if finding.detail else "",
            )
    console.print(table)
    console.print(f"Repeat this run with --seed {report.fuzz_seed}\n")


def _short_json(value: Any, limit: int = 60) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "..."


def _summary_line(report: RunReport) -> str:
    status = "[green bold]PASSED[/green bold]" if report.passed else "[red bold]FAILED[/red bold]"
    parts = [status]
    if "tests" in report.phases:
        passed = len(report.tests) - report.tests_failed
        parts.append(f"tests: {passed} passed, {report.tests_failed} failed")
    if "checks" in report.phases:
        errors = sum(1 for c in report.checks if c.severity == "error")
        parts.append(f"checks: {errors} errors, {len(report.checks) - errors} warnings")
    if "evals" in report.phases and report.evals is not None:
        ev = report.evals
        parts.append(f"evals: {ev.accuracy:.0%} accuracy ({ev.correct}/{len(ev.cases)})")
    if "bench" in report.phases:
        failed = sum(1 for b in report.bench if not b.passed)
        parts.append(f"bench: {len(report.bench) - failed} passed, {failed} failed")
    if "fuzz" in report.phases:
        findings = sum(len(f.findings) for f in report.fuzz)
        failed = sum(1 for f in report.fuzz if not f.passed)
        parts.append(f"fuzz: {findings} findings in {failed} tools")
    parts.append(f"{report.duration_s:.2f}s")
    return "  |  ".join(parts)


# ---------- JUnit XML ----------


def write_junit(report: RunReport, path: str | Path) -> None:
    """Write a JUnit XML file that CI systems (GitHub, GitLab, Jenkins) can display.

    Each phase that ran gets its own suite: "static checks" and "fuzz" have one
    test case per tool, "tests" one per test case, "bench" one per target.
    """
    root = ET.Element("testsuites", name="toolproof")
    if "checks" in report.phases:
        _junit_checks(root, report)
    if "tests" in report.phases or report.error:
        _junit_tests(root, report)
    if "evals" in report.phases and report.evals is not None:
        _junit_evals(root, report)
    if "bench" in report.phases:
        _junit_bench(root, report)
    if "fuzz" in report.phases:
        _junit_fuzz(root, report)

    tree = ET.ElementTree(root)
    ET.indent(tree)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _junit_checks(root: ET.Element, report: RunReport) -> None:
    checks_suite = ET.SubElement(root, "testsuite", name="static checks")
    by_tool: dict[str, list[str]] = {name: [] for name in report.tool_names}
    for check in report.checks:
        if check.severity == "error" or report.strict:
            by_tool.setdefault(check.tool, []).append(f"[{check.check}] {check.message}")
    for tool, messages in by_tool.items():
        case = ET.SubElement(checks_suite, "testcase", classname="toolproof.checks", name=tool)
        if messages:
            failure = ET.SubElement(case, "failure", message=messages[0])
            failure.text = "\n".join(messages)
    failed_tools = sum(1 for messages in by_tool.values() if messages)
    _set_counts(checks_suite, total=len(by_tool), failures=failed_tools, time_s=0.0)


def _junit_tests(root: ET.Element, report: RunReport) -> None:
    tests_suite = ET.SubElement(root, "testsuite", name="tests")
    for test in report.tests:
        case = ET.SubElement(
            tests_suite,
            "testcase",
            classname=f"toolproof.{test.tool}",
            name=test.name,
            time=f"{test.latency_ms / 1000:.3f}",
        )
        if not test.passed:
            failure = ET.SubElement(case, "failure", message=test.failures[0])
            failure.text = "\n".join(test.failures)
        if test.server_stderr:
            ET.SubElement(case, "system-err").text = test.server_stderr
    if report.error:
        case = ET.SubElement(tests_suite, "testcase", classname="toolproof", name="connect")
        ET.SubElement(case, "error", message="server error").text = report.error
    _set_counts(
        tests_suite,
        total=len(report.tests) + (1 if report.error else 0),
        failures=report.tests_failed,
        errors=1 if report.error else 0,
        time_s=sum(t.latency_ms for t in report.tests) / 1000,
    )


def _junit_evals(root: ET.Element, report: RunReport) -> None:
    """One case for the accuracy threshold, then one per eval case.

    A single wrong pick isn't a failure on its own: `min_accuracy` decides
    whether the run fails, so misses are listed in <system-out> instead.
    """
    ev = report.evals
    assert ev is not None
    suite = ET.SubElement(root, "testsuite", name="evals")
    accuracy = ET.SubElement(suite, "testcase", classname="toolproof.evals", name="accuracy")
    ET.SubElement(accuracy, "system-out").text = (
        f"provider={ev.provider} model={ev.model} accuracy={ev.accuracy:.2%} "
        f"({ev.correct}/{len(ev.cases)}) minimum={ev.min_accuracy:.2%}"
    )
    if not ev.passed:
        message = ev.error or f"accuracy {ev.accuracy:.0%} is below {ev.min_accuracy:.0%}"
        ET.SubElement(accuracy, "failure", message=message).text = message
    for c in ev.cases:
        case = ET.SubElement(suite, "testcase", classname="toolproof.evals", name=c.name)
        picked = c.picked_tool or "no tool"
        status = "correct" if c.passed else "MISS: " + "; ".join(c.failures)
        ET.SubElement(
            case, "system-out"
        ).text = f"prompt: {c.prompt}\npicked: {picked} {_short_json(c.picked_args, 300)}\n{status}"
    _set_counts(suite, total=len(ev.cases) + 1, failures=0 if ev.passed else 1, time_s=0.0)


def _junit_bench(root: ET.Element, report: RunReport) -> None:
    suite = ET.SubElement(root, "testsuite", name="bench")
    for b in report.bench:
        case = ET.SubElement(
            suite,
            "testcase",
            classname=f"toolproof.bench.{b.tool}",
            name=b.name,
            time=f"{b.duration_s:.3f}",
        )
        ET.SubElement(case, "system-out").text = (
            f"calls={b.calls} concurrency={b.concurrency} p50={b.p50_ms:.1f}ms "
            f"p95={b.p95_ms:.1f}ms p99={b.p99_ms:.1f}ms throughput={b.throughput:.1f}/s "
            f"error_rate={b.error_rate:.2%}"
        )
        if not b.passed:
            failure = ET.SubElement(case, "failure", message=b.failures[0])
            failure.text = "\n".join(b.failures)
    failed = sum(1 for b in report.bench if not b.passed)
    _set_counts(
        suite,
        total=len(report.bench),
        failures=failed,
        time_s=sum(b.duration_s for b in report.bench),
    )


def _junit_fuzz(root: ET.Element, report: RunReport) -> None:
    suite = ET.SubElement(root, "testsuite", name="fuzz")
    for f in report.fuzz:
        case = ET.SubElement(
            suite,
            "testcase",
            classname="toolproof.fuzz",
            name=f.tool,
            time=f"{f.duration_s:.3f}",
        )
        if f.skipped:
            ET.SubElement(case, "skipped", message=f.skipped)
        elif f.findings:
            lines = [
                f"[{x.kind}, {x.mode} input] {_short_json(x.input, 500)}: {x.detail}"
                for x in f.findings
            ]
            failure = ET.SubElement(case, "failure", message=lines[0])
            failure.text = "\n".join(lines) + f"\n(seed {report.fuzz_seed})"
    _set_counts(
        suite,
        total=len(report.fuzz),
        failures=sum(1 for f in report.fuzz if not f.passed),
        skipped=sum(1 for f in report.fuzz if f.skipped),
        time_s=sum(f.duration_s for f in report.fuzz),
    )


def _set_counts(
    suite: ET.Element,
    total: int,
    failures: int,
    time_s: float,
    errors: int = 0,
    skipped: int = 0,
) -> None:
    suite.set("tests", str(total))
    suite.set("failures", str(failures))
    suite.set("errors", str(errors))
    suite.set("skipped", str(skipped))
    suite.set("time", f"{time_s:.3f}")


# ---------- JSON ----------


def report_to_dict(report: RunReport) -> dict[str, Any]:
    """A plain dict version of the report, safe to json.dump."""
    return {
        "target": report.target,
        "server": {"name": report.server_name, "version": report.server_version},
        "passed": report.passed,
        "duration_s": round(report.duration_s, 3),
        "error": report.error,
        "checks": [
            {
                "tool": c.tool,
                "check": c.check,
                "severity": c.severity,
                "message": c.message,
            }
            for c in report.checks
        ],
        "tests": [
            {
                "name": t.name,
                "tool": t.tool,
                "passed": t.passed,
                "failures": t.failures,
                "latency_ms": round(t.latency_ms, 1),
                "attempts": t.attempts,
                "is_error": t.result.is_error if t.result else None,
                "text": t.result.text if t.result else None,
                "server_stderr": t.server_stderr or None,
            }
            for t in report.tests
        ],
        "bench": [
            {
                "name": b.name,
                "tool": b.tool,
                "passed": b.passed,
                "failures": b.failures,
                "calls": b.calls,
                "concurrency": b.concurrency,
                "errors": b.errors,
                "error_rate": round(b.error_rate, 4),
                "throughput": round(b.throughput, 2),
                "p50_ms": round(b.p50_ms, 2),
                "p95_ms": round(b.p95_ms, 2),
                "p99_ms": round(b.p99_ms, 2),
                "mean_ms": round(b.mean_ms, 2),
                "max_ms": round(b.max_ms, 2),
                "first_error": b.first_error,
            }
            for b in report.bench
        ],
        "fuzz": {
            "seed": report.fuzz_seed,
            "tools": [
                {
                    "tool": f.tool,
                    "passed": f.passed,
                    "calls": f.calls,
                    "skipped": f.skipped,
                    "duration_s": round(f.duration_s, 2),
                    "findings": [
                        {"kind": x.kind, "mode": x.mode, "input": x.input, "detail": x.detail}
                        for x in f.findings
                    ],
                }
                for f in report.fuzz
            ],
        },
        "evals": _evals_to_dict(report),
        "summary": {
            "phases": report.phases,
            "tests": len(report.tests),
            "failed": report.tests_failed,
            "check_errors": sum(1 for c in report.checks if c.severity == "error"),
            "check_warnings": sum(1 for c in report.checks if c.severity == "warning"),
            "bench_failed": sum(1 for b in report.bench if not b.passed),
            "fuzz_findings": sum(len(f.findings) for f in report.fuzz),
            "eval_accuracy": round(report.evals.accuracy, 4) if report.evals else None,
        },
    }


def _evals_to_dict(report: RunReport) -> dict[str, Any] | None:
    ev = report.evals
    if ev is None:
        return None
    return {
        "provider": ev.provider,
        "model": ev.model,
        "passed": ev.passed,
        "accuracy": round(ev.accuracy, 4),
        "correct": ev.correct,
        "min_accuracy": ev.min_accuracy,
        "error": ev.error,
        "skipped_tools": ev.skipped_tools,
        "cases": [
            {
                "name": c.name,
                "prompt": c.prompt,
                "passed": c.passed,
                "expect_tool": c.expect_tool,
                "expect_args": c.expect_args,
                "picked_tool": c.picked_tool,
                "picked_args": c.picked_args,
                "failures": c.failures,
                "cached": c.cached,
            }
            for c in ev.cases
        ],
    }


def write_json(report: RunReport, path: str | Path) -> None:
    Path(path).write_text(json.dumps(report_to_dict(report), indent=2), encoding="utf-8")


# ---------- Markdown summary ----------


def render_markdown(report: RunReport) -> str:
    """A short Markdown summary, for GitHub's job summary or a PR comment."""

    def cell(value: Any) -> str:
        # Keep cells on one line, and stop text from the server breaking the table.
        return str(value).replace("|", "\\|").replace("\n", " ").strip()

    status = "Passed" if report.passed else "Failed"
    icon = "✅" if report.passed else "❌"
    name = report.server_name or report.target
    lines = [
        f"## {icon} toolproof: {status}",
        "",
        f"`{cell(name)}` in {report.duration_s:.1f}s",
        "",
    ]
    if report.error:
        lines += [f"**Error:** {cell(report.error)}", ""]

    rows: list[tuple[str, str, bool]] = []
    if "checks" in report.phases:
        errors = sum(1 for c in report.checks if c.severity == "error")
        warnings = len(report.checks) - errors
        rows.append(
            ("Static checks", f"{errors} errors, {warnings} warnings", not report.checks_failed)
        )
    if "tests" in report.phases:
        passed = len(report.tests) - report.tests_failed
        rows.append(("Tests", f"{passed}/{len(report.tests)} passed", report.tests_failed == 0))
    if "evals" in report.phases and report.evals is not None:
        ev = report.evals
        detail = ev.error or f"{ev.accuracy:.0%} accuracy, minimum {ev.min_accuracy:.0%}"
        rows.append(("Evals", detail, ev.passed))
    if "bench" in report.phases:
        failed = sum(1 for b in report.bench if not b.passed)
        within = f"{len(report.bench) - failed}/{len(report.bench)} within limits"
        rows.append(("Bench", within, failed == 0))
    if "fuzz" in report.phases:
        findings = sum(len(f.findings) for f in report.fuzz)
        rows.append(("Fuzz", f"{findings} findings (seed {report.fuzz_seed})", findings == 0))
    if rows:
        lines += ["| | Phase | Result |", "|---|---|---|"]
        lines += [f"| {'✅' if ok else '❌'} | {p} | {cell(r)} |" for p, r, ok in rows]
        lines.append("")

    problems = [
        f"- **{cell(t.name)}**: {cell(t.failures[0])}" for t in report.tests if not t.passed
    ]
    problems += [
        f"- **fuzz {cell(f.tool)}**: {cell(x.kind)} with `{cell(_short_json(x.input, 80))}`"
        for f in report.fuzz
        for x in f.findings
    ]
    problems += [
        f"- **bench {cell(b.name)}**: {cell(b.failures[0])}" for b in report.bench if not b.passed
    ]
    if report.evals is not None:
        problems += [
            f"- **eval {cell(c.name)}**: {cell(c.failures[0])}"
            for c in report.evals.cases
            if not c.passed
        ]
    if problems:
        lines += ["<details><summary>Failures</summary>", "", *problems[:50], "", "</details>", ""]
    return "\n".join(lines)


def write_markdown(report: RunReport, path: str | Path) -> None:
    """Write the Markdown summary. Appends, so it works with $GITHUB_STEP_SUMMARY."""
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(render_markdown(report) + "\n")
