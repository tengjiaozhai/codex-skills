from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
from openpyxl import load_workbook

from scripts.csv_diff import compare_all_dsn_csvs
from scripts.export_report import export_excel
from scripts.models import DiffRow


FIXTURE_ROOT = Path("/Users/shenmingjie/tinno/hardware-diagram")
OLD_EDIF = FIXTURE_ROOT / "AI_SCH_CPU_V1.EDF"
NEW_EDIF = FIXTURE_ROOT / "AI_SCH_CPU_V2.EDF"


@pytest.mark.skipif(
    not OLD_EDIF.is_file() or not NEW_EDIF.is_file(),
    reason="reference EDIF files are not available on this machine",
)
def test_edif_reference_case_matches_expected_diff_distribution(tmp_path: Path) -> None:
    from scripts.edif_import import import_edif_pair_to_dirs

    old_dir = tmp_path / "v1"
    new_dir = tmp_path / "v2"
    old_dir.mkdir()
    new_dir.mkdir()

    out1, out2 = import_edif_pair_to_dirs(OLD_EDIF, NEW_EDIF, old_dir, new_dir)
    rows = compare_all_dsn_csvs(
        out1["parts"],
        out2["parts"],
        out1["pins"],
        out2["pins"],
        out1["nets"],
        out2["nets"],
    )

    counts = Counter((row.category, row.change_type) for row in rows)

    assert len(rows) == 77
    assert counts == Counter(
        {
            ("器件", "位号重编"): 54,
            ("器件", "删除"): 2,
            ("器件", "新增"): 3,
            ("管脚", "删除"): 6,
            ("管脚", "新增"): 6,
            ("网络", "新增"): 1,
            ("网络", "连接变更"): 5,
        }
    )


def test_export_excel_uses_standard_compare_columns(tmp_path: Path) -> None:
    rows = [
        DiffRow(
            category="器件",
            change_type="位号重编",
            object_id="[Parts] C9001|UTAH_MB|10_BB_PWR_PDN1",
            detail="位号C1001→C9001，属性不变",
            prop_name="refdes",
            old_value="Value：4.3uF | 料号：- | 描述：- | 型号：- | 品牌：- | 封装：- | 贴装：- | 电压：- | 精度：- | 功率：-",
            new_value="Value：4.3uF | 料号：- | 描述：- | 型号：- | 品牌：- | 封装：- | 贴装：- | 电压：- | 精度：- | 功率：-",
            meta={
                "oldRefdes": "C1001",
                "newRefdes": "C9001",
                "schematicNameDsn1": "UTAH_MB",
                "pageNameDsn1": "10_BB_PWR_PDN1",
                "schematicNameDsn2": "UTAH_MB",
                "pageNameDsn2": "10_BB_PWR_PDN1",
            },
        )
    ]
    out = tmp_path / "report.xlsx"

    export_excel(
        out,
        rows,
        {
            "oldPath": str(OLD_EDIF),
            "newPath": str(NEW_EDIF),
            "selectedProps": [
                "Description",
                "ISNC",
                "PCB Footprint",
                "Part Number",
                "Power",
                "Tolerance",
                "Value",
                "Vendor",
                "Vendor_PN",
                "Voltage",
            ],
        },
    )

    wb = load_workbook(out, read_only=True, data_only=True)
    ws = wb["对比结果"]
    header = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
    first = next(ws.iter_rows(min_row=2, max_row=2, values_only=True))

    assert header == (
        "差异类型",
        "类别",
        "DSN 1",
        "DSN 2",
        "旧值",
        "新值",
        "页面",
        "修改详情",
        "风险等级",
        "差异说明",
    )
    assert first == (
        "位号重编",
        "器件",
        "C1001",
        "C9001",
        "Value：4.3uF ; 料号：  ; 描述：  ; 型号：  ; 品牌：  ; 封装：  ; 贴装：  ; 电压：  ; 精度：  ; 功率： ",
        "Value：4.3uF ; 料号：  ; 描述：  ; 型号：  ; 品牌：  ; 封装：  ; 贴装：  ; 电压：  ; 精度：  ; 功率： ",
        "UTAH_MB/10_BB_PWR_PDN1 ; UTAH_MB/10_BB_PWR_PDN1",
        "位号C1001→C9001，属性不变",
        "低",
        "仅位号调整，属性不变",
    )
