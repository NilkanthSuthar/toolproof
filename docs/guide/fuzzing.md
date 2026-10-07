# Fuzzing

`toolproof fuzz` calls every tool many times with inputs generated from its input schema, and reports anything a well-behaved server shouldn't do. It needs no test cases, so it is a good first thing to run against a new server.

```bash
toolproof fuzz -- python my_server.py
toolproof fuzz -c toolproof.yaml --examples 200 --seed 42
```

!!! danger "Fuzzing calls your tools for real"
    Every tool is called many times with odd arguments. A tool that writes files, sends messages, deletes records or spends money will do so. Before fuzzing a server like that:

    - point it at a test instance, a temporary folder or a throwaway account
    - list risky tools under `fuzz.skip`, or fuzz only safe ones with `fuzz.tools` / `--tool`
    - rely on annotations: tools with `destructiveHint: true` are skipped unless you pass `--include-destructive`

    Most servers don't annotate their tools, so don't count on the last point alone.

## How inputs are generated

Inputs come from [Hypothesis](https://hypothesis.readthedocs.io) and [hypothesis-jsonschema](https://github.com/python-jsonschema/hypothesis-jsonschema). Each tool gets two batches of `max_examples` inputs:

**Valid inputs** match the input schema. Some of them have a string field replaced with an edge case that still matches the schema:

- empty and whitespace-only strings, `"0"`, `"null"`
- control characters and a null byte
- emoji, right-to-left text
- an SQL injection string and a path-traversal string
- a 100,000-character string

**Invalid inputs** start from a valid input and break it in one way: remove a required field, set a typed field to `null`, or give it a value of the wrong JSON type. Each one is checked against the schema to make sure it really is invalid.

Unless the schema says otherwise with `additionalProperties`, inputs don't include extra keys. Extra keys are allowed by JSON Schema by default, but they make failing inputs noisy and rarely find anything.

## What counts as a finding

| Finding | When |
|---|---|
| `crash` | The server process died or the connection dropped. |
| `hang` | No answer within `fuzz.timeout_ms`. |
| `internal-error` | A JSON-RPC error other than "invalid params" (`-32602`). |
| `unhandled-exception` | An error result containing a Python traceback, or the Python SDK's generic message for an exception the tool didn't handle. |
| `output-schema` | A successful result that doesn't match the tool's `outputSchema`. |
| `rejected-valid` | A schema-valid input rejected with "invalid params". The schema and the server's own validation disagree. |
| `accepted-invalid` | An invalid input that returned a success result. Turn off with `invalid_must_fail: false`. |
| `unexpected-error` | An error result for a valid input. Off by default, since tools often reject valid-looking input for business reasons ("unknown city"); turn on with `valid_must_succeed: true`. |
| `bad-schema` | The input schema isn't valid JSON Schema, so no inputs can be generated. |

An error result for invalid input is the correct behaviour, and so is a JSON-RPC "invalid params" error.

## Smallest failing input

When an input triggers a finding, Hypothesis shrinks it: it tries simpler and smaller inputs until it finds the smallest one that still triggers the same kind of finding. Each kind is shrunk separately, so a tool can report, say, both a `crash` and an `accepted-invalid`, each with its own input.

```
┌──────┬─────────────┬───────┬────────────────────────────┬──────────────┬──────────────────────────────────────────┐
│      │ Tool        │ Calls │ Finding                    │ Smallest     │ Details                                  │
│      │             │       │                            │ input        │                                          │
├──────┼─────────────┼───────┼────────────────────────────┼──────────────┼──────────────────────────────────────────┤
│ FAIL │ get_weather │    22 │ crash (valid)              │ {"city": ""} │ connection lost, server probably crashed │
│      │             │       │ accepted-invalid (invalid) │ {"city": []} │ invalid input returned a success result  │
└──────┴─────────────┴───────┴────────────────────────────┴──────────────┴──────────────────────────────────────────┘
Repeat this run with --seed 3
```

## Crashes, hangs and time limits

- After a crash, toolproof starts a fresh server process and carries on, so one crash doesn't hide the next bug.
- After a hang, the tool isn't called again in that run, because every further call would also wait for the full timeout. If the whole server stopped answering, it is restarted too.
- Each tool has a time budget, `fuzz.max_time_s` (60 seconds by default). Shrinking a crash restarts the server many times, and the budget keeps that bounded.

## Repeating a run

Each run prints the seed it used. Pass it back to get the same inputs:

```bash
toolproof fuzz --seed 3 -- python my_server.py
```

For CI, fix the seed in `toolproof.yaml` (`fuzz.seed`) so a pull request can't fail because of luck. Run a separate scheduled job without a seed, or with a higher `--examples`, to keep exploring new inputs.

## Tips

- **Tools with slow defaults.** A tool that waits by design, for example one with a `duration` argument that defaults to 10 seconds, will be reported as a `hang` if `timeout_ms` is shorter. Raise `fuzz.timeout_ms` or skip the tool.
- **Stateful servers.** Fuzzing changes server state. Run it last, or against a fresh instance. `toolproof run` already puts it after tests and benchmarks.
- **More coverage.** `--examples 500` finds rarer bugs at the cost of time. The default of 50 is tuned for CI.
