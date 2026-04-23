from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def check_capture_environment() -> None:
    if sys.platform != "win32":
        raise RuntimeError(
            "DSN 对比模式仅支持 Windows 系统。\n"
            f"当前系统: {sys.platform}\n"
            "请改用 EDIF 或 CSV 模式。"
        )


def _win_subprocess_kwargs(*, show_console: bool) -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    kwargs: dict[str, Any] = {}
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 1 if show_console else subprocess.SW_HIDE
    kwargs["startupinfo"] = startup
    if not show_console and hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return kwargs


def resolve_capture_exe(prefs: dict | None = None) -> Path | None:
    env = os.environ.get("SCHCOMPARE_CAPTURE_EXE", "").strip()
    if env:
        path = Path(env)
        if path.is_file():
            return path

    if prefs:
        configured = str(prefs.get("captureExe") or "").strip()
        if configured:
            path = Path(configured)
            if path.is_file():
                return path

    found = shutil.which("capture.exe")
    if found:
        return Path(found)

    if sys.platform == "win32":
        candidates = [
            Path(r"C:\Cadence\SPB_23.1\tools\bin\capture.exe"),
            Path(r"C:\Cadence\SPB_22.1\tools\bin\capture.exe"),
            Path(r"C:\Cadence\SPB_17.4\tools\bin\capture.exe"),
        ]
        cds_root = os.environ.get("CDS_ROOT", "").strip()
        if cds_root:
            candidates.append(Path(cds_root) / "tools" / "bin" / "capture.exe")
        for candidate in candidates:
            if candidate.is_file():
                return candidate
    return None


def is_capture_already_running(capture_exe: Path | None = None) -> bool:
    if sys.platform != "win32":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq capture.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            **_win_subprocess_kwargs(show_console=False),
        )
    except Exception:
        return False
    if "capture.exe" not in result.stdout.lower():
        return False
    return True


def write_capture_debug_tcl(content: str, filename: str = "temp.tcl") -> Path:
    temp_dir = Path(os.environ.get("TEMP") or os.environ.get("TMP") or tempfile.gettempdir())
    temp_dir.mkdir(parents=True, exist_ok=True)
    tcl_path = temp_dir / filename
    tcl_path.write_text((content or "").rstrip() + "\n", encoding="utf-8")
    return tcl_path


def _capture_export_argv(capture_exe: Path, tcl_path: Path, product: str = "") -> list[str]:
    argv = [str(capture_exe.resolve())]
    if product.strip():
        argv.extend(["-product", product.strip()])
    if os.environ.get("SCHCOMPARE_CAPTURE_USE_TCLFILE_ARG", "").strip() == "1":
        argv.extend(["-tclfile", str(tcl_path.resolve())])
    else:
        argv.append(str(tcl_path.resolve()))
    return argv


def _terminate_capture_process(proc: subprocess.Popen[Any], grace_sec: float = 12.0) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=grace_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            pass
    except OSError:
        try:
            proc.kill()
        except OSError:
            pass


def _terminate_process_tree_win(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=25,
            **_win_subprocess_kwargs(show_console=False),
        )
    except Exception:
        _terminate_capture_process(proc)


def run_capture_with_tcl_path(
    capture_exe: Path,
    product: str,
    tcl_path: Path,
    *,
    subprocess_timeout_sec: float = 120.0,
) -> str:
    check_capture_environment()

    argv = _capture_export_argv(capture_exe, tcl_path, product)
    cwd_bin = str(capture_exe.resolve().parent)
    log_fd, log_name = tempfile.mkstemp(suffix=".log", prefix="schcompare_capmsg_")
    os.close(log_fd)
    log_path = Path(log_name)
    proc: subprocess.Popen[Any] | None = None
    try:
        with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
            popen_kwargs: dict[str, Any] = {
                "stdout": log_file,
                "stderr": subprocess.STDOUT,
                "env": os.environ.copy(),
                "cwd": cwd_bin,
            }
            popen_kwargs.update(_win_subprocess_kwargs(show_console=False))
            if sys.platform == "win32":
                comspec = os.environ.get("COMSPEC", "cmd.exe")
                inner = subprocess.list2cmdline(argv)
                popen_kwargs["args"] = [comspec, "/c", inner]
            else:
                popen_kwargs["args"] = argv
            proc = subprocess.Popen(**popen_kwargs)
            try:
                proc.wait(timeout=subprocess_timeout_sec)
            except subprocess.TimeoutExpired:
                if sys.platform == "win32":
                    _terminate_process_tree_win(proc)
                else:
                    _terminate_capture_process(proc)

        output = log_path.read_text(encoding="utf-8", errors="replace")
        exit_code = proc.poll() if proc is not None else None
        if (
            exit_code is not None
            and exit_code != 0
            and os.environ.get("SCHCOMPARE_IGNORE_CAPTURE_EXIT_CODE", "").strip() != "1"
        ):
            tail = (output or "").strip()[-2000:] if (output or "").strip() else "（空）"
            raise RuntimeError(f"capture.exe 退出码 {exit_code}。子进程日志尾部：\n{tail}")
        return output
    finally:
        try:
            log_path.unlink(missing_ok=True)
        except OSError:
            pass


def run_capture_with_tcl(
    capture_exe: Path,
    tcl_content: str,
    *,
    product: str = "",
    timeout_sec: float = 120.0,
) -> str:
    check_capture_environment()
    tcl_path = write_capture_debug_tcl(tcl_content, filename="schcompare_bundle.tcl")
    return run_capture_with_tcl_path(
        capture_exe,
        product,
        tcl_path,
        subprocess_timeout_sec=timeout_sec,
    )
