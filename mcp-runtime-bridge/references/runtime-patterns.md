# Runtime Patterns

Use this file when deciding how an MCP server should be launched on a machine where Node comes from `nvm` and Python comes from Conda.

## Core Rule

Prefer a launch command that does not depend on shell init, login shell semantics, or PATH mutation.

## Node and `npx`

### Why bare `npx` is fragile

- Many `npx` entrypoints use `#!/usr/bin/env node`.
- Even if `npx` itself is referenced by absolute path, it may still ask PATH to locate `node`.
- This breaks easily in MCP runtimes that do not load `.zshrc` or `nvm.sh`.

### Preferred launch pattern

Use the absolute Node executable and pass the absolute `npx-cli.js` path as the first arg.

Example shape:

```toml
command = "/Users/shenmingjie/.nvm/versions/node/v22.20.0/bin/node"
args = [
  "/Users/shenmingjie/.nvm/versions/node/v22.20.0/lib/node_modules/npm/bin/npx-cli.js",
  "-y",
  "chrome-devtools-mcp@latest",
]
```

### When a direct package bin is better

- If the MCP server exposes a stable installed executable and you know its absolute path, that can be even simpler.
- Still avoid relying on PATH unless the environment is intentionally controlled.

## Python and `uvx`

### Preferred launch pattern

Use the absolute `uvx` from the intended Conda environment.

Example:

```toml
command = "/opt/anaconda3/envs/py311/bin/uvx"
args = ["mcp-server-fetch"]
```

### Python module launch

If a server should be started with Python directly, prefer the environment interpreter:

```toml
command = "/opt/anaconda3/envs/py311/bin/python3"
args = ["-m", "some_mcp_server"]
```

### Conda wrapper fallback

Use `conda run` only when the target environment is not otherwise addressable by a stable absolute executable.

## Shell Wrapper Fallback

Use `/bin/zsh -lc` only when the command depends on:

- `nvm` shell functions
- shell-only aliases
- environment activation done inside rc files

Example:

```toml
command = "/bin/zsh"
args = [
  "-lc",
  "source ~/.zshrc >/dev/null 2>&1; exec some-command ..."
]
```

This is a fallback, not the preferred default.

## Secrets and Env Blocks

- Keep server-specific tokens in `[mcp_servers.<name>.env]` when isolation is helpful.
- Keep broadly shared credentials in shell startup files only if the MCP process reliably inherits them.
- Do not duplicate secrets across shell rc files and config env blocks without a reason.
