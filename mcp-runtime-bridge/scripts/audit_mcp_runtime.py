#!/usr/bin/env python3
"""Audit Codex MCP runtime configuration and suggest stable launch commands."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib


def expand(path_str: str) -> Path:
    return Path(path_str).expanduser().resolve()


def command_exists(path: str | None) -> bool:
    return bool(path) and Path(path).exists()


def which(name: str) -> str | None:
    return shutil.which(name)


def smoke(command: list[str]) -> dict[str, object]:
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            env={"HOME": os.environ.get("HOME", "")},
            timeout=10,
        )
        text = (result.stdout or result.stderr).strip()
        return {"ok": True, "output": text}
    except Exception as exc:  # pragma: no cover - defensive utility path
        return {"ok": False, "output": str(exc)}


def resolve_command(raw_command: str) -> str | None:
    if raw_command.startswith("/"):
        return raw_command if Path(raw_command).exists() else None
    return which(raw_command)


def classify(raw_command: str, raw_args: list[str]) -> str:
    name = Path(raw_command).name
    if name == "node" and raw_args and raw_args[0].endswith("npx-cli.js"):
        return "node_npx"
    if name == "npx":
        return "npx"
    if name == "uvx":
        return "uvx"
    if name in {"python", "python3"}:
        return "python"
    if name == "conda":
        return "conda"
    return "other"


def build_npx_recommendation(raw_args: list[str], resolved_command: str | None) -> dict[str, object]:
    npx_path = resolved_command or which("npx")
    node_path = which("node")
    if not npx_path or not node_path:
        return {
            "kind": "npx",
            "status": "missing_runtime",
            "reason": "Unable to resolve both npx and node.",
        }

    cli_path = str(Path(npx_path).resolve())
    recommended = {
        "kind": "npx",
        "status": "ok",
        "reason": "Prefer absolute node + npx-cli.js because npx commonly depends on /usr/bin/env node.",
        "command": node_path,
        "args": [cli_path, *raw_args],
        "smoke": smoke([node_path, cli_path, "--version"]),
    }
    return recommended


def build_uvx_recommendation(raw_args: list[str], resolved_command: str | None) -> dict[str, object]:
    uvx_path = resolved_command or which("uvx")
    if not uvx_path:
        return {
            "kind": "uvx",
            "status": "missing_runtime",
            "reason": "Unable to resolve uvx.",
        }

    return {
        "kind": "uvx",
        "status": "ok",
        "reason": "Use the absolute uvx from the intended Conda environment.",
        "command": uvx_path,
        "args": raw_args,
        "smoke": smoke([uvx_path, "--version"]),
    }


def build_python_recommendation(raw_args: list[str], resolved_command: str | None) -> dict[str, object]:
    python_path = resolved_command or which("python3") or which("python")
    if not python_path:
        return {
            "kind": "python",
            "status": "missing_runtime",
            "reason": "Unable to resolve python.",
        }

    return {
        "kind": "python",
        "status": "ok",
        "reason": "Use the absolute interpreter from the intended Conda environment.",
        "command": python_path,
        "args": raw_args,
        "smoke": smoke([python_path, "--version"]),
    }


def build_node_npx_recommendation(raw_command: str, raw_args: list[str], resolved_command: str | None) -> dict[str, object]:
    smoke_args = raw_args[:1] if raw_args else []
    return {
        "kind": "node_npx",
        "status": "ok" if resolved_command else "missing_runtime",
        "reason": "Already using the stable direct node + npx-cli.js launch mode.",
        "command": resolved_command or raw_command,
        "args": raw_args,
        "smoke": smoke([resolved_command or raw_command, *smoke_args, "--version"])
        if resolved_command and smoke_args
        else None,
    }


def build_generic_recommendation(raw_command: str, raw_args: list[str], resolved_command: str | None) -> dict[str, object]:
    if resolved_command:
        return {
            "kind": "other",
            "status": "ok",
            "reason": "Command already resolves; prefer absolute path if Codex startup remains unstable.",
            "command": resolved_command,
            "args": raw_args,
        }

    return {
        "kind": "other",
        "status": "missing_runtime",
        "reason": "Command does not resolve in the current environment.",
    }


def build_recommendation(raw_command: str, raw_args: list[str], resolved_command: str | None) -> dict[str, object]:
    kind = classify(raw_command, raw_args)
    if kind == "node_npx":
        return build_node_npx_recommendation(raw_command, raw_args, resolved_command)
    if kind == "npx":
        return build_npx_recommendation(raw_args, resolved_command)
    if kind == "uvx":
        return build_uvx_recommendation(raw_args, resolved_command)
    if kind == "python":
        return build_python_recommendation(raw_args, resolved_command)
    return build_generic_recommendation(raw_command, raw_args, resolved_command)


def toml_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def build_toml_snippet(name: str, recommendation: dict[str, object], enabled: bool) -> str | None:
    command = recommendation.get("command")
    args = recommendation.get("args")
    if not command or not isinstance(args, list):
        return None

    arg_text = ", ".join(toml_value(str(item)) for item in args)
    return "\n".join(
        [
            f"[mcp_servers.{name}]",
            f"command = {toml_value(str(command))}",
            f"args = [{arg_text}]",
            f"enabled = {'true' if enabled else 'false'}",
        ]
    )


def audit(config_path: Path) -> dict[str, object]:
    config = tomllib.loads(config_path.read_text())
    servers = config.get("mcp_servers", {})
    results = []

    for name, data in servers.items():
        raw_command = str(data.get("command", ""))
        raw_args = [str(item) for item in data.get("args", [])]
        enabled = bool(data.get("enabled", False))
        resolved_command = resolve_command(raw_command) if raw_command else None
        recommendation = build_recommendation(raw_command, raw_args, resolved_command)
        results.append(
            {
                "name": name,
                "enabled": enabled,
                "original": {
                    "command": raw_command,
                    "args": raw_args,
                    "resolved_command": resolved_command,
                },
                "recommendation": recommendation,
                "suggested_toml": build_toml_snippet(name, recommendation, enabled),
            }
        )

    return {
        "config_path": str(config_path),
        "observed": {
            "node": which("node"),
            "npm": which("npm"),
            "npx": which("npx"),
            "python3": which("python3"),
            "uvx": which("uvx"),
            "conda": which("conda"),
        },
        "servers": results,
    }


def print_pretty(report: dict[str, object]) -> None:
    print(f"Config: {report['config_path']}")
    print("Observed runtimes:")
    observed = report["observed"]
    for key in ("node", "npm", "npx", "python3", "uvx", "conda"):
        print(f"  - {key}: {observed.get(key) or 'MISSING'}")

    print("\nServers:")
    for server in report["servers"]:
        print(f"- {server['name']}")
        print(f"  enabled: {server['enabled']}")
        print(f"  original command: {server['original']['command']}")
        print(f"  resolved command: {server['original']['resolved_command'] or 'MISSING'}")
        recommendation = server["recommendation"]
        print(f"  recommended kind: {recommendation.get('kind')}")
        print(f"  status: {recommendation.get('status')}")
        print(f"  reason: {recommendation.get('reason')}")
        if recommendation.get("command"):
            print(f"  recommended command: {recommendation['command']}")
        if recommendation.get("args"):
            print(f"  recommended args: {recommendation['args']}")
        smoke_result = recommendation.get("smoke")
        if isinstance(smoke_result, dict):
            print(f"  smoke ok: {smoke_result.get('ok')}")
            if smoke_result.get("output"):
                print(f"  smoke output: {smoke_result['output']}")
        if server.get("suggested_toml"):
            print("  suggested toml:")
            for line in str(server["suggested_toml"]).splitlines():
                print(f"    {line}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="~/.codex/config.toml",
        help="Path to the Codex config TOML file.",
    )
    parser.add_argument(
        "--format",
        choices=("pretty", "json"),
        default="pretty",
        help="Output format.",
    )
    args = parser.parse_args()

    config_path = expand(args.config)
    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        return 1

    report = audit(config_path)
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_pretty(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
