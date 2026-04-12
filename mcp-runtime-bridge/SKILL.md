---
name: mcp-runtime-bridge
description: Diagnose and stabilize Codex MCP server startup when commands fail because Node or npm are managed by nvm and Python or uv are managed by Conda. Use when MCP servers fail to launch, tools disappear across shells, `npx` or `uvx` or `python` resolve inconsistently, or `~/.codex/config.toml` needs absolute commands, wrapper commands, or environment fixes.
---

# MCP Runtime Bridge

This skill fixes MCP startup issues caused by mixed runtime managers such as `nvm` for Node and Conda for Python. It audits the current machine, explains why a server is fragile, and rewrites or suggests `~/.codex/config.toml` entries that work reliably in non-interactive Codex sessions.

## Quick Start

1. Run `python3 scripts/audit_mcp_runtime.py --config ~/.codex/config.toml --format pretty`.
2. Read [runtime-patterns.md](references/runtime-patterns.md) if the failing server is Node, `npx`, Python, `uvx`, or Conda based.
3. Read [config-recipes.md](references/config-recipes.md) before patching `~/.codex/config.toml`.
4. Prefer absolute executables over bare `npx`, `uvx`, `python`, or shell-dependent PATH lookups.
5. After patching config, rerun the audit and restart Codex.

## Workflow

### 1. Audit the Current Runtime

- Check the actual command paths with `command -v node npm npx python3 uvx conda`.
- Treat the current active runtime managers as the source of truth:
  - Node and npm from the active `nvm` installation
  - Python and `uvx` from the intended Conda environment
- Run `python3 scripts/audit_mcp_runtime.py --config ~/.codex/config.toml --format pretty`.
- If needed, use `--format json` when you want structured output for deeper inspection.

### 2. Choose the Stable Launch Mode

- For Node MCP servers launched via `npx`, prefer:
  - absolute `node`
  - absolute `npx-cli.js` as the first arg
- Do not assume absolute `npx` is enough. `npx` commonly uses `#!/usr/bin/env node`, so it can still fail if PATH does not expose the right Node binary.
- For Python or `uvx` servers, prefer the absolute executable from the target Conda environment.
- Use `/bin/zsh -lc` wrappers only as a fallback when shell init or environment activation is truly required.

### 3. Patch `~/.codex/config.toml`

- Preserve the existing server names, `enabled` flags, and `env` blocks.
- Replace fragile command basenames with stable absolute launch commands.
- Keep secrets where they already live unless a server needs an explicit isolated env block.
- Avoid duplicating shell exports in multiple places unless the server truly cannot inherit them.

### 4. Validate Before Handoff

- Rerun the audit script and confirm the recommended launch mode is now stable.
- Smoke-test the underlying runtime with `--version` when possible.
- If the server itself is remote or package-backed, validate the launcher separately from package behavior.
- Tell the user to restart Codex so MCP configs are reloaded.

## Decision Rules

- Prefer absolute command paths over PATH lookups.
- Prefer direct interpreter plus script over shebang wrappers when a wrapper depends on `env`.
- Prefer the current Conda environment over system Python.
- Prefer the current `nvm` Node installation over system Node.
- Use shell wrappers only when a direct executable path is impossible or incomplete.

## Observed Local Setup

- Observed on `2026-04-10`: `node` and `npm` resolve under `/Users/shenmingjie/.nvm/versions/node/v22.20.0/bin`.
- Observed on `2026-04-10`: `python3` and `uvx` resolve under `/opt/anaconda3/envs/py311/bin`.
- Treat these as hints, not hardcoded truth. Recheck before applying changes.

## Resources

- `scripts/audit_mcp_runtime.py`: inspect Codex MCP config and generate stable launch recommendations.
- [runtime-patterns.md](references/runtime-patterns.md): runtime-specific rules for Node, `npx`, Python, `uvx`, Conda, and shell wrappers.
- [config-recipes.md](references/config-recipes.md): ready-to-adapt `config.toml` snippets for common MCP startup patterns.
