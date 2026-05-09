"""差异类型常量定义（全应用统一使用以下中文名称）。"""

from __future__ import annotations

# --- 基础差异类型 ---
RENUMBER_REFDES = "位号重编"
ADD = "新增"
DELETE = "删除"

# 向后兼容别名
ADD_COMPONENT = ADD_PIN = ADD_NET = ADD
DEL_COMPONENT = DEL_PIN = DEL_NET = DELETE

# 属性级变更
COMPONENT_PROP = "器件属性"
PIN_INFO = "管脚属性"
NET_RENAME = "网络重命名"
NET_CONNECTION = "连接变更"

ALL_CHANGE_TYPES: tuple[str, ...] = (
    RENUMBER_REFDES,
    ADD,
    DELETE,
    COMPONENT_PROP,
    PIN_INFO,
    NET_RENAME,
    NET_CONNECTION,
)

DELETE_TYPES = frozenset({DELETE})
ADD_TYPES = frozenset({ADD})
PROPERTY_STYLE_TYPES = frozenset({COMPONENT_PROP, PIN_INFO, NET_CONNECTION})


def change_types_for_category(cat: str) -> tuple[str, ...]:
    """给定「类别」筛选项时，返回该类下可能出现的差异类型。"""
    c = (cat or "").strip()
    if c in ("", "全部"):
        return ALL_CHANGE_TYPES
    if c == "器件":
        return (RENUMBER_REFDES, ADD, DELETE, COMPONENT_PROP)
    if c == "管脚":
        return (RENUMBER_REFDES, ADD, DELETE, PIN_INFO)
    if c == "网络":
        return (ADD, DELETE, NET_RENAME, NET_CONNECTION)
    return ALL_CHANGE_TYPES


def csv_change_type(category: str, base: str) -> str:
    """将 CSV 对比中的类别+基础类型映射为统一差异类型。"""
    c = (category or "").strip()
    b = (base or "").strip()
    if b == "新增":
        return ADD
    if b == "删除":
        return DELETE
    if b == "属性修改":
        if c == "器件":
            return COMPONENT_PROP
        if c == "管脚":
            return PIN_INFO
        return NET_CONNECTION
    if b == "位号重编" and c in ("器件", "管脚"):
        return RENUMBER_REFDES
    return b


def format_renumber_refdes_detail(old_ref: str, new_ref: str) -> str:
    """位号重编详情格式化。"""
    o = (old_ref or "").strip()
    n = (new_ref or "").strip()
    return f"位号{o}→{n}，属性不变"
