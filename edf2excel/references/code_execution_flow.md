# Code Execution Flow

This diagram covers the main command paths in the current workspace.

```mermaid
flowchart TD
    A["User runs python -m scripts.schcompare_cli"] --> B{"Subcommand"}

    B --> C["check-env"]
    C --> C1["Print OS, Python, EDIF/CSV/DSN availability"]

    B --> D["edif-export input.edf -o full.xlsx --json full.json"]
    D --> D1["Validate input path"]
    D1 --> D2["extract_full_edif(input_path)"]
    D2 --> D3["parse_edif_sexpr(path)"]
    D3 --> D4["Tokenize EDIF: comments, strings, symbols, |quoted names|"]
    D4 --> D5["Build EdifNode tree with line/column/path"]
    D5 --> D6["Walk tree and collect semantic sheets"]
    D6 --> D7["Summary, Libraries, Cells, Ports, Pages"]
    D6 --> D8["Instances, InstanceProperties, PinInstances"]
    D6 --> D9["Nets, NetConnections, Displays, Geometry"]
    D6 --> D10["Arrays, HierarchyRefs, RawNodes"]
    D7 --> D11["FullEdifTables"]
    D8 --> D11
    D9 --> D11
    D10 --> D11
    D11 --> D12["export_full_edif_xlsx(output, tables, meta)"]
    D12 --> D13["Write fixed-column workbook; split RawNodes if needed"]
    D11 --> D14{"--json provided?"}
    D14 -->|"yes"| D15["export_full_edif_json(json_output, tables, meta)"]
    D14 -->|"no"| D16["Finish with XLSX only"]

    B --> E["edif old.edf new.edf"]
    E --> E1["edif_import.import_edif_pair_to_dirs"]
    E1 --> E2["parse_edif_file via lightweight compare parser"]
    E2 --> E3["write Capture-style Parts/Pins/Nets CSVs"]
    E3 --> H["csv_diff.build_default_compare_prefs"]

    B --> F["csv old_dir new_dir"]
    F --> F1["Read Parts_Properties.csv, Pins_Info.csv, Nets_Info.csv"]
    F1 --> H

    B --> G["dsn old.dsn new.dsn"]
    G --> G1["run_dsn_compare_export_sequence"]
    G1 --> G2["Windows/OrCAD Capture Tcl export"]
    G2 --> H

    H --> I["csv_diff.compare_all_dsn_csvs_from_prefs"]
    I --> J["Compare parts, pins, nets"]
    J --> K["Post-process renumber, net rename, connection changes"]
    K --> L{"-o output provided?"}
    L -->|"xlsx"| M["export_report.export_excel"]
    L -->|"md/other"| N["export_report.export_markdown"]
    L -->|"none"| O["Print console summary"]
```

## Important Separation

- `scripts.edif_import.py` is the lightweight parser for comparison.
- `scripts.edif_sexpr.py` plus `scripts.edif_full_extract.py` is the full semantic
  extraction path.
- `RawNodes` is the fallback coverage table for EDIF structures that are not yet
  promoted into dedicated semantic sheets.
