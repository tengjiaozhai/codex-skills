"""Full EDIF semantic extraction built on the S-expression parser."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .edif_sexpr import EdifAtom, EdifNode, parse_edif_sexpr


SHEET_ORDER = [
    "Summary",
    "Libraries",
    "Cells",
    "Ports",
    "Pages",
    "Instances",
    "InstanceProperties",
    "PinInstances",
    "Nets",
    "NetConnections",
    "Displays",
    "Geometry",
    "Arrays",
    "HierarchyRefs",
    "RawNodes",
]


@dataclass(slots=True)
class FullEdifTables:
    source_path: str
    edif_name: str
    sheets: dict[str, list[dict[str, Any]]]

    @property
    def summary(self) -> dict[str, Any]:
        rows = self.sheets.get("Summary") or []
        return rows[0] if rows else {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "edif_name": self.edif_name,
            "sheets": self.sheets,
        }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _node_to_obj(item: EdifAtom | EdifNode) -> Any:
    if isinstance(item, EdifAtom):
        return item.value
    return [_node_to_obj(child) for child in item.items]


def _direct_child(node: EdifNode, head: str) -> EdifNode | None:
    folded = head.casefold()
    for child in node.child_nodes():
        if child.head.casefold() == folded:
            return child
    return None


def _direct_children(node: EdifNode, head: str) -> list[EdifNode]:
    folded = head.casefold()
    return [child for child in node.child_nodes() if child.head.casefold() == folded]


def _node_name(item: EdifAtom | EdifNode | None) -> tuple[str, str]:
    if item is None:
        return "", ""
    if isinstance(item, EdifAtom):
        return item.value, ""
    head = item.head.casefold()
    if head in {"rename", "name"}:
        key, _ = _node_name(item.items[1] if len(item.items) > 1 else None)
        display = ""
        for child in item.items[2:]:
            if isinstance(child, EdifAtom):
                display = child.value
                break
        return key, display
    return item.head, ""


def _object_name(node: EdifNode) -> tuple[str, str]:
    return _node_name(node.items[1] if len(node.items) > 1 else None)


def _first_atom_after_head(node: EdifNode | None) -> str:
    if node is None:
        return ""
    for item in node.items[1:]:
        if isinstance(item, EdifAtom):
            return item.value
    return ""


def _string_display_text(node: EdifNode) -> str:
    if node.head.casefold() == "stringdisplay":
        return _first_atom_after_head(node)
    found = node.find_first("stringDisplay")
    return _first_atom_after_head(found) if found is not None else ""


def _value_text(value_node: EdifNode | None) -> str:
    if value_node is None:
        return ""
    head = value_node.head.casefold()
    if head == "string":
        direct = _first_atom_after_head(value_node)
        return direct if direct else _string_display_text(value_node)
    if head == "stringdisplay":
        return _first_atom_after_head(value_node)
    if head in {"integer", "number", "e"}:
        return " ".join(item.value for item in value_node.items[1:] if isinstance(item, EdifAtom))
    if head == "boolean":
        atoms = [
            item.value
            for child in value_node.walk()
            for item in child.items
            if isinstance(item, EdifAtom)
        ]
        return atoms[-1] if atoms else ""
    direct = _first_atom_after_head(value_node)
    return direct if direct else _json(_node_to_obj(value_node))


def _property_parts(prop: EdifNode) -> dict[str, Any]:
    key, display_name = _node_name(prop.items[1] if len(prop.items) > 1 else None)
    value_node = None
    for item in prop.items[2:]:
        if isinstance(item, EdifNode) and item.head.casefold() not in {"owner"}:
            value_node = item
            break
    origin_x, origin_y = _origin_xy(_direct_child(prop, "display") or prop.find_first("display"))
    return {
        "key": key,
        "display_name": display_name,
        "value_raw": _json(_node_to_obj(value_node)) if value_node is not None else "",
        "value_text": _value_text(value_node),
        "display_origin_x": origin_x,
        "display_origin_y": origin_y,
        "visible": _visible(_direct_child(prop, "display") or prop.find_first("display")),
        "source_path": prop.path,
    }


def _properties_json(node: EdifNode) -> str:
    props = {}
    for prop in _direct_children(node, "property"):
        parts = _property_parts(prop)
        if parts["key"]:
            props[parts["key"]] = parts["value_text"]
    return _json(props)


def _property_text(node: EdifNode, key: str) -> str:
    folded = key.casefold()
    for prop in _direct_children(node, "property"):
        parts = _property_parts(prop)
        if parts["key"].casefold() == folded:
            return parts["value_text"]
    return ""


def _property_text_recursive(node: EdifNode, key: str) -> str:
    folded = key.casefold()
    found = ""
    for sub in node.walk():
        if sub.head.casefold() != "property":
            continue
        parts = _property_parts(sub)
        if parts["key"].casefold() == folded:
            found = parts["value_text"]
    return found


def _pt_xy(pt_node: EdifNode | None) -> tuple[str, str]:
    if pt_node is None:
        return "", ""
    values = [item.value for item in pt_node.items[1:] if isinstance(item, EdifAtom)]
    if len(values) >= 2:
        return values[0], values[1]
    return "", ""


def _origin_xy(node: EdifNode | None) -> tuple[str, str]:
    if node is None:
        return "", ""
    origin = node if node.head.casefold() == "origin" else node.find_first("origin")
    if origin is None:
        return "", ""
    return _pt_xy(_direct_child(origin, "pt") or origin.find_first("pt"))


def _direct_transform_origin(node: EdifNode) -> tuple[str, str]:
    transform = _direct_child(node, "transform")
    if transform is None:
        direct_origin = _direct_child(node, "origin")
        return _origin_xy(direct_origin)
    return _origin_xy(transform)


def _orientation(node: EdifNode) -> str:
    transform = _direct_child(node, "transform")
    search = transform if transform is not None else node
    orientation = search.find_first("orientation")
    return _first_atom_after_head(orientation) if orientation is not None else ""


def _visible(display: EdifNode | None) -> bool:
    if display is None:
        return True
    visible = display.find_first("visible")
    if visible is None:
        return True
    value = _first_atom_after_head(visible)
    return value.casefold() not in {"false", "off", "0"}


def _designator_text(node: EdifNode) -> str:
    designator = _direct_child(node, "designator")
    if designator is None:
        return ""
    text = _string_display_text(designator)
    return text if text else _first_atom_after_head(designator)


def _view_ref_parts(node: EdifNode) -> tuple[str, str, str]:
    view_ref = _direct_child(node, "viewRef")
    if view_ref is None:
        return "", "", ""
    view_name = _first_atom_after_head(view_ref)
    cell_ref = view_ref.find_first("cellRef")
    library_ref = view_ref.find_first("libraryRef")
    return (
        view_name,
        _first_atom_after_head(cell_ref) if cell_ref is not None else "",
        _first_atom_after_head(library_ref) if library_ref is not None else "",
    )


def _pin_symbol(port_instance: EdifNode) -> str:
    name_node = _direct_child(port_instance, "name")
    if name_node is not None:
        return _first_atom_after_head(name_node)
    return _first_atom_after_head(port_instance)


def _point_list(node: EdifNode) -> str:
    point_list = node if node.head.casefold() == "pointlist" else node.find_first("pointList")
    if point_list is None:
        return ""
    points = []
    for pt in _direct_children(point_list, "pt"):
        x, y = _pt_xy(pt)
        if x or y:
            points.append(f"{x},{y}")
    return ";".join(points)


def _owner(ctx: dict[str, str]) -> str:
    for key in ("instance_id", "net_name", "page_name", "cell_name", "library_name"):
        value = ctx.get(key, "")
        if value:
            return value
    return ""


def _raw_nodes(root: EdifNode) -> list[dict[str, Any]]:
    rows = []
    for node in root.walk():
        atom_values = [
            item.value
            for item in node.items[1:]
            if isinstance(item, EdifAtom)
        ]
        rows.append(
            {
                "node_path": node.path,
                "parent_path": node.parent.path if node.parent is not None else "",
                "depth": node.path.count("/") - 1,
                "head": node.head,
                "value": " ".join(atom_values),
                "line": node.line,
                "column": node.column,
                "child_index": node.child_index,
            }
        )
    return rows


GEOMETRY_HEADS = {
    "figure",
    "path",
    "pointlist",
    "rectangle",
    "polygon",
    "circle",
    "arc",
    "dot",
}


def extract_full_edif(path: Path) -> FullEdifTables:
    source = Path(path)
    root = parse_edif_sexpr(source)
    edif_name = root.atom_value(1)
    sheets: dict[str, list[dict[str, Any]]] = {
        name: [] for name in SHEET_ORDER if name != "Summary"
    }
    raw_rows = _raw_nodes(root)
    sheets["RawNodes"] = raw_rows

    instances_by_id: dict[str, dict[str, str]] = {}
    pin_lookup: dict[tuple[str, str], dict[str, str]] = {}
    pin_rows: dict[tuple[str, str], dict[str, Any]] = {}

    def visit(node: EdifNode, ctx: dict[str, str]) -> None:
        head = node.head.casefold()
        local = dict(ctx)

        if head == "library":
            name, _display = _object_name(node)
            local["library_name"] = name
            local.pop("cell_name", None)
            local.pop("view_name", None)
            sheets["Libraries"].append(
                {
                    "library_name": name,
                    "properties_json": _properties_json(node),
                    "source_path": node.path,
                }
            )

        elif head == "cell":
            name, display = _object_name(node)
            local["cell_name"] = name
            local.pop("view_name", None)
            sheets["Cells"].append(
                {
                    "library_name": local.get("library_name", ""),
                    "cell_name": name,
                    "cell_display_name": display,
                    "cellType": _first_atom_after_head(_direct_child(node, "cellType"))
                    if _direct_child(node, "cellType") is not None
                    else _property_text(node, "CELLTYPE"),
                    "properties_json": _properties_json(node),
                }
            )

        elif head == "view":
            name, _display = _object_name(node)
            local["view_name"] = name

        elif head == "port":
            name, display = _object_name(node)
            port_type = _first_atom_after_head(_direct_child(node, "direction"))
            port_type = port_type or _property_text(node, "TYPE")
            sheets["Ports"].append(
                {
                    "library_name": local.get("library_name", ""),
                    "cell_name": local.get("cell_name", ""),
                    "view_name": local.get("view_name", ""),
                    "port_name": name,
                    "designator": _designator_text(node) or display,
                    "Type": port_type,
                    "PackagePortNumbers": _property_text(node, "PACKAGEPORTNUMBERS"),
                    "properties_json": _properties_json(node),
                }
            )

        elif head == "page":
            token, display = _object_name(node)
            schematic = _property_text_recursive(node, "SCHEMATIC_NAME") or local.get(
                "cell_name", ""
            )
            page_name = _property_text_recursive(node, "PAGE_NAME") or display or token
            local.update(
                {
                    "schematic": schematic,
                    "page_name": page_name,
                    "page_token": token,
                }
            )
            sheets["Pages"].append(
                {
                    "schematic": schematic,
                    "page_name": page_name,
                    "page_token": token,
                    "properties_json": _properties_json(node),
                    "source_path": node.path,
                }
            )

        elif head == "instance":
            instance_id, display = _object_name(node)
            refdes = _designator_text(node) or _property_text(node, "DESIGNATOR") or display or instance_id
            view_ref, cell_ref, library_ref = _view_ref_parts(node)
            origin_x, origin_y = _direct_transform_origin(node)
            instance_row = {
                "instance_id": instance_id,
                "refdes": refdes,
                "schematic": local.get("schematic", ""),
                "page": local.get("page_name", ""),
                "library_ref": library_ref,
                "cell_ref": cell_ref,
                "view_ref": view_ref,
                "origin_x": origin_x,
                "origin_y": origin_y,
                "orientation": _orientation(node),
                "properties_json": _properties_json(node),
            }
            sheets["Instances"].append(instance_row)
            instances_by_id[instance_id] = {
                "refdes": refdes,
                "schematic": local.get("schematic", ""),
                "page": local.get("page_name", ""),
            }
            local["instance_id"] = instance_id
            local["refdes"] = refdes

            if view_ref or cell_ref or library_ref:
                sheets["HierarchyRefs"].append(
                    {
                        "instance_id": instance_id,
                        "view_ref": view_ref,
                        "cell_ref": cell_ref,
                        "library_ref": library_ref,
                        "source_path": node.path,
                    }
                )

            for prop in _direct_children(node, "property"):
                parts = _property_parts(prop)
                sheets["InstanceProperties"].append(
                    {
                        "instance_id": instance_id,
                        "refdes": refdes,
                        "property_key": parts["key"],
                        "display_name": parts["display_name"],
                        "value_raw": parts["value_raw"],
                        "value_text": parts["value_text"],
                        "display_origin_x": parts["display_origin_x"],
                        "display_origin_y": parts["display_origin_y"],
                        "visible": parts["visible"],
                        "source_path": parts["source_path"],
                    }
                )

            for port_instance in _direct_children(node, "portInstance"):
                symbol = _pin_symbol(port_instance)
                pin_number = _designator_text(port_instance) or symbol
                pin_name = symbol[1:] if symbol.startswith("&") else symbol
                px, py = _direct_transform_origin(port_instance)
                row = {
                    "instance_id": instance_id,
                    "refdes": refdes,
                    "symbol_pin": symbol,
                    "pin_number": pin_number,
                    "pin_name": pin_name,
                    "net_name": "",
                    "schematic": local.get("schematic", ""),
                    "page": local.get("page_name", ""),
                    "origin_x": px,
                    "origin_y": py,
                }
                sheets["PinInstances"].append(row)
                key = (instance_id.casefold(), symbol.casefold())
                pin_lookup[key] = {
                    "pin_number": pin_number,
                    "pin_name": pin_name,
                }
                pin_rows[key] = row

        elif head == "net":
            net_name, _display = _object_name(node)
            local["net_name"] = net_name
            pins_json: list[str] = []
            connection_count = 0
            for port_ref in [n for n in node.walk() if n.head.casefold() == "portref"]:
                symbol = _first_atom_after_head(port_ref)
                instance_ref = port_ref.find_first("instanceRef")
                instance_id = (
                    _first_atom_after_head(instance_ref) if instance_ref is not None else ""
                )
                instance_info = instances_by_id.get(instance_id, {})
                refdes = instance_info.get("refdes", "")
                pin_info = pin_lookup.get((instance_id.casefold(), symbol.casefold()), {})
                pin_number = pin_info.get("pin_number", "")
                pin_name = pin_info.get("pin_name", symbol[1:] if symbol.startswith("&") else symbol)
                resolved = bool(instance_id and refdes)
                if instance_id:
                    key = (instance_id.casefold(), symbol.casefold())
                    if key in pin_rows:
                        pin_rows[key]["net_name"] = net_name
                connection_count += 1
                pins_json.append(f"{refdes or instance_id}.{pin_number or symbol}")
                sheets["NetConnections"].append(
                    {
                        "net_name": net_name,
                        "refdes": refdes,
                        "instance_id": instance_id,
                        "symbol_pin": symbol,
                        "pin_number": pin_number,
                        "pin_name": pin_name,
                        "resolved": resolved,
                    }
                )
            sheets["Nets"].append(
                {
                    "net_name": net_name,
                    "schematic": local.get("schematic", ""),
                    "page": local.get("page_name", ""),
                    "connection_count": connection_count,
                    "Pins": _json(pins_json),
                    "source_path": node.path,
                }
            )

        elif head == "array":
            name = node.atom_value(1)
            sheets["Arrays"].append(
                {
                    "array_name": name,
                    "length": node.atom_value(2),
                    "owner_library": local.get("library_name", ""),
                    "owner_cell": local.get("cell_name", ""),
                    "owner_interface": local.get("view_name", ""),
                    "source_path": node.path,
                }
            )

        if head == "display":
            origin_x, origin_y = _origin_xy(node)
            justify = node.find_first("justify")
            sheets["Displays"].append(
                {
                    "owner": _owner(local),
                    "display_type": _first_atom_after_head(node),
                    "origin_x": origin_x,
                    "origin_y": origin_y,
                    "justify": _first_atom_after_head(justify) if justify is not None else "",
                    "visible": _visible(node),
                    "raw_json": _json(_node_to_obj(node)),
                }
            )

        if head in GEOMETRY_HEADS:
            origin_x, origin_y = _origin_xy(node)
            sheets["Geometry"].append(
                {
                    "owner": _owner(local),
                    "geometry_type": node.head,
                    "point_list": _point_list(node),
                    "origin": f"{origin_x},{origin_y}" if origin_x or origin_y else "",
                    "orientation": _orientation(node),
                    "source_path": node.path,
                }
            )

        for child in node.child_nodes():
            visit(child, local)

    visit(root, {})

    raw_counts = Counter(row["head"] for row in raw_rows)
    summary = {
        "file_path": str(source),
        "edif_name": edif_name,
        "library_count": len(sheets["Libraries"]),
        "page_count": len(sheets["Pages"]),
        "instance_count": len(sheets["Instances"]),
        "net_count": len(sheets["Nets"]),
        "property_count": raw_counts["property"],
        "coordinate_count": raw_counts["origin"] + raw_counts["pt"],
        "raw_node_count": len(raw_rows),
        "raw_property_count": raw_counts["property"],
        "raw_origin_count": raw_counts["origin"],
        "raw_pt_count": raw_counts["pt"],
        "raw_orientation_count": raw_counts["orientation"],
        "raw_display_count": raw_counts["display"],
        "raw_library_count": raw_counts["library"],
        "raw_cell_count": raw_counts["cell"],
        "raw_interface_count": raw_counts["interface"],
        "raw_port_count": raw_counts["port"],
        "raw_portInstance_count": raw_counts["portInstance"],
        "raw_array_count": raw_counts["array"],
        "raw_page_count": raw_counts["page"],
        "raw_instance_count": raw_counts["instance"],
        "raw_net_count": raw_counts["net"],
    }
    return FullEdifTables(
        source_path=str(source),
        edif_name=edif_name,
        sheets={"Summary": [summary], **sheets},
    )
