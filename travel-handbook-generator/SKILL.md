---
name: travel-handbook-generator
description: Generate reusable DOCX/PDF travel handbooks from a standardized JSON spec. Use when a travel plan needs to be saved, exported, templatized, or rebuilt across cities with the same cover/overview/day-page/budget/source structure.
---

# Travel Handbook Generator

## Overview

Use this skill when a verified itinerary needs to become a reusable travel handbook instead of a one-off chat answer.

This skill standardizes the handbook workflow around:

- one JSON spec per trip
- one reusable renderer script
- one stable output shape: `cover -> overview -> daily pages -> budget -> sources`

Keep the context lean. Read only the file needed for the current step.

## File Map

| File | Use when |
| --- | --- |
| `scripts/init_handbook_spec.py` | You need to scaffold a new handbook spec under the current workspace |
| `scripts/render_handbook.py` | You need to render a spec into `DOCX + PDF` and preview images |
| `assets/handbook_spec_template.json` | You need the base shape for a new trip spec |
| `references/spec-schema.md` | You need field-level rules for filling titles, images, days, budget rows, or sources |

## Core Rules

1. This skill consumes verified planning data.
   Do not use it as a replacement for transport, hotel, ticket, or local-mobility verification. First verify the trip with the relevant travel skills, then write the handbook spec.

2. Prefer spec updates over new city-specific scripts.
   If the layout is still the same handbook family, add or update a JSON spec instead of creating another `generate_<city>_travel_handbook.py`.

3. Keep price language explicit inside the spec.
   Use `已核实金额`, `估算区间`, or `参考实时价` consistently in titles, rows, and notes.

4. Keep dates absolute.
   Do not leave `五一`, `明天`, or `下周` inside the handbook content. Convert them to explicit dates before writing the spec.

5. Always localize images at render time.
   The renderer downloads network images into the workspace temp directory before inserting them into the document. Do not hotlink images inside the DOCX.

6. Keep the source page visible.
   Every meaningful price, image, or route claim should map back to a source row in the spec.

## Workflow

### 1. Prepare verified inputs

Before creating the handbook spec, collect:

- final route and nightly stay plan
- verified long-distance transport
- verified hotel choice plus any upgrade reference
- scenic ticket rules and exclusions
- local mobility plan
- image URLs for cover and day pages

### 2. Scaffold the trip spec

Use `scripts/init_handbook_spec.py` to create a starter spec in the current workspace.

Recommended destination for specs:

- `./travel_specs/<slug>.json`

Example:

```bash
python3 /Users/shenmingjie/.codex/skills/travel-handbook-generator/scripts/init_handbook_spec.py \
  --workspace /Users/shenmingjie/Documents/skills \
  --slug huangshan-2026-05-01-2026-05-04 \
  --title "南京 - 黄山五一情侣图文旅行手册" \
  --subtitle "2026年5月1日 - 5月4日 | 4天3夜 | 黄山风景区 + 宏村 + 屯溪 + 西溪南" \
  --start-date 2026-05-01 \
  --end-date 2026-05-04
```

Then fill the generated JSON using `references/spec-schema.md`.

### 3. Fill the handbook spec

At minimum, fill these sections:

- `meta`
- `cover`
- `overview`
- `images`
- `days`
- `budget`
- `sources`

Only add `hotels` or `hotel_card` sections when the handbook needs explicit stay cards.

### 4. Render the handbook

Run:

```bash
python3 /Users/shenmingjie/.codex/skills/travel-handbook-generator/scripts/render_handbook.py \
  /absolute/path/to/spec.json
```

The renderer will:

- download images into `tmp/docs/<slug>/images`
- build the DOCX
- convert it to PDF
- render PDF preview PNGs for review

### 5. Review before delivery

Use the `doc` skill mindset for the last check:

- no broken image ratios
- no table overflow
- no clipped Chinese text
- budget and source pages remain readable

If the layout is wrong, fix the spec first. Only patch the renderer when the issue is structural across multiple trips.

## Output Conventions

- Store specs under `travel_specs/`
- Store finished documents under `output/doc/`
- Store temporary render files under `tmp/docs/<slug>/`

Suggested filenames:

- `城市-主题图文旅行手册-YYYY-MM-DD至YYYY-MM-DD.docx`
- `城市-主题图文旅行手册-YYYY-MM-DD至YYYY-MM-DD.pdf`

## When To Patch The Renderer

Patch `scripts/render_handbook.py` only when the improvement is reusable across many trips, for example:

- a new reusable section type
- better budget page layout
- more stable image handling
- more robust preview rendering

Do not patch the renderer just to accommodate one city's data wording.
