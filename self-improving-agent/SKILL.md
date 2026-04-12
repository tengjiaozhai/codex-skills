---
name: self-improving-agent
description: Capture errors, corrections, missing capabilities, and non-obvious fixes into `.learnings/`, then promote durable patterns into `AGENTS.md`, `memory.md`, or `.github/copilot-instructions.md`. Use when a task exposes a failure, a user correction, a recurring workaround, or a solution valuable enough to become a reusable skill.
---

# Self Improving Agent

Use this skill to turn debugging, user feedback, and repeated workarounds into durable knowledge instead of losing them in chat history.

## What This Skill Does

- Initializes a local `.learnings/` workspace if it does not exist yet.
- Logs corrections, errors, feature requests, and best practices in a consistent format.
- Promotes broadly useful learnings into stable prompt context such as `AGENTS.md`, `memory.md`, or `.github/copilot-instructions.md`.
- Helps extract reusable skills from validated learnings.

## First Use

Before logging anything, ensure the `.learnings/` directory and files exist in the project or workspace root:

```bash
mkdir -p .learnings
[ -f .learnings/LEARNINGS.md ] || printf "# Learnings\n\nCorrections, insights, and knowledge gaps captured during development.\n\n**Categories**: correction | insight | knowledge_gap | best_practice\n\n---\n" > .learnings/LEARNINGS.md
[ -f .learnings/ERRORS.md ] || printf "# Errors\n\nCommand failures and integration errors.\n\n---\n" > .learnings/ERRORS.md
[ -f .learnings/FEATURE_REQUESTS.md ] || printf "# Feature Requests\n\nCapabilities requested by the user.\n\n---\n" > .learnings/FEATURE_REQUESTS.md
```

Never overwrite existing files. Do not log secrets, tokens, private keys, raw environment dumps, or full transcripts unless the user explicitly asks for that level of detail.

## Quick Reference

| Situation | Action |
|-----------|--------|
| Command or tool fails in a non-obvious way | Log to `.learnings/ERRORS.md` |
| User corrects the agent | Log to `.learnings/LEARNINGS.md` with category `correction` |
| A new workaround or better approach is discovered | Log to `.learnings/LEARNINGS.md` with category `best_practice` |
| User asks for a capability that does not exist | Log to `.learnings/FEATURE_REQUESTS.md` |
| Same issue appears again | Link with `See Also`, bump priority, and consider promotion |
| Learning is broadly reusable | Promote to `AGENTS.md`, `memory.md` when the workspace uses it, and/or `.github/copilot-instructions.md` |
| Learning is reusable across projects | Extract a dedicated skill with `scripts/extract-skill.sh` |

## Codex Workflow

1. Solve the task first.
2. If the task exposed a durable lesson, log it immediately while context is fresh.
3. Search `.learnings/` before adding a new entry so duplicates become linked recurrences instead of noise.
4. When a pattern becomes stable, promote the concise rule to long-lived context:
   - `AGENTS.md` for workflow and tool rules
   - `memory.md` when the workspace uses rolling memory
   - `.github/copilot-instructions.md` for shared repo guidance
5. If a learning becomes broadly reusable and self-contained, extract a new skill.

## Logging Format

### Learning Entry

Append to `.learnings/LEARNINGS.md`:

```markdown
## [LRN-YYYYMMDD-XXX] category

**Logged**: ISO-8601 timestamp
**Priority**: low | medium | high | critical
**Status**: pending
**Area**: frontend | backend | infra | tests | docs | config

### Summary
One-line description of what was learned

### Details
Full context: what happened, what was wrong, what is correct

### Suggested Action
Specific fix or improvement to make

### Metadata
- Source: conversation | error | user_feedback
- Related Files: path/to/file.ext
- Tags: tag1, tag2
- See Also: LRN-20250110-001
- Pattern-Key: simplify.dead_code
- Recurrence-Count: 1
- First-Seen: 2025-01-15
- Last-Seen: 2025-01-15

---
```

### Error Entry

Append to `.learnings/ERRORS.md`:

```markdown
## [ERR-YYYYMMDD-XXX] skill_or_command_name

**Logged**: ISO-8601 timestamp
**Priority**: high
**Status**: pending
**Area**: frontend | backend | infra | tests | docs | config

### Summary
Brief description of what failed

### Error
```
Actual error message or short redacted excerpt
```

### Context
- Command or operation attempted
- Input or parameters used
- Environment details if relevant
- Short summary of the relevant output

### Suggested Fix
If identifiable, what might resolve this

### Metadata
- Reproducible: yes | no | unknown
- Related Files: path/to/file.ext
- See Also: ERR-20250110-001

---
```

### Feature Request Entry

Append to `.learnings/FEATURE_REQUESTS.md`:

```markdown
## [FEAT-YYYYMMDD-XXX] capability_name

**Logged**: ISO-8601 timestamp
**Priority**: medium
**Status**: pending
**Area**: frontend | backend | infra | tests | docs | config

### Requested Capability
What the user wanted to do

### User Context
Why they needed it

### Complexity Estimate
simple | medium | complex

### Suggested Implementation
How this could be built

### Metadata
- Frequency: first_time | recurring
- Related Features: existing_feature_name

---
```

## Promotion Rules

Promote a learning when it is stable, repeatable, and likely to help future sessions.

### Good Promotion Targets

| Target | What Belongs There |
|--------|-------------------|
| `AGENTS.md` | Workflow rules, tool usage patterns, automation safeguards |
| `memory.md` | Stable workspace-specific decisions and implementation preferences |
| `.github/copilot-instructions.md` | Shared repo conventions for contributors using Copilot |

### Promotion Guidance

- Distill the long entry into a short prevention rule.
- Prefer action-oriented wording over incident write-ups.
- Update the original learning entry to `Status: promoted` and mention the destination.

## Recurrence And Review

If something similar already exists:

1. Search `.learnings/` first.
2. Link the earlier entry with `See Also`.
3. Increase `Recurrence-Count` and refresh `Last-Seen`.
4. Escalate to a systemic fix if it keeps coming back.

Review `.learnings/` at natural breakpoints:

- before a major task
- after a feature is finished
- when working in an area with past failures
- during periodic project cleanup

## Hook Integration

Hook reminders are optional. If your Codex build supports `.codex/settings.json` command hooks, use the activator for lightweight reminders and the error detector for command-failure hints.

- Activator: `scripts/activator.sh`
- Error detector: `scripts/error-detector.sh`
- Setup details: `references/hooks-setup.md`

If hooks are unavailable in your Codex build, use this skill manually after non-obvious tasks.

## Skill Extraction

Use `scripts/extract-skill.sh` when a learning becomes reusable across projects.

Typical extraction signals:

- the same issue recurs three or more times
- the fix required genuine investigation
- the solution is no longer project-specific
- the user explicitly asks to save it as a skill

## References

- Formatting examples: `references/examples.md`
- Hook setup notes: `references/hooks-setup.md`
- Starter markdown files: `assets/`
