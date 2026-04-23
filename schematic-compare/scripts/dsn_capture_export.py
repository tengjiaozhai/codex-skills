from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable

from .capture_runner import (
    check_capture_environment,
    resolve_capture_exe,
    run_capture_with_tcl_path,
    write_capture_debug_tcl,
)

_EXPORT_CSV = {
    "parts": "Parts_Properties.csv",
    "pins": "Pins_Info.csv",
    "nets": "Nets_Info.csv",
}


def tcl_quoted_string(text: str) -> str:
    value = str(text)
    for old, new in (
        ("\\", "\\\\"),
        ('"', '\\"'),
        ("$", "\\$"),
        ("[", "\\["),
        ("]", "\\]"),
    ):
        value = value.replace(old, new)
    return '"' + value + '"'


def tcl_quoted_path(path: Path) -> str:
    return tcl_quoted_string(path.resolve().as_posix())


def discover_export_csv_bundle(folder: Path) -> tuple[dict[str, Path], list[str]]:
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        return {}, [f"目录不存在或不是文件夹：{folder}"]
    files = {item.name.casefold(): item for item in folder.iterdir() if item.is_file()}
    bundle: dict[str, Path] = {}
    missing: list[str] = []
    for kind, filename in _EXPORT_CSV.items():
        found = files.get(filename.casefold())
        if found is None:
            missing.append(filename)
        else:
            bundle[kind] = found.resolve()
    return bundle, missing


def clear_export_slot_standard_csvs(*folders: Path) -> None:
    targets = {name.casefold() for name in _EXPORT_CSV.values()}
    for folder in folders:
        try:
            if not folder.is_dir():
                continue
            for item in folder.iterdir():
                if item.is_file() and item.name.casefold() in targets:
                    try:
                        item.unlink()
                    except OSError:
                        pass
        except OSError:
            pass


def _bundle_paths(folder: Path) -> tuple[Path, Path, Path]:
    return (
        folder / _EXPORT_CSV["parts"],
        folder / _EXPORT_CSV["pins"],
        folder / _EXPORT_CSV["nets"],
    )


def wait_for_export_csv_paths(
    paths: list[Path],
    *,
    timeout_sec: float = 45.0,
    poll_interval_sec: float = 0.1,
    min_bytes: int = 8,
) -> str | None:
    deadline = time.monotonic() + max(5.0, float(timeout_sec))
    stable_sleep = max(0.05, min(3.0, float(os.environ.get("SCHCOMPARE_EXPORT_CSV_STABLE_SLEEP_SEC", "0.3"))))
    last_error = ""

    def snapshot() -> tuple[int, ...] | None:
        sizes: list[int] = []
        for path in paths:
            try:
                if not path.is_file():
                    return None
                size = path.stat().st_size
                if size < min_bytes:
                    return None
                sizes.append(size)
            except OSError:
                return None
        return tuple(sizes)

    while time.monotonic() < deadline:
        missing_bits: list[str] = []
        ready = True
        for path in paths:
            try:
                if not path.is_file():
                    missing_bits.append(f"{path}: 尚未创建")
                    ready = False
                    continue
                size = path.stat().st_size
                if size < min_bytes:
                    missing_bits.append(f"{path}: 仅 {size} bytes")
                    ready = False
            except OSError as exc:
                missing_bits.append(f"{path}: {exc}")
                ready = False
        if ready:
            snap_a = snapshot()
            time.sleep(stable_sleep)
            snap_b = snapshot()
            if snap_a is not None and snap_a == snap_b:
                return None
            ready = False
            missing_bits = ["CSV 仍在写入，体积尚未稳定"]
        last_error = "\n".join(missing_bits)
        time.sleep(poll_interval_sec)

    report = [f"在 {timeout_sec:.0f}s 内未等到全部 CSV 就绪。", last_error or "（无）"]
    for path in paths:
        try:
            if path.is_file():
                report.append(f"{path}: {path.stat().st_size} bytes")
            else:
                report.append(f"{path}: 不存在")
        except OSError as exc:
            report.append(f"{path}: {exc}")
    return "\n".join(report)


def _build_export_bundle_tcl(entries: list[tuple[Path, Path]]) -> str:
    tcl_dir = Path(__file__).parent / "tcl"
    cap_export_tcl = tcl_dir / "capExportAllInfo.tcl"
    cap_find_tcl = tcl_dir / "capFind.tcl"
    if not cap_export_tcl.is_file():
        raise FileNotFoundError(f"缺少 Tcl 导出脚本：{cap_export_tcl}")
    if not cap_find_tcl.is_file():
        raise FileNotFoundError(f"缺少 Tcl 定位脚本：{cap_find_tcl}")

    lines = [
        f"source {tcl_quoted_path(cap_export_tcl)}",
        f"source {tcl_quoted_path(cap_find_tcl)}",
    ]
    for dsn_path, out_dir in entries:
        lines.append(f"exportDsnCsv {tcl_quoted_path(dsn_path)} {tcl_quoted_path(out_dir)}")
    return "\n".join(lines) + "\n"


def export_dsn_to_csvs(
    dsn_path: Path,
    out_dir: Path,
    *,
    capture_exe: Path | None = None,
    on_log: Callable[[str], None] | None = None,
) -> tuple[Path, Path, Path]:
    def log(message: str) -> None:
        if on_log:
            on_log(message)

    check_capture_environment()
    capture_exe = capture_exe or resolve_capture_exe()
    if capture_exe is None:
        raise RuntimeError("未找到 capture.exe，请设置 SCHCOMPARE_CAPTURE_EXE 或在 PATH 中配置。")
    if not dsn_path.is_file():
        raise FileNotFoundError(f"DSN 文件不存在：{dsn_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    clear_export_slot_standard_csvs(out_dir)

    tcl_path = write_capture_debug_tcl(
        _build_export_bundle_tcl([(dsn_path, out_dir)]),
        filename="schcompare_dsn_single_bundle.tcl",
    )
    log(f"调用 Capture 导出：{dsn_path.name} → {out_dir}")
    run_capture_with_tcl_path(
        capture_exe,
        os.environ.get("SCHCOMPARE_CAPTURE_PRODUCT", "").strip(),
        tcl_path,
        subprocess_timeout_sec=120.0,
    )

    parts_csv, pins_csv, nets_csv = _bundle_paths(out_dir)
    wait_err = wait_for_export_csv_paths([parts_csv, pins_csv, nets_csv])
    if wait_err:
        raise FileNotFoundError(wait_err)
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
    def log(message: str) -> None:
        if on_log:
            on_log(message)

    check_capture_environment()
    capture_exe = capture_exe or resolve_capture_exe()
    if capture_exe is None:
        raise RuntimeError("未找到 capture.exe，请设置 SCHCOMPARE_CAPTURE_EXE 或在 PATH 中配置。")
    if not dsn1.is_file():
        raise FileNotFoundError(f"DSN 1 文件不存在：{dsn1}")
    if not dsn2.is_file():
        raise FileNotFoundError(f"DSN 2 文件不存在：{dsn2}")

    out_dir1.mkdir(parents=True, exist_ok=True)
    out_dir2.mkdir(parents=True, exist_ok=True)
    clear_export_slot_standard_csvs(out_dir1, out_dir2)

    tcl_path = write_capture_debug_tcl(
        _build_export_bundle_tcl([(dsn1, out_dir1), (dsn2, out_dir2)]),
        filename="schcompare_dsn_compare_bundle.tcl",
    )
    log(f"调用 Capture 合并导出：{dsn1.name}, {dsn2.name}")
    run_capture_with_tcl_path(
        capture_exe,
        os.environ.get("SCHCOMPARE_CAPTURE_PRODUCT", "").strip(),
        tcl_path,
        subprocess_timeout_sec=180.0,
    )

    bundle1 = _bundle_paths(out_dir1)
    bundle2 = _bundle_paths(out_dir2)
    wait_err = wait_for_export_csv_paths([*bundle1, *bundle2])
    if wait_err:
        raise FileNotFoundError(wait_err)

    return (
        {"parts": bundle1[0], "pins": bundle1[1], "nets": bundle1[2]},
        {"parts": bundle2[0], "pins": bundle2[1], "nets": bundle2[2]},
    )
