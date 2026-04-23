"""
对比报告导出模块。
支持 Excel (.xlsx) 和 Markdown (.md) 两种输出格式。

Excel 依赖 openpyxl（可选）；Markdown 为纯文本，零依赖。
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import DiffRow, merge_property_change_rows_for_display
from .diff_types import ADD, DELETE, NET_CONNECTION, NET_RENAME, RENUMBER_REFDES


# ============================================================
# 风险等级与颜色编码
# ============================================================

_RISK_MAP = {
    DELETE: ("高", "🔴"),
    NET_CONNECTION: ("高", "🔴"),
    ADD: ("中", "🟡"),
    "器件属性": ("中", "🟡"),
    "管脚属性": ("中", "🟡"),
    NET_RENAME: ("低", "🟢"),
    RENUMBER_REFDES: ("低", "🟢"),
}


def risk_level(row: DiffRow) -> str:
    """返回差异行的风险等级文字。"""
    info = _RISK_MAP.get(row.change_type, ("中", "🟡"))
    return info[0]


def risk_emoji(row: DiffRow) -> str:
    info = _RISK_MAP.get(row.change_type, ("中", "🟡"))
    return info[1]


# ============================================================
# Markdown 报告导出
# ============================================================

def export_markdown(
    path: str | Path,
    rows: list[DiffRow],
    meta: dict[str, Any] | None = None,
) -> None:
    """
    导出 Markdown 格式的对比报告。

    参数：
        path: 输出文件路径
        rows: DiffRow 列表
        meta: 元数据字典（可选，含 oldPath/newPath 等）
    """
    p = Path(path)
    meta = meta or {}
    merged = merge_property_change_rows_for_display(rows)
    sorted_rows = sorted(merged, key=lambda r: (r.category, r.change_type, r.object_id))

    lines: list[str] = []
    lines.append("# 原理图对比报告\n")
    lines.append(f"**生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    if meta.get("oldPath"):
        lines.append(f"**旧版本 (DSN1)**：`{meta['oldPath']}`\n")
    if meta.get("newPath"):
        lines.append(f"**新版本 (DSN2)**：`{meta['newPath']}`\n")

    # 统计摘要
    by_type: dict[str, int] = {}
    for r in sorted_rows:
        by_type[r.change_type] = by_type.get(r.change_type, 0) + 1

    lines.append(f"\n## 摘要（共 {len(sorted_rows)} 处差异）\n")
    lines.append("| 差异类型 | 数量 | 风险 |")
    lines.append("|---------|------|------|")
    for ct, count in sorted(by_type.items()):
        risk_info = _RISK_MAP.get(ct, ("中", "🟡"))
        lines.append(f"| {ct} | {count} | {risk_info[1]} {risk_info[0]} |")

    # 详细表格
    lines.append("\n## 详细差异列表\n")
    lines.append("| # | 类别 | 差异类型 | 对象 | 修改详情 | 旧值 | 新值 | 风险 |")
    lines.append("|---|------|---------|------|---------|------|------|------|")
    for idx, r in enumerate(sorted_rows, start=1):
        ov = (r.old_value or "-").replace("|", "\\|")
        nv = (r.new_value or "-").replace("|", "\\|")
        detail = (r.detail or "").replace("|", "\\|")
        obj = (r.object_id or "").replace("|", "\\|")
        ri = _RISK_MAP.get(r.change_type, ("中", "🟡"))
        lines.append(
            f"| {idx} | {r.category} | {r.change_type} | {obj} | {detail} | {ov} | {nv} | {ri[1]} |"
        )

    p.write_text("\n".join(lines), encoding="utf-8")


# ============================================================
# Excel 报告导出
# ============================================================

def export_excel(
    path: str | Path,
    rows: list[DiffRow],
    meta: dict[str, Any] | None = None,
) -> None:
    """
    导出 Excel 格式的对比报告（需要 openpyxl）。

    参数：
        path: 输出文件路径 (.xlsx)
        rows: DiffRow 列表
        meta: 元数据字典（可选）
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise ImportError(
            "Excel 导出需要 openpyxl 库。请执行：pip install openpyxl"
        )

    p = Path(path)
    meta = meta or {}
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "对比结果"

    merged = merge_property_change_rows_for_display(rows)
    sorted_rows = sorted(merged, key=lambda r: (r.category, r.change_type, r.object_id))

    # 表头
    headers = ("序号", "分类", "差异类型", "对象标识", "旧值", "新值", "修改详情", "风险等级")
    header_fill = PatternFill("solid", fgColor="D4D0C8")
    header_font = Font(bold=True)
    for col, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(vertical="center", wrap_text=True)

    # 风险等级背景色映射
    risk_fills = {
        "高": PatternFill("solid", fgColor="FFEBEE"),
        "中": PatternFill("solid", fgColor="FFF8E1"),
        "低": PatternFill("solid", fgColor="E3F2FD"),
    }

    # 数据行
    for idx, r in enumerate(sorted_rows, start=1):
        row_num = idx + 1
        rl = risk_level(r)
        ws.cell(row=row_num, column=1, value=idx)
        ws.cell(row=row_num, column=2, value=r.category)
        ws.cell(row=row_num, column=3, value=r.change_type)
        ws.cell(row=row_num, column=4, value=r.object_id or "")
        ws.cell(row=row_num, column=5, value=r.old_value or "-")
        ws.cell(row=row_num, column=6, value=r.new_value or "-")
        ws.cell(row=row_num, column=7, value=r.detail or "")
        ws.cell(row=row_num, column=8, value=rl)
        fill = risk_fills.get(rl)
        for c in range(1, 9):
            cell = ws.cell(row=row_num, column=c)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if fill:
                cell.fill = fill

    # 列宽
    widths = (6, 8, 12, 28, 40, 40, 44, 8)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # 元数据工作表
    info = wb.create_sheet("元数据")
    info.append(("导出时间", datetime.now().isoformat(timespec="seconds")))
    if meta.get("oldPath"):
        info.append(("旧版本路径", str(meta["oldPath"])))
    if meta.get("newPath"):
        info.append(("新版本路径", str(meta["newPath"])))
    if meta.get("mode"):
        info.append(("对比模式", str(meta["mode"])))
    info.append(("差异总数", str(len(sorted_rows))))

    wb.save(p)
