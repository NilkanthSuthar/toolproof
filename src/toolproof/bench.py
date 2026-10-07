"""Benchmark tool calls: latency percentiles, throughput and error rate."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import anyio

from toolproof.client import McpServer
from toolproof.config import BenchConfig, BenchTarget, BenchThresholds, TestCase


@dataclass
class BenchResult:
    """Numbers for one benchmarked call."""

    name: str
    tool: str
    calls: int
    concurrency: int
    errors: int
    duration_s: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    mean_ms: float
    max_ms: float
    failures: list[str] = field(default_factory=list)
    first_error: str | None = None

    @property
    def error_rate(self) -> float:
        return self.errors / self.calls if self.calls else 0.0

    @property
    def throughput(self) -> float:
        """Calls per second."""
        return self.calls / self.duration_s if self.duration_s else 0.0

    @property
    def passed(self) -> bool:
        return not self.failures


def percentile(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile of an already sorted list."""
    if not sorted_values:
        return 0.0
    rank = max(1, math.ceil(pct / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


def targets_from_tests(tests: list[TestCase]) -> list[BenchTarget]:
    """Benchmark every test case that is expected to succeed."""
    return [
        BenchTarget(tool=t.tool, args=t.args, name=t.name)
        for t in tests
        if t.expect.is_error is not True
    ]


def check_thresholds(result: BenchResult, limits: BenchThresholds) -> list[str]:
    """Return a message for every threshold the result breaks."""
    failures = []
    for pct in ("p50", "p95", "p99"):
        limit = getattr(limits, f"{pct}_ms")
        value = getattr(result, f"{pct}_ms")
        if limit is not None and value > limit:
            failures.append(f"{pct} {value:.1f}ms is over {limit:g}ms")
    if limits.max_error_rate is not None and result.error_rate > limits.max_error_rate:
        failures.append(f"error rate {result.error_rate:.1%} is over {limits.max_error_rate:.1%}")
    if limits.min_throughput is not None and result.throughput < limits.min_throughput:
        failures.append(
            f"throughput {result.throughput:.1f}/s is under {limits.min_throughput:g}/s"
        )
    return failures


async def bench_target(server: McpServer, target: BenchTarget, config: BenchConfig) -> BenchResult:
    """Call one tool `config.calls` times with `config.concurrency` calls in flight."""
    timeout_s = config.timeout_ms / 1000
    for _ in range(config.warmup):
        await server.call(target.tool, target.args, timeout_s=timeout_s)

    latencies: list[float] = []
    errors = 0
    first_error: str | None = None
    remaining = config.calls

    async def worker() -> None:
        nonlocal remaining, errors, first_error
        while remaining > 0:
            remaining -= 1
            result = await server.call(target.tool, target.args, timeout_s=timeout_s)
            latencies.append(result.latency_ms)
            if result.is_error:
                errors += 1
                if first_error is None:
                    first_error = result.transport_error or result.text[:200]

    started = time.perf_counter()
    async with anyio.create_task_group() as tg:
        for _ in range(max(1, min(config.concurrency, config.calls))):
            tg.start_soon(worker)
    duration = time.perf_counter() - started

    ordered = sorted(latencies)
    result = BenchResult(
        name=target.label,
        tool=target.tool,
        calls=len(latencies),
        concurrency=config.concurrency,
        errors=errors,
        duration_s=duration,
        p50_ms=percentile(ordered, 50),
        p95_ms=percentile(ordered, 95),
        p99_ms=percentile(ordered, 99),
        mean_ms=sum(ordered) / len(ordered) if ordered else 0.0,
        max_ms=ordered[-1] if ordered else 0.0,
        first_error=first_error,
    )
    result.failures = check_thresholds(result, target.thresholds or config.thresholds)
    return result


async def run_bench(
    server: McpServer, config: BenchConfig, tests: list[TestCase]
) -> list[BenchResult]:
    """Benchmark each target in turn (one at a time, so they don't skew each other)."""
    targets = config.targets or targets_from_tests(tests)
    return [await bench_target(server, target, config) for target in targets]
