# Skill Pressure Scenarios

These scenarios define how future agents should prove they are using this workspace
skill correctly. They are scoped to this repository and do not install anything into
global skill directories.

## Scenario 1: User Wants Full EDIF Export

Prompt: "把 `/path/design.edf` 导出为 Excel，并保留 JSON。"

Expected behavior:
- Use `/opt/anaconda3/envs/py311/bin/python3`.
- Run `python -m scripts.schcompare_cli edif-export`.
- Write `.xlsx` as the primary output and optional `.json` when requested.
- Verify `Summary` and `RawNodes` counts when a real fixture is available.

Failure pattern to avoid:
- Editing `scripts.edif_import.py` for full export behavior.
- Using bare `python`, which may not resolve on this machine.

## Scenario 2: User Asks To Change Existing EDIF Compare

Prompt: "改一下 EDIF 对比里的解析，顺便让全量导出更完整。"

Expected behavior:
- Keep the compare path and full-export path separate.
- Use `scripts.edif_import.py` only for lightweight compare CSV generation.
- Use `scripts.edif_sexpr.py`, `scripts.edif_full_extract.py`, and
  `scripts.edif_full_export.py` for full semantic extraction.
- Run both full-export tests and regression compare tests.

Failure pattern to avoid:
- Sharing new full-extraction assumptions with the old compare importer.

## Scenario 3: Large Real EDIF Fixture

Prompt: "用 `AI_SCH_CPU_V1.EDF` 验证导出是否完整。"

Expected behavior:
- Run the real fixture command from `PLAN.md`.
- Confirm raw coverage at least matches:
  `property=9170`, `origin=7430`, `pt=14766`, `orientation=605`,
  `display=6176`, `library=21`, `cell=53`, `interface=53`, `port=880`,
  `portInstance=1195`, `array=16`, `page=8`, `instance=1263`, `net=357`.

Failure pattern to avoid:
- Checking only that the workbook file exists.
- Ignoring `RawNodes`, which is the completeness backstop.

## Scenario 4: Missing Or Incomplete EDIF Constructs

Prompt: "这个 EDIF 的 port 没有 direction，导出失败了。"

Expected behavior:
- Add a focused regression test in `tests/test_edif_full_export.py`.
- Keep missing optional EDIF fields as empty strings instead of crashing.
- Re-run full test suite.

Failure pattern to avoid:
- Special-casing one file path or hiding parse errors in the CLI.
