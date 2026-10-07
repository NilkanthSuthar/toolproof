# Servers in other languages

toolproof only talks MCP to the server, so the server can be written in anything. Put the command that starts it in `server.command`; toolproof itself still runs on Python.

=== "TypeScript / Node"

    ```yaml
    server:
      command: ["node", "dist/index.js"]
    ```

    Build first (`npm run build`). Pointing at the built file starts faster and more reliably than `npx` or `ts-node`, which matters because toolproof restarts the server after a crash.

=== "Published npm package"

    ```yaml
    server:
      command: ["npx", "-y", "@modelcontextprotocol/server-memory"]
    ```

    On Windows, use `npx.cmd`, or install the package locally and run `node node_modules/<package>/dist/index.js`.

=== "Go / Rust / any binary"

    ```yaml
    server:
      command: ["./bin/my-server", "--stdio"]
    ```

=== "Docker"

    ```yaml
    server:
      command: ["docker", "run", "-i", "--rm", "my-org/my-server:latest"]
    ```

    `-i` keeps stdin open, which stdio servers need.

=== "Python with uvx"

    ```yaml
    server:
      command: ["uvx", "mcp-server-time"]
    ```

## Environment variables

A stdio server only inherits a small set of environment variables (see [Configuration](../guide/configuration.md#server)). Pass anything else explicitly:

```yaml
server:
  command: ["node", "dist/index.js"]
  env:
    API_KEY: "${API_KEY}"
    LOG_LEVEL: error
```

## Server logs

toolproof captures the server's stderr instead of printing it. When the server fails to start or crashes during a test, the last lines are shown in the report, so logging to stderr is the easiest way to see why.
