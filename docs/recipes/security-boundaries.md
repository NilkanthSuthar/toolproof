# Security boundaries

Random fuzzing is good at finding crashes. It is not good at finding a server that does exactly what it was asked, when it shouldn't have been allowed to: reading a file outside its folder, or passing an argument that turns into a command-line option. Those need targeted tests, and they are easy to write in YAML.

These examples come from running toolproof against the official [filesystem](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) and [git](https://github.com/modelcontextprotocol/servers/tree/main/src/git) reference servers. Both passed every test.

## Path escapes

Give the server one allowed folder, put a "secret" file next to it, and check every way of reaching it is refused.

```yaml title="filesystem.yaml"
server:
  command: ["node", "node_modules/@modelcontextprotocol/server-filesystem/dist/index.js", "sandbox/allowed"]

# The filesystem server resolves relative paths against its allowed folder,
# so "a.txt" means sandbox/allowed/a.txt and "../outside" means sandbox/outside.
tests:
  - name: reads a file inside the allowed folder
    tool: read_text_file
    args: { path: a.txt }
    expect: { is_error: false }

  - name: refuses an absolute path outside
    tool: read_text_file
    args: { path: /etc/passwd }
    expect: { is_error: true }

  - name: refuses ../ traversal
    tool: read_text_file
    args: { path: ../outside/secret.txt }
    expect: { is_error: true }

  - name: refuses a sibling folder that shares the prefix
    # "sandbox/allowed-2" starts with "sandbox/allowed": a naive startswith() check lets it through.
    tool: read_text_file
    args: { path: ../allowed-2/secret.txt }
    expect: { is_error: true }

  - name: listing outside is refused too
    tool: list_directory
    args: { path: ../outside }
    expect: { is_error: true }
```

Check how your own server resolves relative paths first, with a test like the first one. If a path that should be inside is refused, every "refuses" test passes for the wrong reason.

Other variants worth a test on your platform:

- backslashes on Windows: `'sandbox\allowed\..\outside\secret.txt'` (single quotes, so YAML leaves the backslashes alone)
- a different letter case on case-insensitive file systems
- a symlink inside the allowed folder that points outside it

## Option injection

When a tool passes an argument to a command-line program, a value starting with `-` can become an option. With git, `--output=FILE` writes a file wherever the caller wants.

```yaml title="git.yaml"
server:
  command: ["uvx", "mcp-server-git", "--repository", "sandbox/repo"]

tests:
  - name: works on the allowed repository
    tool: git_status
    args: { repo_path: sandbox/repo }
    expect: { is_error: false }

  - name: refuses another repository
    tool: git_log
    args: { repo_path: sandbox/other-repo }
    expect: { is_error: true }

  - name: diff target can't inject --output
    tool: git_diff
    args: { repo_path: sandbox/repo, target: "--output=sandbox/injected.txt" }
    expect: { is_error: true }

  - name: show revision can't inject an option
    tool: git_show
    args: { repo_path: sandbox/repo, revision: "--output=sandbox/injected.txt" }
    expect: { is_error: true }
```

After the run, also check that `sandbox/injected.txt` was not created. An injected option can succeed *and* return an error.

## Keep it contained

Run these tests against throwaway folders and repositories, never against real data. A test that fails here means the server did the unsafe thing.
