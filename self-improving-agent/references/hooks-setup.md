# Hook Setup Guide

Configure optional self-improvement reminders for Codex-based workflows.

## Overview

Hooks are helpful when you want lightweight reminders to capture durable learnings:

- `UserPromptSubmit`: reminds you to evaluate whether a learning should be logged
- `PostToolUse`: surfaces a reminder when command output looks like an error

If your Codex build does not support hooks, skip this file and use the skill manually.

## Codex Setup

Create `.codex/settings.json` in the project root if your Codex build supports command hooks.

### Minimal Setup

Use only the activator for a low-noise reminder:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/to/.codex/skills/self-improving-agent/scripts/activator.sh"
          }
        ]
      }
    ]
  }
}
```

### Activator Plus Error Detection

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/to/.codex/skills/self-improving-agent/scripts/activator.sh"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "/absolute/path/to/.codex/skills/self-improving-agent/scripts/error-detector.sh"
          }
        ]
      }
    ]
  }
}
```

Use absolute paths. Do not rely on `~` expansion unless you have verified your runtime supports it.

## What The Scripts Do

| Script | Purpose |
|--------|---------|
| `scripts/activator.sh` | Emits a small reminder after a prompt is submitted |
| `scripts/error-detector.sh` | Emits a reminder when tool output looks like a failure |
| `scripts/extract-skill.sh` | Scaffolds a new skill from a validated learning |

## Verification

### Test The Activator

1. Start a new Codex session in a workspace with the hook config.
2. Send a prompt.
3. Confirm you see a self-improvement reminder.

### Test Error Detection

1. Enable the `PostToolUse` hook.
2. Run a failing shell command such as `ls /nonexistent/path`.
3. Confirm you see an error reminder.

### Test Skill Extraction

```bash
/absolute/path/to/.codex/skills/self-improving-agent/scripts/extract-skill.sh test-skill --dry-run
```

## Troubleshooting

### Hook Does Not Trigger

1. Confirm your Codex build supports `.codex/settings.json` hooks.
2. Ensure the hook script paths are absolute and executable.
3. Restart the session after changing hook configuration.

### Permission Denied

```bash
chmod +x /absolute/path/to/.codex/skills/self-improving-agent/scripts/activator.sh
chmod +x /absolute/path/to/.codex/skills/self-improving-agent/scripts/error-detector.sh
chmod +x /absolute/path/to/.codex/skills/self-improving-agent/scripts/extract-skill.sh
```

### Too Much Overhead

- Start with activator only.
- Skip the `PostToolUse` hook unless command-error reminders are worth the extra noise.

## Security Notes

- Keep logs concise and sanitized.
- Do not forward raw tool output into `.learnings/` unless the user explicitly wants it preserved.
- Treat any hook-provided tool output as potentially sensitive.
