# Full EDIF Export Spec

`edif-export` reads one `.edf/.edif` file, parses the complete EDIF S-expression tree,
extracts common schematic semantics, and writes a multi-sheet `.xlsx` workbook. The
export path is independent from `scripts.edif_import.parse_edif_file()`, which remains
the lightweight parser used by the existing EDIF comparison flow.

## CLI

```bash
/opt/anaconda3/envs/py311/bin/python3 -m scripts.schcompare_cli edif-export input.edf -o full_edif.xlsx --json full_edif.json
```

`--json` is optional and writes the same nested table payload used by the Excel exporter.

## Sheets

### Summary

One row with file path, EDIF name, semantic table counts, and raw node counts for
`property`, `origin`, `pt`, `orientation`, `display`, `library`, `cell`, `interface`,
`port`, `portInstance`, `array`, `page`, `instance`, and `net`.

### Libraries

Columns: `library_name`, `properties_json`, `source_path`.

Direct `property` children of each `library` are serialized into `properties_json`.

### Cells

Columns: `library_name`, `cell_name`, `cell_display_name`, `cellType`,
`properties_json`.

`cellType` is read from direct `cellType` children first, then from a `CELLTYPE`
property when present.

### Ports

Columns: `library_name`, `cell_name`, `view_name`, `port_name`, `designator`, `Type`,
`PackagePortNumbers`, `properties_json`.

`Type` comes from `direction` or a `TYPE` property. `PackagePortNumbers` comes from the
matching property if present.

### Pages

Columns: `schematic`, `page_name`, `page_token`, `properties_json`, `source_path`.

`SCHEMATIC_NAME` and `PAGE_NAME` are resolved recursively inside the page because
OrCAD often stores those values on the title block instance.

### Instances

Columns: `instance_id`, `refdes`, `schematic`, `page`, `library_ref`, `cell_ref`,
`view_ref`, `origin_x`, `origin_y`, `orientation`, `properties_json`.

`refdes` is read from `designator/stringDisplay` first, then `DESIGNATOR`, then the
instance token.

### InstanceProperties

Columns: `instance_id`, `refdes`, `property_key`, `display_name`, `value_raw`,
`value_text`, `display_origin_x`, `display_origin_y`, `visible`, `source_path`.

`value_raw` keeps a JSON representation of the EDIF value node. `value_text` is the
best-effort display or scalar text value.

### PinInstances

Columns: `instance_id`, `refdes`, `symbol_pin`, `pin_number`, `pin_name`, `net_name`,
`schematic`, `page`, `origin_x`, `origin_y`.

`net_name` is filled when a matching `portRef` / `instanceRef` connection is found.

### Nets

Columns: `net_name`, `schematic`, `page`, `connection_count`, `Pins`, `source_path`.

`Pins` is a JSON list of resolved `refdes.pin` display strings.

### NetConnections

Columns: `net_name`, `refdes`, `instance_id`, `symbol_pin`, `pin_number`, `pin_name`,
`resolved`.

`resolved` is true when the `instanceRef` can be mapped to a parsed instance.

### Displays

Columns: `owner`, `display_type`, `origin_x`, `origin_y`, `justify`, `visible`,
`raw_json`.

Every EDIF `display` node is exported.

### Geometry

Columns: `owner`, `geometry_type`, `point_list`, `origin`, `orientation`,
`source_path`.

`figure`, `path`, `pointList`, `rectangle`, `polygon`, `circle`, `arc`, and `dot`
nodes are exported. `point_list` uses `x,y;x,y` text.

### Arrays

Columns: `array_name`, `length`, `owner_library`, `owner_cell`, `owner_interface`,
`source_path`.

### HierarchyRefs

Columns: `instance_id`, `view_ref`, `cell_ref`, `library_ref`, `source_path`.

One row is emitted for each instance that has a `viewRef`, `cellRef`, or `libraryRef`.

### RawNodes

Columns: `node_path`, `parent_path`, `depth`, `head`, `value`, `line`, `column`,
`child_index`.

`RawNodes` is the completeness backstop. It includes every S-expression list node with
1-based source line/column. If the row count exceeds an Excel sheet limit, the exporter
creates `RawNodes`, `RawNodes_2`, `RawNodes_3`, and so on.

## Known Limits

- Bus and array structures are recorded but not flattened into every possible bit.
- Cross-page and cross-hierarchy net equivalence is not flattened in v1.
- Instance origin is taken from a direct `transform/origin` when present. Display
  origins remain in `Displays` and `InstanceProperties`.
- Property values use best-effort scalar extraction. The raw JSON column preserves the
  original node shape for follow-up tooling.
