from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


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

DEFAULT_PARTS_SLOT_MAP_COLUMNS: dict[str, str] = {
    "value": "Value",
    "part_number": "Part Number",
    "description": "Description",
    "model": "Vendor_PN",
    "brand": "Vendor",
    "footprint": "PCB Footprint",
    "mount": "ISNC",
    "voltage": "Voltage",
    "tolerance": "Tolerance",
    "power": "Power",
}

SLOT_IDS: tuple[str, ...] = tuple(slot_id for slot_id, _ in FIXED_PART_SLOTS)

_SLOT_HEADER_HINTS: dict[str, tuple[str, ...]] = {
    "value": ("value", "值", "电容", "电阻值", "阻值"),
    "part_number": ("part number", "part_number", "part no", "料号", "mpn", "vendor_pn"),
    "description": ("description", "描述", "comment", "备注"),
    "model": ("model", "型号", "type", "device"),
    "brand": ("brand", "品牌", "vendor", "manufacturer", "mfg"),
    "footprint": ("footprint", "封装", "pcb footprint", "package", "source package"),
    "mount": ("贴装", "mount", "assembly"),
    "voltage": ("voltage", "电压", "额定电压", "耐压"),
    "tolerance": ("tolerance", "精度", "误差", "偏差"),
    "power": ("power", "功率", "额定功率", "功耗"),
}


def empty_slot_maps() -> dict[str, str]:
    return {slot_id: "" for slot_id in SLOT_IDS}


def normalize_slot_maps(raw: Any) -> dict[str, str]:
    out = empty_slot_maps()
    if not isinstance(raw, dict):
        return out
    for slot_id in SLOT_IDS:
        value = raw.get(slot_id)
        if value is None:
            continue
        out[slot_id] = str(value).strip()
    return out


def maps_have_any_mapping(m_old: dict[str, str], m_new: dict[str, str]) -> bool:
    for slot_id in SLOT_IDS:
        if (m_old.get(slot_id) or "").strip() or (m_new.get(slot_id) or "").strip():
            return True
    return False


def header_column_index(headers: list[str], chosen: str) -> int:
    target = chosen.strip()
    if not target:
        return -1
    target_cf = target.casefold()
    for idx, header in enumerate(headers):
        if str(header).strip().casefold() == target_cf:
            return idx
    return -1


def _score_header(header: str, slot_id: str) -> float:
    name = str(header).strip().casefold()
    if not name:
        return 0.0
    preferred = (DEFAULT_PARTS_SLOT_MAP_COLUMNS.get(slot_id) or "").strip().casefold()
    if preferred and name == preferred:
        return 110.0
    label = slot_label(slot_id).casefold()
    if name == label:
        return 100.0
    best = 0.0
    for hint in _SLOT_HEADER_HINTS.get(slot_id, ()):
        hint_cf = hint.casefold()
        if name == hint_cf:
            best = max(best, 95.0)
        elif hint_cf in name:
            best = max(best, 70.0 + min(15.0, len(hint_cf) / 3.0))
    return best


def pick_header_for_slot(
    headers: list[str],
    slot_id: str,
    used_casefold: set[str],
    *,
    min_score: float = 62.0,
) -> str:
    best_header = ""
    best_score = 0.0
    for header in headers:
        text = str(header).strip()
        if not text or text.casefold() in used_casefold:
            continue
        score = _score_header(text, slot_id)
        if score > best_score:
            best_score = score
            best_header = text
    if best_score >= min_score:
        return best_header
    return ""


def auto_map_parts_headers(
    headers_old: list[str], headers_new: list[str]
) -> tuple[dict[str, str], dict[str, str]]:
    used_old: set[str] = set()
    used_new: set[str] = set()
    mapped_old = empty_slot_maps()
    mapped_new = empty_slot_maps()
    for slot_id, _label in FIXED_PART_SLOTS:
        old_header = pick_header_for_slot(headers_old, slot_id, used_old)
        new_header = pick_header_for_slot(headers_new, slot_id, used_new)
        if old_header:
            mapped_old[slot_id] = old_header
            used_old.add(old_header.casefold())
        if new_header:
            mapped_new[slot_id] = new_header
            used_new.add(new_header.casefold())
    return mapped_old, mapped_new


def read_parts_csv_header(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            return [str(cell).strip() for cell in next(csv.reader(handle), [])]
    except OSError:
        return []


def get_effective_parts_slot_maps(
    prefs: dict[str, Any]
) -> tuple[dict[str, str], dict[str, str]]:
    mapped_old = normalize_slot_maps(prefs.get("partsCsvSlotMapDsn1"))
    mapped_new = normalize_slot_maps(prefs.get("partsCsvSlotMapDsn2"))
    if maps_have_any_mapping(mapped_old, mapped_new):
        return mapped_old, mapped_new
    old_path = Path(str(prefs.get("lastDsn1PartsCsv") or "").strip())
    new_path = Path(str(prefs.get("lastDsn2PartsCsv") or "").strip())
    if not old_path.is_file() or not new_path.is_file():
        return mapped_old, mapped_new
    return auto_map_parts_headers(
        read_parts_csv_header(old_path),
        read_parts_csv_header(new_path),
    )


def slot_label(slot_id: str) -> str:
    for current_id, label in FIXED_PART_SLOTS:
        if current_id == slot_id:
            return label
    return slot_id


def slot_display_value_from_map(values: dict[str, str], slot_id: str, label: str) -> str:
    for key in (label.casefold(), slot_id.casefold()):
        if key in values:
            return values[key]
    for hint in _SLOT_HEADER_HINTS.get(slot_id, ()):
        hint_cf = hint.casefold()
        if hint_cf in values:
            return values[hint_cf]
    return ""


def format_part_slots_display_line(values: dict[str, str]) -> str:
    bits: list[str] = []
    for slot_id, label in FIXED_PART_SLOTS:
        value = slot_display_value_from_map(values, slot_id, label)
        bits.append(f"{label}：{value if value else '-'}")
    return " | ".join(bits)
