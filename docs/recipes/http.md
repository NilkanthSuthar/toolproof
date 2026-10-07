# Testing over HTTP

For a server that speaks [streamable HTTP](https://modelcontextprotocol.io/specification/latest/basic/transports), give its URL instead of a command:

```bash
toolproof inspect --url http://localhost:8000/mcp
```

```yaml
server:
  url: http://localhost:8000/mcp
```

toolproof doesn't start or stop an HTTP server. Start it first, for example in a CI step that runs in the background:

```yaml
      - run: python server.py --http --port 8000 &
      - run: |
          for i in $(seq 1 30); do curl -s localhost:8000 >/dev/null && break; sleep 1; done
      - run: toolproof run toolproof.yaml --junit report.xml
```

## Authentication

Send headers with every request, reading secrets from the environment:

```yaml
server:
  url: https://mcp.example.com/mcp
  headers:
    Authorization: "Bearer ${MCP_TOKEN}"
    X-Team: qa
```

`${MCP_TOKEN}` is read when the file is loaded, and loading fails if it isn't set. OAuth flows that need a browser aren't supported; use a token issued for testing.

## Differences from stdio

- A crash can't be detected by watching a process. A server that stops answering shows up as connection errors and timeouts.
- toolproof can't restart an HTTP server. After the connection is lost, it reconnects before the next test; if the server is down, the run stops with a connection error.
- There is no server stderr to show; check the server's own logs.
- Benchmarks include network time.
