"""
Capture 子进程管理模块。
负责环境检测、capture.exe 路径解析、Tcl 脚本执行。

⚠️ 仅 Windows 系统可用。非 Windows 调用 check_capture_environment() 会立即报错。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def check_capture_environment() -> None:
    """
    检查当前环境是否支持 DSN 模式。
    非 Windows 系统或未安装 OrCAD Capture 时抛出 RuntimeError。
    """
    if sys.platform != "win32":
        raise RuntimeError(
            "DSN 对比模式仅支持 Windows 系统。\n"
            f"当前系统: {sys.platform}\n"
            "请使用以下替代方案：\n"
            "  1. EDIF 模式：在 Windows 端将 DSN 导出为 EDIF 网表，然后跨平台对比\n"
            "  2. CSV 模式：在 Windows 端通过 Tcl 脚本导出 CSV，然后跨平台对比"
        )


def resolve_capture_exe(prefs: dict | None = None) -> Path | None:
    """
    按优先级查找 capture.exe：
    1. 环境变量 SCHCOMPARE_CAPTURE_EXE
    2. prefs 字典中的 captureExe 键
    3. 系统 PATH
    4. 常见安装目录
    """
    # 1. 环境变量
    env_path = os.environ.get("SCHCOMPARE_CAPTURE_EXE", "").strip()
    if env_path:
        p = Path(env_path)
        if p.is_file():
            return p

    # 2. prefs 配置
    if prefs:
        cfg = str(prefs.get("captureExe", "")).strip()
        if cfg:
            p = Path(cfg)
            if p.is_file():
                return p

    # 3. 系统 PATH
    found = shutil.which("capture.exe")
    if found:
        return Path(found)

    # 4. 常见安装目录（Cadence 17.x / 22.x / 23.x）
    if sys.platform == "win32":
        for base_dir in (
            r"C:\Cadence",
            r"C:\Cadence\SPB_17.4",
            r"C:\Cadence\SPB_22.1",
            os.path.expandvars(r"%CDSROOT%"),
        ):
            candidate = Path(base_dir) / "tools" / "capture" / "capture.exe"
            if candidate.is_file():
                return candidate

    return None


def is_capture_already_running(capture_exe: Path | None = None) -> bool:
    """检查 capture.exe 是否已在运行（仅 Windows）。"""
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq capture.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return "capture.exe" in result.stdout.lower()
    except Exception:
        return False


def write_capture_debug_tcl(content: str, filename: str = "schcompare_bundle.tcl") -> Path:
    """将合并后的 Tcl 脚本内容写入临时文件。"""
    tmp_dir = Path(tempfile.gettempdir()) / "schcompare"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tcl_path = tmp_dir / filename
    tcl_path.write_text(content, encoding="utf-8")
    return tcl_path


def run_capture_with_tcl(
    capture_exe: Path,
    tcl_content: str,
    *,
    timeout_sec: float = 600.0,
) -> str:
    """
    将 Tcl 内容写入临时文件，通过 capture.exe -TCLScript 执行。
    返回 stdout+stderr 的尾部输出。
    """
    check_capture_environment()

    tcl_path = write_capture_debug_tcl(tcl_content)

    cmd = [str(capture_exe), "-TCLScript", str(tcl_path)]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            cwd=str(tcl_path.parent),
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        return output[-2000:]  # 仅保留尾部便于诊断
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"Capture 执行超时（{timeout_sec}s）。"
            "请检查 DSN 文件是否过大或 Capture 是否卡死。"
        )
    except FileNotFoundError:
        raise RuntimeError(f"无法执行 capture.exe：{capture_exe}")


def run_capture_with_tcl_path(
    capture_exe: Path,
    product: str,
    tcl_path: Path,
    *,
    subprocess_timeout_sec: float = 600.0,
) -> str:
    """通过已有 Tcl 文件路径执行 Capture（兼容旧接口）。"""
    check_capture_environment()

    cmd = [str(capture_exe)]
    if product:
        cmd.extend(["-product", product])
    cmd.extend(["-TCLScript", str(tcl_path)])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=subprocess_timeout_sec,
            cwd=str(tcl_path.parent),
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        return output[-2000:]
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Capture 执行超时（{subprocess_timeout_sec}s）")
    except FileNotFoundError:
        raise RuntimeError(f"无法执行 capture.exe：{capture_exe}")
