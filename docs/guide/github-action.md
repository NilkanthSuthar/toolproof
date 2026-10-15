# GitHub Action

The toolproof Action installs toolproof, runs it, uploads the reports and adds a summary to the workflow run.

```yaml title=".github/workflows/mcp.yml"
name: MCP server tests
on: [push, pull_request]

jobs:
  toolproof:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.12"
      - run: pip install -e .      # your server and its dependencies

      - uses: NilkanthSuthar/toolproof@v0.3.0
        with:
          config: toolproof.yaml
          python-version: ""       # use the Python set up above
```

The run page then shows a summary like this, and the reports are attached as the `toolproof-report` artifact:

| | Phase | Result |
|---|---|---|
| ✅ | Static checks | 0 errors, 0 warnings |
| ✅ | Tests | 7/7 passed |
| ✅ | Bench | 4/4 within limits |
| ✅ | Fuzz | 0 findings (seed 1) |

## Inputs

| Input | Default | Description |
|---|---|---|
| `command` | `run` | `run`, `fuzz`, `bench` or `eval`. |
| `config` | `toolproof.yaml` | Path to the config, relative to `working-directory`. |
| `args` | | Extra arguments, for example `--strict --skip-fuzz` or `--examples 200`. |
| `working-directory` | `.` | Where to run. |
| `python-version` | `3.12` | Python to set up. Set it to `""` to use one your job already set up, which you need when toolproof should run in the same environment as your server. |
| `version` | latest | toolproof version to install, for example `0.3.0`. Pin it for reproducible builds. |
| `extras` | | Optional extras, for example `anthropic` or `openai` for evals. |
| `report-name` | `toolproof-report` | Name of the uploaded artifact. |
| `upload-report` | `true` | Upload `report.xml`, `report.json` and `report.html`. |
| `job-summary` | `true` | Add the summary to the run page. |

## Outputs

| Output | Description |
|---|---|
| `passed` | `"true"` or `"false"`. |
| `report-dir` | Folder with the three report files. |

The step fails when toolproof fails, like any test step. To keep going and decide yourself, add `continue-on-error: true` and read `steps.<id>.outputs.passed`.

## Examples

**Evals with a secret key:**

```yaml
      - uses: NilkanthSuthar/toolproof@v0.3.0
        with:
          command: eval
          extras: anthropic
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

**Nightly deep fuzzing:**

```yaml
on:
  schedule:
    - cron: "0 3 * * *"
jobs:
  fuzz:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: NilkanthSuthar/toolproof@v0.3.0
        with:
          command: fuzz
          args: --examples 500 --max-time 300
```

**A Node server:**

```yaml
      - uses: actions/setup-node@v7
        with:
          node-version: "22"
      - run: npm ci && npm run build
      - uses: NilkanthSuthar/toolproof@v0.3.0
```

## Versions

Reference a release tag such as `@v0.3.0`. Tags never move, so a pinned workflow keeps working the same way. The `version` input pins the toolproof package separately; leave it empty to get the latest release with a given Action version.
