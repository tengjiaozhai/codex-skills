# Config Recipes

Use these recipes when patching [`/Users/shenmingjie/.codex/config.toml`](/Users/shenmingjie/.codex/config.toml).

## 1. Stable Node MCP via `node + npx-cli.js`

Use this when the server is currently launched with bare `npx`.

```toml
[mcp_servers.some_server]
command = "/Users/shenmingjie/.nvm/versions/node/v22.20.0/bin/node"
args = [
  "/Users/shenmingjie/.nvm/versions/node/v22.20.0/lib/node_modules/npm/bin/npx-cli.js",
  "-y",
  "some-package@latest",
]
enabled = true
```

## 2. Stable Python or `uvx` MCP from Conda

Use this when the server is launched with `uvx`.

```toml
[mcp_servers.some_python_server]
command = "/opt/anaconda3/envs/py311/bin/uvx"
args = ["mcp-server-fetch"]
enabled = true
```

Or with Python directly:

```toml
[mcp_servers.some_python_server]
command = "/opt/anaconda3/envs/py311/bin/python3"
args = ["-m", "some_mcp_module"]
enabled = true
```

## 3. Shell Fallback for Hard Shell Dependencies

Use this only when the server needs rc-file initialization:

```toml
[mcp_servers.some_server]
command = "/bin/zsh"
args = [
  "-lc",
  "source ~/.zshrc >/dev/null 2>&1; exec npx -y some-package@latest"
]
enabled = true
```

## 4. Preserve Existing Env Blocks

If the original server has an `env` block, keep it in place:

```toml
[mcp_servers.some_server.env]
TOKEN = "..."
```

Changing the launcher should not silently drop server credentials.
