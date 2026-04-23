---
name: pdf-drawing-diff
description: Compare two or more local PDF drawings by rendering pages to images, running GLM-OCR for text differences, using a VLM for visual differences, merging bbox annotations, and producing pairwise annotated images plus JSON / Markdown / PDF summary reports. Use when the user wants PDF drawing comparison, OCR diff, bbox grounding, explosion drawing review, BOM/text mismatch detection, or pairwise difference reports from explicit local PDF paths.
---

# PDF Drawing Diff

Compare any number of local PDF drawings (N >= 2) and emit reusable review artifacts.

## When To Use

Trigger when the request involves any of:

- 比较多个 PDF 图纸 / pairwise PDF compare
- 爆炸图差异分析 / explosion drawing diff
- OCR 差异比对 / text diff between drawings
- bbox 标注定位 / grounding boxes for diffs
- 汇总 `json / md / pdf` 报告

The agent must collect at least 2 explicit local PDF paths from the user before running this skill. Do not auto-scan directories.

## What This Skill Does

For N input PDFs (N >= 2):

1. Render the first page of each PDF to PNG with PyMuPDF.
2. Run `GLM-OCR layout_parsing` to extract `text_line` / `table_row` units and bboxes.
3. Build OCR doc summaries and run an LLM N-way综合分析 (falls back to a static summary if the text model fails).
4. Iterate every unordered pair `(la, lb)`:
   - Compute pixel diff heatmap + overlay (OpenCV).
   - Extract DWG strings if a sibling `.dwg` exists; otherwise stub it out.
   - Call the VLM for coarse 双图分析（可选分块扫描）.
   - Build callout / geometry / pixel ROIs and run VLM grounding (整图或 ROI 分块).
   - Sanitize, merge with OCR text-diff annotations and draw final annotated PNGs (CJK fonts).
   - Run a text-model verdict over the ROI rows.
5. Write per-pair outputs and top-level `pipeline_result_*.json`, `report.md`, `pipeline_annotated_*.pdf`.

Defaults:

- Auto-derive labels from filename stems if the user does not name them.
- Only the first page is compared (matches the original pipeline).
- `near_mismatch` stays in JSON / Markdown but is **not** drawn as a bbox.
- DWG sibling is auto-discovered: for `<stem>.pdf` (or `<stem>-Model.pdf`) the script looks for `<stem>.dwg` in the same directory.

## How To Run

The skill ships two scripts under `scripts/`. Invoke from the skill directory or via absolute path.

Minimum (auto labels):

```bash
/opt/anaconda3/envs/py311/bin/python3 scripts/run_pdf_drawing_diff.py \
  --pdf /abs/path/A.pdf \
  --pdf /abs/path/B.pdf
```

Explicit labels:

```bash
/opt/anaconda3/envs/py311/bin/python3 scripts/run_pdf_drawing_diff.py \
  --label P229A=/abs/path/P229A.pdf \
  --label P329A=/abs/path/P329A.pdf \
  --label P329C=/abs/path/P329C.pdf
```

Four (or more) PDFs work the same way; pairs are auto-generated as `combinations(labels, 2)`:

```bash
/opt/anaconda3/envs/py311/bin/python3 scripts/run_pdf_drawing_diff.py \
  --label A=/abs/A.pdf --label B=/abs/B.pdf \
  --label C=/abs/C.pdf --label D=/abs/D.pdf
```

Useful options:

- `--output-dir DIR`              输出根目录（默认 `./reports/output`）
- `--ocr-model NAME`              覆盖 `GLM_OCR_MODEL`
- `--vlm-model NAME`              覆盖 `VLM_MODEL`
- `--text-model NAME`             覆盖 `TEXT_MODEL`
- `--dpi N`                        渲染 DPI（默认 220）
- `--max-pages N`                  每个 PDF 最多渲染页数（v1 实际只比较第一页）
- `--ocr-timeout SEC`              OCR 调用超时
- `--vlm-timeout SEC`              VLM 调用超时
- `--openai-base-url URL`          覆盖 `OPENAI_BASE_URL`
- `--openai-api-key KEY`           覆盖 `OPENAI_API_KEY`
- `--zai-api-key KEY`              覆盖 `ZAI_API_KEY`
- `--dwg label=path`               显式指定某个 label 的 DWG 文件（重复传入）

## Required Environment

Provide either through `.env` (the skill auto-loads `<cwd>/.env` and `<skill>/.env`) or via CLI flags:

```dotenv
OPENAI_API_KEY=...
OPENAI_BASE_URL=...
TEXT_MODEL=gpt-4.1
VLM_MODEL=qwen3-vl-235b-a22b-thinking
VLM_API_STYLE=auto
ZAI_API_KEY=...
SSL_VERIFY=0
```

See `.env.example` for the complete tunable list (tile scan, ROI limits, callout heuristics, retry policy, etc.).

## Agent Rules

- Extract explicit local PDF paths from the user message before running the script.
- If the user gave labels in natural language, pass `--label LABEL=path`. Otherwise pass repeated `--pdf path` and let the script auto-label via filename stem.
- If fewer than 2 valid PDF paths exist, stop and clearly report which paths are missing or invalid.
- Never auto-scan a directory in v1.
- After the script finishes, surface to the user:
  - the run output directory,
  - paths to `pipeline_result_*.json`, `report.md`, `pipeline_annotated_*.pdf`,
  - count of pairs processed.
- The pipeline can take several minutes per pair due to OCR + VLM tile scans. Inform the user before kicking off long runs.

## Output Layout

Each run creates `reports/output/pipeline_run_<timestamp>/` with:

- `pipeline_result_<timestamp>.json`   — full structured result (OCR units, VLM analysis, ROIs, verdicts, paths)
- `report.md`                           — human Markdown report
- `pipeline_annotated_<timestamp>.pdf`  — multi-page export (cover + per-pair caption + 2 annotated pages)
- `rendered/<label>/page_001.png`       — OCR render input
- `<la>_vs_<lb>/`
  - `<la>_annotated.png` / `<lb>_annotated.png` — final merged annotation (VLM grounding + OCR diff)
  - `<la>_vs_<lb>_overlay.png`                  — diff overlay on B
  - `<la>_vs_<lb>_heatmap.png`                  — pixel diff heatmap
