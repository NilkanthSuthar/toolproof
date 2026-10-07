# Changelog

All notable changes to toolproof are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `headers:` for HTTP servers, sent with every request (for example `Authorization`).
- `${NAME}` in the `server:` section of toolproof.yaml is replaced with the environment variable `NAME`, so secrets can come from CI instead of the file. An unset variable is a clear error.
- `run_config`, `run_config_async`, `RunReport` and `ConfigError` are exported from `toolproof` as public API.
- The package ships a `py.typed` marker, so type checkers use toolproof's type hints.
- Documentation site with guides, recipes and a full reference.

### Fixed

- `import toolproof` and the pytest plugin no longer load Hypothesis up front. It's loaded the first time fuzzing runs.

## [0.2.0] - 2026-10-07

### Added

- `toolproof fuzz`: generates valid and invalid inputs from each tool's input schema with Hypothesis and reports crashes, hangs, internal errors, leaked tracebacks, outputSchema violations and invalid input that was accepted, each shrunk to the smallest failing input.
- Fuzzing restarts a crashed server and keeps going, skips tools marked destructive by default, and prints its seed so a run can be repeated.
- `toolproof bench`: p50/p95/p99 latency, throughput and error rate at a chosen concurrency, with thresholds that fail the run.
- `bench:` and `fuzz:` sections in toolproof.yaml; `toolproof run` includes them when present (`--skip-bench`, `--skip-fuzz`).
- Fuzz and bench results in the console, JUnit and JSON reports.
- `fuzz`, `bench` and `inspect` fall back to `./toolproof.yaml` when no server is given.

## [0.1.0] - 2026-10-06

First release.

### Added

- `toolproof inspect`: list a server's tools, resources and prompts (table or `--json`).
- Static checks for tool definitions: names, descriptions, input/output JSON Schemas, required fields.
- YAML test cases with `is_error`, `equals`, `contains`, `regex`, `jsonpath`, `max_latency_ms` and automatic `outputSchema` validation.
- `toolproof run` with per-test timeouts, retries, crash detection and automatic server restart.
- Console, JUnit XML and JSON reports; exit code 0/1 for CI.
- pytest plugin with an `mcp_server` fixture.
- stdio and streamable HTTP transports.
- Example weather server and a buggy server with planted bugs.

[Unreleased]: https://github.com/NilkanthSuthar/toolproof/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/NilkanthSuthar/toolproof/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/NilkanthSuthar/toolproof/releases/tag/v0.1.0
