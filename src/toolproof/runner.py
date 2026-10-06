"""Run static checks and test cases against a server and collect the results."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import anyio
import mcp_types as types

from toolproof.assertions import check_expectations
from toolproof.checks import CheckResult, has_failures, run_checks
from toolproof.client import CallResult, McpServer, ServerError
from toolproof.config import Config, TestCase


@dataclass
class TestResult:
    """The outcome of one test case."""

    __test__ = False  # stop pytest from trying to collect this class

    name: str
    tool: str
    passed: bool
    failures: list[str]
    latency_ms: float = 0.0
    attempts: int = 1
    result: CallResult | None = None
    server_stderr: str = ""


@dataclass
class RunReport:
    """Everything a reporter needs to print or write a run."""

    target: str
    server_name: str | None = None
    server_version: str | None = None
    tool_names: list[str] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    tests: list[TestResult] = field(default_factory=list)
    duration_s: float = 0.0
    strict: bool = False
    error: str | None = None

    @property
    def checks_failed(self) -> bool:
        return has_failures(self.checks, self.strict)

    @property
    def tests_failed(self) -> int:
        return sum(1 for t in self.tests if not t.passed)

    @property
    def passed(self) -> bool:
        return self.error is None and not self.checks_failed and self.tests_failed == 0


def run_config(config: Config) -> RunReport:
    """Synchronous entry point used by the CLI."""
    return anyio.run(run_config_async, config)


async def run_config_async(config: Config) -> RunReport:
    """Connect to the server, run static checks, then every test case in order."""
    started = time.perf_counter()
    report = RunReport(target=describe_target(config), strict=config.checks.strict)

    server = McpServer(config.server, base_dir=config.base_dir)
    try:
        await server.connect()
    except ServerError as exc:
        report.error = str(exc)
        report.duration_s = time.perf_counter() - started
        return report

    try:
        info = server.client.server_info
        if info is not None:
            report.server_name, report.server_version = info.name, info.version

        tools = await server.list_tools()
        report.tool_names = [tool.name for tool in tools]
        if config.checks.enabled:
            report.checks = run_checks(tools, config.checks)

        tools_by_name = {tool.name: tool for tool in tools}
        for case in config.tests:
            result = await _run_test(server, case, tools_by_name, config)
            report.tests.append(result)
    except ServerError as exc:
        report.error = str(exc)
    finally:
        await server.close()

    report.duration_s = time.perf_counter() - started
    return report


async def _run_test(
    server: McpServer,
    case: TestCase,
    tools: dict[str, types.Tool],
    config: Config,
) -> TestResult:
    tool = tools.get(case.tool)
    if tool is None:
        return TestResult(
            name=case.name,
            tool=case.tool,
            passed=False,
            failures=[f"server has no tool named {case.tool!r}"],
            attempts=0,
        )

    timeout_ms = case.timeout_ms if case.timeout_ms is not None else config.timeout_ms
    retries = case.retries if case.retries is not None else config.retries

    attempts = 0
    stderr = ""
    while True:
        attempts += 1
        result = await server.call(case.tool, case.args, timeout_s=timeout_ms / 1000)
        failures = check_expectations(result, case.expect, tool.output_schema)

        if result.transport_error and not await server.is_alive():
            # The connection broke, most likely because the server crashed.
            # Keep its last words for the report and start a fresh server
            # so the remaining tests can still run.
            stderr = server.stderr_tail()
            await server.reconnect()

        if not failures or attempts > retries:
            break

    return TestResult(
        name=case.name,
        tool=case.tool,
        passed=not failures,
        failures=failures,
        latency_ms=result.latency_ms,
        attempts=attempts,
        result=result,
        server_stderr=stderr,
    )


def describe_target(config: Config) -> str:
    """A short human-readable label for the server, e.g. 'python server.py'."""
    if config.server.url:
        return config.server.url
    return " ".join(config.server.command or [])
