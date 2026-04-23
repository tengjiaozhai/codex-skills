#!/usr/bin/env python3
"""
SchCompare Skill 统一命令行入口。
支持 DSN、CSV、EDIF 三种格式的对比，并内置跨平台环境感知。

用法：
    python -m scripts.schcompare_cli edif old.edf new.edf [-o report.md]
    python -m scripts.schcompare_cli csv  dir_v1 dir_v2  [-o report.xlsx]
    python -m scripts.schcompare_cli dsn  old.dsn new.dsn [-o report.xlsx]
    python -m scripts.schcompare_cli check-env
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from . import edif_import
from . import csv_diff
from .export_report import export_markdown, export_excel
from .models import DiffRow


def _check_env() -> None:
    """环境探针：报告当前系统对三种模式的支持情况。"""
    import platform

    print("--- SchCompare Skill 环境探针 ---")
    print(f"操作系统: {platform.system()} ({platform.release()})")
    print(f"Python 版本: {sys.version.split()[0]}")
    print()
    print("--- 模式可用性分析 ---")
    print("✅ EDIF 模式: 支持 (跨平台，零依赖)")
    print("✅ CSV 模式: 支持 (跨平台，零依赖)")

    if sys.platform == "win32":
        from .capture_runner import resolve_capture_exe

        cap = resolve_capture_exe()
        if cap:
            print(f"✅ DSN 模式: 支持 (capture.exe = {cap})")
        else:
            print("⚠️  DSN 模式: 系统支持但未找到 capture.exe")
    else:
        print("❌ DSN 模式: 不支持 (非 Windows 系统)")

    print()
    if sys.platform != "win32":
        print(
            "💡 建议：当前环境为 Mac/Linux，请使用 OrCAD 导出为 EDIF 网表或 CSV 后再对比。"
        )
    else:
        print("💡 建议：系统原生支持 DSN 模式，可直接对比 .dsn 文件。")


def _run_compare(
    mode: str, path1: Path, path2: Path, output: Path | None
) -> list[DiffRow]:
    """执行对比，返回差异列表。"""
    print(f"正在启动对比，模式: {mode}")
    print(f"旧版本: {path1}")
    print(f"新版本: {path2}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        dir1, dir2 = tmp / "v1", tmp / "v2"
        dir1.mkdir()
        dir2.mkdir()

        if mode == "dsn":
            from .dsn_capture_export import run_dsn_compare_export_sequence

            print("校验 Windows/OrCAD 环境...")
            try:
                out1, out2 = run_dsn_compare_export_sequence(
                    path1, path2, dir1, dir2, on_log=lambda m: print(f"  {m}")
                )
                p1, i1, n1 = out1["parts"], out1["pins"], out1["nets"]
                p2, i2, n2 = out2["parts"], out2["pins"], out2["nets"]
            except Exception as e:
                print(f"❌ 环境校验失败或执行异常: {e}")
                print("提示：请先导出为 EDIF 或 CSV 再进行对比。")
                sys.exit(1)

        elif mode == "edif":
            print("解析 EDIF 网表...")
            out1, out2 = edif_import.import_edif_pair_to_dirs(
                path1, path2, dir1, dir2
            )
            p1, i1, n1 = out1["parts"], out1["pins"], out1["nets"]
            p2, i2, n2 = out2["parts"], out2["pins"], out2["nets"]

        elif mode == "csv":
            print("CSV 模式：假设输入为包含三张标准表的目录...")
            p1 = path1 / "Parts_Properties.csv"
            i1 = path1 / "Pins_Info.csv"
            n1 = path1 / "Nets_Info.csv"
            p2 = path2 / "Parts_Properties.csv"
            i2 = path2 / "Pins_Info.csv"
            n2 = path2 / "Nets_Info.csv"

        else:
            print(f"未知模式: {mode}")
            sys.exit(1)

        print("\n--- 正在执行对比算法 ---")
        prefs = csv_diff.build_default_compare_prefs(
            p1, p2, i1, i2, n1, n2, mode=mode
        )
        results, err = csv_diff.compare_all_dsn_csvs_from_prefs(prefs)
        if err:
            print(f"❌ 对比失败: {err}")
            sys.exit(1)

    print(f"\n--- 对比完成，共发现 {len(results)} 处差异 ---\n")

    # 控制台输出摘要
    for row in results:
        print(f"  [{row.category}] {row.change_type} | {row.object_id} | {row.detail}")

    # 导出报告
    if output:
        meta = {
            "oldPath": str(path1),
            "newPath": str(path2),
            "mode": mode,
            "selectedProps": [
                "Description",
                "ISNC",
                "PCB Footprint",
                "Part Number",
                "Power",
                "Tolerance",
                "Value",
                "Vendor",
                "Vendor_PN",
                "Voltage",
            ],
        }
        suffix = output.suffix.lower()
        if suffix == ".xlsx":
            export_excel(output, results, meta)
            print(f"\n📊 Excel 报告已导出: {output}")
        elif suffix in (".md", ".markdown"):
            export_markdown(output, results, meta)
            print(f"\n📝 Markdown 报告已导出: {output}")
        else:
            export_markdown(output, results, meta)
            print(f"\n📝 报告已导出 (Markdown): {output}")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="原理图差异对比工具 (SchCompare Skill)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  %(prog)s check-env
  %(prog)s edif old.edf new.edf
  %(prog)s edif old.edf new.edf -o diff_report.md
  %(prog)s csv  ./export/v1 ./export/v2 -o diff_report.xlsx
  %(prog)s dsn  old.dsn new.dsn -o diff_report.xlsx
""",
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # check-env 子命令
    sub.add_parser("check-env", help="检查当前环境对各模式的支持情况")

    # compare 子命令（直接作为 positional mode）
    for mode_name in ("dsn", "csv", "edif"):
        sp = sub.add_parser(mode_name, help=f"{mode_name.upper()} 模式对比")
        sp.add_argument("old_path", type=Path, help="旧版本路径")
        sp.add_argument("new_path", type=Path, help="新版本路径")
        sp.add_argument(
            "-o", "--output", type=Path, default=None, help="输出报告路径 (.md/.xlsx)"
        )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "check-env":
        _check_env()
        return

    if not args.old_path.exists():
        print(f"错误: 找不到旧版本文件 {args.old_path}")
        sys.exit(1)
    if not args.new_path.exists():
        print(f"错误: 找不到新版本文件 {args.new_path}")
        sys.exit(1)

    _run_compare(args.command, args.old_path, args.new_path, args.output)


if __name__ == "__main__":
    main()
