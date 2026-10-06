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

    if report.error:
        console.print(f"[red bold]Error:[/red bold] {report.error}", markup=True)

    console.print(_summary_line(report))


def _summary_line(report: RunReport) -> str:
    errors = sum(1 for c in report.checks if c.severity == "error")
    warnings = len(report.checks) - errors
    passed = len(report.tests) - report.tests_failed
    status = "[green bold]PASSED[/green bold]" if report.passed else "[red bold]FAILED[/red bold]"
    return (
        f"{status}  tests: {passed} passed, {report.tests_failed} failed  |  "
        f"checks: {errors} errors, {warnings} warnings  |  {report.duration_s:.2f}s"
    )


# ---------- JUnit XML ----------


def write_junit(report: RunReport, path: str | Path) -> None:
    """Write a JUnit XML file that CI systems (GitHub, GitLab, Jenkins) can display.

    Static checks become one test case per tool in a "static checks" suite.
    Test cases go in a "tests" suite.
    """
    root = ET.Element("testsuites", name="toolproof")

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

    tree = ET.ElementTree(root)
    ET.indent(tree)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _set_counts(
    suite: ET.Element, total: int, failures: int, time_s: float, errors: int = 0
) -> None:
    suite.set("tests", str(total))
    suite.set("failures", str(failures))
    suite.set("errors", str(errors))
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
        "summary": {
            "tests": len(report.tests),
            "failed": report.tests_failed,
            "check_errors": sum(1 for c in report.checks if c.severity == "error"),
            "check_warnings": sum(1 for c in report.checks if c.severity == "warning"),
        },
    }


def write_json(report: RunReport, path: str | Path) -> None:
    Path(path).write_text(json.dumps(report_to_dict(report), indent=2), encoding="utf-8")
