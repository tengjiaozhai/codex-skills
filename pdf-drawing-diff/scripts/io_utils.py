"""
流水线导出：中文字体检测、Pillow 绘制标注、多页 PDF、旧产物清理。
"""
from __future__ import annotations

import io
import shutil
from pathlib import Path

import cv2
import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont


def find_cjk_font() -> Path | None:
    candidates = [
        Path("/System/Library/Fonts/PingFang.ttc"),
        Path("/System/Library/Fonts/STHeiti Light.ttc"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
        Path("C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = find_cjk_font()
    if path is None:
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(str(path), size=size)
    except OSError:
        return ImageFont.load_default()


def bbox_2d_to_xyxy(b2d: list, w: int, h: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = int(b2d[0]), int(b2d[1]), int(b2d[2]), int(b2d[3])
    return (
        int(x1 / 1000 * w),
        int(y1 / 1000 * h),
        int(x2 / 1000 * w),
        int(y2 / 1000 * h),
    )


def draw_grounding_boxes_cjk(
    img_bgr: np.ndarray,
    items: list[dict],
    *,
    font_scale: float | None = None,
) -> np.ndarray:
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    draw = ImageDraw.Draw(pil)
    h, w = img_bgr.shape[:2]
    fs = int(font_scale) if font_scale else max(18, min(36, w // 55))
    font = _load_font(fs)
    colors = [
        (255, 0, 0),
        (255, 140, 0),
        (200, 0, 200),
        (0, 128, 0),
        (0, 100, 255),
    ]
    lw = max(2, w // 500)
    for i, it in enumerate(items):
        if not isinstance(it, dict) or "bbox_2d" not in it:
            continue
        b2d = it["bbox_2d"]
        if not isinstance(b2d, (list, tuple)) or len(b2d) < 4:
            continue
        x1, y1, x2, y2 = bbox_2d_to_xyxy(list(b2d), w, h)
        color = colors[i % len(colors)]
        for t in range(lw):
            draw.rectangle([x1 - t, y1 - t, x2 + t, y2 + t], outline=color)
        lab = str(it.get("label", ""))[:80]
        if lab:
            ty = max(2, y1 - fs - 4)
            draw.text((x1 + 4, ty), lab, fill=color, font=font)
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def cleanup_previous_pipeline_runs(output_dir: Path, keep_name: str | None = None) -> None:
    if not output_dir.is_dir():
        return
    for p in sorted(output_dir.glob("pipeline_run_*")):
        if not p.is_dir():
            continue
        if keep_name and p.name == keep_name:
            continue
        shutil.rmtree(p, ignore_errors=True)


def cleanup_legacy_pipeline_files(output_dir: Path) -> None:
    if not output_dir.is_dir():
        return
    for pattern in (
        "pipeline_grounding_*.png",
        "图纸差异综合流水线报告_*.md",
        "图纸差异对比报告_*.md",
        "图纸差异比对*.md",
        "compare_*.png",
        "overlay_*.png",
        "pipeline_result_*.json",
        "pipeline_annotated_*.pdf",
    ):
        for f in output_dir.glob(pattern):
            if f.is_file():
                f.unlink(missing_ok=True)


def _insert_png_page_a4(doc: fitz.Document, png_path: Path) -> None:
    pw, ph = 595, 842
    page = doc.new_page(width=pw, height=ph)
    margin = 28
    avail_w, avail_h = pw - 2 * margin, ph - 2 * margin
    im = Image.open(png_path).convert("RGB")
    im.thumbnail((avail_w, avail_h), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    data = buf.getvalue()
    nw, nh = im.size
    x0 = (pw - nw) // 2
    y0 = (ph - nh) // 2
    page.insert_image(fitz.Rect(x0, y0, x0 + nw, y0 + nh), stream=data)


def build_pipeline_pdf(
    out_pdf: Path,
    title_lines: list[str],
    pair_pages: list[tuple[str, str, Path, Path]],
    *,
    font_path: Path | None = None,
) -> None:
    """
    生成多页 PDF：封面文字 + 每组 1 页说明 + 2 页高清图（A、B 各一页）。
    pair_pages: (label_a, label_b, path_png_a, path_png_b)
    """
    doc = fitz.open()
    fp = font_path or find_cjk_font()
    fontname = "helv"
    p0 = doc.new_page(width=595, height=842)
    if fp and fp.exists():
        try:
            p0.insert_font(fontname="zh", fontfile=str(fp))
            fontname = "zh"
        except Exception:
            fontname = "helv"
    cover = "\n".join(title_lines[:80])
    try:
        p0.insert_textbox(fitz.Rect(48, 48, 547, 790), cover, fontname=fontname, fontsize=10)
    except Exception:
        p0.insert_text((72, 72), "pdf-drawing-diff pipeline export", fontname="helv", fontsize=12)

    for la, lb, pa, pb in pair_pages:
        if not pa.exists() or not pb.exists():
            continue
        sec = doc.new_page(width=595, height=842)
        cap = f"对比组：{la}  vs  {lb}\n以下两页依次为 [{la}] 、[{lb}] 的差异标注图（高清）。"
        try:
            sec.insert_textbox(fitz.Rect(48, 72, 547, 200), cap, fontname=fontname, fontsize=11)
        except Exception:
            sec.insert_text((72, 72), f"{la} vs {lb}", fontname="helv", fontsize=12)
        _insert_png_page_a4(doc, pa)
        _insert_png_page_a4(doc, pb)

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_pdf))
    doc.close()
