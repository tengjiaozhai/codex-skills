#!/usr/bin/env python3
"""pdf-drawing-diff skill CLI: pairwise diff for N >= 2 PDF drawings."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SKILL_DIR = THIS_DIR.parent
sys.path.insert(0, str(THIS_DIR))


def _maybe_load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        return
    for candidate in (Path.cwd() / ".env", SKILL_DIR / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)


def _parse_label_pair(spec: str, *, flag_name: str) -> tuple[str, Path]:
    if "=" not in spec:
        raise argparse.ArgumentTypeError(
            f"{flag_name} 参数格式应为 LABEL=PATH，收到：{spec!r}"
        )
    label, raw_path = spec.split("=", 1)
    label = label.strip()
    if not label:
        raise argparse.ArgumentTypeError(f"{flag_name} 缺少 LABEL：{spec!r}")
    path = Path(raw_path.strip()).expanduser().resolve()
    if not path.is_file():
        raise argparse.ArgumentTypeError(f"路径不存在：{path}")
    return label, path


def _auto_label(path: Path, used: set[str]) -> str:
    base = path.stem
    if base.endswith("-Model"):
        base = base[: -len("-Model")]
    elif base.endswith("_Model"):
        base = base[: -len("_Model")]
    label = base or "doc"
    suffix = 2
    final = label
    while final in used:
        final = f"{label}_{suffix}"
        suffix += 1
    used.add(final)
    return final


def _build_documents(args: argparse.Namespace) -> list[tuple[str, Path]]:
    used_labels: set[str] = set()
    documents: list[tuple[str, Path]] = []

    for spec in args.label or []:
        label, path = _parse_label_pair(spec, flag_name="--label")
        if label in used_labels:
            raise SystemExit(f"重复的 label：{label}")
        used_labels.add(label)
        documents.append((label, path))

    for raw in args.pdf or []:
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            raise SystemExit(f"PDF 不存在：{path}")
        label = _auto_label(path, used_labels)
        documents.append((label, path))

    if len(documents) < 2:
        raise SystemExit("至少需要 2 个 PDF（通过 --pdf 或 --label LABEL=PATH 指定）。")
    return documents


def _build_dwg_overrides(args: argparse.Namespace, doc_labels: set[str]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for spec in args.dwg or []:
        label, path = _parse_label_pair(spec, flag_name="--dwg")
        if label not in doc_labels:
            raise SystemExit(f"--dwg 引用了未知 label：{label}")
        out[label] = path
    return out


def _resolve_str(arg_val: str | None, env_keys: tuple[str, ...], default: str = "") -> str:
    if arg_val:
        return arg_val.strip()
    for key in env_keys:
        v = os.getenv(key, "").strip()
        if v:
            return v
    return default


def main() -> int:
    parser = argparse.ArgumentParser(
        description="pdf-drawing-diff: pairwise multi-modal diff for N >= 2 PDF drawings",
    )
    parser.add_argument(
        "--pdf",
        action="append",
        default=[],
        help="PDF 路径（自动从 stem 取 label，可重复传入）",
    )
    parser.add_argument(
        "--label",
        action="append",
        default=[],
        help="LABEL=PATH 形式显式命名 PDF（可重复传入）",
    )
    parser.add_argument(
        "--dwg",
        action="append",
        default=[],
        help="LABEL=PATH 形式显式指定某个 PDF 对应的 DWG（可重复传入；不指定则按 PDF 同名自动发现）",
    )
    parser.add_argument("--output-dir", type=Path, default=None, help="输出根目录（默认 ./reports/output）")
    parser.add_argument("--ocr-model", type=str, default=None, help="覆盖 GLM_OCR_MODEL")
    parser.add_argument("--vlm-model", type=str, default=None, help="覆盖 VLM_MODEL")
    parser.add_argument("--text-model", type=str, default=None, help="覆盖 TEXT_MODEL")
    parser.add_argument("--vlm-api-style", type=str, default=None, help="VLM_API_STYLE：auto/responses/chat")
    parser.add_argument("--dpi", type=int, default=None, help="渲染 DPI（默认 220）")
    parser.add_argument("--max-pages", type=int, default=None, help="每个 PDF 处理的最大页数（默认 1）")
    parser.add_argument("--ocr-timeout", type=float, default=None, help="OCR 超时秒数")
    parser.add_argument("--vlm-timeout", type=float, default=None, help="VLM grounding 超时秒数")
    parser.add_argument("--openai-base-url", type=str, default=None, help="覆盖 OPENAI_BASE_URL")
    parser.add_argument("--openai-api-key", type=str, default=None, help="覆盖 OPENAI_API_KEY")
    parser.add_argument("--zai-api-key", type=str, default=None, help="覆盖 ZAI_API_KEY")
    args = parser.parse_args()

    _maybe_load_dotenv()

    documents = _build_documents(args)
    dwg_overrides = _build_dwg_overrides(args, {label for label, _ in documents})

    base_url = _resolve_str(args.openai_base_url, ("OPENAI_BASE_URL", "TINNO_OPENAI_BASE_URL"))
    api_key = _resolve_str(args.openai_api_key, ("OPENAI_API_KEY", "TINNO_OPENAI_API_KEY"))
    if not base_url or not api_key:
        raise SystemExit(
            "缺少 OPENAI_BASE_URL / OPENAI_API_KEY，请通过 .env、CLI 参数或环境变量提供。"
        )

    vl_model = _resolve_str(args.vlm_model, ("VLM_MODEL", "VL_MODEL"), default="qwen3-vl-235b-a22b-thinking")
    text_model = _resolve_str(args.text_model, ("TEXT_MODEL",), default="gpt-4.1")
    ocr_model = _resolve_str(args.ocr_model, ("GLM_OCR_MODEL",), default="glm-ocr")
    vl_api_style = _resolve_str(args.vlm_api_style, ("VLM_API_STYLE", "VL_BACKEND"), default="auto")
    zai_api_key = _resolve_str(args.zai_api_key, ("ZAI_API_KEY", "ZHIPUAI_API_KEY"))

    output_dir = args.output_dir if args.output_dir is not None else Path(os.getenv("REPORT_DIR", "./reports/output"))
    output_dir = Path(output_dir).expanduser().resolve()

    dpi = args.dpi if args.dpi is not None else int(os.getenv("PDF_RENDER_DPI", "220"))
    max_pages = args.max_pages if args.max_pages is not None else 1
    ocr_timeout = args.ocr_timeout if args.ocr_timeout is not None else float(os.getenv("GLM_OCR_TIMEOUT_SEC", "180"))
    vlm_timeout = args.vlm_timeout if args.vlm_timeout is not None else float(os.getenv("VL_REQUEST_TIMEOUT_SEC", "240"))

    # The vlm module reads PDF_RENDER_DPI / VL_* env vars at import time.
    # Make sure CLI overrides reach it via env so downstream calls stay consistent.
    if args.dpi is not None:
        os.environ["PDF_RENDER_DPI"] = str(dpi)

    from pipeline import PipelineConfig, run_pipeline  # type: ignore

    cfg = PipelineConfig(
        base_url=base_url,
        api_key=api_key,
        vl_model=vl_model,
        text_model=text_model,
        ocr_model=ocr_model,
        vl_api_style=vl_api_style,
        output_dir=output_dir,
        dpi=dpi,
        max_pages=max_pages,
        ocr_timeout=ocr_timeout,
        vlm_timeout=vlm_timeout,
        zai_api_key=zai_api_key,
    )

    summary = run_pipeline(cfg, documents=documents, dwg_overrides=dwg_overrides)
    print("\n=== pdf-drawing-diff 完成 ===")
    print(f"run_id           : {summary['run_id']}")
    print(f"run_dir          : {summary['run_dir']}")
    print(f"pipeline_result  : {summary['json']}")
    print(f"pipeline_pdf     : {summary['pdf']}")
    print(f"report.md        : {summary['report']}")
    print(f"pairs_processed  : {summary['pairs_processed']} / {summary['pair_count_total']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
