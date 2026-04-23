"""
图纸多模态差异对比 —— 视觉通道
通道一：PDF → PyMuPDF 渲染为高清图像 → OpenCV 像素级差异热图
通道二：DWG 二进制 → 字符串提取 → 图层/块名/文字内容对比
通道三：多模态语义分析（默认 qwen3-vl-235b-a22b-thinking，接口自动识别：qwen*→chat，gpt-5*→responses）

环境变量要点：
  VLM_MODEL（推荐）/ VL_MODEL / TINNO_CODEX_MODEL — 视觉模型名
  VLM_API_STYLE — auto（推荐）/ responses / chat
  VL_REQUEST_TIMEOUT_SEC / VL_TILE_REQUEST_TIMEOUT_SEC — 视觉请求超时秒数
  VL_TILE_SCAN=1 — 启用分块放大扫描（多请求，利于细线/小字，降幻觉）
  VL_TILE_ROWS / VL_TILE_COLS / VL_TILE_MAX_W / VL_TILE_MARGIN_PX
  PDF_RENDER_DPI — 提高渲染 DPI 相当于「放大」图源
  VL_TILE_PLUS_OVERVIEW=1 — 分块模式下额外跑一次全图概览
"""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path

import cv2
import fitz  # PyMuPDF
import numpy as np

try:
    from .http_client import (
        response_completion_from_payload,
        strip_thinking_tags,
    )
except ImportError:  # pragma: no cover - direct script execution
    from http_client import (
        response_completion_from_payload,
        strip_thinking_tags,
    )

PDF_RENDER_DPI = int(os.getenv("PDF_RENDER_DPI", "220"))
MAX_IMG_WIDTH = int(os.getenv("VL_MAX_IMG_WIDTH", "2048"))
DIFF_THRESH = 15
DIFF_DILATE = 5
VL_REQUEST_TIMEOUT_SEC = max(30.0, float(os.getenv("VL_REQUEST_TIMEOUT_SEC", "240")))
VL_TILE_REQUEST_TIMEOUT_SEC = max(30.0, float(os.getenv("VL_TILE_REQUEST_TIMEOUT_SEC", "180")))


def render_pdf_to_images(pdf_path: Path, dpi: int = PDF_RENDER_DPI) -> list[np.ndarray]:
    """用 PyMuPDF 把 PDF 每页渲染成 BGR ndarray 列表"""
    doc = fitz.open(str(pdf_path))
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    images = []
    for page in doc:
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        images.append(cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    doc.close()
    return images


def resize_to_width(img: np.ndarray, max_w: int) -> np.ndarray:
    h, w = img.shape[:2]
    if w <= max_w:
        return img
    scale = max_w / w
    return cv2.resize(img, (max_w, int(h * scale)), interpolation=cv2.INTER_AREA)


def img_to_base64(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encode failed")
    return base64.b64encode(buf.tobytes()).decode()


def _tile_spans(dim: int, n: int, margin: int) -> list[tuple[int, int]]:
    if n <= 1 or dim <= 0:
        return [(0, dim)]
    step = max(1, dim // n)
    spans: list[tuple[int, int]] = []
    for i in range(n):
        lo = max(0, i * step - margin)
        hi = min(dim, (i + 1) * step + margin) if i < n - 1 else dim
        if hi <= lo:
            hi = min(dim, lo + step)
        spans.append((lo, hi))
    return spans


def _vl_responses_pair(
    base_url: str,
    api_key: str,
    vl_model: str,
    b64_a: str,
    b64_b: str,
    user_text: str,
    *,
    max_tokens: int = 3000,
) -> str:
    payload: dict = {
        "model": vl_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_a}"}},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_b}"}},
                    {"type": "text", "text": user_text},
                ],
            },
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
    }
    return strip_thinking_tags(
        response_completion_from_payload(
            base_url,
            api_key,
            payload,
            timeout=VL_REQUEST_TIMEOUT_SEC,
        )
    )


def compute_visual_diff(
    img_a: np.ndarray,
    img_b: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, dict]:
    h_a, w_a = img_a.shape[:2]
    img_b_r = cv2.resize(img_b, (w_a, h_a), interpolation=cv2.INTER_AREA)

    gray_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(img_b_r, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(gray_a, gray_b)

    _, thresh = cv2.threshold(diff, DIFF_THRESH, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DIFF_DILATE, DIFF_DILATE))
    dilated = cv2.dilate(thresh, kernel)

    diff_pixels = int(np.count_nonzero(thresh))
    total_pixels = gray_a.size
    diff_pct = round(diff_pixels / total_pixels * 100, 2)

    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:20]
    bboxes = [cv2.boundingRect(c) for c in contours]

    heatmap_color = cv2.applyColorMap(cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX), cv2.COLORMAP_JET)

    overlay = img_b_r.copy()
    for x, y, w, h in bboxes:
        cv2.rectangle(overlay, (x, y), (x + w, y + h), (0, 0, 255), 3)
    mask_3ch = cv2.cvtColor(thresh, cv2.COLOR_GRAY2BGR)
    overlay = cv2.addWeighted(overlay, 0.75, mask_3ch, 0.25, 0)

    stats = {
        "diff_pixels": diff_pixels,
        "total_pixels": total_pixels,
        "diff_pct": diff_pct,
        "diff_regions": len(bboxes),
        "largest_region_area": int(cv2.contourArea(contours[0])) if contours else 0,
    }
    return heatmap_color, overlay, stats


def make_side_by_side(img_a: np.ndarray, img_b: np.ndarray, label_a: str, label_b: str) -> np.ndarray:
    h = max(img_a.shape[0], img_b.shape[0])
    def pad(img):
        dh = h - img.shape[0]
        if dh > 0:
            img = cv2.copyMakeBorder(img, 0, dh, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        return img
    combined = cv2.hconcat([pad(img_a), pad(img_b)])
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(combined, label_a, (20, 50), font, 2, (0, 0, 200), 3)
    cv2.putText(combined, label_b, (img_a.shape[1] + 20, 50), font, 2, (0, 120, 0), 3)
    return combined


def extract_dwg_strings(dwg_path: Path, min_len: int = 4) -> dict:
    """从 DWG 二进制中提取可读字符串（图层名、块名、文字内容等）。"""
    with open(dwg_path, "rb") as f:
        data = f.read()

    ascii_pat = re.compile(rb'[\x20-\x7E]{4,}')
    cn_pat = re.compile(rb'[\xB0-\xF7][\xA0-\xFE]{1,30}')

    raw_strings: set[str] = set()

    for m in ascii_pat.finditer(data):
        s = m.group().decode("ascii", errors="ignore").strip()
        if len(s) >= min_len and re.search(r'[A-Za-z\u4e00-\u9fff]', s):
            raw_strings.add(s)

    for m in cn_pat.finditer(data):
        try:
            s = m.group().decode("gb2312", errors="ignore").strip()
            if len(s) >= 2:
                raw_strings.add(s)
        except Exception:
            pass

    try:
        text_utf16 = data.decode("utf-16-le", errors="ignore")
        for m in re.finditer(r'[\u4e00-\u9fff\w]{2,}', text_utf16):
            raw_strings.add(m.group())
    except Exception:
        pass

    layers, text_items, others = [], [], []
    for s in sorted(raw_strings):
        if re.match(r'^[A-Z0-9_\-]{2,20}$', s):
            layers.append(s)
        elif re.search(r'[\u4e00-\u9fff]', s):
            text_items.append(s)
        else:
            others.append(s[:60])

    return {
        "total_strings": len(raw_strings),
        "likely_layers": layers[:40],
        "chinese_text": text_items[:60],
        "file_size_mb": round(dwg_path.stat().st_size / 1024 / 1024, 2),
    }


def diff_dwg_strings(info_a: dict, info_b: dict, label_a: str, label_b: str) -> dict:
    layers_a = set(info_a["likely_layers"])
    layers_b = set(info_b["likely_layers"])
    text_a = set(info_a["chinese_text"])
    text_b = set(info_b["chinese_text"])

    return {
        "label_a": label_a,
        "label_b": label_b,
        "file_size_diff_kb": round((info_b["file_size_mb"] - info_a["file_size_mb"]) * 1024),
        "layers_only_in_a": sorted(layers_a - layers_b)[:20],
        "layers_only_in_b": sorted(layers_b - layers_a)[:20],
        "layers_common": sorted(layers_a & layers_b)[:20],
        "text_only_in_a": sorted(text_a - text_b)[:20],
        "text_only_in_b": sorted(text_b - text_a)[:20],
    }


def empty_dwg_info() -> dict:
    """Stub used when no DWG companion file exists."""
    return {"total_strings": 0, "likely_layers": [], "chinese_text": [], "file_size_mb": 0}


_SYSTEM_PROMPT = """你是一名资深机械结构工程师，专注于 2D 工程图纸（爆炸图）的差异审查。

任务：对比提供的两张工程图纸（图A 和 图B），找出所有可见差异。

请按以下结构输出（中文，专业严谨）：

## 图纸对比分析

### 一、概览
- 两张图的总体相似度评估
- 差异显著程度（微小 / 轻度 / 中等 / 显著）

### 二、结构与几何差异
逐条列出：
- 零件增减（新增或删除的零件/组件）
- 位置/角度变化
- 形状/尺寸变化
- 爆炸方向或距离变化

### 三、标注与文字差异
- 图号/版本号变化
- 零件序号变化
- 尺寸标注变化
- 技术要求文字变化

### 四、图层/线型差异
- 线宽、线型变化
- 视图边框差异

### 五、风险评估
- 哪些差异可能影响生产或装配
- 需要人工重点核查的区域

### 六、综合结论（2-3句话）
"""

_SYSTEM_PROMPT_TILE = """你是机械图纸差异审查助手。当前输入为整图的一小块裁剪（图A、图B 同一矩形区域）。
只描述该局部内肉眼可辨的差异；看不清、不确定时必须写「不确定」或「无法从本块判断」，禁止编造毫米数与零件编号。"""


def _build_aux_context(
    label_a: str,
    label_b: str,
    diff_stats: dict,
    dwg_diff: dict,
) -> str:
    return (
        f"**图A（{label_a}）vs 图B（{label_b}）**\n\n"
        f"像素差异分析：\n"
        f"- 差异像素比例：{diff_stats['diff_pct']}%\n"
        f"- 差异区域数量：{diff_stats['diff_regions']} 个\n"
        f"- 最大差异区域面积：{diff_stats['largest_region_area']} px²\n\n"
        f"DWG 字符串差异：\n"
        f"- 文件大小差异：{dwg_diff['file_size_diff_kb']} KB\n"
        f"- 仅在{label_a}中出现的图层/字符串：{dwg_diff['layers_only_in_a'][:10]}\n"
        f"- 仅在{label_b}中出现的图层/字符串：{dwg_diff['layers_only_in_b'][:10]}\n"
        f"- {label_a}独有中文文字（前10）：{dwg_diff['text_only_in_a'][:10]}\n"
        f"- {label_b}独有中文文字（前10）：{dwg_diff['text_only_in_b'][:10]}\n"
    )


def call_vl_model(
    base_url: str,
    api_key: str,
    vl_model: str,
    img_a: np.ndarray,
    img_b: np.ndarray,
    label_a: str,
    label_b: str,
    diff_stats: dict,
    dwg_diff: dict,
) -> str:
    """多模态差异分析：默认 POST /v1/responses；可选分块放大扫描（VL_TILE_SCAN=1）。"""
    ctx = _build_aux_context(label_a, label_b, diff_stats, dwg_diff)
    h, w = img_a.shape[:2]
    img_b_r = cv2.resize(img_b, (w, h), interpolation=cv2.INTER_AREA)

    tile_on = os.getenv("VL_TILE_SCAN", "0").strip() in ("1", "true", "True", "yes")
    rows = max(1, int(os.getenv("VL_TILE_ROWS", "3")))
    cols = max(1, int(os.getenv("VL_TILE_COLS", "3")))
    margin = max(0, int(os.getenv("VL_TILE_MARGIN_PX", "40")))
    tile_max_w = max(512, int(os.getenv("VL_TILE_MAX_W", "1536")))
    plus_overview = os.getenv("VL_TILE_PLUS_OVERVIEW", "1").strip() in ("1", "true", "True", "yes")

    try:
        if tile_on:
            sections: list[str] = [
                "### 分块扫描说明\n"
                "以下为同一对图纸按网格**裁剪放大**后逐块调用模型得到的结果，用于减轻整图缩小导致的细节丢失与幻觉；"
                "请综合各分块阅读，冲突处以「可见局部」为准。\n",
            ]
            ys = _tile_spans(h, rows, margin)
            xs = _tile_spans(w, cols, margin)
            total = len(ys) * len(xs)
            idx = 0
            for (y1, y2) in ys:
                for (x1, x2) in xs:
                    idx += 1
                    ca = img_a[y1:y2, x1:x2]
                    cb = img_b_r[y1:y2, x1:x2]
                    if ca.size == 0 or cb.size == 0:
                        continue
                    b64_a = img_to_base64(resize_to_width(ca, tile_max_w))
                    b64_b = img_to_base64(resize_to_width(cb, tile_max_w))
                    user_t = (
                        f"分块 **{idx}/{total}**：裁剪像素范围 x=[{x1},{x2}) y=[{y1},{y2})，全图 {w}×{h}。\n"
                        f"图A=【{label_a}】图B=【{label_b}】。仅写本块内可见差异；禁止臆造尺寸。\n"
                        f"全图差异像素比例约 {diff_stats['diff_pct']}%。\n"
                    )
                    try:
                        seg = _vl_responses_pair_tile(base_url, api_key, vl_model, b64_a, b64_b, user_t)
                    except Exception as ex:
                        seg = f"（本块 API 失败：{ex}）"
                    sections.append(f"### 分块 {idx}/{total}\n{seg}")

            if plus_overview:
                b64_a0 = img_to_base64(resize_to_width(img_a, MAX_IMG_WIDTH))
                b64_b0 = img_to_base64(resize_to_width(img_b_r, MAX_IMG_WIDTH))
                overview_t = (
                    f"【{label_a}】与【{label_b}】组件爆炸图**全图缩小**概览。\n"
                    "请用 3～6 句中文概括整体差异印象，并说明与局部分块的关系（哪些需在分块中核对）。\n\n"
                    f"辅助数据：\n{ctx}\n"
                    "请详细分析这两张工程图纸的主要差异。"
                )
                try:
                    overview = _vl_responses_pair(base_url, api_key, vl_model, b64_a0, b64_b0, overview_t, max_tokens=2000)
                    sections.insert(1, f"### 全图概览\n{overview}")
                except Exception as ex:
                    sections.insert(1, f"### 全图概览\n（调用失败：{ex}）")

            return "\n\n".join(sections)

        b64_a = img_to_base64(resize_to_width(img_a, MAX_IMG_WIDTH))
        b64_b = img_to_base64(resize_to_width(img_b_r, MAX_IMG_WIDTH))
        user_main = (
            f"上方第一张图是【{label_a}】组件爆炸图，"
            f"第二张图是【{label_b}】组件爆炸图。\n\n"
            f"辅助数据（供参考）：\n{ctx}\n\n"
            "请详细分析这两张工程图纸的所有差异；不确定处请明确写出，勿编造。"
        )
        return _vl_responses_pair(base_url, api_key, vl_model, b64_a, b64_b, user_main, max_tokens=3000)
    except Exception as e:
        return (
            f"VLM 调用失败：{e}\n\n"
            f"（像素差异：{diff_stats['diff_pct']}%，差异区域：{diff_stats['diff_regions']} 个）"
        )


def _vl_responses_pair_tile(
    base_url: str,
    api_key: str,
    vl_model: str,
    b64_a: str,
    b64_b: str,
    user_text: str,
) -> str:
    payload: dict = {
        "model": vl_model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT_TILE},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_a}"}},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_b}"}},
                    {"type": "text", "text": user_text},
                ],
            },
        ],
        "temperature": 0.1,
        "max_tokens": min(2000, int(os.getenv("VL_TILE_MAX_TOKENS", "1200"))),
    }
    return strip_thinking_tags(
        response_completion_from_payload(
            base_url,
            api_key,
            payload,
            timeout=VL_TILE_REQUEST_TIMEOUT_SEC,
        )
    )
