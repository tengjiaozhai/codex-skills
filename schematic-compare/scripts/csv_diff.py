"""
精简版 CSV 对比引擎。
实现了原理图对比的核心三路并行对比算法及行键匹配机制。
完全自包含，无任何图形界面或外部框架依赖。
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from .models import DiffRow
from .diff_types import (
    ADD,
    DELETE,
    COMPONENT_PROP,
    PIN_INFO,
    NET_RENAME,
    NET_CONNECTION,
    RENUMBER_REFDES,
)

_KIND_CATEGORY = {
    "parts": "器件",
    "pins": "管脚",
    "nets": "网络",
}

# 用于推断行键的列名关键词
_KEY_HINTS = ("refdes", "reference", "part ref", "part reference", "位号", "pin", "net", "signal", "flat")


def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    if not path.is_file():
        return [], []
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        return [], []
    header = [str(c).strip() for c in rows[0]]
    body = [list(r) for r in rows[1:]]
    return header, body


def _norm_headers(h: list[str]) -> list[str]:
    return [x.strip().casefold() for x in h]


def _row_key(headers: list[str], row: list[str]) -> str:
    """启发式提取行键：提取包含位号、管脚、网络等关键信息的列组合。"""
    n = max(len(headers), len(row))
    r = list(row) + [""] * (n - len(row))
    picks: list[tuple[int, str]] = []
    
    for i, name in enumerate(headers):
        if not name:
            continue
        n_cf = name.casefold()
        if any(k in n_cf for k in _KEY_HINTS):
            val = str(r[i]).strip() if i < len(r) else ""
            if val.casefold() in ("true", "false"):
                continue
            picks.append((i, val))
            
    if picks:
        return "|".join(v for _, v in sorted(picks, key=lambda t: t[0]))
    return (str(r[0]).strip() if r else "") or "__empty__"


def _build_merged_map(rows: list[list[str]], headers: list[str], ncol: int) -> dict[str, list[str]]:
    """按行键聚合：同键多行合并。"""
    groups: dict[str, list[list[str]]] = {}
    for r in rows:
        padded = list(r) + [""] * (ncol - len(r))
        padded = padded[:ncol]
        k = _row_key(headers, padded)
        if k not in groups:
            groups[k] = []
        groups[k].append(padded)
        
    merged: dict[str, list[str]] = {}
    for k, grp in groups.items():
        if len(grp) == 1:
            merged[k] = grp[0]
            continue
            
        m_row: list[str] = []
        for i in range(ncol):
            vals: list[str] = []
            seen: set[str] = set()
            for pr in grp:
                v = pr[i].strip()
                v_cf = v.casefold()
                if v and v_cf not in seen:
                    seen.add(v_cf)
                    vals.append(v)
            m_row.append(" | ".join(vals))
        merged[k] = m_row
        
    return merged


def compare_csv_pair(path_old: Path, path_new: Path, sheet_kind: str) -> list[DiffRow]:
    """对比一对 CSV 文件，返回差异列表。"""
    cat = _KIND_CATEGORY.get(sheet_kind.lower(), "器件")
    ho, ro = _read_csv(path_old)
    hn, rn = _read_csv(path_new)
    out: list[DiffRow] = []

    if not ho and not hn:
        return out
        
    ncol = max(len(ho), len(hn))
    use_h = ho + [f"列{i+1}" for i in range(len(ho), ncol)]
    
    map_o = _build_merged_map(ro, use_h, ncol)
    map_n = _build_merged_map(rn, use_h, ncol)
    
    keys_o = set(map_o.keys())
    keys_n = set(map_n.keys())
    
    all_keys = sorted(keys_o | keys_n)
    
    for k in all_keys:
        if k == "__empty__":
            continue
            
        if k in keys_o and k not in keys_n:
            out.append(DiffRow(
                category=cat,
                change_type=DELETE,
                object_id=k,
                detail=f"删除 {k}",
            ))
            continue
            
        if k in keys_n and k not in keys_o:
            out.append(DiffRow(
                category=cat,
                change_type=ADD,
                object_id=k,
                detail=f"新增 {k}",
            ))
            continue
            
        # 两边都有，对比属性
        vo = map_o[k]
        vn = map_n[k]
        
        for i, col_name in enumerate(use_h):
            # 跳过全局管脚列表等容易引起噪音的列
            if "global" in col_name.casefold() and "pin" in col_name.casefold():
                continue
                
            co = vo[i] if i < len(vo) else ""
            cn = vn[i] if i < len(vn) else ""
            
            if co != cn:
                prop_type = COMPONENT_PROP
                if cat == "管脚":
                    prop_type = PIN_INFO
                elif cat == "网络":
                    if "pin" in col_name.casefold() or "page" in col_name.casefold():
                        prop_type = NET_CONNECTION
                    else:
                        prop_type = NET_RENAME
                
                out.append(DiffRow(
                    category=cat,
                    change_type=prop_type,
                    object_id=k,
                    prop_name=col_name,
                    old_value=co,
                    new_value=cn,
                    detail=f"{col_name} 修改",
                ))

    return out


def compare_all_dsn_csvs(parts1: Path, parts2: Path, pins1: Path, pins2: Path, nets1: Path, nets2: Path) -> list[DiffRow]:
    """主入口：对比三组 CSV，返回统一差异列表。"""
    rows: list[DiffRow] = []
    
    if parts1.is_file() and parts2.is_file():
        rows.extend(compare_csv_pair(parts1, parts2, "parts"))
        
    if pins1.is_file() and pins2.is_file():
        rows.extend(compare_csv_pair(pins1, pins2, "pins"))
        
    if nets1.is_file() and nets2.is_file():
        rows.extend(compare_csv_pair(nets1, nets2, "nets"))
        
    # (此处省略了后处理管线如位号重编抑制、网络重命名合并，
    # 在完整项目中可引入更复杂的清洗逻辑以提升准确度)
        
    return rows
