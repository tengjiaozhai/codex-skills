"""数据模型：DiffRow（差异结果行）与合并显示逻辑。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .diff_types import PROPERTY_STYLE_TYPES

# 固定对比槽位：(内部 id, 界面/导出用中文名)
FIXED_PART_SLOTS: tuple[tuple[str, str], ...] = (
    ("value", "Value"),
    ("part_number", "料号"),
    ("description", "描述"),
    ("model", "型号"),
    ("brand", "品牌"),
    ("footprint", "封装"),
    ("mount", "贴装"),
    ("voltage", "电压"),
    ("tolerance", "精度"),
    ("power", "功率"),
)

PART_SLOT_DISPLAY_LABELS: frozenset[str] = frozenset(lab for _, lab in FIXED_PART_SLOTS)


@dataclass
class DiffRow:
    """一条对比结果行。"""

    category: str  # 器件 | 管脚 | 网络
    change_type: str
    object_id: str
    detail: str
    prop_name: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def component_key(c: dict[str, Any]) -> tuple[str, str]:
    return (str(c.get("hierarchyPath", "")), str(c.get("refdes", "")))


def net_signature(pins: list[dict[str, str]]) -> frozenset[tuple[str, str]]:
    s: set[tuple[str, str]] = set()
    for p in pins:
        rd = str(p.get("refdes", ""))
        pin = str(p.get("pin", ""))
        s.add((rd, pin))
    return frozenset(s)


def _compact_prop_change(prop: str, old: Any, new: Any) -> str:
    """详情列：仅一条属性变化，短写。"""
    o = str(old).strip() or "（空）"
    n = str(new).strip() or "（空）"
    p = (prop or "").strip() or "属性"
    return f"{p} {o}→{n}"


def _part_prop_merge_rank(prop_name: str | None) -> int:
    pn = (prop_name or "").strip().casefold()
    for i, (_, lab) in enumerate(FIXED_PART_SLOTS):
        if lab.casefold() == pn:
            return i
    return len(FIXED_PART_SLOTS) + 1


def _net_property_merge_sort_key(prop_name: str | None) -> tuple[int, str]:
    pn = (prop_name or "").strip()
    cf = pn.casefold()
    if "pin" in cf and "page" in cf:
        return (0, pn.casefold())
    if "pin" in cf and "global" in cf:
        return (1, pn.casefold())
    return (2, pn.casefold())


def merge_property_change_rows_for_display(rows: list[DiffRow]) -> list[DiffRow]:
    """
    将同一对象的多条属性修改行合并为一行：
    - 旧值/新值用 " | " 拼接
    - 详情按属性名罗列
    非属性修改类型的行原样保留。
    """
    merged: list[DiffRow] = []
    groups: dict[str, list[DiffRow]] = {}
    order: list[str] = []
    for r in rows:
        if r.change_type not in PROPERTY_STYLE_TYPES:
            merged.append(r)
            continue
        # 网络类结果行按页坐标签名分组
        loc_key = _net_display_merge_location_key(r)
        gk = f"{r.category}|{r.change_type}|{r.object_id}|{loc_key}"
        if gk not in groups:
            groups[gk] = []
            order.append(gk)
        groups[gk].append(r)

    for gk in order:
        grp = groups[gk]
        if len(grp) == 1:
            merged.append(grp[0])
            continue
        # 按槽位排序
        if grp[0].category == "器件":
            grp.sort(key=lambda r: _part_prop_merge_rank(r.prop_name))
        elif grp[0].category == "网络":
            grp.sort(key=lambda r: _net_property_merge_sort_key(r.prop_name))
        first = grp[0]
        ov_parts: list[str] = []
        nv_parts: list[str] = []
        detail_parts: list[str] = []
        for r in grp:
            pn = (r.prop_name or "").strip()
            ov = str(r.old_value or "").strip()
            nv = str(r.new_value or "").strip()
            if pn:
                ov_parts.append(f"{pn}：{ov or '-'}")
                nv_parts.append(f"{pn}：{nv or '-'}")
            else:
                ov_parts.append(ov or "-")
                nv_parts.append(nv or "-")
            detail_parts.append(_compact_prop_change(pn, ov, nv))
        combined = DiffRow(
            category=first.category,
            change_type=first.change_type,
            object_id=first.object_id,
            detail=" | ".join(detail_parts),
            prop_name=None,
            old_value=" | ".join(ov_parts),
            new_value=" | ".join(nv_parts),
            meta=dict(first.meta),
        )
        merged.append(combined)
    return merged


def _net_display_merge_location_key(row: DiffRow) -> str:
    """网络类结果行合并展示时的「页坐标」签名。"""
    if (row.category or "").strip() != "网络":
        return ""
    m = row.meta or {}
    return "|".join(
        str(m.get(k) or "").strip()
        for k in (
            "schematicNameDsn1",
            "pageNameDsn1",
            "schematicNameDsn2",
            "pageNameDsn2",
        )
    )
