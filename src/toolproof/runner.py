"""Run static checks, test cases, benchmarks and fuzzing against a server."""

from __future__ import annotations

import time
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Literal

import anyio
import mcp_types as types

from toolproof.assertions import check_expectations
from toolproof.bench import BenchResult, run_bench
from toolproof.checks import CheckResult, has_failures, run_checks
from toolproof.client import CallResult, McpServer, ServerError
from toolproof.config import Config, TestCase
from toolproof.fuzz import FuzzResult, run_fuzz

Phase = Literal["checks", "tests", "bench", "fuzz"]


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
    phases: list[str] = field(default_factory=list)
    server_name: str | None = None
    server_version: str | None = None
    tool_names: list[str] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    tests: list[TestResult] = field(default_factory=list)
    bench: list[BenchResult] = field(default_factory=list)
    fuzz: list[FuzzResult] = field(default_factory=list)
    fuzz_seed: int | None = None
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
        return (
            self.error is None
            and not self.checks_failed
            and self.tests_failed == 0
            and all(b.passed for b in self.bench)
            and all(f.passed for f in self.fuzz)
        )


def default_phases(config: Config) -> list[Phase]:
    """What `toolproof run` does: checks and tests, plus bench/fuzz if configured."""
    phases: list[Phase] = ["checks", "tests"]
    if config.bench is not None and config.bench.enabled:
        phases.append("bench")
    if config.fuzz is not None and config.fuzz.enabled:
        phases.append("fuzz")
    return phases


def run_config(config: Config, phases: Collection[Phase] | None = None) -> RunReport:
    """Synchronous entry point used by the CLI."""
    return anyio.run(run_config_async, config, phases)


async def run_config_async(config: Config, phases: Collection[Phase] | None = None) -> RunReport:
    """Connect to the server and run the requested phases in order.

    Fuzzing goes last because it is the most likely to crash or wedge the server.
    """
    phases = default_phases(config) if phases is None else phases
    started = time.perf_counter()
    report = RunReport(
        target=describe_target(config), phases=list(phases), strict=config.checks.strict
    )

    try:
        async with McpServer(config.server, base_dir=config.base_dir) as server:
            info = server.client.server_info
            if info is not None:
                report.server_name, report.server_version = info.name, info.version

            tools = await server.list_tools()
            report.tool_names = [tool.name for tool in tools]

            if "checks" in phases and config.checks.enabled:
                report.checks = run_checks(tools, config.checks)

            if "tests" in phases:
                tools_by_name = {tool.name: tool for tool in tools}
                for case in config.tests:
                    report.tests.append(await _run_test(server, case, tools_by_name, config))

            if "bench" in phases and config.bench is not None:
                report.bench = await run_bench(server, config.bench, config.tests)

            if "fuzz" in phases and config.fuzz is not None:
                report.fuzz, report.fuzz_seed = await run_fuzz(server, tools, config.fuzz)
    except ServerError as exc:
        report.error = str(exc)

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
