from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .csv_column_compare import (
    effective_pins_nets_column_pairs,
    guess_nets_pins_page_column,
    guess_pin_name_column,
)
from .diff_types import (
    ADD,
    COMPONENT_PROP,
    DELETE,
    NET_CONNECTION,
    PIN_INFO,
    RENUMBER_REFDES,
    csv_change_type,
    format_renumber_refdes_detail,
)
from .models import DiffRow
from .part_attr_slots import (
    FIXED_PART_SLOTS,
    format_part_slots_display_line,
    get_effective_parts_slot_maps,
    header_column_index,
    maps_have_any_mapping,
)

_KIND_CATEGORY = {
    "parts": "器件",
    "pins": "管脚",
    "nets": "网络",
}

_REFDES_TOKEN = re.compile(r"^[A-Za-z]{1,6}\d[\w-]*$", re.ASCII)
_PIN_TOKEN = re.compile(r"([A-Za-z]{1,6}\d[\w-]*)\.([^\s,;|]+)", re.ASCII)


def _read_csv(path: Path) -> tuple[list[str], list[list[str]]]:
    if not path.is_file():
        return [], []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return [], []
    return [str(cell).strip() for cell in rows[0]], [list(row) for row in rows[1:]]


def _pad(row: list[str], ncol: int) -> list[str]:
    padded = list(row)
    while len(padded) < ncol:
        padded.append("")
    return padded[:ncol]


def _first_cell_segment(value: str) -> str:
    for part in str(value).split("|"):
        text = part.strip()
        if text:
            return text
    return ""


def _cell(row: list[str], idx: int) -> str:
    if idx < 0 or idx >= len(row):
        return ""
    return str(row[idx]).strip()


def _locate_column_indices(headers: list[str]) -> dict[str, int]:
    normalized = [str(header).strip().casefold() for header in headers]
    idx = {"refdes": -1, "schematic": -1, "page": -1, "net": -1, "pin": -1, "pin_name": -1}
    for i, name in enumerate(normalized):
        if idx["refdes"] < 0:
            if name in ("reference designator", "part reference", "refdes", "reference", "gate"):
                idx["refdes"] = i
            elif "reference" in name and "designator" in name:
                idx["refdes"] = i
        if idx["schematic"] < 0 and "schematic" in name and "page" not in name:
            idx["schematic"] = i
        if idx["page"] < 0 and (name == "page" or name.endswith(" page") or "页" == name):
            idx["page"] = i
        if idx["net"] < 0:
            if name in ("net name", "netname", "signal", "flatnet", "flat net", "flat_net"):
                idx["net"] = i
            elif "net" in name and "pin" not in name and "internet" not in name:
                idx["net"] = i
        if idx["pin"] < 0:
            if name in ("pin number", "pin num", "pin", "pad"):
                idx["pin"] = i
            elif "pin" in name and "pins" not in name and "name" not in name:
                idx["pin"] = i
        if idx["pin_name"] < 0:
            if name in ("pin name", "pinname"):
                idx["pin_name"] = i
            elif "pin" in name and "name" in name:
                idx["pin_name"] = i
    return idx


def _csv_row_location_meta(
    headers_old: list[str],
    row_old: list[str] | None,
    headers_new: list[str],
    row_new: list[str] | None,
) -> dict[str, str]:
    meta = {
        "schematicNameDsn1": "",
        "pageNameDsn1": "",
        "schematicNameDsn2": "",
        "pageNameDsn2": "",
    }
    if row_old is not None:
        idx_old = _locate_column_indices(headers_old)
        meta["schematicNameDsn1"] = _cell(row_old, idx_old["schematic"])
        meta["pageNameDsn1"] = _cell(row_old, idx_old["page"])
    if row_new is not None:
        idx_new = _locate_column_indices(headers_new)
        meta["schematicNameDsn2"] = _cell(row_new, idx_new["schematic"])
        meta["pageNameDsn2"] = _cell(row_new, idx_new["page"])
    return meta


def _part_slot_value_map(row: list[str], slot_cols: list[tuple[str, str, int]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for slot_id, label, idx in slot_cols:
        value = _cell(row, idx)
        if not value:
            continue
        values[slot_id.casefold()] = value
        values[label.casefold()] = value
    return values


def _part_slot_signature(row: list[str], headers: list[str], slot_cols: list[tuple[str, str, int]]) -> tuple[str, ...]:
    loc = _locate_column_indices(headers)
    sig = [
        _cell(row, loc["schematic"]).casefold(),
        _cell(row, loc["page"]).casefold(),
    ]
    for slot_id, _label, idx in slot_cols:
        sig.append(_cell(row, idx).casefold())
    return tuple(sig)


def _part_slot_lines(
    old_row: list[str] | None,
    new_row: list[str] | None,
    slot_cols_old: list[tuple[str, str, int]],
    slot_cols_new: list[tuple[str, str, int]],
) -> tuple[str, str]:
    old_values = _part_slot_value_map(old_row or [], [(sid, label, idx) for sid, label, idx in slot_cols_old]) if old_row else {}
    new_values = _part_slot_value_map(new_row or [], [(sid, label, idx) for sid, label, idx in slot_cols_new]) if new_row else {}
    return format_part_slots_display_line(old_values), format_part_slots_display_line(new_values)


def _selected_part_slot_columns(
    headers_old: list[str],
    headers_new: list[str],
    parts_slot_map_old: dict[str, str],
    parts_slot_map_new: dict[str, str],
) -> tuple[list[tuple[str, str, int]], list[tuple[str, str, int]]]:
    old_cols: list[tuple[str, str, int]] = []
    new_cols: list[tuple[str, str, int]] = []
    for slot_id, label in FIXED_PART_SLOTS:
        old_idx = header_column_index(headers_old, parts_slot_map_old.get(slot_id) or "")
        new_idx = header_column_index(headers_new, parts_slot_map_new.get(slot_id) or "")
        if old_idx < 0 and new_idx < 0:
            continue
        old_cols.append((slot_id, label, old_idx))
        new_cols.append((slot_id, label, new_idx))
    return old_cols, new_cols


def _part_refdes(row: list[str], headers: list[str]) -> str:
    return _cell(row, _locate_column_indices(headers)["refdes"])


def compare_parts_csv_pair(
    path_old: Path,
    path_new: Path,
    *,
    parts_slot_map_old: dict[str, str] | None = None,
    parts_slot_map_new: dict[str, str] | None = None,
) -> list[DiffRow]:
    headers_old, body_old = _read_csv(path_old)
    headers_new, body_new = _read_csv(path_new)
    if not headers_old and not headers_new:
        return []

    parts_slot_map_old = parts_slot_map_old or {}
    parts_slot_map_new = parts_slot_map_new or {}
    old_slot_cols, new_slot_cols = _selected_part_slot_columns(
        headers_old, headers_new, parts_slot_map_old, parts_slot_map_new
    )

    loc_old = _locate_column_indices(headers_old)
    loc_new = _locate_column_indices(headers_new)

    old_map = {_part_refdes(row, headers_old): row for row in body_old if _part_refdes(row, headers_old)}
    new_map = {_part_refdes(row, headers_new): row for row in body_new if _part_refdes(row, headers_new)}

    paired_old: set[str] = set()
    paired_new: set[str] = set()
    rows: list[DiffRow] = []
    renumber_rows: list[DiffRow] = []

    if old_slot_cols or new_slot_cols:
        old_only_by_sig: dict[tuple[str, ...], list[tuple[str, list[str]]]] = defaultdict(list)
        new_only_by_sig: dict[tuple[str, ...], list[tuple[str, list[str]]]] = defaultdict(list)
        for refdes, row in old_map.items():
            if refdes not in new_map:
                old_only_by_sig[_part_slot_signature(row, headers_old, old_slot_cols)].append((refdes, row))
        for refdes, row in new_map.items():
            if refdes not in old_map:
                new_only_by_sig[_part_slot_signature(row, headers_new, new_slot_cols)].append((refdes, row))

        for signature, old_items in old_only_by_sig.items():
            new_items = new_only_by_sig.get(signature, [])
            if not new_items:
                continue
            old_sorted = sorted(old_items, key=lambda item: item[0].casefold())
            new_sorted = sorted(new_items, key=lambda item: item[0].casefold())
            for (old_ref, old_row), (new_ref, new_row) in zip(old_sorted, new_sorted):
                if old_ref.casefold() == new_ref.casefold():
                    continue
                paired_old.add(old_ref)
                paired_new.add(new_ref)
                old_line, new_line = _part_slot_lines(old_row, new_row, old_slot_cols, new_slot_cols)
                meta = _csv_row_location_meta(headers_old, old_row, headers_new, new_row)
                meta["oldRefdes"] = old_ref
                meta["newRefdes"] = new_ref
                renumber_rows.append(
                    DiffRow(
                        category="器件",
                        change_type=RENUMBER_REFDES,
                        object_id=f"[Parts] {new_ref}|{meta['schematicNameDsn2']}|{meta['pageNameDsn2']}",
                        detail=format_renumber_refdes_detail(old_ref, new_ref),
                        prop_name="refdes",
                        old_value=old_line,
                        new_value=new_line,
                        meta=meta,
                    )
                )

    renumber_rows.sort(
        key=lambda row: (
            str((row.meta or {}).get("newRefdes") or "").casefold(),
            str((row.meta or {}).get("oldRefdes") or "").casefold(),
        )
    )
    rows.extend(renumber_rows)

    for refdes in sorted(set(old_map) | set(new_map), key=str.casefold):
        old_row = old_map.get(refdes)
        new_row = new_map.get(refdes)
        if old_row is not None and new_row is not None:
            if old_slot_cols or new_slot_cols:
                for (slot_id, label, old_idx), (_slot_id_new, _label_new, new_idx) in zip(old_slot_cols, new_slot_cols):
                    old_value = _cell(old_row, old_idx)
                    new_value = _cell(new_row, new_idx)
                    if old_value == new_value:
                        continue
                    rows.append(
                        DiffRow(
                            category="器件",
                            change_type=COMPONENT_PROP,
                            object_id=f"[Parts] {refdes}",
                            detail=f"{label} {old_value or '（空）'}→{new_value or '（空）'}",
                            prop_name=label,
                            old_value=old_value,
                            new_value=new_value,
                            meta=_csv_row_location_meta(headers_old, old_row, headers_new, new_row),
                        )
                    )
            continue
        if old_row is not None and refdes not in paired_old:
            old_line, new_line = _part_slot_lines(old_row, None, old_slot_cols, new_slot_cols)
            meta = _csv_row_location_meta(headers_old, old_row, headers_new, None)
            rows.append(
                DiffRow(
                    category="器件",
                    change_type=DELETE,
                    object_id=f"[Parts] {refdes}|{meta['schematicNameDsn1']}|{meta['pageNameDsn1']}",
                    detail=f"删除{refdes}",
                    old_value=old_line,
                    new_value=new_line,
                    meta=meta,
                )
            )
        if new_row is not None and refdes not in paired_new:
            old_line, new_line = _part_slot_lines(None, new_row, old_slot_cols, new_slot_cols)
            meta = _csv_row_location_meta(headers_old, None, headers_new, new_row)
            rows.append(
                DiffRow(
                    category="器件",
                    change_type=ADD,
                    object_id=f"[Parts] {refdes}|{meta['schematicNameDsn2']}|{meta['pageNameDsn2']}",
                    detail=f"新增{refdes}",
                    old_value=old_line,
                    new_value=new_line,
                    meta=meta,
                )
            )
    return rows


def _pin_row_key(row: list[str], headers: list[str]) -> str:
    loc = _locate_column_indices(headers)
    refdes = _cell(row, loc["refdes"])
    pin = _cell(row, loc["pin"])
    sch = _cell(row, loc["schematic"])
    page = _cell(row, loc["page"])
    return "|".join((refdes, pin, sch, page))


def _pin_snapshot_line(row: list[str], headers: list[str]) -> str:
    loc = _locate_column_indices(headers)
    refdes = _cell(row, loc["refdes"])
    pin = _cell(row, loc["pin"])
    pin_name = _cell(row, loc["pin_name"])
    net_name = _cell(row, loc["net"])
    bits = [
        f"Reference：{refdes}",
        f"Pin Number：{pin}",
        f"脚名：{pin_name}",
        f"网名：{net_name}",
    ]
    return " | ".join(bits)


def _pin_refdes_dot_pin(row: list[str], headers: list[str]) -> str:
    loc = _locate_column_indices(headers)
    refdes = _cell(row, loc["refdes"])
    pin = _cell(row, loc["pin"])
    return f"{refdes}.{pin}" if refdes and pin else refdes


def compare_pins_csv_pair(
    path_old: Path,
    path_new: Path,
    *,
    pins_nets_column_compare: Any | None = None,
) -> list[DiffRow]:
    headers_old, body_old = _read_csv(path_old)
    headers_new, body_new = _read_csv(path_new)
    if not headers_old and not headers_new:
        return []

    pairs = effective_pins_nets_column_pairs(headers_old, headers_new, pins_nets_column_compare)
    if pairs is None:
        guessed_old = guess_pin_name_column(headers_old)
        guessed_new = guess_pin_name_column(headers_new)
        pairs = [(guessed_old or guessed_new or "Pin Name", header_column_index(headers_old, guessed_old), header_column_index(headers_new, guessed_new))]

    old_map = {_pin_row_key(row, headers_old): row for row in body_old if _pin_row_key(row, headers_old).strip("|")}
    new_map = {_pin_row_key(row, headers_new): row for row in body_new if _pin_row_key(row, headers_new).strip("|")}

    rows: list[DiffRow] = []
    for key in sorted(set(old_map) | set(new_map), key=str.casefold):
        old_row = old_map.get(key)
        new_row = new_map.get(key)
        if old_row is not None and new_row is not None:
            for label, old_idx, new_idx in pairs or []:
                old_value = _cell(old_row, old_idx)
                new_value = _cell(new_row, new_idx)
                if old_value == new_value:
                    continue
                rows.append(
                    DiffRow(
                        category="管脚",
                        change_type=PIN_INFO,
                        object_id=f"[Pins] {key}",
                        detail=f"{label} {old_value or '（空）'}→{new_value or '（空）'}",
                        prop_name=label,
                        old_value=old_value,
                        new_value=new_value,
                        meta=_csv_row_location_meta(headers_old, old_row, headers_new, new_row),
                    )
                )
            continue
        if old_row is not None:
            ref_pin = _pin_refdes_dot_pin(old_row, headers_old)
            rows.append(
                DiffRow(
                    category="管脚",
                    change_type=DELETE,
                    object_id=f"[Pins] {key}",
                    detail=f"删除{ref_pin}",
                    old_value=_pin_snapshot_line(old_row, headers_old),
                    new_value="",
                    meta=_csv_row_location_meta(headers_old, old_row, headers_new, None),
                )
            )
        if new_row is not None:
            ref_pin = _pin_refdes_dot_pin(new_row, headers_new)
            rows.append(
                DiffRow(
                    category="管脚",
                    change_type=ADD,
                    object_id=f"[Pins] {key}",
                    detail=f"新增{ref_pin}",
                    old_value="",
                    new_value=_pin_snapshot_line(new_row, headers_new),
                    meta=_csv_row_location_meta(headers_old, None, headers_new, new_row),
                )
            )
    return rows


def _nets_tokenize_pin_like_list(payload: str) -> list[str]:
    text = (payload or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[,;|]+", text) if part.strip()]


def _normalize_pin_list(payload: str) -> str:
    unique: dict[str, str] = {}
    for token in _nets_tokenize_pin_like_list(payload):
        key = token.casefold()
        if key not in unique:
            unique[key] = token
    return ", ".join(unique[key] for key in sorted(unique, key=str.lower))


def _net_row_key(row: list[str], headers: list[str]) -> str:
    loc = _locate_column_indices(headers)
    net_name = _cell(row, loc["net"])
    sch = _cell(row, loc["schematic"])
    page = _cell(row, loc["page"])
    return "|".join((net_name, sch, page))


def _net_name_from_key(key: str) -> str:
    return key.split("|", 1)[0].strip()


def _nets_pins_connection_detail_cn(old_value: str, new_value: str) -> str:
    old_tokens = {token.casefold(): token for token in _nets_tokenize_pin_like_list(old_value)}
    new_tokens = {token.casefold(): token for token in _nets_tokenize_pin_like_list(new_value)}
    added = [new_tokens[key] for key in sorted(set(new_tokens) - set(old_tokens), key=str.lower)]
    removed = [old_tokens[key] for key in sorted(set(old_tokens) - set(new_tokens), key=str.lower)]
    segments: list[str] = []
    if removed:
        segments.append(f"Pins 减少{','.join(removed)}")
    if added:
        if removed:
            segments.append(f"增加{','.join(added)}")
        else:
            segments.append(f"Pins 增加{','.join(added)}")
    return " ".join(segments) if segments else "Pins"


def compare_nets_csv_pair(
    path_old: Path,
    path_new: Path,
    *,
    pins_nets_column_compare: Any | None = None,
) -> list[DiffRow]:
    headers_old, body_old = _read_csv(path_old)
    headers_new, body_new = _read_csv(path_new)
    if not headers_old and not headers_new:
        return []

    pairs = effective_pins_nets_column_pairs(headers_old, headers_new, pins_nets_column_compare)
    if pairs is None:
        guessed_old = guess_nets_pins_page_column(headers_old)
        guessed_new = guess_nets_pins_page_column(headers_new)
        pairs = [(guessed_old or guessed_new or "Pins (Page)", header_column_index(headers_old, guessed_old), header_column_index(headers_new, guessed_new))]

    old_map = {_net_row_key(row, headers_old): row for row in body_old if _net_row_key(row, headers_old).strip("|")}
    new_map = {_net_row_key(row, headers_new): row for row in body_new if _net_row_key(row, headers_new).strip("|")}

    rows: list[DiffRow] = []
    for key in sorted(set(old_map) | set(new_map), key=str.casefold):
        old_row = old_map.get(key)
        new_row = new_map.get(key)
        if old_row is not None and new_row is not None:
            for label, old_idx, new_idx in pairs or []:
                old_value = _normalize_pin_list(_cell(old_row, old_idx))
                new_value = _normalize_pin_list(_cell(new_row, new_idx))
                if old_value == new_value:
                    continue
                rows.append(
                    DiffRow(
                        category="网络",
                        change_type=NET_CONNECTION,
                        object_id=f"[Nets] {key}",
                        detail=_nets_pins_connection_detail_cn(old_value, new_value),
                        prop_name=label,
                        old_value=old_value,
                        new_value=new_value,
                        meta=_csv_row_location_meta(headers_old, old_row, headers_new, new_row),
                    )
                )
            continue
        if old_row is not None:
            rows.append(
                DiffRow(
                    category="网络",
                    change_type=DELETE,
                    object_id=f"[Nets] {key}",
                    detail=f"删除{_net_name_from_key(key)}",
                    old_value=_normalize_pin_list(_cell(old_row, pairs[0][1] if pairs else -1)),
                    new_value="",
                    meta=_csv_row_location_meta(headers_old, old_row, headers_new, None),
                )
            )
        if new_row is not None:
            rows.append(
                DiffRow(
                    category="网络",
                    change_type=ADD,
                    object_id=f"[Nets] {key}",
                    detail=f"新增{_net_name_from_key(key)}",
                    old_value="",
                    new_value=_normalize_pin_list(_cell(new_row, pairs[0][2] if pairs else -1)),
                    meta=_csv_row_location_meta(headers_old, None, headers_new, new_row),
                )
            )
    return rows


def parse_csv_diff_object_id(object_id: str) -> tuple[str | None, str]:
    text = (object_id or "").strip()
    for kind, label in (("parts", "Parts"), ("pins", "Pins"), ("nets", "Nets")):
        prefix = f"[{label}] "
        if text.startswith(prefix):
            return kind, text[len(prefix) :].strip()
    return None, ""


def _component_refdes_from_pin_list_token(token: str) -> str:
    text = (token or "").strip()
    if not text:
        return ""
    match = _PIN_TOKEN.match(text)
    if match:
        return match.group(1)
    if "." in text:
        return text.split(".", 1)[0].strip()
    return text if _REFDES_TOKEN.match(text) else ""


def suppress_pin_add_delete_for_refdes_renumber(rows: list[DiffRow]) -> list[DiffRow]:
    old_refs = {
        str(row.meta.get("oldRefdes") or "").strip().casefold()
        for row in rows
        if row.category == "器件" and row.change_type == RENUMBER_REFDES
    }
    new_refs = {
        str(row.meta.get("newRefdes") or "").strip().casefold()
        for row in rows
        if row.category == "器件" and row.change_type == RENUMBER_REFDES
    }
    if not old_refs and not new_refs:
        return rows
    out: list[DiffRow] = []
    for row in rows:
        if row.category != "管脚" or row.change_type not in (ADD, DELETE):
            out.append(row)
            continue
        kind, key = parse_csv_diff_object_id(row.object_id)
        if kind != "pins":
            out.append(row)
            continue
        refdes = key.split("|", 1)[0].strip().casefold()
        if row.change_type == DELETE and refdes in old_refs:
            continue
        if row.change_type == ADD and refdes in new_refs:
            continue
        out.append(row)
    return out


def suppress_net_connection_pins_for_refdes_renumber(rows: list[DiffRow]) -> list[DiffRow]:
    old_refs = {
        str(row.meta.get("oldRefdes") or "").strip().casefold()
        for row in rows
        if row.category == "器件" and row.change_type == RENUMBER_REFDES
    }
    new_refs = {
        str(row.meta.get("newRefdes") or "").strip().casefold()
        for row in rows
        if row.category == "器件" and row.change_type == RENUMBER_REFDES
    }
    if not old_refs and not new_refs:
        return rows

    def keep_old(token: str) -> bool:
        refdes = _component_refdes_from_pin_list_token(token).casefold()
        return not refdes or refdes not in old_refs

    def keep_new(token: str) -> bool:
        refdes = _component_refdes_from_pin_list_token(token).casefold()
        return not refdes or refdes not in new_refs

    out: list[DiffRow] = []
    for row in rows:
        if row.category != "网络" or row.change_type != NET_CONNECTION:
            out.append(row)
            continue
        old_tokens = [token for token in _nets_tokenize_pin_like_list(str(row.old_value or "")) if keep_old(token)]
        new_tokens = [token for token in _nets_tokenize_pin_like_list(str(row.new_value or "")) if keep_new(token)]
        old_value = ", ".join(old_tokens)
        new_value = ", ".join(new_tokens)
        if old_value == new_value:
            continue
        meta = dict(row.meta)
        if not old_value.strip():
            meta["schematicNameDsn1"] = ""
            meta["pageNameDsn1"] = ""
        if not new_value.strip():
            meta["schematicNameDsn2"] = ""
            meta["pageNameDsn2"] = ""
        out.append(
            DiffRow(
                category=row.category,
                change_type=row.change_type,
                object_id=row.object_id,
                detail=_nets_pins_connection_detail_cn(old_value, new_value),
                prop_name=row.prop_name,
                old_value=old_value,
                new_value=new_value,
                meta=meta,
            )
        )
    return out


def compare_csv_pair(
    path_old: Path,
    path_new: Path,
    sheet_kind: str,
    *,
    parts_slot_map_old: dict[str, str] | None = None,
    parts_slot_map_new: dict[str, str] | None = None,
    pins_nets_column_compare: Any | None = None,
) -> list[DiffRow]:
    kind = sheet_kind.casefold()
    if kind == "parts":
        return compare_parts_csv_pair(
            path_old,
            path_new,
            parts_slot_map_old=parts_slot_map_old,
            parts_slot_map_new=parts_slot_map_new,
        )
    if kind == "pins":
        return compare_pins_csv_pair(
            path_old,
            path_new,
            pins_nets_column_compare=pins_nets_column_compare,
        )
    if kind == "nets":
        return compare_nets_csv_pair(
            path_old,
            path_new,
            pins_nets_column_compare=pins_nets_column_compare,
        )
    return []


def compare_all_dsn_csvs_from_prefs(prefs: dict[str, Any]) -> tuple[list[DiffRow], str | None]:
    keys = (
        ("parts", "lastDsn1PartsCsv", "lastDsn2PartsCsv"),
        ("pins", "lastDsn1PinsCsv", "lastDsn2PinsCsv"),
        ("nets", "lastDsn1NetsCsv", "lastDsn2NetsCsv"),
    )
    missing: list[str] = []
    paths: list[tuple[str, Path, Path]] = []
    for kind, old_key, new_key in keys:
        old_path = Path(str(prefs.get(old_key) or "").strip())
        new_path = Path(str(prefs.get(new_key) or "").strip())
        if not old_path.is_file():
            missing.append(str(old_path))
        if not new_path.is_file():
            missing.append(str(new_path))
        if old_path.is_file() and new_path.is_file():
            paths.append((kind, old_path, new_path))
    if missing:
        return [], "以下文件无效或缺失：\n" + "\n".join(missing)

    rows: list[DiffRow] = []
    slot_map_old, slot_map_new = get_effective_parts_slot_maps(prefs)
    for kind, old_path, new_path in paths:
        if kind == "parts" and maps_have_any_mapping(slot_map_old, slot_map_new):
            rows.extend(
                compare_parts_csv_pair(
                    old_path,
                    new_path,
                    parts_slot_map_old=slot_map_old,
                    parts_slot_map_new=slot_map_new,
                )
            )
        elif kind == "pins":
            rows.extend(
                compare_pins_csv_pair(
                    old_path,
                    new_path,
                    pins_nets_column_compare=prefs.get("pinsCsvColumnCompare"),
                )
            )
        else:
            rows.extend(
                compare_nets_csv_pair(
                    old_path,
                    new_path,
                    pins_nets_column_compare=prefs.get("netsCsvColumnCompare"),
                )
            )
    rows = suppress_pin_add_delete_for_refdes_renumber(rows)
    rows = suppress_net_connection_pins_for_refdes_renumber(rows)
    return rows, None


def build_default_compare_prefs(
    parts1: Path,
    parts2: Path,
    pins1: Path,
    pins2: Path,
    nets1: Path,
    nets2: Path,
) -> dict[str, Any]:
    return {
        "lastDsn1PartsCsv": str(parts1),
        "lastDsn2PartsCsv": str(parts2),
        "lastDsn1PinsCsv": str(pins1),
        "lastDsn2PinsCsv": str(pins2),
        "lastDsn1NetsCsv": str(nets1),
        "lastDsn2NetsCsv": str(nets2),
        "pinsCsvColumnCompare": [
            {"on": True, "d1": "Pin Name", "d2": "Pin Name"},
            {"on": False, "d1": "Net Name", "d2": "Net Name"},
        ],
        "netsCsvColumnCompare": [
            {"on": True, "d1": "Pins (Page)", "d2": "Pins (Page)"},
        ],
    }


def compare_all_dsn_csvs(
    parts1: Path,
    parts2: Path,
    pins1: Path,
    pins2: Path,
    nets1: Path,
    nets2: Path,
) -> list[DiffRow]:
    prefs = build_default_compare_prefs(parts1, parts2, pins1, pins2, nets1, nets2)
    rows, err = compare_all_dsn_csvs_from_prefs(prefs)
    if err:
        raise FileNotFoundError(err)
    return rows
