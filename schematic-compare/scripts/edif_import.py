"""
从 EDIF 网表（常见 Level 2 子集）提取器件与网络连接，生成与 Capture 导出列名兼容的
Parts_Properties / Pins_Info / Nets_Info CSV，供 compare_csv_pair 使用。

Capture / OrCAD 导出的 EDIF：真实器件为 ``(instance INS数字 ...)``，用户位号在
``(designator (stringDisplay "R1" (display PARTREFERENCE ...)))``，属性值在
``(property (rename VALUE ...) (string (stringDisplay "100R" ...)))``；网络里为
``(portRef &1 (instanceRef INS47236280))``，需将 INS id 映射到位号。

OrCAD 将各页放在 ``(page (rename &… "页显示名") …)`` 内，图框属性中含
``(property (rename SCHEMATIC_NAME "Schematic Name") (string "UTAH_MB"))``。
本模块在存在含 INS 的 page 块时，为器件/管脚/网络填入对应的 Schematic 与 Page。

非 Cadence 网表仍支持旧式 ``(instance ... (rename REF ...) ... (cellRef ...))``。
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

_DEFAULT_SCH = "EDIF"
_DEFAULT_PAGE = "1"

_RE_INSTANCE_OPEN = re.compile(r"\(\s*instance\b", re.I)
_RE_NET_OPEN = re.compile(r"\(\s*net\b", re.I)
_RE_PAGE_OPEN = re.compile(r"\(\s*page\s+", re.I)
_RE_INS_HEAD = re.compile(r"\(\s*instance\s+(INS\d+)\b", re.I)
_RE_HAS_PLACEMENT_INS = re.compile(r"\(\s*instance\s+INS\d+\b", re.I)


def _strip_edif_comments(text: str) -> str:
    out: list[str] = []
    for line in text.splitlines():
        if ";" in line:
            line = line.split(";", 1)[0]
        out.append(line)
    return "\n".join(out)


def _extract_balanced(text: str, start: int) -> tuple[str, int] | None:
    if start >= len(text) or text[start] != "(":
        return None
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[start : i + 1], i + 1
    return None


def _find_balanced_blocks(content: str, open_rx: re.Pattern[str]) -> list[str]:
    out: list[str] = []
    for m in open_rx.finditer(content):
        got = _extract_balanced(content, m.start())
        if got:
            out.append(got[0])
    return out


def _parse_page_name_property(page_block: str) -> str:
    m = re.search(
        r"\(\s*property\s+\(\s*rename\s+PAGE_NAME\b[^)]*\)\s*\(\s*string\s+\"([^\"]*)\""  ,
        page_block, re.I,
    )
    return m.group(1).strip() if m else ""


def _parse_page_display_name(page_block: str) -> str:
    pn = _parse_page_name_property(page_block)
    if pn:
        return pn
    m = re.search(
        r"\(\s*page\s+\(\s*rename\s+[^\s()]+\s+\"([^\"]*)\"",
        page_block, re.I | re.S,
    )
    if m:
        return m.group(1).strip()
    m2 = re.match(r"\(\s*page\s+(&?[^\s()]+)", page_block, re.I)
    if m2:
        tok = m2.group(1).strip()
        if tok.startswith("&"):
            tok = tok[1:]
        return tok
    return ""


def _parse_schematic_name_from_page(page_block: str) -> str:
    matches = list(
        re.finditer(
            r"\(\s*property\s+\(\s*rename\s+SCHEMATIC_NAME\b[^)]*\)\s*\(\s*string\s+\"([^\"]*)\"",
            page_block, re.I,
        )
    )
    return matches[-1].group(1).strip() if matches else ""


def _extract_partreference_designator(block: str) -> str:
    md = re.search(r"\(\s*designator\b", block, re.I)
    if not md:
        return ""
    got = _extract_balanced(block, md.start())
    if not got:
        return ""
    sub = got[0]
    mref = re.search(
        r"\(\s*stringDisplay\s+\"([^\"]*)\"\s*\(\s*display\s+PARTREFERENCE\b",
        sub, re.I,
    )
    if mref:
        return mref.group(1).strip()
    m2 = re.search(r"\(\s*stringDisplay\s+\"([^\"]*)\"", sub)
    return m2.group(1).strip() if m2 else ""


def _extract_value_property_cadence(block: str) -> str:
    m = re.search(r"\(\s*rename\s+VALUE\b", block, re.I)
    if not m:
        return ""
    window = block[m.start() : m.start() + 12000]
    msd = re.search(r"\(\s*stringDisplay\s+\"([^\"]*)\"", window)
    if msd:
        return msd.group(1)
    ms = re.search(r"\(\s*string\s+\"\s*([^\"]*)\"\s*\)", window)
    return ms.group(1).strip() if ms else ""


def _extract_pinnumber_from_port_instance(sub: str) -> str:
    md = re.search(r"\(\s*designator\b", sub, re.I)
    if not md:
        return ""
    got = _extract_balanced(sub, md.start())
    if not got:
        return ""
    des = got[0]
    mnum = re.search(
        r"\(\s*stringDisplay\s+\"([^\"]*)\"\s*\(\s*display\s+PINNUMBER\b",
        des, re.I,
    )
    if mnum:
        return mnum.group(1).strip()
    m2 = re.search(r"\(\s*stringDisplay\s+\"([^\"]*)\"", des)
    return m2.group(1).strip() if m2 else ""


def _parse_port_instances_cadence(block: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"\(\s*portInstance\b", block, re.I):
        got = _extract_balanced(block, m.start())
        if not got:
            continue
        sub = got[0]
        nm = re.search(r"\(\s*name\s+([^\s()]+)", sub, re.I)
        if not nm:
            continue
        sym_raw = nm.group(1).strip()
        sym = _normalize_pin_token(sym_raw)
        ball = _extract_pinnumber_from_port_instance(sub)
        if not ball:
            ball = sym
        out.append((sym, ball))
    return out


def _parse_cadence_ins_instance(block: str) -> tuple[str, str, str] | None:
    mh = _RE_INS_HEAD.match(block)
    if not mh:
        return None
    internal_id = mh.group(1)
    refdes = _extract_partreference_designator(block)
    if not refdes:
        return None
    value = _extract_value_property_cadence(block)
    return internal_id, refdes, value


def _parse_instance_block(block: str) -> tuple[str, str] | None:
    mr = re.search(r"\(\s*rename\s+([^\s()|]+)", block)
    if not mr:
        return None
    ref = mr.group(1).strip()
    if not ref:
        return None
    mc = re.search(r"\(\s*cellRef\s+([^\s()|]+)", block)
    cell = mc.group(1).strip() if mc else ""
    if not cell:
        mi = re.match(r"\(\s*instance\s+(\S+)", block)
        if mi:
            cell = mi.group(1).strip()
    return ref, cell


def _parse_net_name(block: str) -> str:
    m = re.match(r"\(\s*net\s+(\|[^\|]*\||[^\s()]+)", block)
    if m:
        raw = m.group(1).strip()
        if raw.startswith("|") and raw.endswith("|") and len(raw) >= 2:
            return raw[1:-1]
        return raw
    mr = re.search(r"\(\s*rename\s+(\|[^\|]*\||[^\s()]+)", block)
    if mr:
        raw = mr.group(1).strip()
        if raw.startswith("|") and raw.endswith("|") and len(raw) >= 2:
            return raw[1:-1]
        return raw
    return ""


def _normalize_pin_token(tok: str) -> str:
    t = tok.strip()
    if t.startswith("&"):
        t = t[1:]
    return t


def _resolve_instance_ref(tok: str, idmap: dict[str, str]) -> str:
    return idmap.get(tok, tok)


def _parse_net_block(
    block: str, idmap: dict[str, str]
) -> tuple[str, list[tuple[str, str]]]:
    name = _parse_net_name(block)
    pairs: list[tuple[str, str]] = []
    for m in re.finditer(
        r"portRef\s+(\S+)\s+\(\s*instanceRef\s+([^)\s]+)\s*\)",
        block, flags=re.I,
    ):
        pin_raw, ref_tok = m.group(1).strip(), m.group(2).strip()
        if not ref_tok:
            continue
        pin = _normalize_pin_token(pin_raw)
        ref = _resolve_instance_ref(ref_tok, idmap)
        pairs.append((ref, pin))
    return name, pairs


NetKey = tuple[str, str, str]  # (flat_net, schematic, page)


def parse_edif_file(path: Path) -> dict[str, Any]:
    """
    解析单个 EDIF 文件。
    返回 dict:
      instances: list[tuple[refdes, value, schematic, page]]
      nets: dict[NetKey, list[tuple[refdes, pinSym]]]
      pin_lookup: dict[tuple[str, str], tuple[str, str]]
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    content = _strip_edif_comments(raw)

    id_to_refdes: dict[str, str] = {}
    instances: list[tuple[str, str, str, str]] = []
    pin_lookup: dict[tuple[str, str], tuple[str, str]] = {}
    nets_out: dict[NetKey, list[tuple[str, str]]] = defaultdict(list)

    all_pages = _find_balanced_blocks(content, _RE_PAGE_OPEN)
    placement_pages = [pb for pb in all_pages if _RE_HAS_PLACEMENT_INS.search(pb)]

    if placement_pages:
        for pb in placement_pages:
            sch = _parse_schematic_name_from_page(pb) or _DEFAULT_SCH
            pg = _parse_page_display_name(pb) or _DEFAULT_PAGE
            for ins_blk in _find_balanced_blocks(pb, _RE_INSTANCE_OPEN):
                p = _parse_cadence_ins_instance(ins_blk)
                if not p:
                    continue
                ins_id, refdes, value = p
                id_to_refdes[ins_id] = refdes
                instances.append((refdes, value, sch, pg))
                for sym, ball in _parse_port_instances_cadence(ins_blk):
                    pin_lookup[(refdes.casefold(), sym.casefold())] = (ball, sym)

            for net_blk in _find_balanced_blocks(pb, _RE_NET_OPEN):
                nname, pairs = _parse_net_block(net_blk, id_to_refdes)
                if not nname or not pairs:
                    continue
                nk = nname.strip()
                key: NetKey = (nk, sch, pg)
                seen: set[tuple[str, str]] = set()
                for ref, pin in pairs:
                    sig = (ref.casefold(), pin.casefold())
                    if sig in seen:
                        continue
                    seen.add(sig)
                    nets_out[key].append((ref, pin))
    else:
        for blk in _find_balanced_blocks(content, _RE_INSTANCE_OPEN):
            p = _parse_cadence_ins_instance(blk)
            if p:
                ins_id, refdes, value = p
                id_to_refdes[ins_id] = refdes
                instances.append((refdes, value, _DEFAULT_SCH, _DEFAULT_PAGE))
                for sym, ball in _parse_port_instances_cadence(blk):
                    pin_lookup[(refdes.casefold(), sym.casefold())] = (ball, sym)
                continue

        if not instances:
            seen_cf: set[str] = set()
            for blk in _find_balanced_blocks(content, _RE_INSTANCE_OPEN):
                parsed = _parse_instance_block(blk)
                if parsed:
                    ref, cell = parsed
                    cf = ref.casefold()
                    if cf not in seen_cf:
                        seen_cf.add(cf)
                        instances.append((ref, cell, _DEFAULT_SCH, _DEFAULT_PAGE))

        for blk in _find_balanced_blocks(content, _RE_NET_OPEN):
            nname, pairs = _parse_net_block(blk, id_to_refdes)
            if not nname or not pairs:
                continue
            nk = nname.strip()
            key = (nk, _DEFAULT_SCH, _DEFAULT_PAGE)
            seen2: set[tuple[str, str]] = set()
            for ref, pin in pairs:
                sig = (ref.casefold(), pin.casefold())
                if sig in seen2:
                    continue
                seen2.add(sig)
                nets_out[key].append((ref, pin))

    return {
        "instances": instances,
        "nets": dict(nets_out),
        "pin_lookup": pin_lookup,
    }


def _pin_net_display(
    ref: str, pin_sym: str, pin_lookup: dict[tuple[str, str], tuple[str, str]]
) -> str:
    lk = pin_lookup.get((ref.casefold(), pin_sym.casefold()))
    pin_disp = lk[0] if lk else pin_sym
    return f"{ref}.{pin_disp}"


def write_capture_style_csvs(
    data: dict[str, Any],
    out_dir: Path,
    *,
    schematic: str = _DEFAULT_SCH,
    page: str = _DEFAULT_PAGE,
) -> tuple[Path, Path, Path]:
    """将 parse_edif_file 结果写入三个 CSV，返回 (parts, pins, nets) 路径。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_inst = data.get("instances") or []
    nets: dict[Any, list[tuple[str, str]]] = data.get("nets") or {}
    pin_lookup: dict[tuple[str, str], tuple[str, str]] = data.get("pin_lookup") or {}

    instances: list[tuple[str, str, str, str]] = []
    for t in raw_inst:
        if len(t) >= 4:
            instances.append((t[0], t[1], str(t[2]), str(t[3])))
        else:
            instances.append((t[0], t[1], schematic, page))

    parts_path = out_dir / "Parts_Properties.csv"
    pins_path = out_dir / "Pins_Info.csv"
    nets_path = out_dir / "Nets_Info.csv"

    parts_header = ["Reference Designator", "Schematic", "Page", "Value"]
    pins_header = ["Reference", "Pin Number", "Pin Name", "Net Name", "Schematic", "Page"]
    nets_header = ["FlatNet", "Schematic", "Page", "Pins (Page)", "Pins (Global)"]

    pin_rows: list[list[str]] = []
    for net_key, plist in nets.items():
        if isinstance(net_key, tuple) and len(net_key) == 3:
            net_name, sch_n, page_n = net_key[0], net_key[1], net_key[2]
        else:
            net_name, sch_n, page_n = str(net_key), schematic, page
        for ref, pin in plist:
            lk = pin_lookup.get((ref.casefold(), pin.casefold()))
            if lk:
                pin_num, pin_name = lk[0], lk[1]
            else:
                pin_num, pin_name = pin, pin
            pin_rows.append([ref, pin_num, pin_name, net_name, sch_n, page_n])

    for ref, _val, sch_i, page_i in instances:
        if not any(r[0] == ref for r in pin_rows):
            pin_rows.append([ref, "", "", "", sch_i, page_i])

    net_rows: list[list[str]] = []
    for net_key, plist in sorted(
        nets.items(),
        key=lambda it: (
            str(it[0][0]).casefold() if isinstance(it[0], tuple) else str(it[0]).casefold(),
            str(it[0][1]).casefold() if isinstance(it[0], tuple) and len(it[0]) > 1 else "",
            str(it[0][2]).casefold() if isinstance(it[0], tuple) and len(it[0]) > 2 else "",
        ),
    ):
        if isinstance(net_key, tuple) and len(net_key) == 3:
            net_name, sch_n, page_n = net_key[0], net_key[1], net_key[2]
        else:
            net_name, sch_n, page_n = str(net_key), schematic, page
        pins_txt = ",".join(_pin_net_display(ref, p, pin_lookup) for ref, p in plist)
        if not pins_txt:
            continue
        net_rows.append([net_name, sch_n, page_n, pins_txt, pins_txt])

    with parts_path.open("w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp, quoting=csv.QUOTE_MINIMAL)
        w.writerow(parts_header)
        for ref, val, sch_i, page_i in sorted(
            instances, key=lambda t: (t[0].casefold(), t[2].casefold(), t[3])
        ):
            w.writerow([ref, sch_i, page_i, val])

    with pins_path.open("w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp, quoting=csv.QUOTE_MINIMAL)
        w.writerow(pins_header)
        for row in sorted(
            pin_rows, key=lambda r: (r[0].casefold(), r[4].casefold(), r[5], r[1])
        ):
            w.writerow(row)

    with nets_path.open("w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp, quoting=csv.QUOTE_MINIMAL)
        w.writerow(nets_header)
        for row in net_rows:
            w.writerow(row)

    if not instances and not nets:
        raise ValueError(
            "EDIF 中未解析到任何 instance 或 net；请确认文件为网表视图且含 "
            "OrCAD 的 (page …)(instance INS…)、(designator … PARTREFERENCE) 或通用 "
            "(instance…(rename…))、(net…(portRef…(instanceRef…))) 等结构。"
        )
    return parts_path, pins_path, nets_path


def import_edif_pair_to_dirs(
    edif1: Path, edif2: Path, out_dir1: Path, out_dir2: Path,
) -> tuple[dict[str, Path], dict[str, Path]]:
    """解析两个 EDIF 文件并分别写入 CSV 目录。"""
    d1 = parse_edif_file(edif1)
    d2 = parse_edif_file(edif2)
    p1, i1, n1 = write_capture_style_csvs(d1, out_dir1)
    p2, i2, n2 = write_capture_style_csvs(d2, out_dir2)
    return (
        {"parts": p1, "pins": i1, "nets": n1},
        {"parts": p2, "pins": i2, "nets": n2},
    )
