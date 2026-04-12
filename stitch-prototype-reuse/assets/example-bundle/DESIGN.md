# Design System Specification: The Precision Editorial

## 1. Overview & Creative North Star
The "Creative North Star" for this design system is **The Intellectual Architect**. 

In the world of enterprise questionnaires, "boring" is the default. We reject the generic "form-filler" aesthetic in favor of a high-end editorial experience. This system moves away from rigid, boxed-in grids and toward a layout that feels curated, intentional, and authoritative. By leveraging expansive white space, sophisticated tonal layering, and high-contrast typography, we transform a standard data-gathering exercise into a premium brand touchpoint. 

The goal is to provide "Cognitive Ease" through **Soft Minimalism**—where the UI recedes to let the content breathe, using depth and light rather than lines and boxes to guide the user.

---

## 2. Colors & Tonal Architecture
We utilize a Material 3-inspired palette to create a "Living Surface" where elements are defined by light and shadow, not strokes.

### The "No-Line" Rule
**Explicit Instruction:** Designers are prohibited from using 1px solid borders for sectioning or containment. 
Boundaries must be defined solely through background color shifts. For example, a `surface-container-low` section should sit on a `surface` background. If you feel the need to "draw a line," use a spacing shift (Scale 6 or 8) or a tonal transition instead.

### Surface Hierarchy & Nesting
Treat the UI as a series of stacked, semi-opaque sheets.
- **Base Layer:** `surface` (#f8f9fb)
- **Content Zones:** `surface-container-low` (#f3f4f6)
- **Active Cards:** `surface-container-lowest` (#ffffff)
- **Pop-overs/Modals:** `surface-bright` (#f8f9fb) with Glassmorphism.

### The "Glass & Gradient" Rule
To elevate the "Corporate Blue," avoid flat fills for primary actions. 
- **Signature Gradient:** Use a linear gradient from `primary` (#003d9b) to `primary-container` (#0052cc) at a 135-degree angle for primary CTAs. This adds a "jewel-toned" depth that feels expensive.
- **Glassmorphism:** For floating headers or steppers, use `surface` at 80% opacity with a `backdrop-filter: blur(20px)`. This integrates the component into the environment rather than "pasting" it on top.

---

## 3. Typography: The Editorial Voice
We pair **Manrope** (Display/Headlines) with **Inter** (Body/Labels) to create a sophisticated, modern hierarchy.

| Level | Token | Font | Size | Weight | Tracking |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Hero Title** | `display-md` | Manrope | 2.75rem | 700 | -0.02em |
| **Section Header** | `headline-sm` | Manrope | 1.5rem | 600 | -0.01em |
| **Question Text** | `title-md` | Inter | 1.125rem | 500 | 0 |
| **Body/Helper** | `body-md` | Inter | 0.875rem | 400 | 0 |
| **Caps Label** | `label-sm` | Inter | 0.6875rem | 600 | 0.05em |

**Editorial Note:** Use `display-md` for progress milestones (e.g., "01") to create an asymmetrical, "magazine-style" layout that anchors the page.

---

## 4. Elevation & Depth
Hierarchy is achieved through **Tonal Layering** and **Ambient Light**, never through heavy drop shadows.

- **The Layering Principle:** To lift a questionnaire card, place a `surface-container-lowest` (#ffffff) object on top of a `surface-container-low` (#f3f4f6) background. The 8px (`DEFAULT`) corner radius softens the transition.
- **Ambient Shadows:** For "floating" elements (e.g., a sticky bottom navigation), use a shadow with a 40px blur, 0% spread, and 6% opacity of the `on-surface` color (#191c1e). 
- **The "Ghost Border" Fallback:** If accessibility requirements demand a border (e.g., high-contrast mode), use `outline-variant` (#c3c6d6) at **15% opacity**. It should be felt, not seen.

---

## 5. Components

### Input Fields & Text Areas
- **Style:** No bottom lines or full borders. Use `surface-container-high` as a subtle background fill with an 8px radius.
- **Active State:** On focus, the background transitions to `surface-container-lowest` and gains a 2px `surface-tint` (#0c56d0) "Glow" (shadow), not a solid border.
- **Placeholder:** Use `on-surface-variant` at 50% opacity.

### Horizontal 1-5 Rating Scales
- **Execution:** Do not use boxes. Use five `surface-container-highest` circles.
- **Interaction:** On hover, the circle expands slightly (Scale 1.5) and shifts to `primary-fixed`. Upon selection, the chosen value uses the **Signature Gradient** with a white `on-primary` digit.

### Radio Button Groups
- **Layout:** Stacked vertically with **Spacing 4** between items.
- **Visuals:** The radio hit area is a 24px circle. Instead of a standard dot, use a `primary` outer ring and a `primary-fixed-dim` inner glow when selected.

### Stepper / Progress Indicators
- **The "Editorial" Stepper:** Use an asymmetrical layout. A large `display-lg` number in `surface-variant` tucked behind the `headline-sm` section title.
- **Progress Bar:** A thin (4px) track using `surface-container-high` with a `primary` fill that features a subtle pulse animation.

### Cards & Lists
- **Rule:** Forbid divider lines. 
- **Separation:** Use **Spacing 8** (2.75rem) to separate major question groups. Use a subtle background shift to `surface-container-low` to group related sub-questions.

---

## 6. Do's and Don'ts

### Do:
- **Use Intentional Asymmetry:** Align your "Step Number" to the far left, while the questionnaire card sits slightly off-center to the right to create a professional, non-template look.
- **Embrace White Space:** If a page feels "empty," add more padding (Scale 12 or 16). In enterprise software, space is a luxury that signals quality.
- **Color with Purpose:** Use `secondary` (#006c47) for "Save Progress" success states and `tertiary` (#5e3c00) for "Action Required" warnings.

### Don't:
- **Don't use 100% Black:** Always use `on-surface` (#191c1e) for text to maintain a premium, softer contrast.
- **Don't use Standard Shadows:** Never use the default "Drop Shadow" settings in design tools. Always tint your shadows with the primary brand color to keep them "clean."
- **Don't Over-Round:** Stick to the `DEFAULT` (8px) or `md` (12px) for cards. Avoid "Pill" shapes for everything except small tags/chips; otherwise, the UI loses its authoritative edge.