---
name: stitch-prototype-reuse
description: "Reconstruct pages from the fixed triplet `code.html`, `DESIGN.md`, and `screen.png`, then implement them in the current project framework. Default output is framework-native pages (Vue/React) with route integration; static HTML-only output is used only when explicitly requested."
---

# Stitch Prototype Reuse

## Quick Start

1. Confirm the bundle contract in each target bundle directory:
   - required: `code.html`, `DESIGN.md`, `screen.png`
   - optional: Stitch project URL for extra context
2. Run `python scripts/audit_stitch_bundle.py --dir <bundle-dir> --pretty`.
3. Detect the runtime framework of the current project (`Vue` or `React`) from project files.
4. Treat `DESIGN.md` + `screen.png` as source-of-truth for structure and style.
5. Implement or update framework pages/components and route entries for each bundle.
6. Summarize restoration deltas and unresolved fidelity gaps.

## Workflow

### 1) Validate Inputs

- Run the auditor script before making changes.
- If any required file is missing, stop and ask for the missing artifact.
- If a Stitch URL is provided but inaccessible (auth/render limits), continue from local files and state the limitation explicitly.

### 2) Detect Framework + Targets

- Determine framework from local project metadata:
  - `Vue`: `vue` dependency or `.vue` SFC routing structure.
  - `React`: `react` dependency with JSX/TSX entry/router.
- Choose framework-native output paths:
  - Vue: create/update `src/views/*.vue` or `src/components/*.vue`, plus router registration.
  - React: create/update route pages/components, plus router registration.
- Map each bundle directory (for example `design/vote`, `design/finish`) to one project page/route.

### 3) Build Design Map from `DESIGN.md`

- Extract color tokens, typography scale, spacing rules, and explicit do/don't constraints.
- Treat explicit constraints as higher priority than visual guesses.

### 4) Build Target Map from `screen.png`

- Identify shell structure, section order, visual emphasis, spacing rhythm, and key component shapes.
- Resolve ambiguity by preferring `DESIGN.md` explicit rules over screenshot inference.

### 5) Reconstruct Framework Pages

- Rebuild page structure in framework-native components (`.vue` or `.jsx/.tsx`).
- Prefer semantic layout (`header/main/footer`, grouped cards, clear labels/controls).
- Reuse existing project styling strategy first (existing CSS/Tailwind/UI library tokens) to avoid style drift.
- Keep behavior static unless user requests dynamic data or API integration.
- Only edit `code.html` directly when user explicitly asks for static HTML restoration.

### 6) QA Before Handoff

- Re-run `scripts/audit_stitch_bundle.py` for each bundle after edits.
- Keep the three fixed bundle filenames unchanged as reference artifacts.
- Verify the framework page renders and route navigation works.
- Ensure restored fidelity is acceptable for structure, style, and interaction cues.

## Output Pattern

Use this shape in final responses:

- `Restoration Completed`: what pages/routes were reconstructed in the framework codebase.
- `Fidelity Notes`: how implementation aligns with `DESIGN.md` and `screen.png`.
- `Open Gaps`: unresolved items due to missing assets, conflicting project constraints, or inaccessible remote context.

## Resources

- `scripts/audit_stitch_bundle.py`: validate fixed triplet and extract quick structural signals.
- `references/stitch-bundle-contract.md`: strict input/output contract.
- `references/design-alignment-checklist.md`: practical quality checklist.
- `references/editorial-patterns-from-sample.md`: reusable patterns distilled from the provided sample prototype.
- `assets/example-bundle/`: example triplet snapshot for fast bootstrapping.
