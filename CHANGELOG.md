# Changelog

## 0.1.0 - 2026-10-06

First release.

- `toolproof inspect`: list a server's tools, resources and prompts (table or `--json`)
- Static checks for tool definitions: names, descriptions, input/output JSON Schemas, required fields
- YAML test cases with `is_error`, `equals`, `contains`, `regex`, `jsonpath`, `max_latency_ms` and automatic `outputSchema` validation
- `toolproof run` with per-test timeouts, retries, crash detection and automatic server restart
- Console, JUnit XML and JSON reports; exit code 0/1 for CI
- pytest plugin with an `mcp_server` fixture
- stdio and streamable HTTP transports
- Example weather server and a buggy server with planted bugs
