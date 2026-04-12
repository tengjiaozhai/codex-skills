# Stitch Bundle Contract

## Required Input Files

Use this skill only when the target directory contains exactly these required artifacts:

- `code.html`: Stitch-exported static HTML prototype.
- `DESIGN.md`: design-system and visual direction spec.
- `screen.png`: screenshot or rendered reference for fidelity checks.

## Optional Inputs

- Stitch project URL for additional context (often requires login).
- User notes for copy/content or interaction requirements.

## File Handling Rules

- Keep required filenames unchanged.
- Edit `code.html` in place unless user requests split files.
- Treat `DESIGN.md` as source-of-truth for style constraints.
- Use `screen.png` to confirm component hierarchy, spacing rhythm, and visual emphasis.

## Output Rules

- Deliver updated `code.html`.
- Preserve static runtime assumptions (single HTML page).
- Report any mismatch between `DESIGN.md` and existing HTML implementation.
