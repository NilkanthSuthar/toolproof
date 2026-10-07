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

    if report.bench:
        _print_bench(report, console)
    if report.fuzz:
        _print_fuzz(report, console)

    if report.error:
        console.print(f"[red bold]Error:[/red bold] {report.error}", markup=True)

    console.print(_summary_line(report))


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
        "summary": {
            "phases": report.phases,
            "tests": len(report.tests),
            "failed": report.tests_failed,
            "check_errors": sum(1 for c in report.checks if c.severity == "error"),
            "check_warnings": sum(1 for c in report.checks if c.severity == "warning"),
            "bench_failed": sum(1 for b in report.bench if not b.passed),
            "fuzz_findings": sum(len(f.findings) for f in report.fuzz),
        },
    }


def write_json(report: RunReport, path: str | Path) -> None:
    Path(path).write_text(json.dumps(report_to_dict(report), indent=2), encoding="utf-8")
