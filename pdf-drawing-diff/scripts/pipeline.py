"""图纸差异综合流水线（VLM 视觉差异 + OCR 文字差异）。

支持任意数量（N >= 2）PDF 输入，自动生成全部成对组合。
不再依赖任何硬编码的 DRAWINGS / PAIRS。
"""
from __future__ import annotations

import ast
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from rich.console import Console
from rich.panel import Panel

try:
    from . import vlm as cvl
    from .http_client import (
        chat_completion_text,
        response_completion_from_payload,
        strip_thinking_tags,
    )
    from .io_utils import build_pipeline_pdf, draw_grounding_boxes_cjk
    from .ocr import (
        DEFAULT_MODEL as DEFAULT_OCR_MODEL,
        DEFAULT_TIMEOUT as DEFAULT_OCR_TIMEOUT,
        OCRPage,
        build_mask_from_boxes,
        build_static_three_way_ocr_summary,
        build_three_way_ocr_messages,
        collect_hint_items_from_ocr_page,
        collect_ocr_block_boxes,
        compare_ocr_documents,
        create_zhipu_client,
        extract_roi_text_from_ocr_page,
        normalize_label,
        prepare_ocr_documents,
        resolve_api_key,
    )
except ImportError:  # pragma: no cover - direct script execution
    import vlm as cvl  # type: ignore
    from http_client import (  # type: ignore
        chat_completion_text,
        response_completion_from_payload,
        strip_thinking_tags,
    )
    from io_utils import build_pipeline_pdf, draw_grounding_boxes_cjk  # type: ignore
    from ocr import (  # type: ignore
        DEFAULT_MODEL as DEFAULT_OCR_MODEL,
        DEFAULT_TIMEOUT as DEFAULT_OCR_TIMEOUT,
        OCRPage,
        build_mask_from_boxes,
        build_static_three_way_ocr_summary,
        build_three_way_ocr_messages,
        collect_hint_items_from_ocr_page,
        collect_ocr_block_boxes,
        compare_ocr_documents,
        create_zhipu_client,
        extract_roi_text_from_ocr_page,
        normalize_label,
        prepare_ocr_documents,
        resolve_api_key,
    )

console = Console()


# ---------- 配置：保留与原工程一致的环境变量入口 ----------

DIFF_THRESH = 15
DIFF_DILATE = 5
PROX_PX = 120
MAX_GROUND_W = int(os.environ.get("VLM_GROUND_MAX_W", "2400"))
TEXT_MASK_PAD = max(0, int(os.environ.get("TEXT_MASK_PAD", "8")))
GEOM_ROI_MIN_AREA_PX = max(16, int(os.environ.get("GEOM_ROI_MIN_AREA_PX", "260")))
GEOM_ROI_MAX_AREA_RATIO = float(os.environ.get("GEOM_ROI_MAX_AREA_RATIO", "0.22"))
GEOM_ROI_MAX_COUNT = max(4, int(os.environ.get("GEOM_ROI_MAX_COUNT", "14")))
GROUND_TEXT_OVERLAP_DROP = float(os.environ.get("GROUND_TEXT_OVERLAP_DROP", "0.60"))
GROUND_MIN_BOX_SIDE_NORM = max(1, int(os.environ.get("GROUND_MIN_BOX_SIDE_NORM", "4")))
GROUND_MIN_BOX_AREA_NORM = max(4, int(os.environ.get("GROUND_MIN_BOX_AREA_NORM", "64")))
GROUND_FALLBACK_GEOM_BOXES = max(0, int(os.environ.get("GROUND_FALLBACK_GEOM_BOXES", "4")))
CALLOUT_DENSE_RADIUS_PX = max(40, int(os.environ.get("CALLOUT_DENSE_RADIUS_PX", "150")))
CALLOUT_DENSE_TEXT_LIMIT = max(4, int(os.environ.get("CALLOUT_DENSE_TEXT_LIMIT", "14")))
CALLOUT_LINE_SCAN_MAX_W = max(1024, int(os.environ.get("CALLOUT_LINE_SCAN_MAX_W", "2200")))
CALLOUT_LINE_NEAR_DIST_PX = max(8, int(os.environ.get("CALLOUT_LINE_NEAR_DIST_PX", "46")))
CALLOUT_LINE_MIN_FAR_DIST_PX = max(24, int(os.environ.get("CALLOUT_LINE_MIN_FAR_DIST_PX", "70")))
CALLOUT_ROI_HALF_SIZE = max(28, int(os.environ.get("CALLOUT_ROI_HALF_SIZE", "95")))
CALLOUT_MAX_ROIS = max(2, int(os.environ.get("CALLOUT_MAX_ROIS", "10")))
CALLOUT_CANDIDATE_LIMIT = max(8, int(os.environ.get("CALLOUT_CANDIDATE_LIMIT", "30")))
CALLOUT_PAIR_TOP_K = max(2, int(os.environ.get("CALLOUT_PAIR_TOP_K", "12")))
CALLOUT_PAIR_DIFF_MIN = float(os.environ.get("CALLOUT_PAIR_DIFF_MIN", "0.014"))
CALLOUT_PAIR_MIN_KEEP = max(1, int(os.environ.get("CALLOUT_PAIR_MIN_KEEP", "4")))
CALLOUT_MASK_OVERLAP_DROP = float(os.environ.get("CALLOUT_MASK_OVERLAP_DROP", "0.35"))
_CALLOUT_PRIORITY_RAW = os.environ.get("CALLOUT_PRIORITY_NUMBERS", "22,23,24,25")
CALLOUT_PRIORITY_NUMBERS = tuple(
    sorted(
        {
            int(x)
            for x in re.split(r"[,\s]+", _CALLOUT_PRIORITY_RAW.strip())
            if x.strip().isdigit() and 1 <= int(x.strip()) <= 500
        }
    )
)
PIXEL_FALLBACK_MAX_BOXES = max(0, int(os.environ.get("PIXEL_FALLBACK_MAX_BOXES", "4")))
PIXEL_FALLBACK_MIN_AREA_PX = max(16, int(os.environ.get("PIXEL_FALLBACK_MIN_AREA_PX", "220")))
PIXEL_FALLBACK_TEXT_OVERLAP_DROP = float(os.environ.get("PIXEL_FALLBACK_TEXT_OVERLAP_DROP", "0.55"))

VLM_GROUND_TILE_SCAN = os.environ.get("VLM_GROUND_TILE_SCAN", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
VLM_GROUND_ROI_PAD = max(0, int(os.environ.get("VLM_GROUND_ROI_PAD", "96")))
VLM_GROUND_ROI_LIMIT = max(1, int(os.environ.get("VLM_GROUND_ROI_LIMIT", "6")))
VLM_GROUND_TILE_PLUS_OVERVIEW = os.environ.get(
    "VLM_GROUND_TILE_PLUS_OVERVIEW", "1"
).strip().lower() in ("1", "true", "yes")
VLM_GROUND_TILE_MAX_TOKENS = int(os.environ.get("VLM_GROUND_TILE_MAX_TOKENS", "1800"))


# ---------- DWG 自动发现 ----------

def discover_dwg_for_pdf(pdf_path: Path) -> Path | None:
    """根据 PDF 文件名猜测同目录下的同名 .dwg。

    支持两种命名：
      - foo.pdf -> foo.dwg
      - foo-Model.pdf -> foo.dwg
    """
    stem = pdf_path.stem
    candidates = [pdf_path.with_suffix(".dwg")]
    if stem.endswith("-Model"):
        candidates.append(pdf_path.with_name(stem[: -len("-Model")] + ".dwg"))
    if stem.endswith("_Model"):
        candidates.append(pdf_path.with_name(stem[: -len("_Model")] + ".dwg"))
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


# ---------- ROI / mask 辅助函数（与原 compare_pipeline 保持一致） ----------

def diff_bboxes_from_images(
    img_a: np.ndarray,
    img_b: np.ndarray,
    top_n: int = 25,
    ignore_mask: np.ndarray | None = None,
) -> list[tuple[int, int, int, int]]:
    h_a, w_a = img_a.shape[:2]
    img_b_r = cv2.resize(img_b, (w_a, h_a), interpolation=cv2.INTER_AREA)
    gray_a = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(img_b_r, cv2.COLOR_BGR2GRAY)
    diff = cv2.absdiff(gray_a, gray_b)
    _, thresh = cv2.threshold(diff, DIFF_THRESH, 255, cv2.THRESH_BINARY)
    if ignore_mask is not None:
        mask = ignore_mask
        if mask.shape != thresh.shape:
            mask = cv2.resize(mask, (w_a, h_a), interpolation=cv2.INTER_NEAREST)
        thresh = thresh.copy()
        thresh[mask > 0] = 0
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (DIFF_DILATE, DIFF_DILATE))
    dilated = cv2.dilate(thresh, kernel)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:top_n]
    return [cv2.boundingRect(c) for c in contours]


def merge_binary_masks(masks: list[np.ndarray | None]) -> np.ndarray | None:
    valid = [m for m in masks if m is not None]
    if not valid:
        return None
    base = valid[0].copy()
    for mask in valid[1:]:
        if mask.shape != base.shape:
            mask = cv2.resize(mask, (base.shape[1], base.shape[0]), interpolation=cv2.INTER_NEAREST)
        base = cv2.bitwise_or(base, mask)
    return base


def apply_ignore_mask_to_image(
    img_bgr: np.ndarray,
    ignore_mask: np.ndarray | None,
    *,
    fill_value: int = 255,
) -> np.ndarray:
    if ignore_mask is None:
        return img_bgr
    h, w = img_bgr.shape[:2]
    mask = ignore_mask
    if mask.shape != (h, w):
        mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST)
    out = img_bgr.copy()
    out[mask > 0] = (fill_value, fill_value, fill_value)
    return out


def _intersection_area_xywh(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> int:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x1, y1 = max(ax, bx), max(ay, by)
    x2, y2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x2 <= x1 or y2 <= y1:
        return 0
    return (x2 - x1) * (y2 - y1)


def _iou_xywh(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    inter = _intersection_area_xywh(a, b)
    if inter <= 0:
        return 0.0
    aa = max(1, a[2] * a[3])
    ab = max(1, b[2] * b[3])
    return inter / float(aa + ab - inter)


def filter_geometry_rois(
    coarse_geom: list[tuple[int, int, int, int]],
    text_boxes: list[tuple[int, int, int, int]],
    img_w: int,
    img_h: int,
) -> list[tuple[int, int, int, int]]:
    max_area = GEOM_ROI_MAX_AREA_RATIO * img_w * img_h
    selected: list[tuple[int, int, int, int]] = []
    for box in coarse_geom:
        _, _, w, h = box
        area = w * h
        if area < GEOM_ROI_MIN_AREA_PX or area > max_area:
            continue
        inter_sum = 0
        for tb in text_boxes:
            inter_sum += _intersection_area_xywh(box, tb)
            if inter_sum >= area:
                break
        text_cover = inter_sum / float(max(1, area))
        if text_cover >= 0.72:
            continue
        if any(_iou_xywh(box, kept) >= 0.45 for kept in selected):
            continue
        selected.append(box)
        if len(selected) >= GEOM_ROI_MAX_COUNT:
            break
    if selected:
        return selected
    loose_min_area = max(16, GEOM_ROI_MIN_AREA_PX // 2)
    for box in coarse_geom:
        _, _, w, h = box
        area = w * h
        if area < loose_min_area or area > max_area:
            continue
        if any(_iou_xywh(box, kept) >= 0.45 for kept in selected):
            continue
        selected.append(box)
        if len(selected) >= max(4, GEOM_ROI_MAX_COUNT // 2):
            break
    return selected


def _parse_hint_number(raw: str) -> int | None:
    s = normalize_label(raw)
    if not s:
        return None
    if s.isdigit():
        n = int(s)
        return n if 1 <= n <= 500 else None
    if len(s) == 1:
        try:
            n = int(unicodedata.numeric(s))
            return n if 1 <= n <= 500 else None
        except (TypeError, ValueError):
            pass
    m = re.search(r"\d{1,3}", s)
    if not m:
        return None
    n = int(m.group(0))
    return n if 1 <= n <= 500 else None


def _line_segments_from_image(img_bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
    h, w = img_bgr.shape[:2]
    if w <= CALLOUT_LINE_SCAN_MAX_W:
        scan = img_bgr
        scale = 1.0
    else:
        scale = CALLOUT_LINE_SCAN_MAX_W / float(w)
        scan = cv2.resize(img_bgr, (int(round(w * scale)), int(round(h * scale))), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(scan, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 150)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180.0,
        threshold=24,
        minLineLength=24,
        maxLineGap=12,
    )
    if lines is None:
        return []
    out: list[tuple[int, int, int, int]] = []
    inv = 1.0 / scale
    for row in lines:
        x1, y1, x2, y2 = [int(v) for v in row[0]]
        out.append(
            (
                int(round(x1 * inv)),
                int(round(y1 * inv)),
                int(round(x2 * inv)),
                int(round(y2 * inv)),
            )
        )
    return out


def _center(b: tuple[int, int, int, int]) -> tuple[float, float]:
    x, y, w, h = b
    return x + w / 2, y + h / 2


def _collect_isolated_hint_items(
    hint_items: list[dict],
    text_boxes: list[tuple[int, int, int, int]],
) -> list[dict]:
    out: list[dict] = []
    text_centers = [_center(box) for box in text_boxes]
    for item in hint_items:
        b = item.get("bbox")
        if not isinstance(b, tuple) or len(b) < 4:
            continue
        cx, cy = _center((int(b[0]), int(b[1]), int(b[2]), int(b[3])))
        dense = 0
        for tx, ty in text_centers:
            if abs(cx - tx) + abs(cy - ty) <= CALLOUT_DENSE_RADIUS_PX:
                dense += 1
                if dense > CALLOUT_DENSE_TEXT_LIMIT:
                    break
        no = _parse_hint_number(str(item.get("text", "")))
        if dense <= CALLOUT_DENSE_TEXT_LIMIT:
            out.append({**item, "_dense_count": dense, "_dense_filtered": False})
            continue
        if no is not None and no <= 60:
            out.append({**item, "_dense_count": dense, "_dense_filtered": True})
    return out


def _roi_around_point(
    px: int,
    py: int,
    img_w: int,
    img_h: int,
    half: int = CALLOUT_ROI_HALF_SIZE,
) -> tuple[int, int, int, int]:
    x0 = max(0, px - half)
    y0 = max(0, py - half)
    x1 = min(img_w, px + half)
    y1 = min(img_h, py + half)
    if x1 <= x0:
        x1 = min(img_w, x0 + 1)
    if y1 <= y0:
        y1 = min(img_h, y0 + 1)
    return x0, y0, x1 - x0, y1 - y0


def build_callout_guided_rois(
    img_bgr: np.ndarray,
    hint_items: list[dict],
    text_boxes: list[tuple[int, int, int, int]],
) -> tuple[list[tuple[int, int, int, int]], list[dict]]:
    h, w = img_bgr.shape[:2]
    isolated = _collect_isolated_hint_items(hint_items, text_boxes)
    if not isolated:
        return [], []
    segments = _line_segments_from_image(img_bgr)
    if not segments:
        return [], []

    best_by_no: dict[int, dict[str, Any]] = {}
    for item in isolated:
        raw = str(item.get("text", ""))
        no = _parse_hint_number(raw)
        b = item.get("bbox")
        if no is None or not isinstance(b, tuple) or len(b) < 4:
            continue
        cx, cy = _center((int(b[0]), int(b[1]), int(b[2]), int(b[3])))
        dense_penalty = 0.0
        try:
            dense_v = int(item.get("_dense_count", 0))
            if dense_v > CALLOUT_DENSE_TEXT_LIMIT:
                dense_penalty = float(dense_v - CALLOUT_DENSE_TEXT_LIMIT) * 2.5
        except Exception:
            dense_penalty = 0.0

        near_limit = int(round(CALLOUT_LINE_NEAR_DIST_PX * 1.25))
        far_min = int(round(CALLOUT_LINE_MIN_FAR_DIST_PX * 0.85))
        best_score = -1.0
        best_endpoint: tuple[int, int] | None = None
        for x1, y1, x2, y2 in segments:
            d1 = ((x1 - cx) ** 2 + (y1 - cy) ** 2) ** 0.5
            d2 = ((x2 - cx) ** 2 + (y2 - cy) ** 2) ** 0.5
            near = d1 if d1 < d2 else d2
            far = d2 if d1 < d2 else d1
            if near > near_limit or far < far_min:
                continue
            ex, ey = (x2, y2) if d1 < d2 else (x1, y1)
            score = far - near * 0.35 - dense_penalty
            if score > best_score:
                best_score = score
                best_endpoint = (ex, ey)
        if best_endpoint is None:
            continue
        px, py = best_endpoint
        roi = _roi_around_point(px, py, w, h)
        prev = best_by_no.get(no)
        if prev is None or best_score > float(prev["score"]):
            best_by_no[no] = {
                "score": best_score,
                "roi": roi,
                "endpoint": [int(px), int(py)],
                "hint_bbox": [int(b[0]), int(b[1]), int(b[2]), int(b[3])],
                "hint_text": raw,
            }

    ranked_rows = [{"no": int(no), **row} for no, row in best_by_no.items()]
    ranked_rows.sort(key=lambda row: float(row["score"]), reverse=True)
    rois: list[tuple[int, int, int, int]] = []
    debug_rows: list[dict[str, Any]] = []
    for row in ranked_rows:
        roi = row["roi"]
        if any(_iou_xywh(roi, ex) >= 0.50 for ex in rois):
            continue
        rois.append(roi)
        debug_rows.append(
            {
                "no": int(row["no"]),
                "endpoint": row["endpoint"],
                "hint_bbox": row["hint_bbox"],
                "hint_text": row["hint_text"],
                "roi": [int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3])],
                "line_score": round(float(row["score"]), 4),
            }
        )
        if len(rois) >= CALLOUT_CANDIDATE_LIMIT:
            break
    return rois, debug_rows


def merge_roi_groups(
    roi_groups: list[list[tuple[int, int, int, int]]],
    *,
    limit: int = 18,
) -> list[tuple[int, int, int, int]]:
    out: list[tuple[int, int, int, int]] = []
    for group in roi_groups:
        for roi in group:
            if any(_iou_xywh(roi, ex) >= 0.35 for ex in out):
                continue
            out.append(roi)
            if len(out) >= limit:
                return out
    return out


def _clip_roi_xywh(
    roi: tuple[int, int, int, int],
    w: int,
    h: int,
) -> tuple[int, int, int, int] | None:
    x, y, rw, rh = [int(v) for v in roi]
    x0 = max(0, min(w, x))
    y0 = max(0, min(h, y))
    x1 = max(0, min(w, x + rw))
    y1 = max(0, min(h, y + rh))
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1 - x0, y1 - y0


def _callout_patch_diff_metrics(
    img_a: np.ndarray,
    img_b: np.ndarray,
    roi_a: tuple[int, int, int, int],
    roi_b: tuple[int, int, int, int],
    *,
    text_mask_a: np.ndarray | None = None,
    text_mask_b: np.ndarray | None = None,
) -> tuple[float, float, float]:
    h_a, w_a = img_a.shape[:2]
    h_b, w_b = img_b.shape[:2]
    ra = _clip_roi_xywh(roi_a, w_a, h_a)
    rb = _clip_roi_xywh(roi_b, w_b, h_b)
    if ra is None or rb is None:
        return 0.0, 0.0, 0.0

    xa, ya, wa, ha = ra
    xb, yb, wb, hb = rb
    pa = cv2.cvtColor(img_a[ya : ya + ha, xa : xa + wa], cv2.COLOR_BGR2GRAY)
    pb = cv2.cvtColor(img_b[yb : yb + hb, xb : xb + wb], cv2.COLOR_BGR2GRAY)
    if pa.size == 0 or pb.size == 0:
        return 0.0, 0.0, 0.0
    if pa.shape != pb.shape:
        pb = cv2.resize(pb, (pa.shape[1], pa.shape[0]), interpolation=cv2.INTER_AREA)

    mask_union = np.zeros(pa.shape, dtype=np.uint8)
    if text_mask_a is not None:
        ma = text_mask_a[ya : ya + ha, xa : xa + wa]
        if ma.size:
            if ma.shape != pa.shape:
                ma = cv2.resize(ma, (pa.shape[1], pa.shape[0]), interpolation=cv2.INTER_NEAREST)
            mask_union = cv2.bitwise_or(mask_union, (ma > 0).astype(np.uint8) * 255)
    if text_mask_b is not None:
        mb = text_mask_b[yb : yb + hb, xb : xb + wb]
        if mb.size:
            if mb.shape != pa.shape:
                mb = cv2.resize(mb, (pa.shape[1], pa.shape[0]), interpolation=cv2.INTER_NEAREST)
            mask_union = cv2.bitwise_or(mask_union, (mb > 0).astype(np.uint8) * 255)

    diff = cv2.absdiff(pa, pb)
    _, bin_diff = cv2.threshold(diff, 20, 255, cv2.THRESH_BINARY)
    e1 = cv2.Canny(pa, 70, 160)
    e2 = cv2.Canny(pb, 70, 160)
    edge_diff = cv2.absdiff(e1, e2)
    _, edge_bin = cv2.threshold(edge_diff, 18, 255, cv2.THRESH_BINARY)

    if np.count_nonzero(mask_union) > 0:
        bin_diff[mask_union > 0] = 0
        edge_bin[mask_union > 0] = 0

    k = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    bin_diff = cv2.morphologyEx(bin_diff, cv2.MORPH_OPEN, k)
    edge_bin = cv2.morphologyEx(edge_bin, cv2.MORPH_OPEN, k)
    area = max(1, bin_diff.shape[0] * bin_diff.shape[1])
    px_ratio = float(np.count_nonzero(bin_diff)) / float(area)
    edge_ratio = float(np.count_nonzero(edge_bin)) / float(area)

    n_cc, _, stats, _ = cv2.connectedComponentsWithStats(bin_diff, connectivity=8)
    max_cc = 0
    if n_cc > 1 and stats.shape[0] > 1:
        max_cc = int(np.max(stats[1:, cv2.CC_STAT_AREA]))
    cc_ratio = max_cc / float(area)
    return px_ratio, edge_ratio, cc_ratio


def _rows_by_no(rows: list[dict]) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for row in rows:
        no = row.get("no")
        roi = row.get("roi")
        if not isinstance(no, int):
            continue
        if not isinstance(roi, list) or len(roi) < 4:
            continue
        prev = out.get(no)
        if prev is None or float(row.get("line_score", 0.0)) > float(prev.get("line_score", 0.0)):
            out[no] = row
    return out


def _row_roi(row: dict) -> tuple[int, int, int, int] | None:
    roi = row.get("roi")
    if not isinstance(roi, list) or len(roi) < 4:
        return None
    return int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3])


def select_callout_rois_for_pair(
    img_a: np.ndarray,
    img_b: np.ndarray,
    rows_a: list[dict],
    rows_b: list[dict],
    *,
    text_mask_a: np.ndarray | None = None,
    text_mask_b: np.ndarray | None = None,
) -> tuple[list[tuple[int, int, int, int]], list[tuple[int, int, int, int]], list[dict], list[dict]]:
    by_no_a = _rows_by_no(rows_a)
    by_no_b = _rows_by_no(rows_b)
    shared = sorted(set(by_no_a.keys()) & set(by_no_b.keys()))

    paired_rank: list[dict] = []
    for no in shared:
        ra = _row_roi(by_no_a[no])
        rb = _row_roi(by_no_b[no])
        if ra is None or rb is None:
            continue
        px_ratio, edge_ratio, cc_ratio = _callout_patch_diff_metrics(
            img_a, img_b, ra, rb, text_mask_a=text_mask_a, text_mask_b=text_mask_b
        )
        score = px_ratio + edge_ratio * 0.8 + cc_ratio * 1.4
        paired_rank.append(
            {
                "no": no,
                "score": float(score),
                "px_ratio": float(px_ratio),
                "edge_ratio": float(edge_ratio),
                "cc_ratio": float(cc_ratio),
                "a": by_no_a[no],
                "b": by_no_b[no],
            }
        )
    paired_rank.sort(key=lambda row: row["score"], reverse=True)

    out_a: list[tuple[int, int, int, int]] = []
    out_b: list[tuple[int, int, int, int]] = []
    dbg_a: list[dict] = []
    dbg_b: list[dict] = []

    for row in paired_rank:
        ra = _row_roi(row["a"])
        rb = _row_roi(row["b"])
        if ra is None or rb is None:
            continue
        sc = float(row["score"])
        if sc < CALLOUT_PAIR_DIFF_MIN and len(out_a) >= CALLOUT_PAIR_MIN_KEEP:
            continue
        if any(_iou_xywh(ra, ex) >= 0.50 for ex in out_a) or any(_iou_xywh(rb, ex) >= 0.50 for ex in out_b):
            continue
        out_a.append(ra)
        out_b.append(rb)
        dbg_a.append(
            {
                **row["a"],
                "pair_score": round(sc, 4),
                "pair_px_ratio": round(float(row["px_ratio"]), 4),
                "pair_edge_ratio": round(float(row["edge_ratio"]), 4),
                "pair_cc_ratio": round(float(row["cc_ratio"]), 4),
                "pair_selected": True,
            }
        )
        dbg_b.append(
            {
                **row["b"],
                "pair_score": round(sc, 4),
                "pair_px_ratio": round(float(row["px_ratio"]), 4),
                "pair_edge_ratio": round(float(row["edge_ratio"]), 4),
                "pair_cc_ratio": round(float(row["cc_ratio"]), 4),
                "pair_selected": True,
            }
        )
        if len(out_a) >= CALLOUT_PAIR_TOP_K:
            break

    target_keep = min(CALLOUT_MAX_ROIS, max(CALLOUT_PAIR_MIN_KEEP, CALLOUT_PAIR_TOP_K // 2))

    def _single_side_rank(
        rows: list[dict],
        img_x: np.ndarray,
        img_y: np.ndarray,
        text_x: np.ndarray | None,
        text_y: np.ndarray | None,
        selected_rois: list[tuple[int, int, int, int]],
    ) -> list[dict]:
        ranked: list[dict] = []
        for row in rows:
            roi = _row_roi(row)
            if roi is None or any(_iou_xywh(roi, ex) >= 0.50 for ex in selected_rois):
                continue
            px_ratio, edge_ratio, cc_ratio = _callout_patch_diff_metrics(
                img_x, img_y, roi, roi, text_mask_a=text_x, text_mask_b=text_y
            )
            score = px_ratio + edge_ratio * 0.8 + cc_ratio * 1.4
            ranked.append(
                {
                    **row,
                    "pair_score": float(score),
                    "pair_px_ratio": float(px_ratio),
                    "pair_edge_ratio": float(edge_ratio),
                    "pair_cc_ratio": float(cc_ratio),
                    "pair_selected": False,
                    "single_side": True,
                }
            )
        ranked.sort(key=lambda row: float(row.get("pair_score", 0.0)), reverse=True)
        return ranked

    if len(out_a) < target_keep:
        for row in _single_side_rank(rows_a, img_a, img_b, text_mask_a, text_mask_b, out_a):
            roi = _row_roi(row)
            if roi is None:
                continue
            if float(row.get("pair_score", 0.0)) < CALLOUT_PAIR_DIFF_MIN * 0.6 and len(out_a) >= CALLOUT_PAIR_MIN_KEEP:
                continue
            out_a.append(roi)
            dbg_a.append(row)
            if len(out_a) >= target_keep:
                break
    if len(out_b) < target_keep:
        for row in _single_side_rank(rows_b, img_b, img_a, text_mask_b, text_mask_a, out_b):
            roi = _row_roi(row)
            if roi is None:
                continue
            if float(row.get("pair_score", 0.0)) < CALLOUT_PAIR_DIFF_MIN * 0.6 and len(out_b) >= CALLOUT_PAIR_MIN_KEEP:
                continue
            out_b.append(roi)
            dbg_b.append(row)
            if len(out_b) >= target_keep:
                break

    return out_a[:CALLOUT_MAX_ROIS], out_b[:CALLOUT_MAX_ROIS], dbg_a, dbg_b


def _roi_text_overlap_ratio(
    roi: tuple[int, int, int, int],
    text_mask: np.ndarray | None,
) -> float:
    if text_mask is None:
        return 0.0
    h, w = text_mask.shape[:2]
    rr = _clip_roi_xywh(roi, w, h)
    if rr is None:
        return 0.0
    x, y, rw, rh = rr
    area = max(1, rw * rh)
    return float(np.count_nonzero(text_mask[y : y + rh, x : x + rw])) / float(area)


def filter_rois_by_mask(
    rois: list[tuple[int, int, int, int]],
    mask: np.ndarray | None,
    *,
    max_overlap: float = 0.55,
    limit: int | None = None,
) -> list[tuple[int, int, int, int]]:
    if not rois:
        return []
    out: list[tuple[int, int, int, int]] = []
    for roi in rois:
        if _roi_text_overlap_ratio(roi, mask) >= max_overlap:
            continue
        if any(_iou_xywh(roi, ex) >= 0.45 for ex in out):
            continue
        out.append(roi)
        if limit is not None and len(out) >= limit:
            break
    return out


def filter_callout_debug_rows(
    debug_rows: list[dict],
    rois_keep: list[tuple[int, int, int, int]],
) -> list[dict]:
    keep = {(int(r[0]), int(r[1]), int(r[2]), int(r[3])) for r in rois_keep}
    out: list[dict] = []
    for row in debug_rows:
        roi = row.get("roi")
        if not isinstance(roi, (list, tuple)) or len(roi) < 4:
            continue
        key = (int(roi[0]), int(roi[1]), int(roi[2]), int(roi[3]))
        if key in keep:
            out.append(row)
    return out


def extract_pixel_diff_rois(
    img_primary: np.ndarray,
    img_reference: np.ndarray,
    *,
    guide_rois: list[tuple[int, int, int, int]],
    text_mask: np.ndarray | None = None,
    limit: int = PIXEL_FALLBACK_MAX_BOXES,
) -> list[tuple[int, int, int, int]]:
    if limit <= 0 or not guide_rois:
        return []
    h, w = img_primary.shape[:2]
    ref_r = cv2.resize(img_reference, (w, h), interpolation=cv2.INTER_AREA)
    diff = cv2.absdiff(cv2.cvtColor(img_primary, cv2.COLOR_BGR2GRAY), cv2.cvtColor(ref_r, cv2.COLOR_BGR2GRAY))
    _, bin_diff = cv2.threshold(diff, DIFF_THRESH, 255, cv2.THRESH_BINARY)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(3, DIFF_DILATE), max(3, DIFF_DILATE)))
    bin_diff = cv2.dilate(bin_diff, k)
    if text_mask is not None and text_mask.shape == bin_diff.shape:
        bin_diff[text_mask > 0] = 0

    out: list[tuple[int, int, int, int]] = []
    for roi in guide_rois:
        rr = _clip_roi_xywh(roi, w, h)
        if rr is None:
            continue
        x, y, rw, rh = rr
        patch = bin_diff[y : y + rh, x : x + rw]
        if patch.size == 0:
            continue
        contours, _ = cv2.findContours(patch, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:3]
        for contour in contours:
            bx, by, bw, bh = cv2.boundingRect(contour)
            gbox = (x + bx, y + by, bw, bh)
            if bw * bh < PIXEL_FALLBACK_MIN_AREA_PX:
                continue
            if _roi_text_overlap_ratio(gbox, text_mask) >= PIXEL_FALLBACK_TEXT_OVERLAP_DROP:
                continue
            if any(_iou_xywh(gbox, ex) >= 0.45 for ex in out):
                continue
            out.append(gbox)
            if len(out) >= limit:
                return out
    return out


def filter_part_related_rois(
    coarse: list[tuple[int, int, int, int]],
    hints: list[tuple[int, int, int, int]],
    img_w: int,
    img_h: int,
) -> list[tuple[int, int, int, int]]:
    max_area = 0.12 * img_w * img_h
    out: list[tuple[int, int, int, int]] = []
    for box in coarse:
        _, _, w, h = box
        if w * h > max_area:
            continue
        cx, cy = _center(box)
        ok = False
        for hint in hints:
            hx, hy = _center(hint)
            if abs(cx - hx) + abs(cy - hy) < PROX_PX * 3:
                ok = True
                break
        if ok or not hints:
            out.append(box)
    return out[:15] if out else coarse[:8]


def parse_bbox_json(raw: str) -> list[dict]:
    raw = strip_thinking_tags(raw)
    if "```" in raw:
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
        if match:
            raw = match.group(1).strip()
    left, right = raw.find("["), raw.rfind("]")
    if left < 0 or right <= left:
        return []
    chunk = raw[left : right + 1]
    try:
        return json.loads(chunk)
    except json.JSONDecodeError:
        try:
            return ast.literal_eval(chunk)
        except (SyntaxError, ValueError):
            return []


_GROUNDING_SYS = """你是机械图纸空间定位助手。必须只输出一个 JSON 数组，不要 Markdown，不要解释。
每个元素格式：{"bbox_2d": [x1, y1, x2, y2], "label": "简短中文"}
其中 x1,y1,x2,y2 为相对于第一张图（主图）宽高的 0–1000 归一化整数坐标。
只框主图上与另一张对照图相比发生变化或需重点复核的区域；须结合图像实际，不要仅凭辅助文字编造不存在的差异。
优先框结构/轮廓/装配位置变化，对纯文字变化保持克制。"""

_GROUNDING_SYS_TILE = """你是机械图纸空间定位助手。当前图1、图2 为同一矩形区域裁切后的局部放大。
必须只输出一个 JSON 数组，不要 Markdown，不要解释。
每个元素格式：{"bbox_2d": [x1, y1, x2, y2], "label": "简短中文"}
bbox_2d 为相对当前图1 像素宽×高的 0–1000 归一化整数。
只框图1相对图2在本局部内可见的差异；无差异可输出 []。"""


def _align_reference_to_primary(img_primary: np.ndarray, img_reference: np.ndarray) -> np.ndarray:
    hp, wp = img_primary.shape[:2]
    return cv2.resize(img_reference, (wp, hp), interpolation=cv2.INTER_AREA)


def _box_area_norm(b2d: list[int]) -> float:
    x1, y1, x2, y2 = b2d[:4]
    return float(max(0, x2 - x1) * max(0, y2 - y1))


def _iou_norm(a: list[int], b: list[int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih / 1_000_000.0
    area_a = _box_area_norm(a) / 1_000_000.0
    area_b = _box_area_norm(b) / 1_000_000.0
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _dedupe_grounding_items(items: list[dict], *, iou_thresh: float = 0.55) -> list[dict]:
    cleaned: list[dict] = []
    for item in items:
        b = item.get("bbox_2d")
        if not isinstance(b, (list, tuple)) or len(b) < 4:
            continue
        bb = [int(b[0]), int(b[1]), int(b[2]), int(b[3])]
        it2 = {**item, "bbox_2d": bb}
        if any(_iou_norm(bb, prev["bbox_2d"]) >= iou_thresh for prev in cleaned):
            continue
        cleaned.append(it2)
    return cleaned


def xywh_to_bbox_2d(box: tuple[int, int, int, int], full_w: int, full_h: int) -> list[int]:
    x, y, w, h = box
    full_w = max(1, full_w)
    full_h = max(1, full_h)
    x1 = max(0, min(full_w, x))
    y1 = max(0, min(full_h, y))
    x2 = max(0, min(full_w, x + w))
    y2 = max(0, min(full_h, y + h))
    if x2 <= x1:
        x2 = min(full_w, x1 + 1)
    if y2 <= y1:
        y2 = min(full_h, y1 + 1)
    return [
        int(round(x1 / full_w * 1000)),
        int(round(y1 / full_h * 1000)),
        int(round(x2 / full_w * 1000)),
        int(round(y2 / full_h * 1000)),
    ]


def _bbox_2d_to_xyxy_px(b2d: list[int], full_w: int, full_h: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = [int(v) for v in b2d[:4]]
    px1 = int(round(x1 / 1000.0 * full_w))
    py1 = int(round(y1 / 1000.0 * full_h))
    px2 = int(round(x2 / 1000.0 * full_w))
    py2 = int(round(y2 / 1000.0 * full_h))
    px1 = max(0, min(full_w, px1))
    px2 = max(0, min(full_w, px2))
    py1 = max(0, min(full_h, py1))
    py2 = max(0, min(full_h, py2))
    if px2 <= px1:
        px2 = min(full_w, px1 + 1)
    if py2 <= py1:
        py2 = min(full_h, py1 + 1)
    return px1, py1, px2, py2


def _text_overlap_ratio_in_mask(
    b2d: list[int],
    *,
    text_mask: np.ndarray | None,
    full_w: int,
    full_h: int,
) -> float:
    if text_mask is None:
        return 0.0
    x1, y1, x2, y2 = _bbox_2d_to_xyxy_px(b2d, full_w, full_h)
    roi = text_mask[y1:y2, x1:x2]
    if roi.size == 0:
        return 0.0
    return float(np.count_nonzero(roi)) / float(roi.size)


def sanitize_grounding_items(
    items: list[dict],
    *,
    text_mask: np.ndarray | None,
    full_w: int,
    full_h: int,
) -> list[dict]:
    cleaned: list[dict] = []
    for item in items:
        b = item.get("bbox_2d")
        if not isinstance(b, (list, tuple)) or len(b) < 4:
            continue
        bb = [max(0, min(1000, int(v))) for v in b[:4]]
        x1, y1, x2, y2 = bb
        if x2 <= x1:
            x2 = min(1000, x1 + 1)
        if y2 <= y1:
            y2 = min(1000, y1 + 1)
        bw, bh = x2 - x1, y2 - y1
        if bw < GROUND_MIN_BOX_SIDE_NORM or bh < GROUND_MIN_BOX_SIDE_NORM or bw * bh < GROUND_MIN_BOX_AREA_NORM:
            continue
        bb_fix = [x1, y1, x2, y2]
        if _text_overlap_ratio_in_mask(bb_fix, text_mask=text_mask, full_w=full_w, full_h=full_h) >= GROUND_TEXT_OVERLAP_DROP:
            continue
        cleaned.append(
            {
                **item,
                "bbox_2d": bb_fix,
                "source": str(item.get("source", "model") or "model"),
                "label": str(item.get("label", "差异候选") or "差异候选"),
            }
        )
    return _dedupe_grounding_items(cleaned)


def filter_grounding_items_by_mask(
    items: list[dict],
    *,
    mask: np.ndarray | None,
    full_w: int,
    full_h: int,
    max_overlap: float,
) -> list[dict]:
    if mask is None or not items:
        return items
    out: list[dict] = []
    for item in items:
        b = item.get("bbox_2d")
        if not isinstance(b, (list, tuple)) or len(b) < 4:
            continue
        bb = [int(b[0]), int(b[1]), int(b[2]), int(b[3])]
        if _text_overlap_ratio_in_mask(bb, text_mask=mask, full_w=full_w, full_h=full_h) >= max_overlap:
            continue
        out.append(item)
    return _dedupe_grounding_items(out)


def merge_geometry_fallback_boxes(
    items: list[dict],
    *,
    geom_rois: list[tuple[int, int, int, int]],
    full_w: int,
    full_h: int,
    max_add: int = GROUND_FALLBACK_GEOM_BOXES,
) -> list[dict]:
    if max_add <= 0 or not geom_rois:
        return items
    out = list(items)
    added = 0
    for roi in geom_rois:
        b2d = xywh_to_bbox_2d(roi, full_w, full_h)
        if any(_iou_norm(b2d, it["bbox_2d"]) >= 0.35 for it in out if "bbox_2d" in it):
            continue
        out.append({"bbox_2d": b2d, "label": "几何差异候选(低置信)", "source": "geom_fallback"})
        added += 1
        if added >= max_add:
            break
    return _dedupe_grounding_items(out)


def merge_pixel_fallback_boxes(
    items: list[dict],
    *,
    pixel_rois: list[tuple[int, int, int, int]],
    full_w: int,
    full_h: int,
    max_add: int = PIXEL_FALLBACK_MAX_BOXES,
) -> list[dict]:
    if max_add <= 0 or not pixel_rois:
        return items
    out = list(items)
    added = 0
    for roi in pixel_rois:
        b2d = xywh_to_bbox_2d(roi, full_w, full_h)
        if any(_iou_norm(b2d, it["bbox_2d"]) >= 0.35 for it in out if "bbox_2d" in it):
            continue
        out.append({"bbox_2d": b2d, "label": "结构差异候选(像素)", "source": "pixel_fallback"})
        added += 1
        if added >= max_add:
            break
    return _dedupe_grounding_items(out)


def mirror_items_fallback(source_items: list[dict], *, max_add: int = 6) -> list[dict]:
    out: list[dict] = []
    for item in source_items:
        bb = item.get("bbox_2d")
        if not isinstance(bb, (list, tuple)) or len(bb) < 4:
            continue
        b2d = [int(bb[0]), int(bb[1]), int(bb[2]), int(bb[3])]
        if any(_iou_norm(b2d, ex["bbox_2d"]) >= 0.35 for ex in out if "bbox_2d" in ex):
            continue
        label = str(item.get("label", "")).strip() or "差异候选"
        out.append({"bbox_2d": b2d, "label": f"{label}(镜像候选)", "source": "mirror_fallback"})
        if len(out) >= max_add:
            break
    return out


def _map_tile_bbox_to_full_primary(
    b2d: list,
    *,
    th_r: int,
    tw_r: int,
    th0: int,
    tw0: int,
    tile_sx: int,
    tile_sy: int,
    crop_x0: int,
    crop_y0: int,
    full_w: int,
    full_h: int,
) -> list[int]:
    tw_r = max(1, tw_r)
    th_r = max(1, th_r)
    nx1, ny1, nx2, ny2 = (int(b2d[0]), int(b2d[1]), int(b2d[2]), int(b2d[3]))
    x1r = nx1 / 1000.0 * tw_r
    y1r = ny1 / 1000.0 * th_r
    x2r = nx2 / 1000.0 * tw_r
    y2r = ny2 / 1000.0 * th_r
    sx_m = tw0 / tw_r
    sy_m = th0 / th_r
    x1c = x1r * sx_m + tile_sx
    y1c = y1r * sy_m + tile_sy
    x2c = x2r * sx_m + tile_sx
    y2c = y2r * sy_m + tile_sy
    x1f = int(round(x1c + crop_x0))
    y1f = int(round(y1c + crop_y0))
    x2f = int(round(x2c + crop_x0))
    y2f = int(round(y2c + crop_y0))
    x1f = max(0, min(full_w, x1f))
    x2f = max(0, min(full_w, x2f))
    y1f = max(0, min(full_h, y1f))
    y2f = max(0, min(full_h, y2f))
    if x2f <= x1f:
        x2f = min(full_w, x1f + 1)
    if y2f <= y1f:
        y2f = min(full_h, y1f + 1)
    return [
        int(round(x1f / max(1, full_w) * 1000)),
        int(round(y1f / max(1, full_h) * 1000)),
        int(round(x2f / max(1, full_w) * 1000)),
        int(round(y2f / max(1, full_h) * 1000)),
    ]


def _grounding_payload(model: str, system: str, b64_p: str, b64_r: str, instruction: str, max_tokens: int) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_p}"}},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_r}"}},
                    {"type": "text", "text": instruction},
                ],
            },
        ],
        "temperature": 0.05,
        "max_tokens": max_tokens,
    }


# ---------- 配置容器：所有 API/模型/路径以参数传入，避免全局副作用 ----------

@dataclass
class PipelineConfig:
    base_url: str
    api_key: str
    vl_model: str
    text_model: str
    ocr_model: str = DEFAULT_OCR_MODEL
    vl_api_style: str = "auto"
    output_dir: Path = field(default_factory=lambda: Path("./reports/output"))
    dpi: int = 220
    max_pages: int = 1
    ocr_timeout: float = DEFAULT_OCR_TIMEOUT
    vlm_timeout: float = 240.0
    zai_api_key: str = ""


# ---------- VLM grounding（参数化） ----------

def vl_grounding_primary_vs_reference(
    cfg: PipelineConfig,
    img_primary: np.ndarray,
    img_reference: np.ndarray,
    label_primary: str,
    label_reference: str,
    analysis_snippet: str,
    rois: list[tuple[int, int, int, int]] | None = None,
) -> tuple[list[dict], str]:
    ref_r = _align_reference_to_primary(img_primary, img_reference)
    full_h, full_w = img_primary.shape[:2]

    def single_pass() -> tuple[list[dict], str]:
        ip = cvl.resize_to_width(img_primary, MAX_GROUND_W)
        ir = cvl.resize_to_width(ref_r, MAX_GROUND_W)
        hp, wp = ip.shape[:2]
        instruction = (
            f"图1（主图）=[{label_primary}]，图2（对照）=[{label_reference}]。\n"
            "请仅针对图1标出相对图2有差异或需重点复核的区域。\n"
            f"辅助信息：\n{analysis_snippet[:2600]}\n"
            f"图1 当前像素约 {wp}×{hp}；bbox_2d 必须是相对图1 的 0–1000 整数。"
        )
        payload = _grounding_payload(
            cfg.vl_model,
            _GROUNDING_SYS,
            cvl.img_to_base64(ip),
            cvl.img_to_base64(ir),
            instruction,
            2500,
        )
        raw = response_completion_from_payload(cfg.base_url, cfg.api_key, payload, timeout=cfg.vlm_timeout)
        return parse_bbox_json(raw), raw

    if not VLM_GROUND_TILE_SCAN:
        return single_pass()

    rows = max(1, int(os.environ.get("VL_TILE_ROWS", "3")))
    cols = max(1, int(os.environ.get("VL_TILE_COLS", "3")))
    margin = max(0, int(os.environ.get("VL_TILE_MARGIN_PX", "40")))
    tile_max_w = max(512, int(os.environ.get("VL_TILE_MAX_W", "1536")))
    raw_parts: list[str] = []
    crops: list[tuple[int, int, int, int]] = []

    if rois:
        for rx, ry, rw, rh in rois[:VLM_GROUND_ROI_LIMIT]:
            cx0 = max(0, rx - VLM_GROUND_ROI_PAD)
            cy0 = max(0, ry - VLM_GROUND_ROI_PAD)
            cx1 = min(full_w, rx + rw + VLM_GROUND_ROI_PAD)
            cy1 = min(full_h, ry + rh + VLM_GROUND_ROI_PAD)
            if cx1 > cx0 and cy1 > cy0:
                crops.append((cx0, cy0, cx1 - cx0, cy1 - cy0))
    if not crops:
        crops = [(0, 0, full_w, full_h)]

    merged: list[dict] = []
    crop_idx = 0
    for cx0, cy0, cw, ch in crops:
        crop_idx += 1
        p_crop = img_primary[cy0 : cy0 + ch, cx0 : cx0 + cw]
        r_crop = ref_r[cy0 : cy0 + ch, cx0 : cx0 + cw]
        if p_crop.size == 0:
            continue
        ys = cvl._tile_spans(ch, rows, margin)
        xs = cvl._tile_spans(cw, cols, margin)
        total_tiles = len(ys) * len(xs)
        ti = 0
        for y1, y2 in ys:
            for x1, x2 in xs:
                ti += 1
                ca = p_crop[y1:y2, x1:x2]
                cb = r_crop[y1:y2, x1:x2]
                if ca.size == 0 or cb.size == 0:
                    continue
                th0, tw0 = ca.shape[:2]
                ip = cvl.resize_to_width(ca, tile_max_w)
                ir = cvl.resize_to_width(cb, tile_max_w)
                th_r, tw_r = ip.shape[:2]
                instruction = (
                    f"【分块 {ti}/{total_tiles}】裁剪块 {crop_idx}；全图裁剪原点=({cx0},{cy0})；"
                    f"瓦片范围 x=[{x1},{x2}) y=[{y1},{y2})；全图约 {full_w}×{full_h}。\n"
                    f"图1=[{label_primary}] 图2=[{label_reference}]。\n"
                    f"辅助：\n{analysis_snippet[:1400]}\n"
                )
                payload = _grounding_payload(
                    cfg.vl_model,
                    _GROUNDING_SYS_TILE,
                    cvl.img_to_base64(ip),
                    cvl.img_to_base64(ir),
                    instruction,
                    VLM_GROUND_TILE_MAX_TOKENS,
                )
                try:
                    raw_t = response_completion_from_payload(cfg.base_url, cfg.api_key, payload, timeout=cfg.vlm_timeout)
                    raw_parts.append(f"[crop{crop_idx}-tile{ti}]\n{raw_t[:3500]}")
                    for item in parse_bbox_json(raw_t):
                        bb = item.get("bbox_2d")
                        if not isinstance(bb, (list, tuple)) or len(bb) < 4:
                            continue
                        merged.append(
                            {
                                **item,
                                "bbox_2d": _map_tile_bbox_to_full_primary(
                                    list(bb),
                                    th_r=th_r,
                                    tw_r=tw_r,
                                    th0=th0,
                                    tw0=tw0,
                                    tile_sx=x1,
                                    tile_sy=y1,
                                    crop_x0=cx0,
                                    crop_y0=cy0,
                                    full_w=full_w,
                                    full_h=full_h,
                                ),
                            }
                        )
                except Exception as exc:
                    raw_parts.append(f"[crop{crop_idx}-tile{ti}] ERROR {exc}")

    if VLM_GROUND_TILE_PLUS_OVERVIEW:
        items_o, raw_o = single_pass()
        raw_parts.insert(0, f"[overview]\n{raw_o[:4000]}")
        merged = list(items_o) + merged

    return _dedupe_grounding_items(merged), "\n\n---\n\n".join(raw_parts)


def _ocr_pair_diff_snippet(ocr_pair_diff: dict[str, Any]) -> str:
    summary = ocr_pair_diff.get("summary", {}) or {}
    table_row = ocr_pair_diff.get("table_row", {}) or {}
    text_line = ocr_pair_diff.get("text_line", {}) or {}
    return (
        f"表格独有 A/B={summary.get('table_only_in_a', 0)}/{summary.get('table_only_in_b', 0)}；"
        f"文本独有 A/B={summary.get('text_only_in_a', 0)}/{summary.get('text_only_in_b', 0)}；"
        f"近似文本={summary.get('total_near_mismatch', 0)}。\n"
        f"A表格独有样例: {[item.get('text') for item in table_row.get('only_in_a', [])[:6]]}\n"
        f"B表格独有样例: {[item.get('text') for item in table_row.get('only_in_b', [])[:6]]}\n"
        f"A文本独有样例: {[item.get('text') for item in text_line.get('only_in_a', [])[:6]]}\n"
        f"B文本独有样例: {[item.get('text') for item in text_line.get('only_in_b', [])[:6]]}\n"
        f"近似文本样例: {[item.get('a', {}).get('text') for item in text_line.get('near_mismatch', [])[:6]]}"
    )


def infer_roi_verdict(
    cfg: PipelineConfig,
    label_a: str,
    label_b: str,
    roi_rows: list[dict],
    dwg_summary: str,
    vlm_coarse: str,
    ocr_summary: str,
) -> str:
    lines = [
        f"ROI{i} 框{row['bbox']} {label_a}文:「{row['text_a']}」 {label_b}文:「{row['text_b']}」"
        for i, row in enumerate(roi_rows, 1)
    ]
    ctx = "\n".join(lines) if lines else "(无 ROI 文本)"
    prompt = f"""你是结构工艺评审。已知两张爆炸图对比「{label_a} vs {label_b}」。

【OCR 文字差异摘要】
{ocr_summary[:1800]}

【VLM 粗分析摘要】
{vlm_coarse[:2200]}

【DWG/二进制字符串层差异摘要】
{dwg_summary[:1000]}

【各 ROI OCR 文本摘录】
{ctx}

请逐条判断：每处更可能是 (A)图纸表达/标注版本差异 (B)疑似设计变更 (C)信息不足需人工看图。
最后给出「综合结论」3–5 句中文。"""
    try:
        return chat_completion_text(
            cfg.base_url,
            cfg.api_key,
            cfg.text_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.15,
            max_tokens=2000,
            timeout=180.0,
        )
    except Exception as exc:
        return f"【文本模型不可用】推理判定跳过：{exc}"


def _dedupe_render_annotations(items: list[dict]) -> list[dict]:
    seen: set[tuple[tuple[int, int, int, int], str, str]] = set()
    out: list[dict] = []
    for item in items:
        bb = item.get("bbox_2d")
        if not isinstance(bb, (list, tuple)) or len(bb) < 4:
            continue
        key = (
            tuple(int(v) for v in bb[:4]),
            str(item.get("label", "")),
            str(item.get("source", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _llm_n_way_analysis(
    cfg: PipelineConfig,
    *,
    ocr_doc_summaries: dict[str, dict[str, Any]],
    pairwise_ocr: list[dict[str, Any]],
) -> str:
    system_prompt, user_prompt = build_three_way_ocr_messages(
        doc_summaries=ocr_doc_summaries,
        pairwise_results=pairwise_ocr,
    )
    try:
        console.print("[cyan]  正在调用 LLM 进行 OCR N 文件综合分析...[/cyan]")
        return chat_completion_text(
            cfg.base_url,
            cfg.api_key,
            cfg.text_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=2200,
            timeout=300.0,
        )
    except Exception as exc:
        console.print(f"[yellow]  LLM 不可用（{exc}），切换为 OCR 静态总结...[/yellow]")
        return build_static_three_way_ocr_summary(
            doc_summaries=ocr_doc_summaries,
            pairwise_results=pairwise_ocr,
        )


def run_pair(
    cfg: PipelineConfig,
    *,
    la: str,
    lb: str,
    rendered: dict[str, np.ndarray],
    dwg_info: dict[str, dict],
    ocr_pages_by_label: dict[str, list[OCRPage]],
    ocr_doc_summaries: dict[str, dict[str, Any]],
    ocr_pair_result: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    img_a = rendered[la]
    img_b = rendered[lb]
    ha, wa = img_a.shape[:2]
    hb, wb = img_b.shape[:2]
    page_a = (ocr_pages_by_label.get(la) or [None])[0]
    page_b = (ocr_pages_by_label.get(lb) or [None])[0]

    pair_dir = run_dir / f"{la}_vs_{lb}"
    pair_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"\n[bold cyan]══ {la} ↔ {lb} ══[/bold cyan]")

    ocr_pair_diff = dict((ocr_pair_result.get("pages") or [{}])[0])
    ocr_annotations_a = list(ocr_pair_diff.get("ocr_annotations_a", []) or [])
    ocr_annotations_b = list(ocr_pair_diff.get("ocr_annotations_b", []) or [])

    ocr_boxes_a: list = []
    ocr_boxes_b_on_a: list = []
    ocr_boxes_b: list = []
    ocr_boxes_a_on_b: list = []
    hint_items_a: list[dict] = []
    hint_items_b_on_a: list[dict] = []
    hint_items_b: list[dict] = []
    hint_items_a_on_b: list[dict] = []

    if page_a is not None:
        ocr_boxes_a = collect_ocr_block_boxes(page_a, unit_types=("text_line", "table_row"), target_width=wa, target_height=ha)
        hint_items_a = collect_hint_items_from_ocr_page(page_a, target_width=wa, target_height=ha)
    if page_b is not None:
        ocr_boxes_b_on_a = collect_ocr_block_boxes(page_b, unit_types=("text_line", "table_row"), target_width=wa, target_height=ha)
        hint_items_b_on_a = collect_hint_items_from_ocr_page(page_b, target_width=wa, target_height=ha)
        ocr_boxes_b = collect_ocr_block_boxes(page_b, unit_types=("text_line", "table_row"), target_width=wb, target_height=hb)
        hint_items_b = collect_hint_items_from_ocr_page(page_b, target_width=wb, target_height=hb)
    if page_a is not None:
        ocr_boxes_a_on_b = collect_ocr_block_boxes(page_a, unit_types=("text_line", "table_row"), target_width=wb, target_height=hb)
        hint_items_a_on_b = collect_hint_items_from_ocr_page(page_a, target_width=wb, target_height=hb)

    ocr_mask_a = build_mask_from_boxes(width=wa, height=ha, boxes=ocr_boxes_a + ocr_boxes_b_on_a, pad=TEXT_MASK_PAD)
    ocr_mask_b = build_mask_from_boxes(width=wb, height=hb, boxes=ocr_boxes_b + ocr_boxes_a_on_b, pad=TEXT_MASK_PAD)

    coarse_a = diff_bboxes_from_images(img_a, img_b, top_n=40, ignore_mask=ocr_mask_a)
    coarse_b = diff_bboxes_from_images(img_b, img_a, top_n=40, ignore_mask=ocr_mask_b)

    hints_a = [item["bbox"] for item in hint_items_a + hint_items_b_on_a if isinstance(item.get("bbox"), tuple)]
    hints_b = [item["bbox"] for item in hint_items_b + hint_items_a_on_b if isinstance(item.get("bbox"), tuple)]

    rois_text_a = filter_part_related_rois(coarse_a, hints_a, wa, ha)
    rois_text_b = filter_part_related_rois(coarse_b, hints_b, wb, hb)

    coarse_geom_a = diff_bboxes_from_images(img_a, img_b, top_n=48, ignore_mask=ocr_mask_a)
    coarse_geom_b = diff_bboxes_from_images(img_b, img_a, top_n=48, ignore_mask=ocr_mask_b)
    rois_geom_a = filter_geometry_rois(coarse_geom_a, ocr_boxes_a + ocr_boxes_b_on_a, wa, ha)
    rois_geom_b = filter_geometry_rois(coarse_geom_b, ocr_boxes_b + ocr_boxes_a_on_b, wb, hb)

    callout_rois_a_all, callout_debug_a_all = build_callout_guided_rois(img_a, hint_items_a + hint_items_b_on_a, ocr_boxes_a + ocr_boxes_b_on_a)
    callout_rois_b_all, callout_debug_b_all = build_callout_guided_rois(img_b, hint_items_b + hint_items_a_on_b, ocr_boxes_b + ocr_boxes_a_on_b)
    callout_rois_a, callout_rois_b, callout_debug_a, callout_debug_b = select_callout_rois_for_pair(
        img_a,
        img_b,
        callout_debug_a_all,
        callout_debug_b_all,
        text_mask_a=ocr_mask_a,
        text_mask_b=ocr_mask_b,
    )
    callout_rois_a = filter_rois_by_mask(callout_rois_a, ocr_mask_a, max_overlap=CALLOUT_MASK_OVERLAP_DROP, limit=CALLOUT_MAX_ROIS)
    callout_rois_b = filter_rois_by_mask(callout_rois_b, ocr_mask_b, max_overlap=CALLOUT_MASK_OVERLAP_DROP, limit=CALLOUT_MAX_ROIS)
    callout_debug_a = filter_callout_debug_rows(callout_debug_a, callout_rois_a)
    callout_debug_b = filter_callout_debug_rows(callout_debug_b, callout_rois_b)
    if not callout_rois_a:
        callout_rois_a = filter_rois_by_mask(callout_rois_a_all, ocr_mask_a, max_overlap=CALLOUT_MASK_OVERLAP_DROP, limit=CALLOUT_MAX_ROIS)
        callout_debug_a = filter_callout_debug_rows(callout_debug_a_all, callout_rois_a)
    if not callout_rois_b:
        callout_rois_b = filter_rois_by_mask(callout_rois_b_all, ocr_mask_b, max_overlap=CALLOUT_MASK_OVERLAP_DROP, limit=CALLOUT_MAX_ROIS)
        callout_debug_b = filter_callout_debug_rows(callout_debug_b_all, callout_rois_b)

    pixel_rois_a = extract_pixel_diff_rois(img_a, img_b, guide_rois=list(callout_rois_a) + list(rois_geom_a), text_mask=ocr_mask_a)
    pixel_rois_b = extract_pixel_diff_rois(img_b, img_a, guide_rois=list(callout_rois_b) + list(rois_geom_b), text_mask=ocr_mask_b)

    rois_ground_a = merge_roi_groups([callout_rois_a, pixel_rois_a, rois_geom_a, rois_text_a], limit=24)
    rois_ground_b = merge_roi_groups([callout_rois_b, pixel_rois_b, rois_geom_b, rois_text_b], limit=24)
    if not rois_ground_a:
        rois_ground_a = rois_text_a
    if not rois_ground_b:
        rois_ground_b = rois_text_b

    console.print(
        f"  [dim]{la} ROI：粗差分 {len(coarse_a)}，文本候选 {len(rois_text_a)}，几何候选 {len(rois_geom_a)}，"
        f"引线候选 {len(callout_rois_a)}，像素候选 {len(pixel_rois_a)}[/dim]"
    )
    console.print(
        f"  [dim]{lb} ROI：粗差分 {len(coarse_b)}，文本候选 {len(rois_text_b)}，几何候选 {len(rois_geom_b)}，"
        f"引线候选 {len(callout_rois_b)}，像素候选 {len(pixel_rois_b)}[/dim]"
    )
    console.print(
        f"  [dim]OCR 对比：表格独有 A/B={ocr_pair_diff['summary'].get('table_only_in_a', 0)}/{ocr_pair_diff['summary'].get('table_only_in_b', 0)}，"
        f"文本独有 A/B={ocr_pair_diff['summary'].get('text_only_in_a', 0)}/{ocr_pair_diff['summary'].get('text_only_in_b', 0)}，"
        f"近似文本={ocr_pair_diff['summary'].get('total_near_mismatch', 0)}[/dim]"
    )

    img_a_visual = apply_ignore_mask_to_image(img_a, ocr_mask_a)
    img_b_visual = apply_ignore_mask_to_image(img_b, ocr_mask_b)
    diff_heat, diff_overlay, diff_stats = cvl.compute_visual_diff(img_a_visual, img_b_visual)
    overlay_path = pair_dir / f"{la}_vs_{lb}_overlay.png"
    heatmap_path = pair_dir / f"{la}_vs_{lb}_heatmap.png"
    cv2.imwrite(str(overlay_path), diff_overlay)
    cv2.imwrite(str(heatmap_path), diff_heat)

    dwg_diff = cvl.diff_dwg_strings(dwg_info[la], dwg_info[lb], la, lb)
    vlm_coarse = cvl.call_vl_model(cfg.base_url, cfg.api_key, cfg.vl_model, img_a_visual, img_b_visual, la, lb, diff_stats, dwg_diff)

    dwg_summary = (
        f"文件大小差 {dwg_diff['file_size_diff_kb']} KB；"
        f"仅{la}层/串:{dwg_diff['layers_only_in_a'][:8]}；"
        f"仅{lb}:{dwg_diff['layers_only_in_b'][:8]}；"
        f"{la}独有文:{dwg_diff['text_only_in_a'][:5]}；{lb}独有:{dwg_diff['text_only_in_b'][:5]}"
    )
    ocr_pair_hint = _ocr_pair_diff_snippet(ocr_pair_diff)
    analysis_for_ground = (
        f"【VLM 整图粗分析】\n{vlm_coarse[:2200]}\n\n"
        f"【OCR 文字差异摘要】\n{ocr_pair_hint}\n\n"
        f"【DWG/像素辅助】\n差异像素比例 {diff_stats.get('diff_pct')}% ；区域数 {diff_stats.get('diff_regions')} ；{dwg_summary[:700]}\n\n"
        f"【序号引线候选 ROI】\n{';'.join(str(list(bx)) for bx in callout_rois_a[:8]) or '（无）'}\n"
        f"【局部像素候选 ROI】\n{';'.join(str(list(bx)) for bx in pixel_rois_a[:8]) or '（无）'}\n"
        f"【几何候选 ROI】\n{';'.join(str(list(bx)) for bx in rois_geom_a[:8]) or '（无）'}\n"
        "OCR 文字差异已经单独处理；grounding 请优先关注结构、轮廓、装配位置与图形变化。"
    )

    gscan = "ROI分块" if VLM_GROUND_TILE_SCAN else "整图单次"
    console.print(f"  [dim]2D Grounding：VLM 双图（{la}/{lb} 各一轮，{gscan}）...[/dim]")
    try:
        model_items_a, raw_a = vl_grounding_primary_vs_reference(cfg, img_a, img_b, la, lb, analysis_for_ground, rois=rois_ground_a)
    except Exception as exc:
        model_items_a, raw_a = [], str(exc)
    try:
        model_items_b, raw_b = vl_grounding_primary_vs_reference(cfg, img_b, img_a, lb, la, analysis_for_ground, rois=rois_ground_b)
    except Exception as exc:
        model_items_b, raw_b = [], str(exc)
    grounding_method = "vlm_roi_tile" if VLM_GROUND_TILE_SCAN else "vlm_dual_image"

    items_a = sanitize_grounding_items(model_items_a, text_mask=ocr_mask_a, full_w=wa, full_h=ha)
    items_b = sanitize_grounding_items(model_items_b, text_mask=ocr_mask_b, full_w=wb, full_h=hb)
    if not items_a and model_items_a:
        items_a = sanitize_grounding_items(model_items_a, text_mask=None, full_w=wa, full_h=ha)
    if not items_b and model_items_b:
        items_b = sanitize_grounding_items(model_items_b, text_mask=None, full_w=wb, full_h=hb)

    items_a = merge_geometry_fallback_boxes(items_a, geom_rois=rois_geom_a, full_w=wa, full_h=ha)
    items_b = merge_geometry_fallback_boxes(items_b, geom_rois=rois_geom_b, full_w=wb, full_h=hb)
    items_a = merge_pixel_fallback_boxes(items_a, pixel_rois=pixel_rois_a, full_w=wa, full_h=ha)
    items_b = merge_pixel_fallback_boxes(items_b, pixel_rois=pixel_rois_b, full_w=wb, full_h=hb)
    if not items_a and items_b:
        items_a = mirror_items_fallback(items_b)
    if not items_b and items_a:
        items_b = mirror_items_fallback(items_a)

    items_a = filter_grounding_items_by_mask(items_a, mask=ocr_mask_a, full_w=wa, full_h=ha, max_overlap=0.25)
    items_b = filter_grounding_items_by_mask(items_b, mask=ocr_mask_b, full_w=wb, full_h=hb, max_overlap=0.25)

    render_items_a = _dedupe_render_annotations(list(items_a) + list(ocr_annotations_a))
    render_items_b = _dedupe_render_annotations(list(items_b) + list(ocr_annotations_b))

    ann_a = draw_grounding_boxes_cjk(img_a, render_items_a)
    ann_b = draw_grounding_boxes_cjk(img_b, render_items_b)
    path_a = pair_dir / f"{la}_annotated.png"
    path_b = pair_dir / f"{lb}_annotated.png"
    cv2.imwrite(str(path_a), ann_a)
    cv2.imwrite(str(path_b), ann_b)

    verdict_rois = list(callout_rois_a[:8]) + list(pixel_rois_a[:8]) + list(rois_text_a[:8])
    for bx in rois_geom_a[:12]:
        if any(_iou_xywh(bx, ex) >= 0.35 for ex in verdict_rois):
            continue
        verdict_rois.append(bx)
        if len(verdict_rois) >= 12:
            break
    roi_rows: list[dict[str, Any]] = []
    for bx in verdict_rois:
        roi_rows.append(
            {
                "bbox": list(bx),
                "text_a": extract_roi_text_from_ocr_page(page_a, bx, source_width=wa, source_height=ha) if page_a else "",
                "text_b": extract_roi_text_from_ocr_page(page_b, bx, source_width=wa, source_height=ha) if page_b else "",
            }
        )
    verdict = infer_roi_verdict(cfg, la, lb, roi_rows, dwg_summary, vlm_coarse, ocr_pair_hint)

    return {
        "pair": [la, lb],
        "vlm_coarse": vlm_coarse,
        "verdict": verdict,
        "grounding_method": grounding_method,
        "grounding_boxes_a": items_a,
        "grounding_boxes_b": items_b,
        "grounding_raw_a": str(raw_a)[-4000:],
        "grounding_raw_b": str(raw_b)[-4000:],
        "ocr_pair_diff": ocr_pair_diff,
        "ocr_annotations_a": ocr_annotations_a,
        "ocr_annotations_b": ocr_annotations_b,
        "render_annotations_a": render_items_a,
        "render_annotations_b": render_items_b,
        "ocr_doc_summary_a": ocr_doc_summaries.get(la, {}),
        "ocr_doc_summary_b": ocr_doc_summaries.get(lb, {}),
        "roi_rows": roi_rows,
        "roi_text_a": [list(bx) for bx in rois_text_a],
        "roi_text_b": [list(bx) for bx in rois_text_b],
        "roi_geometry_a": [list(bx) for bx in rois_geom_a],
        "roi_geometry_b": [list(bx) for bx in rois_geom_b],
        "roi_pixel_a": [list(bx) for bx in pixel_rois_a],
        "roi_pixel_b": [list(bx) for bx in pixel_rois_b],
        "roi_callout_a": [list(bx) for bx in callout_rois_a],
        "roi_callout_b": [list(bx) for bx in callout_rois_b],
        "callout_debug_a": callout_debug_a,
        "callout_debug_b": callout_debug_b,
        "diff_stats": diff_stats,
        "paths": {
            "annotated_a": str(path_a.relative_to(run_dir)),
            "annotated_b": str(path_b.relative_to(run_dir)),
            "overlay": str(overlay_path.relative_to(run_dir)),
            "heatmap": str(heatmap_path.relative_to(run_dir)),
        },
    }


def save_report_md(
    cfg: PipelineConfig,
    results: list[dict[str, Any]],
    n_way_text: str,
    ts: str,
    run_dir: Path,
    ocr_doc_summaries: dict[str, dict[str, Any]],
) -> Path:
    path = run_dir / "report.md"
    parts = [
        "# 图纸差异综合流水线报告",
        "",
        f"**时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**VLM**：{cfg.vl_model}  ",
        f"**OCR**：{cfg.ocr_model}  ",
        f"**输出目录**：`{run_dir.name}/`  ",
        "",
        "## OCR 综合分析",
        "",
        n_way_text,
        "",
        "## OCR 文档摘要",
        "",
    ]
    for label, summary in ocr_doc_summaries.items():
        parts.extend(
            [
                f"### {label}",
                "",
                f"- 页数：{summary.get('page_count', 0)}",
                f"- 文本行数：{summary.get('text_line_count', 0)}",
                f"- 表格行数：{summary.get('table_row_count', 0)}",
                f"- 标题栏候选：{summary.get('title_block_candidates', [])[:8]}",
                f"- BOM 样例：{summary.get('bom_samples', [])[:8]}",
                f"- 正文样例：{summary.get('text_samples', [])[:8]}",
                "",
            ]
        )

    for result in results:
        la, lb = result["pair"]
        summary = result["ocr_pair_diff"].get("summary", {}) or {}
        text_line = result["ocr_pair_diff"].get("text_line", {}) or {}
        table_row = result["ocr_pair_diff"].get("table_row", {}) or {}
        paths = result["paths"]
        parts.extend(
            [
                f"## 成对分析 {la} ↔ {lb}",
                "",
                "### 像素与视觉摘要",
                "",
                f"- 差异像素比例：{result['diff_stats'].get('diff_pct')}%",
                f"- Grounding：`{result.get('grounding_method', 'unknown')}`",
                f"- 引线 ROI（A/B）：{len(result.get('roi_callout_a', []))} / {len(result.get('roi_callout_b', []))}",
                f"- 像素 ROI（A/B）：{len(result.get('roi_pixel_a', []))} / {len(result.get('roi_pixel_b', []))}",
                f"- 几何 ROI（A/B）：{len(result.get('roi_geometry_a', []))} / {len(result.get('roi_geometry_b', []))}",
                "",
                "### OCR 文字差异摘要",
                "",
                f"- 表格独有 A/B：{summary.get('table_only_in_a', 0)} / {summary.get('table_only_in_b', 0)}",
                f"- 文本独有 A/B：{summary.get('text_only_in_a', 0)} / {summary.get('text_only_in_b', 0)}",
                f"- 近似文本（仅 JSON/报告，不参与标注）：{summary.get('total_near_mismatch', 0)}",
                f"- A 表格独有样例：{[item.get('text') for item in table_row.get('only_in_a', [])[:8]] or '无'}",
                f"- B 表格独有样例：{[item.get('text') for item in table_row.get('only_in_b', [])[:8]] or '无'}",
                f"- A 文本独有样例：{[item.get('text') for item in text_line.get('only_in_a', [])[:8]] or '无'}",
                f"- B 文本独有样例：{[item.get('text') for item in text_line.get('only_in_b', [])[:8]] or '无'}",
                "",
                "### VLM 粗分析",
                "",
                result["vlm_coarse"],
                "",
                "### ROI 推理判定",
                "",
                result["verdict"],
                "",
                "### 像素差分可视化",
                "",
                f"![overlay]({paths.get('overlay')})" if paths.get("overlay") else "_（无 overlay）_",
                "",
                f"![heatmap]({paths.get('heatmap')})" if paths.get("heatmap") else "_（无 heatmap）_",
                "",
                "### 分图标注（高清）",
                "",
                f"![{la}]({paths.get('annotated_a')})",
                "",
                f"![{lb}]({paths.get('annotated_b')})",
                "",
                "---",
                "",
            ]
        )
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def run_pipeline(
    cfg: PipelineConfig,
    *,
    documents: list[tuple[str, Path]],
    dwg_overrides: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """主入口。documents 为 [(label, pdf_path), ...]，N >= 2。

    返回包含 run_id / 输出路径 / 配对结果的字典。
    """
    if len(documents) < 2:
        raise ValueError("需要至少 2 个 PDF 才能进行成对差异分析。")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    cfg.output_dir = Path(cfg.output_dir).expanduser().resolve()
    run_dir = cfg.output_dir / f"pipeline_run_{ts}"
    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    console.print(
        Panel.fit(
            "[bold]图纸差异综合流水线[/bold]\n"
            f"输出目录：[cyan]{run_dir.name}[/cyan]\n"
            f"PDF 数量：{len(documents)}    成对组合：{len(list(combinations(range(len(documents)), 2)))}\n"
            "主链路：VLM 视觉差异 + OCR 文字差异",
            title="pdf-drawing-diff",
        )
    )

    console.print("\n[bold]阶段 A[/bold] OCR 预处理 …")
    api_key = resolve_api_key(cfg.zai_api_key)
    ocr_client = create_zhipu_client(api_key)
    processed_docs, document_meta, ocr_doc_summaries = prepare_ocr_documents(
        documents=documents,
        output_dir=run_dir / "rendered",
        client=ocr_client,
        model=cfg.ocr_model,
        dpi=cfg.dpi,
        timeout=cfg.ocr_timeout,
        max_pages=cfg.max_pages,
    )
    ocr_pages_by_label = {label: pages for label, pages in processed_docs}

    pairwise_ocr = [
        compare_ocr_documents(doc_a=doc_a, doc_b=doc_b, client=ocr_client, model=cfg.ocr_model, timeout=cfg.ocr_timeout)
        for doc_a, doc_b in combinations(processed_docs, 2)
    ]
    pairwise_ocr_by_key = {tuple(pair["pair"]): pair for pair in pairwise_ocr}
    n_way_text = _llm_n_way_analysis(cfg, ocr_doc_summaries=ocr_doc_summaries, pairwise_ocr=pairwise_ocr)

    console.print("\n[bold]阶段 B[/bold] 渲染图像与 DWG 字符串 …")
    rendered: dict[str, np.ndarray] = {}
    for label, pages in ocr_pages_by_label.items():
        if not pages:
            continue
        img = cv2.imread(str(pages[0].image_path))
        if img is not None:
            rendered[label] = img

    dwg_overrides = dwg_overrides or {}
    dwg_info: dict[str, dict] = {}
    for label, pdf_path in documents:
        dwg_path = dwg_overrides.get(label) or discover_dwg_for_pdf(pdf_path)
        if dwg_path and dwg_path.is_file():
            try:
                dwg_info[label] = cvl.extract_dwg_strings(dwg_path)
            except Exception as exc:
                console.print(f"[yellow]  DWG 解析失败 {dwg_path}: {exc}[/yellow]")
                dwg_info[label] = cvl.empty_dwg_info()
        else:
            dwg_info[label] = cvl.empty_dwg_info()

    console.print("\n[bold]阶段 C[/bold] 成对视觉 + OCR 融合 …")
    results: list[dict[str, Any]] = []
    pair_keys = [(la, lb) for la, lb in combinations([label for label, _ in documents], 2)]
    for la, lb in pair_keys:
        if la not in rendered or lb not in rendered:
            console.print(f"[yellow]  跳过 {la} vs {lb}：缺少渲染结果[/yellow]")
            continue
        pair_result = pairwise_ocr_by_key.get((la, lb)) or pairwise_ocr_by_key.get((lb, la))
        if pair_result is None:
            console.print(f"[yellow]  跳过 {la} vs {lb}：缺少 OCR 配对结果[/yellow]")
            continue
        results.append(
            run_pair(
                cfg,
                la=la,
                lb=lb,
                rendered=rendered,
                dwg_info=dwg_info,
                ocr_pages_by_label=ocr_pages_by_label,
                ocr_doc_summaries=ocr_doc_summaries,
                ocr_pair_result=pair_result,
                run_dir=run_dir,
            )
        )

    export_obj = {
        "run_id": ts,
        "vl_model": cfg.vl_model,
        "vl_api_style": cfg.vl_api_style,
        "text_model": cfg.text_model,
        "ocr_model": cfg.ocr_model,
        "documents": document_meta,
        "ocr_doc_summaries": ocr_doc_summaries,
        "n_way_analysis": n_way_text,
        "pairs": results,
    }
    json_path = run_dir / f"pipeline_result_{ts}.json"
    json_path.write_text(json.dumps(export_obj, ensure_ascii=False, indent=2), encoding="utf-8")

    pdf_path = run_dir / f"pipeline_annotated_{ts}.pdf"
    title_lines = [
        "pdf-drawing-diff 图纸差异流水线导出",
        f"run_id: {ts}",
        f"VLM: {cfg.vl_model}",
        f"OCR: {cfg.ocr_model}",
        f"PDF 数量: {len(documents)}",
        "",
        "以下为成对对比；每组含说明页与两张高清标注图（左图 A、右图 B 分开展示）。",
    ]
    pair_pages: list[tuple[str, str, Path, Path]] = []
    for result in results:
        la, lb = result["pair"]
        pair_dir = run_dir / f"{la}_vs_{lb}"
        pair_pages.append((la, lb, pair_dir / f"{la}_annotated.png", pair_dir / f"{lb}_annotated.png"))
    build_pipeline_pdf(pdf_path, title_lines, pair_pages)

    report = save_report_md(cfg, results, n_way_text, ts, run_dir, ocr_doc_summaries)

    console.print(f"\n[green]JSON  {json_path}[/green]")
    console.print(f"[green]PDF   {pdf_path}[/green]")
    console.print(f"[green]MD    {report}[/green]")
    console.print(f"[green]目录  {run_dir}[/green]")

    return {
        "run_id": ts,
        "run_dir": str(run_dir),
        "json": str(json_path),
        "pdf": str(pdf_path),
        "report": str(report),
        "pairs_processed": len(results),
        "pair_count_total": len(pair_keys),
    }
