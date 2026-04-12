# Design Alignment Checklist

Run this checklist after each meaningful edit.

## Layout and Structure

- Maintain a clear `header -> main -> footer` shell.
- Keep section grouping readable with spacing, not divider abuse.
- Preserve mobile-first behavior and viewport fit.

## Visual Language

- Reuse existing color tokens from Tailwind config.
- Keep typography hierarchy coherent (hero, section header, body, labels).
- Prefer tonal layers and subtle depth over hard borders.

## Forms and Interactions

- Keep control states visible (hover, focus, selected, active).
- Preserve or improve accessibility of form labels and hit areas.
- Ensure CTAs are visually prioritized and consistent.

## Consistency and Integrity

- Avoid introducing ad-hoc utility patterns that conflict with established style.
- Keep naming and class usage predictable for future edits.
- Re-run bundle audit script before handoff.
