# Versioning and support

## Version numbers

toolproof follows [Semantic Versioning](https://semver.org). While it is below 1.0:

- **patch** releases (0.2.**x**) only fix bugs and never change behaviour you rely on
- **minor** releases (0.**x**.0) add features and may make small, documented breaking changes; every one is listed in the [changelog](changelog.md) with what to change

From 1.0 on, breaking changes only happen in major releases.

## What counts as the public interface

Covered by the policy above:

- the command-line interface: commands, flags, exit codes
- the `toolproof.yaml` format
- the JSON report fields and the JUnit layout
- the Python names exported from `toolproof` (see [Python API](../reference/python-api.md))
- the `mcp_server` pytest fixture and its ini options

Not covered: anything imported from a submodule (`toolproof.fuzz`, `toolproof.client`, ...), the exact wording of console output and failure messages, and which inputs the fuzzer generates for a given seed across versions.

## Deprecations

When something in the public interface is going away, it first keeps working with a warning for at least one minor release, and the changelog says what to use instead.

## Supported Python versions

toolproof supports every Python version that is not end-of-life and that its dependencies support, currently 3.11 to 3.14. Support for a version is dropped in a minor release, after its end-of-life date.

## Supported MCP versions

toolproof uses the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) for the protocol, so it supports the protocol versions that SDK supports, over stdio and streamable HTTP. The SDK version range is pinned in the package metadata and widened after testing.

## Security fixes

Security fixes are made for the latest minor release. See the [security policy](https://github.com/NilkanthSuthar/toolproof/blob/main/SECURITY.md) to report a problem.
