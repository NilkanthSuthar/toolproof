from tests.conftest import BUGGY, WEATHER
from toolproof.bench import BenchResult, check_thresholds, percentile, targets_from_tests
from toolproof.config import BenchThresholds, TestCase
from toolproof.runner import run_config


def test_percentile_nearest_rank():
    values = [float(v) for v in range(1, 101)]
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile(values, 99) == 99
    assert percentile(values, 100) == 100
    assert percentile([7.0], 99) == 7
    assert percentile([], 50) == 0


def result(**kwargs):
    defaults = dict(
        name="t",
        tool="t",
        calls=100,
        concurrency=1,
        errors=0,
        duration_s=1.0,
        p50_ms=10,
        p95_ms=20,
        p99_ms=30,
        mean_ms=12,
        max_ms=40,
    )
    return BenchResult(**{**defaults, **kwargs})


def test_thresholds():
    r = result(errors=5)
    assert check_thresholds(r, BenchThresholds()) == []
    assert check_thresholds(r, BenchThresholds(p95_ms=25, p99_ms=40)) == []
    assert "p95 20.0ms is over 15ms" in check_thresholds(r, BenchThresholds(p95_ms=15))
    assert "error rate 5.0% is over 1.0%" in check_thresholds(
        r, BenchThresholds(max_error_rate=0.01)
    )
    assert "throughput 100.0/s is under 500/s" in check_thresholds(
        r, BenchThresholds(min_throughput=500)
    )


def test_targets_default_to_tests_that_expect_success():
    tests = [
        TestCase(name="ok", tool="a", args={"x": 1}),
        TestCase.model_validate({"name": "err", "tool": "a", "expect": {"is_error": True}}),
    ]
    targets = targets_from_tests(tests)
    assert [(t.label, t.args) for t in targets] == [("ok", {"x": 1})]


def test_bench_weather_server(write_config):
    config = write_config(
        WEATHER,
        [{"name": "toronto", "tool": "get_weather", "args": {"city": "Toronto"}}],
        bench={"calls": 40, "concurrency": 8, "thresholds": {"max_error_rate": 0}},
    )
    report = run_config(config, ["bench"])
    assert report.error is None
    [b] = report.bench
    assert b.name == "toronto"
    assert b.calls == 40
    assert b.errors == 0
    assert 0 < b.p50_ms <= b.p95_ms <= b.p99_ms <= b.max_ms
    assert b.throughput > 0
    assert report.passed


def test_bench_threshold_fails_the_run(write_config):
    config = write_config(
        WEATHER,
        [],
        bench={
            "calls": 10,
            "targets": [
                {"tool": "list_cities", "thresholds": {"p50_ms": 0.001}},
                {"tool": "list_cities", "name": "no limits"},
            ],
        },
    )
    report = run_config(config, ["bench"])
    assert [b.passed for b in report.bench] == [False, True]
    assert "p50" in report.bench[0].failures[0]
    assert not report.passed


def test_bench_counts_errors(write_config):
    config = write_config(
        BUGGY,
        [],
        bench={
            "calls": 4,
            "concurrency": 2,
            "warmup": 0,
            "timeout_ms": 300,
            "targets": [{"tool": "slow_report", "args": {"city": "x"}}],
            "thresholds": {"max_error_rate": 0.5},
        },
    )
    report = run_config(config, ["bench"])
    [b] = report.bench
    assert b.errors == 4
    assert "timed out" in b.first_error
    assert not b.passed
