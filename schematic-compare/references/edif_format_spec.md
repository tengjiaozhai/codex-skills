# EDIF 关键结构与正则模式

EDIF (Electronic Design Interchange Format) Level 2 网表是 EDA 行业标准明文格式。
本文档摘录 OrCAD Capture 导出 EDIF 中与原理图对比相关的关键结构。

## 顶层结构

```lisp
(edif DESIGN_NAME
  (edifVersion 2 0 0)
  (edifLevel 0)
  (keywordMap (keywordLevel 0))
  (library LIB_NAME
    (cell CELL_NAME
      (view VIEW_NAME
        (contents
          (page (rename &PAGE_TOKEN "PAGE_DISPLAY_NAME")
            (instance INS12345 ...)
            (net NET_NAME ...)
          )
        )
      )
    )
  )
)
```

## 器件实例 (Instance)

### OrCAD Cadence 风格（含 INS 编号）

```lisp
(instance INS47236280
  (viewRef PRIM_NETLIST (cellRef RES (libraryRef DISCRETE)))
  (designator
    (stringDisplay "R1" (display PARTREFERENCE ...))
  )
  (property
    (rename VALUE "Value")
    (string (stringDisplay "100R" ...))
  )
  (portInstance (name &1)
    (designator (stringDisplay "1" (display PINNUMBER ...)))
  )
)
```

**解析正则：**

| 目标 | 正则模式 |
|------|---------|
| 实例 ID | `\(\s*instance\s+(INS\d+)\b` |
| 位号 (RefDes) | `\(\s*stringDisplay\s+"([^"]*)"\s*\(\s*display\s+PARTREFERENCE\b` |
| Value 属性 | `\(\s*rename\s+VALUE\b` → 后续 `\(\s*stringDisplay\s+"([^"]*)"` |
| 管脚编号 | `\(\s*stringDisplay\s+"([^"]*)"\s*\(\s*display\s+PINNUMBER\b` |

### 通用风格（无 INS 编号）

```lisp
(instance (rename R1 ...)
  (cellRef RES_0402 ...)
)
```

**解析正则：**

| 目标 | 正则模式 |
|------|---------|
| 位号 | `\(\s*rename\s+([^\s()|]+)` |
| Cell 引用 | `\(\s*cellRef\s+([^\s()|]+)` |

## 网络 (Net)

```lisp
(net VCC_3V3
  (joined
    (portRef &1 (instanceRef INS47236280))
    (portRef &A1 (instanceRef INS47236281))
  )
)
```

**解析正则：**

| 目标 | 正则模式 |
|------|---------|
| 网络名 | `\(\s*net\s+(\|[^\|]*\||[^\s()]+)` |
| 管脚连接 | `portRef\s+(\S+)\s+\(\s*instanceRef\s+([^)\s]+)\s*\)` |

> **注意**：`portRef` 中的 `&1` 是管脚符号名（symbol pin），需要通过 `portInstance` 中的
> `PINNUMBER` 映射到物理管脚编号。

## 页面 (Page)

```lisp
(page (rename &01_PAGE1 "PAGE1")
  (property (rename PAGE_NAME "Page Name")
    (string "POWER")
  )
  (property (rename SCHEMATIC_NAME "Schematic Name")
    (string "UTAH_MB")
  )
  ...
)
```

**解析正则：**

| 目标 | 正则模式 |
|------|---------|
| 页面块 | `\(\s*page\s+` |
| 页显示名 | `\(\s*page\s+\(\s*rename\s+[^\s()]+\s+"([^"]*)"` |
| PAGE_NAME 属性 | `rename\s+PAGE_NAME\b[^)]*\)\s*\(\s*string\s+"([^"]*)"` |
| SCHEMATIC_NAME | `rename\s+SCHEMATIC_NAME\b[^)]*\)\s*\(\s*string\s+"([^"]*)"` |

## 括号平衡提取

EDIF 的所有结构都是 S 表达式（括号嵌套）。解析时使用**括号计数器**提取完整块：

```python
def _extract_balanced(text: str, start: int) -> tuple[str, int] | None:
    """从 start 位置的 '(' 开始，提取到匹配的 ')' 为止。"""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                return text[start:i+1], i+1
    return None
```

## 注释处理

EDIF 注释以 `;` 开头（行尾注释），解析前应预处理移除：

```python
def _strip_edif_comments(text: str) -> str:
    return "\n".join(line.split(";", 1)[0] for line in text.splitlines())
```
