---
name: edif-full-export
description: Use when working in this workspace to export OrCAD or Cadence EDIF .edf/.edif files, inspect schematic semantic tables, verify RawNodes coverage, or preserve schematic comparison CLI behavior
---

# EDIF Full Export

## Overview

This workspace exports OrCAD/Cadence EDIF files into multi-sheet Excel and optional
JSON while keeping the older schematic comparison flow stable. The core rule is:
full EDIF extraction is separate from lightweight EDIF comparison.

## When To Use

- Export one `.edf/.edif` file to `.xlsx` or `.json`.
- Inspect libraries, cells, ports, pages, instances, properties, pins, nets, displays,
  geometry, arrays, hierarchy refs, or raw EDIF nodes.
- Debug EDIF S-expression parsing, source line/column paths, or missing optional EDIF
  constructs.
- Change CLI behavior while preserving existing `edif`, `csv`, `dsn`, and `check-env`
  commands.

Do not use this skill for PCB layout, Gerber, or unrelated spreadsheet work.

## Quick Commands

Use the stable Conda Python path on this machine:

```bash
/opt/anaconda3/envs/py311/bin/python3 -m scripts.schcompare_cli edif-export input.edf -o full_edif.xlsx --json full_edif.json
/opt/anaconda3/envs/py311/bin/python3 -m pytest tests/test_edif_full_export.py -q
/opt/anaconda3/envs/py311/bin/python3 -m pytest tests/test_edif_full_export.py tests/test_regression_reference_case.py -q
```

## Key Files

| File | Purpose |
| --- | --- |
| `scripts/edif_sexpr.py` | Complete EDIF S-expression parser with source locations. |
| `scripts/edif_full_extract.py` | Semantic table extraction for full export. |
| `scripts/edif_full_export.py` | XLSX/JSON writers and fixed sheet columns. |
| `scripts/edif_import.py` | Lightweight EDIF parser for existing comparison only. |
| `scripts/schcompare_cli.py` | CLI dispatch for export and compare commands. |
| `references/edif_full_export_spec.md` | Sheet columns, semantics, and known limits. |
| `references/code_execution_flow.md` | Overall execution flowchart. |

## Guardrails

- Do not route full-export logic through `edif_import.py`.
- Keep `RawNodes` complete; it is the coverage backstop for unpromoted structures.
- Treat missing EDIF fields as empty values when optional, but keep parse errors visible
  for malformed S-expressions.
- Run compare regression tests after changing shared CLI or report code.

## Acceptance

For `AI_SCH_CPU_V1.EDF`, raw coverage should meet the counts recorded in `PLAN.md`.
The current full suite is `13 passed` with the two pytest commands above.
