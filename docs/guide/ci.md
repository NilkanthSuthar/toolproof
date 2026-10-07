# Running in CI

Every command exits with `0` when everything passed, `1` when a test, check, threshold or fuzz finding failed, and `2` for a usage or configuration error. Add `--junit report.xml` for a test report your CI can display, or `--json report.json` for your own tooling.

## GitHub Actions

```yaml title=".github/workflows/mcp.yml"
name: MCP server tests

on:
  push:
    branches: [main]
  pull_request:

jobs:
  toolproof:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.12"

      # Install your server and toolproof in the same environment.
      - run: pip install -e . mcp-toolproof

      - run: toolproof run toolproof.yaml --junit report.xml
        env:
          API_KEY: ${{ secrets.TEST_API_KEY }}   # read with ${API_KEY} in toolproof.yaml

      - uses: actions/upload-artifact@v7
        if: always()
        with:
          name: toolproof-report
          path: report.xml
```

To show results on the pull request, feed `report.xml` to any JUnit reporter action, for example [dorny/test-reporter](https://github.com/dorny/test-reporter) or [mikepenz/action-junit-report](https://github.com/mikepenz/action-junit-report).

### Node servers

```yaml
      - uses: actions/setup-node@v7
        with:
          node-version: "22"
      - run: npm ci && npm run build
      - uses: actions/setup-python@v7
        with:
          python-version: "3.12"
      - run: pip install mcp-toolproof
      - run: toolproof run toolproof.yaml --junit report.xml
```

### Deeper fuzzing on a schedule

Keep pull requests fast and deterministic with a fixed `fuzz.seed`, and explore more inputs nightly:

```yaml
on:
  schedule:
    - cron: "0 3 * * *"

jobs:
  fuzz:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.12"
      - run: pip install -e . mcp-toolproof
      - run: toolproof fuzz -c toolproof.yaml --examples 500 --max-time 300 --json fuzz.json
      - uses: actions/upload-artifact@v7
        if: always()
        with:
          name: fuzz-report
          path: fuzz.json
```

Without a seed, each run prints the seed it used; copy it into `--seed` to reproduce a failure locally.

## GitLab CI

```yaml title=".gitlab-ci.yml"
toolproof:
  image: python:3.12
  script:
    - pip install -e . mcp-toolproof
    - toolproof run toolproof.yaml --junit report.xml
  artifacts:
    when: always
    reports:
      junit: report.xml
```

## JUnit layout

Each phase that ran gets its own `<testsuite>`:

| Suite | Test cases |
|---|---|
| `static checks` | One per tool. Fails with every error-level problem for that tool. |
| `tests` | One per test case, with the call's latency as its time. A crash adds the server's stderr as `<system-err>`. |
| `bench` | One per target. Its `<system-out>` holds the numbers; it fails on a broken threshold. |
| `fuzz` | One per tool. Skipped tools are marked `<skipped>`; findings are listed in the failure message with the seed. |

If the server can't be started at all, the `tests` suite gets a `connect` case with an `<error>` holding the reason and the server's stderr.
