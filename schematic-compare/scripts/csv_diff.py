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
    ]
    if pin_name.strip():
        bits.append(f"脚名：{pin_name}")
    if net_name.strip():
        bits.append(f"网名：{net_name}")
    return " | ".join(bits)


def _pins_or_nets_attr_snapshot_line_loose(
    headers: list[str], row: list[str], category: str
) -> str:
    loc = _locate_column_indices(headers)
    skip = {idx for idx in (loc["schematic"], loc["page"]) if idx >= 0}
    bits: list[str] = []
    for idx, name in enumerate(headers):
        if idx in skip:
            continue
        value = _cell(row, idx)
        if not value:
            continue
        bits.append(f"{name}：{value}")
    return " | ".join(bits) if bits else "-"


def _value_column_label_for_table(category: str, prop_name: str) -> str:
    text = (prop_name or "").strip()
    if not text:
        return ""
    cf = text.casefold()
    if category == "管脚":
        if ("pin" in cf and "name" in cf) or cf in ("pin name", "pinname", "信号名", "管脚名"):
            return "脚名"
        if "net" in cf or "signal" in cf or ("flat" in cf and "net" in cf) or "网络" in text:
            return "网名"
    if category == "网络":
        if "pin" in cf and "global" in cf:
            return "Pins（Global）"
        if "pin" in cf and "page" in cf:
            return "Pins"
    return text


def _pins_or_nets_pairs_snapshot_line(
    row: list[str],
    category: str,
    pairs_eff: list[tuple[str, int, int]] | None,
    *,
    side: str,
) -> str:
    if not pairs_eff:
        return "-"
    bits: list[str] = []
    for label, idx_old, idx_new in pairs_eff:
        idx = idx_new if side == "new" else idx_old
        if idx < 0:
            idx = idx_old if side == "new" else idx_new
        value = _cell(row, idx)
        if not value:
            continue
        label_base = label.split(" / ")[0].strip() if " / " in label else label
        display = (
            _value_column_label_for_table(category, label)
            or _value_column_label_for_table(category, label_base)
            or label
        )
        bits.append(f"{display}：{value}")
    return " | ".join(bits) if bits else "-"


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
    full_snapshot_for_add_delete: bool = False,
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
            if full_snapshot_for_add_delete:
                old_snapshot = _pin_snapshot_line(old_row, headers_old)
            else:
                old_snapshot = (
                    _pins_or_nets_pairs_snapshot_line(
                        old_row, "管脚", pairs, side="old"
                    )
                    if pairs is not None
                    else _pins_or_nets_attr_snapshot_line_loose(headers_old, old_row, "管脚")
                )
            rows.append(
                DiffRow(
                    category="管脚",
                    change_type=DELETE,
                    object_id=f"[Pins] {key}",
                    detail=f"删除{ref_pin}",
                    old_value=old_snapshot,
                    new_value="",
                    meta=_csv_row_location_meta(headers_old, old_row, headers_new, None),
                )
            )
        if new_row is not None:
            ref_pin = _pin_refdes_dot_pin(new_row, headers_new)
            if full_snapshot_for_add_delete:
                new_snapshot = _pin_snapshot_line(new_row, headers_new)
            else:
                new_snapshot = (
                    _pins_or_nets_pairs_snapshot_line(
                        new_row, "管脚", pairs, side="new"
                    )
                    if pairs is not None
                    else _pins_or_nets_attr_snapshot_line_loose(headers_new, new_row, "管脚")
                )
            rows.append(
                DiffRow(
                    category="管脚",
                    change_type=ADD,
                    object_id=f"[Pins] {key}",
                    detail=f"新增{ref_pin}",
                    old_value="",
                    new_value=new_snapshot,
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


def _nets_ordered_pin_tokens_from_cell(cell: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in _PIN_TOKEN.finditer(str(cell or "")):
        token = f"{match.group(1).strip()}.{match.group(2).strip()}"
        key = token.casefold()
        if key not in seen:
            seen.add(key)
            out.append(token)
    return out


def _net_row_key(row: list[str], headers: list[str]) -> str:
    loc = _locate_column_indices(headers)
    net_name = _cell(row, loc["net"])
    sch = _cell(row, loc["schematic"])
    page = _cell(row, loc["page"])
    return "|".join((net_name, sch, page))


def _net_name_from_key(key: str) -> str:
    return key.split("|", 1)[0].strip()


def _nets_pins_connection_detail_cn(old_value: str, new_value: str) -> str:
    old_tokens = _nets_ordered_pin_tokens_from_cell(old_value)
    new_tokens = _nets_ordered_pin_tokens_from_cell(new_value)
    old_set = {token.casefold() for token in old_tokens}
    new_set = {token.casefold() for token in new_tokens}
    if not old_set and not new_set:
        return "Pins"
    removed = [token for token in old_tokens if token.casefold() in (old_set - new_set)]
    added = [token for token in new_tokens if token.casefold() in (new_set - old_set)]
    bits = ["Pins"]
    if removed:
        bits.append(f"减少{','.join(removed)}")
    if added:
        bits.append(f"增加{','.join(added)}")
    return " ".join(bits) if len(bits) > 1 else "Pins"


def _nets_cell_at_row(row: list[str], idx: int) -> str:
    return _cell(row, idx)


def _is_nets_pins_aggregate_column(col_name: str) -> bool:
    cf = (col_name or "").casefold()
    return "pin" in cf and ("page" in cf or "global" in cf)


def _is_nets_pins_page_only_column(col_name: str) -> bool:
    cf = (col_name or "").casefold()
    return _is_nets_pins_aggregate_column(col_name) and "page" in cf and "global" not in cf


def _nets_pair_pins_display_strings(
    row_old: list[str],
    row_new: list[str],
    pairs_eff: list[tuple[str, int, int]] | None,
    headers: list[str],
) -> tuple[str, str, str]:
    if pairs_eff is not None:
        page_pairs = [
            (label, idx_old, idx_new)
            for label, idx_old, idx_new in pairs_eff
            if _is_nets_pins_page_only_column(label)
        ]
        if len(page_pairs) >= 2:
            old_joined = _nets_join_cells_to_comma_pin_list(
                [_nets_cell_at_row(row_old, idx_old) for _label, idx_old, _idx_new in page_pairs]
            )
            new_joined = _nets_join_cells_to_comma_pin_list(
                [_nets_cell_at_row(row_new, idx_new) for _label, _idx_old, idx_new in page_pairs]
            )
            return old_joined, new_joined, "Pins（Page）"
        aggregate_pairs = [
            (label, idx_old, idx_new)
            for label, idx_old, idx_new in pairs_eff
            if _is_nets_pins_aggregate_column(label)
        ]
        if len(aggregate_pairs) == 1:
            label, idx_old, idx_new = aggregate_pairs[0]
            return _nets_cell_at_row(row_old, idx_old), _nets_cell_at_row(row_new, idx_new), label
        for label, idx_old, idx_new in pairs_eff:
            cf = (label or "").casefold()
            if "internet" in cf:
                continue
            if "pin" in cf:
                return _nets_cell_at_row(row_old, idx_old), _nets_cell_at_row(row_new, idx_new), label
        return "-", "-", "Pins (Page)"

    aggregate_idxs = [idx for idx, header in enumerate(headers) if _is_nets_pins_aggregate_column(header)]
    if len(aggregate_idxs) >= 2:
        return (
            _nets_join_cells_to_comma_pin_list([_nets_cell_at_row(row_old, idx) for idx in aggregate_idxs]),
            _nets_join_cells_to_comma_pin_list([_nets_cell_at_row(row_new, idx) for idx in aggregate_idxs]),
            "Pins（Page）",
        )
    if len(aggregate_idxs) == 1:
        idx = aggregate_idxs[0]
        return _nets_cell_at_row(row_old, idx), _nets_cell_at_row(row_new, idx), headers[idx]
    return "-", "-", "Pins (Page)"


def _nets_join_cells_to_comma_pin_list(cells: list[str]) -> str:
    ordered: list[str] = []
    seen: set[str] = set()
    for raw in cells:
        for token in _nets_tokenize_pin_like_list(str(raw or "")):
            if not token or token in ("-", "—", "–"):
                continue
            key = token.casefold()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(token)
    return ", ".join(ordered) if ordered else "-"


def _nets_display_pin_list(cell: str) -> str:
    joined = _nets_join_cells_to_comma_pin_list([cell])
    if joined == "-" and not str(cell or "").strip():
        return ""
    return joined


def _nets_single_row_pins_snapshot(
    row: list[str],
    pairs_eff: list[tuple[str, int, int]] | None,
    headers: list[str],
) -> str:
    old_text, new_text, _label = _nets_pair_pins_display_strings(row, row, pairs_eff, headers)
    text = (old_text or "").strip() or (new_text or "").strip()
    return _nets_display_pin_list(text) if text else "-"


def compare_nets_csv_pair(
    path_old: Path,
    path_new: Path,
    *,
    pins_nets_column_compare: Any | None = None,
    sort_pin_snapshots: bool = False,
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
                old_value = (
                    _normalize_pin_list(_cell(old_row, old_idx))
                    if sort_pin_snapshots
                    else _nets_display_pin_list(_cell(old_row, old_idx))
                )
                new_value = (
                    _normalize_pin_list(_cell(new_row, new_idx))
                    if sort_pin_snapshots
                    else _nets_display_pin_list(_cell(new_row, new_idx))
                )
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

        # --- Rename detection: pair deleted+added nets with identical pin sets ---
        if old_row is not None and new_row is None:
            # Collect only-old entries for later rename pairing
            pass
        if new_row is not None and old_row is None:
            # Collect only-new entries for later rename pairing
            pass

    # Separate only-old and only-new keys for rename pairing
    only_old_keys = [k for k in sorted(set(old_map) | set(new_map), key=str.casefold)
                     if k in old_map and k not in new_map]
    only_new_keys = [k for k in sorted(set(old_map) | set(new_map), key=str.casefold)
                     if k in new_map and k not in old_map]

    # Build pin-token signature for rename pairing
    def _pin_sig_from_row(row: list[str], is_new: bool) -> frozenset[str]:
        tokens = set()
        for _label, idx_o, idx_n in pairs or []:
            idx = idx_n if is_new else idx_o
            if idx >= 0:
                for tok in _nets_tokenize_pin_like_list(_cell(row, idx)):
                    if tok and tok not in ("-", "—", "–"):
                        tokens.add(tok.casefold())
        return frozenset(tokens)

    old_by_sig: dict[frozenset[str], list[str]] = defaultdict(list)
    new_by_sig: dict[frozenset[str], list[str]] = defaultdict(list)
    for k in only_old_keys:
        sig = _pin_sig_from_row(old_map[k], False)
        if sig:
            old_by_sig[sig].append(k)
    for k in only_new_keys:
        sig = _pin_sig_from_row(new_map[k], True)
        if sig:
            new_by_sig[sig].append(k)

    paired_old: set[str] = set()
    paired_new: set[str] = set()

    from .diff_types import NET_RENAME

    for sig, old_list in old_by_sig.items():
        new_list = new_by_sig.get(sig, [])
        if not new_list:
            continue
        old_sorted = sorted(old_list, key=str.casefold)
        new_sorted = sorted(new_list, key=str.casefold)
        for ok, nk in zip(old_sorted, new_sorted):
            old_name = _net_name_from_key(ok)
            new_name = _net_name_from_key(nk)
            if old_name.casefold() == new_name.casefold():
                continue
            paired_old.add(ok)
            paired_new.add(nk)
            old_row_r = old_map[ok]
            new_row_r = new_map[nk]
            pins_snapshot = _nets_single_row_pins_snapshot(old_row_r, pairs, headers_old)
            if sort_pin_snapshots:
                pins_snapshot = _normalize_pin_list(pins_snapshot)
            meta = _csv_row_location_meta(headers_old, old_row_r, headers_new, new_row_r)
            meta["renameFlatNetOld"] = old_name
            meta["renameFlatNetNew"] = new_name
            meta["csvNetRenamePinsPageValues"] = "1"
            meta["renamePinsPagePropName"] = "Pins (Page)"
            rows.append(
                DiffRow(
                    category="网络",
                    change_type=NET_RENAME,
                    object_id=f"[Nets] {new_name}",
                    detail=f"网络{old_name}→{new_name}，Pins不变",
                    prop_name="Pins (Page)",
                    old_value=pins_snapshot,
                    new_value=pins_snapshot,
                    meta=meta,
                )
            )

    # Emit remaining delete/add for unpaired nets
    for key in only_old_keys:
        if key in paired_old:
            continue
        old_row = old_map[key]
        old_snapshot = _nets_single_row_pins_snapshot(old_row, pairs, headers_old)
        if sort_pin_snapshots:
            old_snapshot = _normalize_pin_list(old_snapshot)
        rows.append(
            DiffRow(
                category="网络",
                change_type=DELETE,
                object_id=f"[Nets] {key}",
                detail=f"删除{_net_name_from_key(key)}",
                old_value=old_snapshot,
                new_value="",
                meta=_csv_row_location_meta(headers_old, old_row, headers_new, None),
            )
        )

    for key in only_new_keys:
        if key in paired_new:
            continue
        new_row = new_map[key]
        new_snapshot = _nets_single_row_pins_snapshot(new_row, pairs, headers_new)
        if sort_pin_snapshots:
            new_snapshot = _normalize_pin_list(new_snapshot)
        rows.append(
            DiffRow(
                category="网络",
                change_type=ADD,
                object_id=f"[Nets] {key}",
                detail=f"新增{_net_name_from_key(key)}",
                old_value="",
                new_value=new_snapshot,
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


def coalesce_net_add_connection_to_rename(rows: list[DiffRow]) -> list[DiffRow]:
    """
    Post-processor: merge 'add net' + 'connection change' into 'rename' when
    the added net's pin set exactly matches the removed pins from a connection change.
    This matches the source tool's coalesce_net_add_connection_to_rename logic.
    """
    from .diff_types import NET_RENAME, NET_CONNECTION

    add_entries: list[tuple[int, DiffRow, str, set[str]]] = []
    for i, r in enumerate(rows):
        if r.category != "网络" or r.change_type != ADD:
            continue
        kind, rk = parse_csv_diff_object_id(r.object_id)
        if kind != "nets" or not rk:
            continue
        new_val = str(r.new_value or "").strip()
        if not new_val or new_val == "-":
            continue
        pins = {tok.casefold() for tok in _nets_tokenize_pin_like_list(new_val)
                if tok.strip() and tok.strip() not in ("-", "—", "–")}
        if not pins:
            continue
        new_flat = _net_name_from_key(rk).strip() or rk.strip()
        add_entries.append((i, r, new_flat, pins))

    conn_by_oid: dict[str, list[tuple[int, DiffRow]]] = defaultdict(list)
    for i, r in enumerate(rows):
        if r.category != "网络" or r.change_type != NET_CONNECTION:
            continue
        kind, _rk = parse_csv_diff_object_id(r.object_id)
        if kind != "nets":
            continue
        conn_by_oid[r.object_id].append((i, r))

    if not add_entries or not conn_by_oid:
        return rows

    used_add: set[int] = set()
    used_oid: set[str] = set()
    synthesized: list[DiffRow] = []

    for ai, r_add, new_name, pins_add in add_entries:
        if ai in used_add:
            continue
        best_oid: str | None = None
        best_meta: dict[str, Any] = {}
        best_old_name = ""
        for oid, lst in sorted(conn_by_oid.items(), key=lambda x: x[0]):
            if oid in used_oid:
                continue
            kind, old_rk = parse_csv_diff_object_id(oid)
            if kind != "nets" or not old_rk:
                continue
            old_name = _net_name_from_key(old_rk).strip() or old_rk.strip()
            removed: set[str] = set()
            meta_conn: dict[str, Any] = {}
            for _j, rc in lst:
                meta_conn = dict(rc.meta) if rc.meta else meta_conn
                for tok in _nets_tokenize_pin_like_list(str(rc.old_value or "")):
                    if tok.strip() and tok.strip() not in ("-", "—", "–"):
                        removed.add(tok.casefold())
            if removed != pins_add or not pins_add:
                continue
            best_oid = oid
            best_meta = meta_conn
            best_old_name = old_name
            break
        if best_oid is None:
            continue
        used_add.add(ai)
        used_oid.add(best_oid)
        merged_meta = dict(best_meta)
        m_add = r_add.meta or {}
        for k2 in ("schematicNameDsn2", "pageNameDsn2"):
            v2 = str(m_add.get(k2) or "").strip()
            if v2:
                merged_meta[k2] = v2
        pins_disp = ", ".join(sorted(pins_add, key=str.lower))
        merged_meta["renameFlatNetOld"] = best_old_name
        merged_meta["renameFlatNetNew"] = new_name
        merged_meta["csvNetRenamePinsPageValues"] = "1"
        merged_meta["renamePinsPagePropName"] = "Pins (Page)"
        synthesized.append(
            DiffRow(
                category="网络",
                change_type=NET_RENAME,
                object_id=f"[Nets] {new_name}",
                detail=f"网络{best_old_name}→{new_name}，Pins不变",
                prop_name="Pins (Page)",
                old_value=pins_disp,
                new_value=pins_disp,
                meta=merged_meta,
            )
        )

    if not used_add and not used_oid:
        return rows

    out: list[DiffRow] = []
    used_conn_indices: set[int] = set()
    for oid in used_oid:
        for idx, _r in conn_by_oid[oid]:
            used_conn_indices.add(idx)
    for i, r in enumerate(rows):
        if i in used_add or i in used_conn_indices:
            continue
        out.append(r)
    out.extend(synthesized)
    return out


def compare_csv_pair(
    path_old: Path,
    path_new: Path,
    sheet_kind: str,
    *,
    parts_slot_map_old: dict[str, str] | None = None,
    parts_slot_map_new: dict[str, str] | None = None,
    pins_nets_column_compare: Any | None = None,
    full_pin_snapshot_for_add_delete: bool = False,
    sort_network_pin_snapshots: bool = False,
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
            full_snapshot_for_add_delete=full_pin_snapshot_for_add_delete,
        )
    if kind == "nets":
        return compare_nets_csv_pair(
            path_old,
            path_new,
            pins_nets_column_compare=pins_nets_column_compare,
            sort_pin_snapshots=sort_network_pin_snapshots,
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
                    full_snapshot_for_add_delete=bool(
                        prefs.get("pinsAddDeleteFullSnapshot")
                    ),
                )
            )
        else:
            rows.extend(
                compare_nets_csv_pair(
                    old_path,
                    new_path,
                    pins_nets_column_compare=prefs.get("netsCsvColumnCompare"),
                    sort_pin_snapshots=bool(prefs.get("sortNetworkPinSnapshots")),
                )
            )
    rows = suppress_pin_add_delete_for_refdes_renumber(rows)
    rows = suppress_net_connection_pins_for_refdes_renumber(rows)
    rows = coalesce_net_add_connection_to_rename(rows)
    return rows, None


def build_default_compare_prefs(
    parts1: Path,
    parts2: Path,
    pins1: Path,
    pins2: Path,
    nets1: Path,
    nets2: Path,
    *,
    mode: str = "csv",
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
            {"on": True, "d1": "Net Name", "d2": "Net Name"},
        ],
        "netsCsvColumnCompare": [
            {"on": True, "d1": "Pins (Page)", "d2": "Pins (Page)"},
        ],
        "pinsAddDeleteFullSnapshot": True,
        "sortNetworkPinSnapshots": mode in ("edif", "dsn"),
    }


def compare_all_dsn_csvs(
    parts1: Path,
    parts2: Path,
    pins1: Path,
    pins2: Path,
    nets1: Path,
    nets2: Path,
) -> list[DiffRow]:
    prefs = build_default_compare_prefs(
        parts1, parts2, pins1, pins2, nets1, nets2, mode="edif"
    )
    rows, err = compare_all_dsn_csvs_from_prefs(prefs)
    if err:
        raise FileNotFoundError(err)
    return rows
