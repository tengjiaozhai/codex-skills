from __future__ import annotations

from typing import Any

from .part_attr_slots import header_column_index


def normalize_csv_column_compare_entries(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "on": bool(item.get("on", True)),
                "d1": str(item.get("d1") or "").strip(),
                "d2": str(item.get("d2") or "").strip(),
            }
        )
    return out


def guess_pin_name_column(headers: list[str]) -> str:
    best = ""
    best_score = -1.0
    for header in headers:
        text = str(header).strip()
        if not text:
            continue
        cf = text.casefold()
        if cf in ("pin name", "pinname"):
            score = 100.0
        elif "pin" in cf and "name" in cf:
            score = 92.0
        elif "信号名" in text or "管脚名" in text:
            score = 88.0
        else:
            score = -1.0
        if score > best_score:
            best_score = score
            best = text
    return best


def guess_nets_pins_page_column(headers: list[str]) -> str:
    best = ""
    best_score = -1.0
    for header in headers:
        text = str(header).strip()
        if not text:
            continue
        cf = text.casefold()
        if "pin" in cf and "global" in cf:
            continue
        if "pins" in cf and "page" in cf:
            score = 100.0
        elif "pin" in cf and "page" in cf:
            score = 92.0
        else:
            score = -1.0
        if score > best_score:
            best_score = score
            best = text
    return best


def is_nets_pins_global_only_column_name(col_name: str) -> bool:
    cf = (col_name or "").strip().casefold()
    return bool(cf) and "pin" in cf and "global" in cf and "page" not in cf


def pins_nets_compare_pairs(
    headers_old: list[str], headers_new: list[str], entries: list[dict[str, Any]]
) -> list[tuple[str, int, int]]:
    pairs: list[tuple[str, int, int]] = []
    seen: set[tuple[int, int]] = set()
    for entry in entries:
        if not entry.get("on"):
            continue
        old_name = str(entry.get("d1") or "").strip()
        new_name = str(entry.get("d2") or "").strip()
        if not old_name and not new_name:
            continue
        old_idx = header_column_index(headers_old, old_name) if old_name else -1
        new_idx = header_column_index(headers_new, new_name) if new_name else -1
        if old_idx < 0 and new_idx < 0:
            continue
        if 0 <= old_idx < len(headers_old) and is_nets_pins_global_only_column_name(headers_old[old_idx]):
            continue
        if 0 <= new_idx < len(headers_new) and is_nets_pins_global_only_column_name(headers_new[new_idx]):
            continue
        key = (old_idx, new_idx)
        if key in seen:
            continue
        seen.add(key)
        if old_name and new_name and old_name.casefold() == new_name.casefold():
            label = old_name
        elif old_name and new_name:
            label = f"{old_name} / {new_name}"
        elif old_name:
            label = f"{old_name}（仅 DSN 1）"
        else:
            label = f"{new_name}（仅 DSN 2）"
        pairs.append((label, old_idx, new_idx))
    return pairs


def effective_pins_nets_column_pairs(
    headers_old: list[str], headers_new: list[str], raw: Any
) -> list[tuple[str, int, int]] | None:
    entries = normalize_csv_column_compare_entries(raw)
    if not entries:
        return None
    pairs = pins_nets_compare_pairs(headers_old, headers_new, entries)
    return pairs or None


def value_column_label_for_table(category: str, prop_name: str) -> str:
    text = (prop_name or "").strip()
    if not text:
        return ""
    cf = text.casefold()
    if category == "管脚":
        if ("pin" in cf and "name" in cf) or cf in ("pin name", "pinname", "信号名", "管脚名"):
            return "脚名"
        if "net" in cf or "signal" in cf or ("flat" in cf and "net" in cf) or "网络" in text:
            return "网名"
        return text
    if category == "网络":
        if "pin" in cf and "global" in cf:
            return "Pins（Global）"
        if "pin" in cf and "page" in cf:
            return "Pins"
        return text
    return text
