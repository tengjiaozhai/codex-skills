---
name: schematic-compare
description: Use when comparing two versions of OrCAD/Cadence schematics to identify differences in components, pins, and nets. Triggers on keywords like schematic diff, DSN compare, BOM diff, netlist comparison, EDIF diff, pin/net change detection, reference designator renumber, or OrCAD Capture export.
---

# OrCAD 原理图差异对比技能

## 概述

对比两个版本的 OrCAD Capture 原理图，识别器件（Parts）、管脚（Pins）、网络（Nets）三个维度的差异。核心原则：**将封闭的二进制 DSN 转换为结构化的 CSV 文本，再用行键匹配算法逐列对比。**

## 何时使用

- 需要对比两版 OrCAD 原理图之间的器件/网络/管脚差异
- 需要从 DSN/EDIF 格式中提取 BOM 或网表信息
- 需要检测位号重编、网络重命名、连接变更等 ECO 变化
- 需要生成原理图变更报告（Excel / Markdown）

**不适用于**：PCB 布局对比、Gerber 文件对比、非 EDA 领域的文本 diff。

## 目录结构

```
schematic-compare/
├── SKILL.md                           # 本文档
├── references/
│   ├── csv_format_spec.md            # CSV 三表列头规范与示例
│   ├── edif_format_spec.md           # EDIF 关键结构与正则模式
│   └── diff_types.md                 # 7 种差异类型定义与风险等级
└── scripts/
    ├── __init__.py                   # Python 包标识
    ├── schcompare_cli.py             # 统一 CLI 入口（三种模式调度 + check-env）
    ├── csv_diff.py                   # CSV 对比引擎（核心算法）
    ├── edif_import.py                # EDIF 明文解析器（自包含，零外部依赖）
    ├── models.py                     # DiffRow 数据模型 + 合并显示逻辑
    ├── diff_types.py                 # 差异类型常量
    ├── dsn_capture_export.py         # DSN→CSV 驱动（含环境检测，非 Win 报错退出）
    ├── capture_runner.py             # Capture 子进程管理（exe 探测 + Tcl 执行）
    ├── export_report.py              # Excel / Markdown 报告导出
    └── tcl/
        ├── capExportAllInfo.tcl      # Tcl 导出函数库（器件/管脚/网络→CSV）
        └── capFind.tcl               # Tcl 定位函数（双击跳转原理图）
```

## 快速使用

### CLI 命令

```bash
# 1. 环境探针（检查当前系统对各模式的支持）
python -m scripts.schcompare_cli check-env

# 2. EDIF 模式对比（跨平台，零依赖）
python -m scripts.schcompare_cli edif old.edf new.edf
python -m scripts.schcompare_cli edif old.edf new.edf -o report.md

# 3. CSV 模式对比（跨平台，需预先导出 CSV 目录）
python -m scripts.schcompare_cli csv ./export/v1 ./export/v2 -o report.xlsx

# 4. DSN 原生对比（仅 Windows + OrCAD Capture 17.4+）
python -m scripts.schcompare_cli dsn old.dsn new.dsn -o report.xlsx
```

### 在代码中调用

```python
from pathlib import Path
from scripts.edif_import import import_edif_pair_to_dirs
from scripts.csv_diff import compare_all_dsn_csvs
from scripts.export_report import export_markdown, export_excel

# EDIF 模式
out1, out2 = import_edif_pair_to_dirs(
    Path("old.edf"), Path("new.edf"),
    Path("/tmp/v1"), Path("/tmp/v2"),
)
results = compare_all_dsn_csvs(
    out1["parts"], out2["parts"],
    out1["pins"], out2["pins"],
    out1["nets"], out2["nets"],
)

# 导出报告
export_markdown("report.md", results, {"oldPath": "old.edf", "newPath": "new.edf"})
export_excel("report.xlsx", results, {"oldPath": "old.edf", "newPath": "new.edf"})
```

## 三种输入格式

| 格式 | 数据丰富度 | 跨平台 | 说明 |
|------|-----------|--------|------|
| **DSN** | 最高（图形+逻辑）| ❌ 仅 Windows + Capture | 原生工程文件，需 Tcl API 提取数据 |
| **CSV** | 高（所有电气属性）| ✅ | 通过 Tcl 脚本从 Capture 导出的宽表 |
| **EDIF** | 中（核心连通性）| ✅ | 行业标准明文网表，Python 可直接解析 |

**推荐路径**：DSN → (Capture + Tcl) → CSV → 对比算法

**环境感知策略**：
- `check_capture_environment()` 在非 Windows 系统调用 DSN 模式时立即抛出 `RuntimeError`
- 错误信息引导用户切换为 EDIF 或 CSV 模式
- `resolve_capture_exe()` 按优先级搜索：环境变量 → 配置 → PATH → 常见安装目录

## 数据模型

### DiffRow（差异结果行）

```python
@dataclass
class DiffRow:
    category: str        # "器件" | "管脚" | "网络"
    change_type: str     # 见下表
    object_id: str       # 如 "[Parts] R1" 或 "[Nets] GND|P1"
    detail: str          # 修改详情描述
    prop_name: str|None  # 属性名（属性修改类用）
    old_value: str|None  # 旧值
    new_value: str|None  # 新值
    meta: dict           # 扩展元数据（原理图名、页名等）
```

### 差异类型常量

| change_type | 适用类别 | 说明 | 风险等级 |
|-------------|---------|------|---------|
| `新增` | 器件/管脚/网络 | 仅在 DSN2 中存在 | 🟡 中 |
| `删除` | 器件/管脚/网络 | 仅在 DSN1 中存在 | 🔴 高 |
| `器件属性` | 器件 | 同一器件的属性值变化 | 🟡 中 |
| `管脚属性` | 管脚 | 同一管脚的属性值变化 | 🟡 中 |
| `网络重命名` | 网络 | 管脚组不变，网名变化 | 🟢 低 |
| `连接变更` | 网络 | 管脚组发生变化 | 🔴 高 |
| `位号重编` | 器件/管脚 | 属性不变，仅位号变化 | 🟢 低 |

> 完整定义与风险评估见 [references/diff_types.md](references/diff_types.md)

## 核心对比算法

### 三路并行对比

```
compare_all_dsn_csvs(parts1, parts2, pins1, pins2, nets1, nets2)
  ├── compare_csv_pair(parts_old, parts_new, "parts")  → list[DiffRow]
  ├── compare_csv_pair(pins_old,  pins_new,  "pins")   → list[DiffRow]
  └── compare_csv_pair(nets_old,  nets_new,  "nets")   → list[DiffRow]
  → 合并 → 后处理（位号重编抑制、网络重命名合并）→ 最终结果
```

### 行键生成算法（`_row_key`）

从 CSV 表头中启发式地选取关键列作为唯一标识：

```python
KEY_HINTS = ("refdes", "reference", "part ref", "pin", "net", "signal", "flat")

def row_key(headers, row):
    picks = []
    for i, name in enumerate(normalized_headers):
        if any(k in name for k in KEY_HINTS):
            val = row[i].strip()
            if val not in ("true", "false"):  # 跳过布尔标志列
                picks.append((i, val))
    return "|".join(v for _, v in sorted(picks))
```

### Nets 对比流程（最复杂）

```
1. 构建网络指纹行键：FlatNet 名 + 页面配对 ID
2. Page 配对算法确定跨版本页面对应关系
3. 对比逻辑：
   - 同键存在 → 比较管脚组（Pins 列）
   - 管脚组相同但网名不同 → NET_RENAME
   - 管脚组不同 → NET_CONNECTION
4. 使用 Jaccard 相似度评估页间管脚重叠度
```

### 后处理管线

```python
rows = suppress_pin_add_delete_for_refdes_renumber(rows)      # 位号重编时抑制管脚假新增/删除
rows = suppress_net_connection_pins_for_refdes_renumber(rows)  # 位号重编引起的网络连接假变更
rows = coalesce_net_add_connection_to_rename(rows)             # 合并新增+删除为重命名
rows = enrich_net_connection_pins_page_meta_from_parts(rows)   # 补充页面元数据
rows = reclassify_net_connection_disjoint_pins_as_rename(rows) # 不相交管脚组重分类为重命名
```

## CSV 文件格式规范

> 完整规范见 [references/csv_format_spec.md](references/csv_format_spec.md)

### Parts_Properties.csv

```csv
"Reference Designator","Schematic","Page","Value","Part","Footprint",...
"R1","UTAH_MB","PAGE1","100R","RES_0402","0402",...
```

### Pins_Info.csv

```csv
"Reference","Pin Number","Pin Name","Net Name","Schematic","Page"
"U1","A1","VCC","VCC_3V3","UTAH_MB","PAGE1"
```

### Nets_Info.csv

```csv
"FlatNet","Schematic","Page","Pins (Page)","Pins (Global)"
"VCC_3V3","UTAH_MB","PAGE1","U1.A1,C1.1","U1.A1,C1.1,U2.B3"
```

## EDIF 解析（无需 Capture 环境）

> 完整正则模式见 [references/edif_format_spec.md](references/edif_format_spec.md)

```python
from pathlib import Path
from scripts.edif_import import parse_edif_file, write_capture_style_csvs

data = parse_edif_file(Path("design.edf"))
# data["instances"]  → list[(refdes, value, schematic, page)]
# data["nets"]       → dict[(net_name, sch, page) → list[(refdes, pin)]]
# data["pin_lookup"] → dict[(refdes, pin_sym) → (pin_num, pin_name)]

parts, pins, nets = write_capture_style_csvs(data, Path("/tmp/output"))
```

## 报告导出

### Markdown 报告

```python
from scripts.export_report import export_markdown

export_markdown("report.md", diff_results, {
    "oldPath": "old.edf",
    "newPath": "new.edf",
    "mode": "edif",
})
```

输出包含：摘要统计表、按风险等级着色的详细差异列表。

### Excel 报告（需 openpyxl）

```python
from scripts.export_report import export_excel

export_excel("report.xlsx", diff_results, meta)
```

输出包含：
- **对比结果** 工作表：序号、分类、差异类型、旧值、新值、风险等级（行背景色按风险着色）
- **元数据** 工作表：导出时间、DSN 路径、差异总数

### 颜色编码

| 风险 | 背景色 | 对应差异类型 |
|------|--------|-------------|
| 🟢 低 | `#E3F2FD` | 位号重编、网络重命名 |
| 🟡 中 | `#FFF8E1` | 新增、器件属性、管脚属性 |
| 🔴 高 | `#FFEBEE` | 删除、连接变更 |

## DSN 原生模式（Windows 专属）

### 架构

```
capture_runner.py  ──→  OrCAD Capture (capture.exe)
                          │
dsn_capture_export.py     │ -TCLScript
                          ↓
                   capExportAllInfo.tcl  ──→  Parts_Properties.csv
                                         ──→  Pins_Info.csv
                                         ──→  Nets_Info.csv
```

### 环境检测

```python
from scripts.capture_runner import check_capture_environment, resolve_capture_exe

check_capture_environment()  # 非 Windows 抛出 RuntimeError
exe = resolve_capture_exe()  # 返回 Path 或 None
```

### Tcl 脚本

- `capExportAllInfo.tcl`：通过 DboTclWriteBasic API 遍历设计中所有原理图/页/器件/网络，导出三张 CSV
- `capFind.tcl`：在 Capture GUI 中根据位号或网名定位原理图对象

## 常见错误

| 问题 | 原因与修复 |
|------|-----------| 
| CSV 全部显示为「新增+删除」| 行键列名不匹配（如一侧用 `RefDes`，另一侧用 `Reference Designator`）→ 检查列头 |
| 网络对比缺少结果 | Nets CSV 的 FlatNet 列为空 → 确认 Tcl 导出是否成功 |
| EDIF 解析器件数为 0 | EDIF 非 OrCAD 导出格式 → 检查是否含 `(instance INS\d+` 模式 |
| 位号重编产生大量假差异 | 后处理管线未执行 → 确保调用完整的后处理步骤 |
| Mac 下调用 DSN 模式报错 | 预期行为 → 使用 `check-env` 确认后切换为 EDIF/CSV 模式 |
| Excel 导出报 ImportError | 缺少 openpyxl → `pip install openpyxl` |

## 模块依赖关系

```
diff_types.py          ← 零依赖（常量定义）
models.py              ← diff_types
edif_import.py         ← 零依赖（纯标准库）
csv_diff.py            ← models, diff_types
capture_runner.py      ← 零依赖（仅 subprocess/shutil）
dsn_capture_export.py  ← capture_runner
export_report.py       ← models, diff_types (openpyxl 可选)
schcompare_cli.py      ← 以上全部
```
