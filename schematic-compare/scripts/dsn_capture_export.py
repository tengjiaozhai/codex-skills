"""
DSN → CSV 驱动模块。
负责将 .dsn 原生文件通过 OrCAD Capture + Tcl 脚本导出为三张标准 CSV 宽表。

⚠️ 本模块仅支持 Windows + OrCAD Capture 17.4+ 环境。
非 Windows 或未安装 Capture 的环境调用时会抛出 RuntimeError。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable

from .capture_runner import (
    check_capture_environment,
    resolve_capture_exe,
    run_capture_with_tcl,
)

# 标准导出 CSV 文件名
_EXPORT_CSV = {
    "parts": "Parts_Properties.csv",
    "pins": "Pins_Info.csv",
    "nets": "Nets_Info.csv",
}


def tcl_quoted_string(s: str) -> str:
    """Tcl 双引号字符串转义：避免 $ [ ] \\ " 被 Tcl 解释。"""
    t = str(s)
    for a, b in (
        ("\\", "\\\\"),
        ('"', '\\"'),
        ("$", "\\$"),
        ("[", "\\["),
        ("]", "\\]"),
    ):
        t = t.replace(a, b)
    return '"' + t + '"'


def tcl_quoted_path(p: Path) -> str:
    """Tcl 双引号绝对路径（正斜杠）。"""
    return tcl_quoted_string(p.resolve().as_posix())


def discover_export_csv_bundle(folder: Path) -> tuple[dict[str, Path], list[str]]:
    """
    在单个目录中查找标准导出文件：
    Parts_Properties.csv、Pins_Info.csv、Nets_Info.csv（大小写不敏感）。
    返回 (kind→路径, 缺失文件名列表)。
    """
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        return {}, [f"目录不存在或不是文件夹：{folder}"]
    by_cf = {p.name.casefold(): p for p in folder.iterdir() if p.is_file()}
    out: dict[str, Path] = {}
    missing: list[str] = []
    for kind, fname in _EXPORT_CSV.items():
        p = by_cf.get(str(fname).casefold())
        if p is None:
            missing.append(fname)
        else:
            out[kind] = p.resolve()
    return out, missing


def clear_export_slot_standard_csvs(out1: Path, out2: Path) -> None:
    """
    DSN 对比启动 Capture 之前：删除 export/1、export/2 下与标准导出同名的 CSV，
    避免上一轮残留与本轮导出混杂。
    """
    targets_cf = {str(n).casefold() for n in _EXPORT_CSV.values()}
    for base in (out1, out2):
        try:
            if not base.is_dir():
                continue
            for p in list(base.iterdir()):
                if p.is_file() and p.name.casefold() in targets_cf:
                    try:
                        p.unlink()
                    except OSError:
                        pass
        except OSError:
            pass


def export_dsn_to_csvs(
    dsn_path: Path,
    out_dir: Path,
    *,
    capture_exe: Path | None = None,
    on_log: Callable[[str], None] | None = None,
) -> tuple[Path, Path, Path]:
    """
    通过 OrCAD Capture + Tcl 脚本将单个 DSN 导出为三张 CSV。

    参数：
        dsn_path: .dsn 文件路径
        out_dir: 导出目录
        capture_exe: capture.exe 绝对路径（不提供则自动探测）
        on_log: 日志回调

    返回：
        (Parts_Properties.csv, Pins_Info.csv, Nets_Info.csv) 路径元组

    异常：
        RuntimeError: 非 Windows 环境或 Capture 不可用
        FileNotFoundError: 导出后 CSV 文件缺失
    """

    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    # 环境校验
    check_capture_environment()

    if capture_exe is None:
        capture_exe = resolve_capture_exe()
    if capture_exe is None:
        raise RuntimeError(
            "未找到 capture.exe，请设置环境变量 SCHCOMPARE_CAPTURE_EXE 或在 PATH 中配置。"
        )

    if not dsn_path.is_file():
        raise FileNotFoundError(f"DSN 文件不存在：{dsn_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    # 定位 Tcl 脚本
    tcl_dir = Path(__file__).parent / "tcl"
    cap_export_tcl = tcl_dir / "capExportAllInfo.tcl"
    cap_find_tcl = tcl_dir / "capFind.tcl"

    if not cap_export_tcl.is_file():
        raise FileNotFoundError(f"缺少 Tcl 导出脚本：{cap_export_tcl}")

    # 构建合并 Tcl 命令
    tcl_lines = [
        f"source {tcl_quoted_path(cap_export_tcl)}",
    ]
    if cap_find_tcl.is_file():
        tcl_lines.append(f"source {tcl_quoted_path(cap_find_tcl)}")
    tcl_lines.append(
        f"exportDsnCsv {tcl_quoted_path(dsn_path)} {tcl_quoted_path(out_dir)}"
    )

    log(f"调用 Capture 导出：{dsn_path.name} → {out_dir}")
    run_capture_with_tcl(capture_exe, "\n".join(tcl_lines))

    # 验证导出结果
    parts_csv = out_dir / _EXPORT_CSV["parts"]
    pins_csv = out_dir / _EXPORT_CSV["pins"]
    nets_csv = out_dir / _EXPORT_CSV["nets"]

    missing = [
        name
        for name, path in [("Parts", parts_csv), ("Pins", pins_csv), ("Nets", nets_csv)]
        if not path.is_file()
    ]
    if missing:
        raise FileNotFoundError(
            f"Capture 导出后以下 CSV 缺失：{', '.join(missing)}。"
            f"请检查 Tcl 脚本执行是否有报错。目录：{out_dir}"
        )

    log(f"导出完成：{parts_csv.name}, {pins_csv.name}, {nets_csv.name}")
    return parts_csv, pins_csv, nets_csv


def run_dsn_compare_export_sequence(
    dsn1: Path,
    dsn2: Path,
    out_dir1: Path,
    out_dir2: Path,
    *,
    capture_exe: Path | None = None,
    on_log: Callable[[str], None] | None = None,
) -> tuple[dict[str, Path], dict[str, Path]]:
    """
    顺序导出两个 DSN 为 CSV，返回两侧的 (kind→path) 字典。
    """
    clear_export_slot_standard_csvs(out_dir1, out_dir2)

    p1, i1, n1 = export_dsn_to_csvs(
        dsn1, out_dir1, capture_exe=capture_exe, on_log=on_log
    )
    p2, i2, n2 = export_dsn_to_csvs(
        dsn2, out_dir2, capture_exe=capture_exe, on_log=on_log
    )

    return (
        {"parts": p1, "pins": i1, "nets": n1},
        {"parts": p2, "pins": i2, "nets": n2},
    )
