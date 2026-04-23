# CSV 三表列头规范与示例

OrCAD Capture 通过 Tcl 导出或 EDIF 解析后，统一生成三张 CSV 宽表。本文档定义列头名称、语义及示例数据。

## 1. Parts_Properties.csv（器件属性表）

| 列名 | 是否必须 | 说明 |
|------|---------|------|
| `Reference Designator` | ✅ | 位号，如 `R1`、`C9020`、`U3` |
| `Schematic` | ✅ | 原理图名（Capture 中的 View Name） |
| `Page` | ✅ | 页名 |
| `Value` | ✅ | 元件值，如 `100R`、`10uF` |
| _动态列…_ | 可选 | 所有有效属性（宽表），列数因设计而异 |

**示例：**

```csv
"Reference Designator","Schematic","Page","Value","Part","Footprint","Brand"
"R1","UTAH_MB","PAGE1","100R","RES_0402","0402","TDK"
"C9020","UTAH_MB","PAGE3","10uF","CAP_0603","0603","Samsung"
```

### 行键策略

对比时以 `Reference Designator` 作为主键。若导出的列名不同（如 `RefDes`、`Part Reference`），
引擎会通过启发式关键词匹配自动识别。

---

## 2. Pins_Info.csv（管脚信息表）

| 列名 | 是否必须 | 说明 |
|------|---------|------|
| `Reference` | ✅ | 所属器件位号 |
| `Pin Number` | ✅ | 管脚编号（物理 ball/pad 号） |
| `Pin Name` | ✅ | 管脚符号名（原理图上的逻辑名） |
| `Net Name` | ✅ | 所连网络名 |
| `Schematic` | ✅ | 原理图名 |
| `Page` | ✅ | 页名 |

**示例：**

```csv
"Reference","Pin Number","Pin Name","Net Name","Schematic","Page"
"U1","A1","VCC","VCC_3V3","UTAH_MB","PAGE1"
"U1","B2","GND","GND","UTAH_MB","PAGE1"
"R1","1","1","NET_R1_1","UTAH_MB","PAGE1"
```

### 行键策略

以 `Reference | Pin Number` 组合作为主键。

---

## 3. Nets_Info.csv（网络信息表）

| 列名 | 是否必须 | 说明 |
|------|---------|------|
| `FlatNet` | ✅ | 扁平化网络名（跨页合并后的唯一名称） |
| `Schematic` | ✅ | 原理图名 |
| `Page` | ✅ | 页名 |
| `Pins (Page)` | ✅ | 本页内连接的管脚列表，逗号分隔 |
| `Pins (Global)` | ✅ | 全设计中连接的管脚列表，逗号分隔 |

**示例：**

```csv
"FlatNet","Schematic","Page","Pins (Page)","Pins (Global)"
"VCC_3V3","UTAH_MB","PAGE1","U1.A1,C1.1","U1.A1,C1.1,U2.B3"
"GND","UTAH_MB","PAGE1","U1.B2,R1.2","U1.B2,R1.2,C9020.2"
```

### 行键策略

以 `FlatNet | Schematic | Page` 的指纹组合作为主键。对比时会优先匹配同页网络；
跨页时使用 Jaccard 管脚相似度阈值判断是否允许配对。

---

## 编码与格式

- **编码**：UTF-8 with BOM (`utf-8-sig`)
- **引用**：CSV 标准引用（含逗号或双引号的字段使用双引号包裹）
- **换行**：Windows `\r\n` 或 Unix `\n` 均可
