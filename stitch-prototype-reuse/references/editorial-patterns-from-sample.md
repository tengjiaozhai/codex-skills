# Editorial Patterns from Sample Prototype

This note captures reusable patterns from the provided Stitch sample (`code.html`, `DESIGN.md`, `screen.png`).

## Core Direction

- Editorial enterprise look: high-contrast hierarchy with generous whitespace.
- "No-line" tendency: use tonal shifts and spacing before explicit borders.
- Premium primary actions: gradient-based CTA treatment.

## Reusable UI Patterns

- Glass-like sticky top bar with subtle blur.
- Hero module with asymmetrical decorative glow.
- Section cards with large left-side sequence numbers.
- Mixed form controls: text/date, radios, rating circles, textarea.
- Sticky bottom action bar with secondary action + primary submit.

## Token and Typography Tendencies

- Tailwind `extend.colors` contains semantic tokens (`surface-*`, `primary-*`, `on-*`).
- Display/headline feel is separated from body/label text.
- Utility classes carry most visual expression; avoid large inline styles.

## Reuse Guidance

- For future prototypes, reuse component rhythm first (shell, hero, numbered sections, bottom actions).
- Reuse token naming strategy even when palette values change.
- Keep interactions lightweight and deterministic for static prototype delivery.
