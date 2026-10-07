# Reports

Every command prints a summary to the console. `run`, `fuzz` and `bench` can also write report files:

```bash
toolproof run toolproof.yaml --junit report.xml --json report.json
```

## Console

One table per phase that ran, then a summary line:

```
PASSED  |  tests: 7 passed, 0 failed  |  checks: 0 errors, 0 warnings  |  bench: 4 passed, 0 failed  |  fuzz: 0 findings in 0 tools  |  6.56s
```

When the server crashes during a test, its last stderr lines are printed under the tests table.

## JUnit XML

Standard JUnit XML that GitHub, GitLab, Jenkins, Azure DevOps and most CI systems display as a test report. Each phase that ran gets a `<testsuite>`; see [Running in CI](../guide/ci.md#junit-layout) for the layout.

## JSON

A single object. Field names are stable within a major version; new fields may be added in minor versions.

```json
{
  "target": "python weather_server.py",
  "server": { "name": "weather", "version": "1.0.0" },
  "passed": true,
  "duration_s": 6.56,
  "error": null,
  "checks": [
    { "tool": "search", "check": "description", "severity": "error", "message": "tool has no description" }
  ],
  "tests": [
    {
      "name": "toronto weather",
      "tool": "get_weather",
      "passed": true,
      "failures": [],
      "latency_ms": 8.1,
      "attempts": 1,
      "is_error": false,
      "text": "{\"city\": \"Toronto\", \"temp_c\": 12.5, \"conditions\": \"cloudy\"}",
      "server_stderr": null
    }
  ],
  "bench": [
    {
      "name": "toronto weather",
      "tool": "get_weather",
      "passed": true,
      "failures": [],
      "calls": 50,
      "concurrency": 5,
      "errors": 0,
      "error_rate": 0.0,
      "throughput": 583.0,
      "p50_ms": 8.3,
      "p95_ms": 10.8,
      "p99_ms": 11.9,
      "mean_ms": 8.7,
      "max_ms": 12.4,
      "first_error": null
    }
  ],
  "fuzz": {
    "seed": 1,
    "tools": [
      {
        "tool": "get_weather",
        "passed": false,
        "calls": 26,
        "skipped": null,
        "duration_s": 23.2,
        "findings": [
          { "kind": "crash", "mode": "valid", "input": { "city": "" }, "detail": "connection lost, server probably crashed (Connection closed)" }
        ]
      }
    ]
  },
  "summary": {
    "phases": ["checks", "tests", "bench", "fuzz"],
    "tests": 1,
    "failed": 0,
    "check_errors": 1,
    "check_warnings": 0,
    "bench_failed": 0,
    "fuzz_findings": 1
  }
}
```

The example is shortened and mixes runs to show every section; a real report only fills the sections for the phases that ran.
