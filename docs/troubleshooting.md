# Troubleshooting

## `could not connect to server: Connection closed`

The server process exited before the MCP handshake finished. toolproof prints the server's last stderr lines under the error; they usually say why. Common causes:

**`ModuleNotFoundError` from a Python server.** The `python` on `PATH` isn't the environment your server's dependencies are in. Install toolproof into the server's environment and run it from there, or put the full interpreter path in `command`:

```yaml
server:
  command: [".venv/bin/python", "server.py"]   # Windows: .venv/Scripts/python.exe
```

**A missing environment variable.** A stdio server only inherits a few variables such as `PATH` and `HOME`. Pass API keys and settings under `server.env`. See [Configuration](guide/configuration.md#server).

**The server writes to stdout.** Over stdio, stdout carries the MCP messages. A `print()` or log line on stdout corrupts the stream. Log to stderr instead.

## `could not connect to server` with a timeout

The server started but didn't answer the handshake within `startup_timeout_s` (default 30). Raise it for slow-starting servers, for example ones that download a model on start:

```yaml
server:
  command: ["python", "server.py"]
  startup_timeout_s: 120
```

## The command isn't found on Windows

Windows needs the real executable name for some tools: `npx.cmd` rather than `npx`. Running the built file directly (`node dist/index.js`) avoids the problem.

## YAML errors with Windows paths

In a double-quoted YAML string, a backslash starts an escape sequence, so `"C:\Users\me"` is an error. Use single quotes or forward slashes:

```yaml
args: { path: 'C:\Users\me\file.txt' }
args: { path: "C:/Users/me/file.txt" }
```

## `--args is not valid JSON`

The shell changed the quotes. See [Quoting JSON in shells](reference/cli.md#quoting-json-in-shells).

## Fuzzing reports a `hang` for a tool that is just slow

`fuzz.timeout_ms` defaults to 2 seconds. Tools that wait on purpose, or whose arguments default to long durations, will hit it. Raise the timeout or skip the tool:

```yaml
fuzz:
  timeout_ms: 15000
  skip: [trigger-long-running-operation]
```

## Fuzzing reports `accepted-invalid` and the server is fine with that

Some servers accept loosely typed input on purpose, for example converting `5` to `"5"`. If that's intended, turn the check off:

```yaml
fuzz:
  invalid_must_fail: false
```

## A test passes locally but times out in CI

CI machines are slower and shared. Raise `timeout_ms` for the slow tests, and give benchmark thresholds plenty of headroom.

## Getting more detail

- `--json report.json` writes everything, including the full text of each result.
- `toolproof inspect --json` shows the exact schemas the server advertises.
- If you think you found a bug in toolproof, [open an issue](https://github.com/NilkanthSuthar/toolproof/issues/new/choose) with the command, the config and the output.
