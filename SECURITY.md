# Security policy

## Supported versions

Security fixes are released for the latest minor version of toolproof. Older versions don't receive fixes; upgrade to the latest release.

## Reporting a vulnerability

Please don't report security problems in public issues.

Use GitHub's private reporting instead: go to the [Security tab](https://github.com/NilkanthSuthar/toolproof/security) and choose **Report a vulnerability**. Include what you found, how to reproduce it, and what an attacker could do with it.

You can expect an acknowledgement within 3 working days and an assessment within 10. Fixes are released as soon as they're ready, and you'll be credited in the release notes unless you prefer not to be.

## Scope

toolproof runs the server command you give it and calls the tools on that server. Things that are expected and not vulnerabilities:

- A config file runs whatever `server.command` says. Only run configs you trust, the same as any build script.
- Fuzzing calls every tool with generated arguments. A server's tools do whatever they do; see the warning in the [fuzzing guide](https://nilkanthsuthar.github.io/toolproof/guide/fuzzing/).

In scope, for example: toolproof itself executing something it wasn't asked to, leaking `env` or `headers` values into reports or logs, or writing files outside the paths given to `--junit` / `--json`.

Problems in an MCP server you tested with toolproof belong to that server's maintainers.
