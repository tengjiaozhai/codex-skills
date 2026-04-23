"""PDF -> PNG -> GLM-OCR -> text diff pipeline helpers."""

from __future__ import annotations

import base64
import html
import json
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from typing import Any, Sequence

import cv2
import fitz
import numpy as np

try:
    from .io_utils import draw_grounding_boxes_cjk
except ImportError:  # pragma: no cover - direct script execution
    from io_utils import draw_grounding_boxes_cjk

DEFAULT_MODEL = "glm-ocr"
DEFAULT_DPI = 220
DEFAULT_TIMEOUT = 180.0
MATCH_THRESHOLD = 0.97
NEAR_THRESHOLD = 0.90
DEFAULT_PLACEHOLDER_SIZE = (1600, 1200)
MAX_SECONDARY_OCR_BLOCKS_PER_PAGE = 12
TEXT_LINE_NOISE_RE = re.compile(r"^[0-9①②③④⑤⑥⑦⑧⑨⑩●○•◦·,，.。\-_/\\|]+$")
ALLOWED_TEXT_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff\s._\-+*/%&:#@()\[\]{}×=<>'\"°·,，:：;；]+")
TEXTLIKE_REGION_LABELS = {"text", "vision_footnote", "table"}


@dataclass
class RenderedPage:
    doc_label: str
    pdf_path: Path
    page_index: int
    image_path: Path
    image_width: int
    image_height: int


@dataclass
class OCRPage:
    doc_label: str
    pdf_path: Path
    page_index: int
    image_path: Path
    image_width: int
    image_height: int
    raw_response: dict[str, Any]
    units: list[dict[str, Any]]


def resolve_api_key(explicit_api_key: str) -> str:
    import os

    key = (
        explicit_api_key.strip()
        or os.getenv("ZAI_API_KEY", "").strip()
        or os.getenv("ZHIPUAI_API_KEY", "").strip()
    )
    if not key:
        raise RuntimeError("缺少 API Key，请设置 ZAI_API_KEY 或 ZHIPUAI_API_KEY。")
    return key


def parse_pdf_specs(specs: Sequence[str] | None) -> list[tuple[str, Path]]:
    if not specs:
        raise ValueError("至少需要一个 --pdf 参数。")

    parsed: list[tuple[str, Path]] = []
    seen_labels: set[str] = set()
    for raw in specs:
        value = str(raw or "").strip()
        if not value or "=" not in value:
            raise ValueError(f"--pdf 参数格式应为 LABEL=PATH，收到：{raw!r}")
        label, path_raw = value.split("=", 1)
        label = label.strip()
        if not label:
            raise ValueError(f"--pdf 参数缺少 LABEL：{raw!r}")
        if label in seen_labels:
            raise ValueError(f"重复的文档标签：{label}")
        path = Path(path_raw.strip()).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"PDF 不存在：{path}")
        seen_labels.add(label)
        parsed.append((label, path))
    return parsed


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def image_path_to_data_uri(path: Path) -> str:
    raw = path.read_bytes()
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


def render_pdf_to_pngs(
    *,
    doc_label: str,
    pdf_path: Path,
    output_dir: Path,
    dpi: int,
    max_pages: int | None,
) -> list[RenderedPage]:
    ensure_dir(output_dir)
    doc = fitz.open(str(pdf_path))
    pages: list[RenderedPage] = []
    try:
        total_pages = doc.page_count
        page_limit = total_pages if max_pages is None else min(total_pages, int(max_pages))
        mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
        for page_index in range(page_limit):
            page = doc.load_page(page_index)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            image_path = output_dir / f"page_{page_index + 1:03d}.png"
            image_path.write_bytes(pix.tobytes("png"))
            pages.append(
                RenderedPage(
                    doc_label=doc_label,
                    pdf_path=pdf_path,
                    page_index=page_index,
                    image_path=image_path,
                    image_width=int(pix.width),
                    image_height=int(pix.height),
                )
            )
    finally:
        doc.close()
    return pages


def recursive_to_plain(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): recursive_to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [recursive_to_plain(v) for v in obj]
    if hasattr(obj, "model_dump"):
        return recursive_to_plain(obj.model_dump())
    if hasattr(obj, "dict"):
        try:
            return recursive_to_plain(obj.dict())
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return recursive_to_plain(vars(obj))
    return repr(obj)


def create_zhipu_client(api_key: str) -> Any:
    try:
        from zai import ZhipuAiClient
    except Exception as exc:  # pragma: no cover - import failure is env-specific
        raise RuntimeError("缺少 zai 依赖，无法调用 GLM-OCR。") from exc
    return ZhipuAiClient(api_key=api_key)


def call_layout_parsing(
    client: Any,
    *,
    model: str,
    image_path: Path,
    timeout: float,
) -> dict[str, Any]:
    response = client.layout_parsing.create(
        model=model,
        file=image_path_to_data_uri(image_path),
        timeout=timeout,
    )
    return recursive_to_plain(response)


def _html_to_text(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def extract_table_rows(content: str) -> list[str]:
    raw = str(content or "").strip()
    if not raw:
        return []

    rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", raw, flags=re.IGNORECASE | re.DOTALL)
    if rows:
        out: list[str] = []
        for row_html in rows:
            cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row_html, flags=re.IGNORECASE | re.DOTALL)
            cell_texts: list[str] = []
            for cell in cells:
                text = _html_to_text(cell)
                if text:
                    cell_texts.append(text)
            if cell_texts:
                out.append(" | ".join(cell_texts))
        if out:
            return out

    fallback = _html_to_text(raw)
    return [line.strip() for line in fallback.splitlines() if line.strip()]


def extract_text_lines(content: str) -> list[str]:
    text = _html_to_text(str(content or ""))
    return [line.strip() for line in text.splitlines() if line.strip()]


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).strip().lower()
    value = re.sub(r"\s+", " ", value)
    value = ALLOWED_TEXT_RE.sub("", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def normalize_label(text: str) -> str:
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = re.sub(r"\s+", " ", value).strip()
    return value


def is_noise_text_line(text: str) -> bool:
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or "")))
    if not compact:
        return True
    if TEXT_LINE_NOISE_RE.fullmatch(compact):
        return True
    if len(compact) <= 4 and not re.search(r"[a-zA-Z\u4e00-\u9fff]", compact):
        return True
    return False


def _field_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _flatten_layout_regions(layout_details: Any) -> list[Any]:
    if not isinstance(layout_details, list):
        return []
    if layout_details and isinstance(layout_details[0], list):
        out: list[Any] = []
        for group in layout_details:
            if isinstance(group, list):
                out.extend(group)
        return out
    return list(layout_details)


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def normalize_bbox_px(bbox_raw: Any, image_width: int, image_height: int) -> list[int] | None:
    if not isinstance(bbox_raw, (list, tuple)) or len(bbox_raw) < 4:
        return None
    try:
        x1 = int(round(float(bbox_raw[0])))
        y1 = int(round(float(bbox_raw[1])))
        x2 = int(round(float(bbox_raw[2])))
        y2 = int(round(float(bbox_raw[3])))
    except Exception:
        return None
    x1 = _clamp(x1, 0, max(0, image_width - 1))
    y1 = _clamp(y1, 0, max(0, image_height - 1))
    x2 = _clamp(x2, x1 + 1, max(x1 + 1, image_width))
    y2 = _clamp(y2, y1 + 1, max(y1 + 1, image_height))
    return [x1, y1, x2, y2]


def bbox_px_to_bbox_2d(bbox_px: Sequence[int], image_width: int, image_height: int) -> list[int]:
    x1, y1, x2, y2 = [int(v) for v in bbox_px[:4]]
    if image_width <= 0 or image_height <= 0:
        return [0, 0, 1000, 1000]
    return [
        _clamp(int(round(x1 / image_width * 1000)), 0, 1000),
        _clamp(int(round(y1 / image_height * 1000)), 0, 1000),
        _clamp(int(round(x2 / image_width * 1000)), 0, 1000),
        _clamp(int(round(y2 / image_height * 1000)), 0, 1000),
    ]


def _merge_bbox_group(bboxes: Sequence[Sequence[int]]) -> list[int]:
    xs1 = [int(bbox[0]) for bbox in bboxes]
    ys1 = [int(bbox[1]) for bbox in bboxes]
    xs2 = [int(bbox[2]) for bbox in bboxes]
    ys2 = [int(bbox[3]) for bbox in bboxes]
    return [min(xs1), min(ys1), max(xs2), max(ys2)]


def _split_index_ranges(count: int, target_count: int) -> list[tuple[int, int]]:
    if count <= 0 or target_count <= 0:
        return []
    boundaries = np.linspace(0, count, target_count + 1, dtype=int)
    ranges: list[tuple[int, int]] = []
    for idx in range(target_count):
        start = int(boundaries[idx])
        end = int(boundaries[idx + 1])
        if end <= start:
            end = min(count, start + 1)
        ranges.append((start, min(count, end)))
    return ranges


def _crop_image_with_bbox(image: np.ndarray, bbox_px: Sequence[int]) -> np.ndarray:
    x1, y1, x2, y2 = [int(v) for v in bbox_px[:4]]
    return image[y1:y2, x1:x2].copy()


def _rebase_local_bbox(local_bbox: Sequence[int], parent_bbox: Sequence[int]) -> list[int]:
    px1, py1, _, _ = [int(v) for v in parent_bbox[:4]]
    x1, y1, x2, y2 = [int(v) for v in local_bbox[:4]]
    return [px1 + x1, py1 + y1, px1 + x2, py1 + y2]


def _estimate_local_row_bbox(
    binary_inv: np.ndarray,
    *,
    y1: int,
    y2: int,
    width: int,
    height: int,
) -> list[int]:
    y1 = _clamp(int(y1), 0, max(0, height - 1))
    y2 = _clamp(int(y2), y1 + 1, max(y1 + 1, height))
    band = binary_inv[y1:y2, :]
    if band.size == 0:
        return [0, y1, max(1, width), y2]

    col_signal = np.count_nonzero(band, axis=0)
    active_cols = np.where(col_signal > max(1, int((y2 - y1) * 0.08)))[0]
    if active_cols.size:
        x1 = max(0, int(active_cols[0]) - 4)
        x2 = min(width, int(active_cols[-1]) + 5)
        if (x2 - x1) >= int(width * 0.95):
            x1, x2 = 0, width
    else:
        x1, x2 = 0, width
    return [x1, y1, max(x1 + 1, x2), y2]


def _extract_row_bands(binary_inv: np.ndarray) -> list[tuple[int, int]]:
    height, width = binary_inv.shape[:2]
    if height <= 0 or width <= 0:
        return []

    row_signal = np.count_nonzero(binary_inv, axis=1).astype(np.float32)
    if not np.any(row_signal):
        return []
    kernel = np.ones(5, dtype=np.float32) / 5.0
    row_signal = np.convolve(row_signal, kernel, mode="same")
    active = row_signal > max(2, int(width * 0.01))

    raw_bands: list[tuple[int, int]] = []
    start: int | None = None
    for idx, is_active in enumerate(active.tolist()):
        if is_active and start is None:
            start = idx
        elif not is_active and start is not None:
            raw_bands.append((start, idx))
            start = None
    if start is not None:
        raw_bands.append((start, height))

    merge_gap = max(2, height // 80)
    min_band_height = max(2, height // 120)
    merged: list[tuple[int, int]] = []
    for band_start, band_end in raw_bands:
        if merged and band_start - merged[-1][1] <= merge_gap:
            merged[-1] = (merged[-1][0], band_end)
        else:
            merged.append((band_start, band_end))
    return [(start, end) for start, end in merged if (end - start) >= min_band_height]


def _prepare_binary_projection(crop_img: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary_inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    binary_inv = cv2.morphologyEx(
        binary_inv,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        iterations=1,
    )
    return binary_inv


def _projection_row_boxes(crop_img: np.ndarray, row_count: int) -> tuple[list[list[int]] | None, dict[str, Any]]:
    height, width = crop_img.shape[:2]
    if row_count <= 0 or height <= 1 or width <= 1:
        return None, {"band_count": 0, "low_confidence": True, "reason": "invalid_shape"}

    binary_inv = _prepare_binary_projection(crop_img)
    bands = _extract_row_bands(binary_inv)
    band_count = len(bands)
    if band_count < row_count:
        return None, {
            "band_count": band_count,
            "low_confidence": True,
            "reason": "insufficient_bands",
        }

    ranges = _split_index_ranges(band_count, row_count)
    row_boxes: list[list[int]] = []
    for start_idx, end_idx in ranges:
        group = bands[start_idx:end_idx]
        if not group:
            continue
        y1 = min(item[0] for item in group)
        y2 = max(item[1] for item in group)
        row_boxes.append(
            _estimate_local_row_bbox(binary_inv, y1=y1, y2=y2, width=width, height=height)
        )

    if len(row_boxes) != row_count:
        return None, {
            "band_count": band_count,
            "low_confidence": True,
            "reason": "projection_mapping_failed",
        }

    heights = [bbox[3] - bbox[1] for bbox in row_boxes]
    abnormal = any(h <= 1 for h in heights) or (
        bool(heights) and max(heights) >= int(height * 0.85) and row_count > 1
    )
    low_confidence = row_count >= 3 and (abs(band_count - row_count) > 1 or abnormal)
    return row_boxes, {
        "band_count": band_count,
        "low_confidence": low_confidence,
        "reason": "ok" if not low_confidence else "band_quality_low",
    }


def _equal_split_row_boxes(crop_img: np.ndarray, row_count: int) -> list[list[int]]:
    height, width = crop_img.shape[:2]
    if row_count <= 0:
        return []
    binary_inv = _prepare_binary_projection(crop_img)
    boundaries = np.linspace(0, height, row_count + 1, dtype=int)
    boxes: list[list[int]] = []
    for idx in range(row_count):
        y1 = int(boundaries[idx])
        y2 = int(boundaries[idx + 1])
        if y2 <= y1:
            y2 = min(height, y1 + 1)
        boxes.append(_estimate_local_row_bbox(binary_inv, y1=y1, y2=y2, width=width, height=height))
    return boxes


def _secondary_ocr_row_boxes(
    *,
    client: Any,
    model: str,
    timeout: float,
    crop_img: np.ndarray,
    row_count: int,
) -> list[list[int]] | None:
    if row_count <= 1:
        return None
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        if not cv2.imwrite(str(tmp_path), crop_img):
            return None
        raw_response = call_layout_parsing(
            client,
            model=model,
            image_path=tmp_path,
            timeout=timeout,
        )
    except Exception:
        return None
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    child_regions: list[list[int]] = []
    for region in _flatten_layout_regions(raw_response.get("layout_details") or []):
        label = str(_field_value(region, "label", "") or "").strip().lower()
        if label not in TEXTLIKE_REGION_LABELS:
            continue
        bbox = normalize_bbox_px(
            _field_value(region, "bbox_2d", None),
            image_width=int(crop_img.shape[1]),
            image_height=int(crop_img.shape[0]),
        )
        if bbox is None:
            continue
        child_regions.append(bbox)

    child_regions.sort(key=lambda bbox: (bbox[1], bbox[0]))
    if len(child_regions) < row_count or abs(len(child_regions) - row_count) > 1:
        return None

    boxes: list[list[int]] = []
    for start_idx, end_idx in _split_index_ranges(len(child_regions), row_count):
        group = child_regions[start_idx:end_idx]
        if not group:
            return None
        boxes.append(_merge_bbox_group(group))
    return boxes if len(boxes) == row_count else None


def _resolve_row_count_from_units(units: Sequence[dict[str, Any]]) -> int:
    if not units:
        return 1
    counts = [int(unit.get("block_row_count", 0) or 0) for unit in units]
    max_count = max(counts) if counts else 0
    return max(1, max_count or len(units))


def _apply_refined_bbox(
    unit: dict[str, Any],
    *,
    bbox_px: Sequence[int],
    bbox_source: str,
    image_width: int,
    image_height: int,
) -> None:
    ocr_block_bbox = normalize_bbox_px(
        unit.get("ocr_block_bbox_px") or unit.get("bbox_px"),
        image_width=image_width,
        image_height=image_height,
    )
    if ocr_block_bbox is None:
        ocr_block_bbox = [0, 0, max(1, image_width), max(1, image_height)]
    refined_bbox = normalize_bbox_px(
        bbox_px,
        image_width=image_width,
        image_height=image_height,
    )
    if refined_bbox is None:
        refined_bbox = ocr_block_bbox
        bbox_source = "equal_split_row"
    unit["ocr_block_bbox_px"] = ocr_block_bbox
    unit["ocr_block_bbox_2d"] = bbox_px_to_bbox_2d(ocr_block_bbox, image_width, image_height)
    unit["bbox_px"] = refined_bbox
    unit["bbox_2d"] = bbox_px_to_bbox_2d(refined_bbox, image_width, image_height)
    unit["bbox_scope"] = bbox_source
    unit["bbox_source"] = bbox_source


def _page_refinement_summary() -> dict[str, int]:
    return {
        "projection_row_count": 0,
        "equal_split_row_count": 0,
        "secondary_ocr_row_count": 0,
        "fallback_block_count": 0,
    }


def units_from_layout_details(
    *,
    doc_label: str,
    page_index: int,
    layout_details: Any,
    image_width: int,
    image_height: int,
) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for region in _flatten_layout_regions(layout_details):
        label = str(_field_value(region, "label", "") or "").strip().lower()
        content = str(_field_value(region, "content", "") or "").strip()
        if label == "image":
            continue
        bbox_px = normalize_bbox_px(
            _field_value(region, "bbox_2d", None),
            image_width=image_width,
            image_height=image_height,
        )
        if bbox_px is None:
            continue
        base = {
            "doc_label": doc_label,
            "page_index": page_index,
            "ocr_label": label,
            "parent_region_index": int(_field_value(region, "index", -1) or -1),
            "bbox_px": bbox_px,
            "bbox_2d": bbox_px_to_bbox_2d(bbox_px, image_width, image_height),
            "ocr_block_bbox_px": bbox_px,
            "ocr_block_bbox_2d": bbox_px_to_bbox_2d(bbox_px, image_width, image_height),
            "bbox_scope": "ocr_block",
            "bbox_source": "ocr_block",
        }
        if label == "table":
            rows = extract_table_rows(content)
            row_count = len(rows)
            for row_index, row in enumerate(rows):
                text_norm = normalize_text(row)
                if not text_norm:
                    continue
                units.append(
                    {
                        **base,
                        "unit_type": "table_row",
                        "text": row,
                        "text_norm": text_norm,
                        "row_index_in_block": row_index,
                        "block_row_count": row_count,
                    }
                )
            continue
        if not content:
            continue
        lines = extract_text_lines(content)
        row_count = len(lines)
        for row_index, line in enumerate(lines):
            if is_noise_text_line(line):
                continue
            text_norm = normalize_text(line)
            if not text_norm:
                continue
            units.append(
                {
                        **base,
                        "unit_type": "text_line",
                        "text": line,
                        "text_norm": text_norm,
                        "row_index_in_block": row_index,
                        "block_row_count": row_count,
                    }
                )
    return units


def _match_unit_group(
    units_a: list[dict[str, Any]],
    units_b: list[dict[str, Any]],
) -> dict[str, Any]:
    available_by_key: dict[str, list[int]] = {}
    for idx, unit in enumerate(units_b):
        available_by_key.setdefault(str(unit.get("text_norm", "")), []).append(idx)

    matched_a: set[int] = set()
    used_b: set[int] = set()

    for ia, unit_a in enumerate(units_a):
        key = str(unit_a.get("text_norm", ""))
        candidates = available_by_key.get(key, [])
        while candidates and candidates[0] in used_b:
            candidates.pop(0)
        if candidates:
            ib = candidates.pop(0)
            matched_a.add(ia)
            used_b.add(ib)

    near: list[dict[str, Any]] = []
    for ia, unit_a in enumerate(units_a):
        if ia in matched_a:
            continue
        best_ib = -1
        best_score = 0.0
        key_a = str(unit_a.get("text_norm", ""))
        for ib, unit_b in enumerate(units_b):
            if ib in used_b:
                continue
            key_b = str(unit_b.get("text_norm", ""))
            if not key_a or not key_b:
                continue
            score = SequenceMatcher(None, key_a, key_b).ratio()
            if score > best_score:
                best_score = score
                best_ib = ib
        if best_ib < 0:
            continue
        if best_score >= MATCH_THRESHOLD:
            matched_a.add(ia)
            used_b.add(best_ib)
        elif best_score >= NEAR_THRESHOLD:
            matched_a.add(ia)
            used_b.add(best_ib)
            near.append(
                {
                    "unit_type": unit_a["unit_type"],
                    "a": unit_a,
                    "b": units_b[best_ib],
                    "similarity": round(float(best_score), 4),
                }
            )

    only_in_a = [unit for idx, unit in enumerate(units_a) if idx not in matched_a]
    only_in_b = [unit for idx, unit in enumerate(units_b) if idx not in used_b]
    return {
        "only_in_a": only_in_a,
        "only_in_b": only_in_b,
        "near_mismatch": near,
        "matched_count": len(units_a) - len(only_in_a) - len(near),
    }


def compare_page_units(
    units_a: list[dict[str, Any]],
    units_b: list[dict[str, Any]],
) -> dict[str, Any]:
    table_a = [unit for unit in units_a if unit.get("unit_type") == "table_row"]
    table_b = [unit for unit in units_b if unit.get("unit_type") == "table_row"]
    text_a = [unit for unit in units_a if unit.get("unit_type") == "text_line"]
    text_b = [unit for unit in units_b if unit.get("unit_type") == "text_line"]

    table_diff = _match_unit_group(table_a, table_b)
    text_diff = _match_unit_group(text_a, text_b)

    summary = {
        "table_only_in_a": len(table_diff["only_in_a"]),
        "table_only_in_b": len(table_diff["only_in_b"]),
        "table_near_mismatch": len(table_diff["near_mismatch"]),
        "text_only_in_a": len(text_diff["only_in_a"]),
        "text_only_in_b": len(text_diff["only_in_b"]),
        "text_near_mismatch": len(text_diff["near_mismatch"]),
    }
    summary["total_only_in_a"] = summary["table_only_in_a"] + summary["text_only_in_a"]
    summary["total_only_in_b"] = summary["table_only_in_b"] + summary["text_only_in_b"]
    summary["total_near_mismatch"] = (
        summary["table_near_mismatch"] + summary["text_near_mismatch"]
    )

    return {
        "table_row": table_diff,
        "text_line": text_diff,
        "summary": summary,
    }


def _annotation_label(unit: dict[str, Any], *, diff_kind: str, similarity: float | None = None) -> str:
    prefix = "表格独有" if unit.get("unit_type") == "table_row" else "文本独有"
    if diff_kind == "near_mismatch":
        prefix = "近似文本"
    text = str(unit.get("text", "")).replace("\n", " ").strip()
    if similarity is not None:
        return f"{prefix}({similarity:.2f}): {text[:28]}"
    return f"{prefix}: {text[:28]}"


def unit_to_annotation(
    unit: dict[str, Any],
    *,
    diff_kind: str,
    similarity: float | None = None,
) -> dict[str, Any]:
    return {
        **unit,
        "diff_kind": diff_kind,
        "similarity": similarity,
        "label": _annotation_label(unit, diff_kind=diff_kind, similarity=similarity),
    }


def build_page_annotations(page_diff: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ann_a: list[dict[str, Any]] = []
    ann_b: list[dict[str, Any]] = []
    for group in ("table_row", "text_line"):
        data = page_diff[group]
        ann_a.extend(unit_to_annotation(unit, diff_kind="only_in_a") for unit in data["only_in_a"])
        ann_b.extend(unit_to_annotation(unit, diff_kind="only_in_b") for unit in data["only_in_b"])
    return ann_a, ann_b


def _collect_page_units_by_group(page: OCRPage) -> dict[tuple[str, int], list[dict[str, Any]]]:
    groups: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for unit in page.units:
        key = (str(unit.get("unit_type", "")), int(unit.get("parent_region_index", -1) or -1))
        groups.setdefault(key, []).append(unit)
    for items in groups.values():
        items.sort(key=lambda item: int(item.get("row_index_in_block", 0) or 0))
    return groups


def _collect_refinement_targets(
    page_diff: dict[str, Any],
    *,
    side: str,
) -> dict[tuple[str, int], list[dict[str, Any]]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    only_key = f"only_in_{side}"
    for group_name in ("table_row", "text_line"):
        group = page_diff[group_name]
        for unit in group[only_key]:
            key = (str(unit.get("unit_type", "")), int(unit.get("parent_region_index", -1) or -1))
            grouped.setdefault(key, []).append(unit)
        for pair in group["near_mismatch"]:
            unit = pair[side]
            key = (str(unit.get("unit_type", "")), int(unit.get("parent_region_index", -1) or -1))
            grouped.setdefault(key, []).append(unit)
    return grouped


def _refine_block_row_boxes(
    *,
    page_image: np.ndarray,
    block_bbox_px: Sequence[int],
    row_count: int,
    client: Any | None,
    model: str,
    timeout: float,
    allow_secondary_ocr: bool,
) -> tuple[list[list[int]], str, bool, bool]:
    normalized_block = normalize_bbox_px(
        block_bbox_px,
        image_width=int(page_image.shape[1]),
        image_height=int(page_image.shape[0]),
    )
    if normalized_block is None:
        fallback = [[0, 0, max(1, int(page_image.shape[1])), max(1, int(page_image.shape[0]))]]
        return fallback, "equal_split_row", True, False

    crop_img = _crop_image_with_bbox(page_image, normalized_block)
    if crop_img.size == 0:
        return [normalized_block for _ in range(max(1, row_count))], "equal_split_row", True, False

    projection_boxes_local, projection_meta = _projection_row_boxes(crop_img, row_count)
    if projection_boxes_local is not None and not projection_meta.get("low_confidence", False):
        rebased = [_rebase_local_bbox(bbox, normalized_block) for bbox in projection_boxes_local]
        return rebased, "projection_row", False, False

    if allow_secondary_ocr and client is not None and row_count >= 3:
        secondary_boxes_local = _secondary_ocr_row_boxes(
            client=client,
            model=model,
            timeout=timeout,
            crop_img=crop_img,
            row_count=row_count,
        )
        if secondary_boxes_local is not None:
            rebased = [_rebase_local_bbox(bbox, normalized_block) for bbox in secondary_boxes_local]
            return rebased, "secondary_ocr_row", True, True

    equal_boxes = _equal_split_row_boxes(crop_img, row_count)
    rebased = [_rebase_local_bbox(bbox, normalized_block) for bbox in equal_boxes]
    return rebased, "equal_split_row", True, False


def refine_page_diff_for_side(
    page_diff: dict[str, Any],
    *,
    page: OCRPage | None,
    side: str,
    client: Any | None,
    model: str,
    timeout: float,
    secondary_ocr_budget: int = MAX_SECONDARY_OCR_BLOCKS_PER_PAGE,
) -> tuple[int, dict[str, int]]:
    summary = _page_refinement_summary()
    if page is None:
        return secondary_ocr_budget, summary

    page_image = cv2.imread(str(page.image_path))
    if page_image is None:
        return secondary_ocr_budget, summary

    page_units_by_group = _collect_page_units_by_group(page)
    target_groups = _collect_refinement_targets(page_diff, side=side)

    for group_key, target_units in target_groups.items():
        region_index = int(group_key[1])
        if region_index < 0:
            for unit in target_units:
                _apply_refined_bbox(
                    unit,
                    bbox_px=unit.get("bbox_px") or [0, 0, page.image_width, page.image_height],
                    bbox_source=str(unit.get("bbox_source", "ocr_block")),
                    image_width=page.image_width,
                    image_height=page.image_height,
                )
            continue

        group_units = page_units_by_group.get(group_key) or target_units
        group_units = sorted(group_units, key=lambda item: int(item.get("row_index_in_block", 0) or 0))
        sample_unit = group_units[0]
        row_count = _resolve_row_count_from_units(group_units)
        allow_secondary = secondary_ocr_budget > 0
        row_boxes, bbox_source, used_fallback, used_secondary = _refine_block_row_boxes(
            page_image=page_image,
            block_bbox_px=sample_unit.get("ocr_block_bbox_px") or sample_unit.get("bbox_px"),
            row_count=row_count,
            client=client,
            model=model,
            timeout=timeout,
            allow_secondary_ocr=allow_secondary,
        )
        if used_secondary:
            secondary_ocr_budget -= 1
        if bbox_source != "projection_row":
            summary["fallback_block_count"] += 1

        for unit in target_units:
            row_index = int(unit.get("row_index_in_block", 0) or 0)
            row_index = _clamp(row_index, 0, max(0, len(row_boxes) - 1))
            _apply_refined_bbox(
                unit,
                bbox_px=row_boxes[row_index],
                bbox_source=bbox_source,
                image_width=page.image_width,
                image_height=page.image_height,
            )
            if bbox_source == "projection_row":
                summary["projection_row_count"] += 1
            elif bbox_source == "secondary_ocr_row":
                summary["secondary_ocr_row_count"] += 1
            elif bbox_source == "equal_split_row":
                summary["equal_split_row_count"] += 1

    return secondary_ocr_budget, summary


def create_placeholder_image(
    path: Path,
    *,
    width: int,
    height: int,
    label: str,
) -> None:
    img = np.full((height, width, 3), 255, dtype=np.uint8)
    annotated = draw_grounding_boxes_cjk(
        img,
        [{"bbox_2d": [20, 20, 980, 980], "label": label}],
    )
    cv2.imwrite(str(path), annotated)


def copy_or_placeholder_render(
    source: Path | None,
    target: Path,
    *,
    width: int,
    height: int,
    label: str | None = None,
) -> None:
    if source is not None and source.exists():
        shutil.copy2(source, target)
        return
    create_placeholder_image(target, width=width, height=height, label=label or "无对应页")


def annotate_image_file(
    *,
    source_path: Path | None,
    target_path: Path,
    annotations: list[dict[str, Any]],
    width: int,
    height: int,
    placeholder_label: str | None = None,
) -> None:
    if source_path is None or not source_path.exists():
        create_placeholder_image(
            target_path,
            width=width,
            height=height,
            label=placeholder_label or "无对应页",
        )
        return
    img = cv2.imread(str(source_path))
    if img is None:
        create_placeholder_image(
            target_path,
            width=width,
            height=height,
            label=placeholder_label or "图片读取失败",
        )
        return
    annotated = draw_grounding_boxes_cjk(img, annotations)
    cv2.imwrite(str(target_path), annotated)


def _blank_page_diff(label: str, page_index: int, width: int, height: int) -> dict[str, Any]:
    full_bbox_px = [0, 0, width, height]
    full_unit = {
        "doc_label": label,
        "page_index": page_index,
        "unit_type": "text_line",
        "text": "整页独有",
        "text_norm": normalize_text("整页独有"),
        "ocr_label": "page_only",
        "parent_region_index": -1,
        "bbox_px": full_bbox_px,
        "bbox_2d": bbox_px_to_bbox_2d(full_bbox_px, width, height),
        "ocr_block_bbox_px": full_bbox_px,
        "ocr_block_bbox_2d": bbox_px_to_bbox_2d(full_bbox_px, width, height),
        "bbox_scope": "ocr_block",
        "bbox_source": "ocr_block",
        "row_index_in_block": 0,
        "block_row_count": 1,
    }
    return {
        "table_row": {"only_in_a": [], "only_in_b": [], "near_mismatch": [], "matched_count": 0},
        "text_line": {"only_in_a": [full_unit], "only_in_b": [], "near_mismatch": [], "matched_count": 0},
        "summary": {
            "table_only_in_a": 0,
            "table_only_in_b": 0,
            "table_near_mismatch": 0,
            "text_only_in_a": 1,
            "text_only_in_b": 0,
            "text_near_mismatch": 0,
            "total_only_in_a": 1,
            "total_only_in_b": 0,
            "total_near_mismatch": 0,
        },
        "refinement_summary": _page_refinement_summary(),
    }


def _page_only_diff(label: str, page_index: int, width: int, height: int, *, side: str) -> dict[str, Any]:
    page_diff = _blank_page_diff(label, page_index, width, height)
    page_diff["page_only_in"] = label
    full_unit = page_diff["text_line"]["only_in_a"][0]
    if side == "b":
        page_diff["summary"] = {
            "table_only_in_a": 0,
            "table_only_in_b": 0,
            "table_near_mismatch": 0,
            "text_only_in_a": 0,
            "text_only_in_b": 1,
            "text_near_mismatch": 0,
            "total_only_in_a": 0,
            "total_only_in_b": 1,
            "total_near_mismatch": 0,
        }
        page_diff["text_line"] = {
            "only_in_a": [],
            "only_in_b": [full_unit],
            "near_mismatch": [],
            "matched_count": 0,
        }
    return page_diff


def _unit_presence_key(unit: dict[str, Any]) -> str:
    return f"{unit.get('unit_type', '')}::{unit.get('text_norm', '')}"


def scale_bbox_xyxy(
    bbox_px: Sequence[int],
    *,
    src_width: int,
    src_height: int,
    dst_width: int,
    dst_height: int,
) -> list[int]:
    if src_width <= 0 or src_height <= 0:
        return [0, 0, max(1, dst_width), max(1, dst_height)]
    x1, y1, x2, y2 = [int(v) for v in bbox_px[:4]]
    sx = dst_width / float(src_width)
    sy = dst_height / float(src_height)
    scaled = [
        int(round(x1 * sx)),
        int(round(y1 * sy)),
        int(round(x2 * sx)),
        int(round(y2 * sy)),
    ]
    normalized = normalize_bbox_px(scaled, image_width=dst_width, image_height=dst_height)
    return normalized or [0, 0, max(1, dst_width), max(1, dst_height)]


def scale_xywh_box(
    box: Sequence[int],
    *,
    src_width: int,
    src_height: int,
    dst_width: int,
    dst_height: int,
) -> tuple[int, int, int, int]:
    x, y, w, h = [int(v) for v in box[:4]]
    scaled = scale_bbox_xyxy(
        [x, y, x + w, y + h],
        src_width=src_width,
        src_height=src_height,
        dst_width=dst_width,
        dst_height=dst_height,
    )
    return scaled[0], scaled[1], scaled[2] - scaled[0], scaled[3] - scaled[1]


def _intersects_xyxy(a: Sequence[int], b: Sequence[int]) -> bool:
    ax1, ay1, ax2, ay2 = [int(v) for v in a[:4]]
    bx1, by1, bx2, by2 = [int(v) for v in b[:4]]
    return min(ax2, bx2) > max(ax1, bx1) and min(ay2, by2) > max(ay1, by1)


def _intersection_area_xyxy(a: Sequence[int], b: Sequence[int]) -> int:
    ax1, ay1, ax2, ay2 = [int(v) for v in a[:4]]
    bx1, by1, bx2, by2 = [int(v) for v in b[:4]]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0
    return (ix2 - ix1) * (iy2 - iy1)


def collect_ocr_block_boxes(
    page: OCRPage,
    *,
    unit_types: Sequence[str] | None = None,
    target_width: int | None = None,
    target_height: int | None = None,
) -> list[tuple[int, int, int, int]]:
    want_unit_types = {str(v) for v in unit_types} if unit_types else None
    seen: set[tuple[int, int, int, int, str]] = set()
    boxes: list[tuple[int, int, int, int]] = []
    for unit in page.units:
        if want_unit_types and str(unit.get("unit_type", "")) not in want_unit_types:
            continue
        bbox = unit.get("ocr_block_bbox_px") or unit.get("bbox_px")
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
        if target_width is not None and target_height is not None:
            x1, y1, x2, y2 = scale_bbox_xyxy(
                [x1, y1, x2, y2],
                src_width=page.image_width,
                src_height=page.image_height,
                dst_width=target_width,
                dst_height=target_height,
            )
        key = (x1, y1, x2, y2, str(unit.get("unit_type", "")))
        if key in seen:
            continue
        seen.add(key)
        boxes.append((x1, y1, max(1, x2 - x1), max(1, y2 - y1)))
    return boxes


def build_mask_from_boxes(
    *,
    width: int,
    height: int,
    boxes: Sequence[Sequence[int]],
    pad: int = 0,
) -> np.ndarray | None:
    if width <= 0 or height <= 0 or not boxes:
        return None
    mask = np.zeros((height, width), dtype=np.uint8)
    for box in boxes:
        x, y, w, h = [int(v) for v in box[:4]]
        x0 = _clamp(x - pad, 0, width)
        y0 = _clamp(y - pad, 0, height)
        x1 = _clamp(x + w + pad, x0 + 1, width)
        y1 = _clamp(y + h + pad, y0 + 1, height)
        mask[y0:y1, x0:x1] = 255
    return mask


def collect_hint_items_from_ocr_page(
    page: OCRPage,
    *,
    target_width: int | None = None,
    target_height: int | None = None,
) -> list[dict[str, Any]]:
    seen: set[tuple[str, int, int, int, int]] = set()
    out: list[dict[str, Any]] = []
    for unit in page.units:
        if unit.get("unit_type") != "text_line":
            continue
        text = str(unit.get("text", "")).strip()
        compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
        if not compact or len(compact) > 8:
            continue
        if not re.fullmatch(r"[0-9①②③④⑤⑥⑦⑧⑨⑩●○•◦·]+", compact):
            continue
        bbox = unit.get("ocr_block_bbox_px") or unit.get("bbox_px")
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            continue
        x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
        if target_width is not None and target_height is not None:
            x1, y1, x2, y2 = scale_bbox_xyxy(
                [x1, y1, x2, y2],
                src_width=page.image_width,
                src_height=page.image_height,
                dst_width=target_width,
                dst_height=target_height,
            )
        box_xywh = (x1, y1, max(1, x2 - x1), max(1, y2 - y1))
        key = (compact, box_xywh[0], box_xywh[1], box_xywh[2], box_xywh[3])
        if key in seen:
            continue
        seen.add(key)
        out.append({"text": compact, "bbox": box_xywh})
    return out


def extract_roi_text_from_ocr_page(
    page: OCRPage,
    roi_img: Sequence[int],
    *,
    source_width: int,
    source_height: int,
    limit: int = 12,
) -> str:
    rx, ry, rw, rh = [int(v) for v in roi_img[:4]]
    target_bbox = scale_bbox_xyxy(
        [rx, ry, rx + rw, ry + rh],
        src_width=source_width,
        src_height=source_height,
        dst_width=page.image_width,
        dst_height=page.image_height,
    )
    ranked: list[tuple[int, int, int, str]] = []
    seen_texts: set[str] = set()
    for unit in page.units:
        bbox = unit.get("ocr_block_bbox_px") or unit.get("bbox_px")
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            continue
        area = _intersection_area_xyxy(target_bbox, bbox)
        if area <= 0:
            continue
        text = normalize_label(str(unit.get("text", "")))
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        ranked.append((area, int(bbox[1]), int(bbox[0]), text))
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))
    return normalize_label(" | ".join(text for _, _, _, text in ranked[:limit]))[:600]


def build_ocr_document_summary(
    label: str,
    pages: Sequence[OCRPage],
) -> dict[str, Any]:
    page_count = len(pages)
    text_units = [unit for page in pages for unit in page.units if unit.get("unit_type") == "text_line"]
    table_units = [unit for page in pages for unit in page.units if unit.get("unit_type") == "table_row"]

    title_candidates: list[str] = []
    bom_samples: list[str] = []
    text_samples: list[str] = []
    title_seen: set[str] = set()
    bom_seen: set[str] = set()
    text_seen: set[str] = set()

    for page in pages:
        for unit in page.units:
            text = normalize_label(str(unit.get("text", "")))
            if not text:
                continue
            bbox = unit.get("ocr_block_bbox_px") or unit.get("bbox_px") or [0, 0, page.image_width, page.image_height]
            x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
            if (
                text not in title_seen
                and (x1 >= int(page.image_width * 0.62) or y1 >= int(page.image_height * 0.72))
                and len(title_candidates) < 12
            ):
                title_seen.add(text)
                title_candidates.append(text)
            if unit.get("unit_type") == "table_row" and text not in bom_seen and len(bom_samples) < 12:
                bom_seen.add(text)
                bom_samples.append(text)
            if unit.get("unit_type") == "text_line" and text not in text_seen and len(text_samples) < 12:
                text_seen.add(text)
                text_samples.append(text)

    return {
        "label": label,
        "page_count": page_count,
        "text_line_count": len(text_units),
        "table_row_count": len(table_units),
        "title_block_candidates": title_candidates,
        "bom_samples": bom_samples,
        "text_samples": text_samples,
    }


def prepare_ocr_documents(
    *,
    documents: Sequence[tuple[str, Path]],
    output_dir: Path,
    client: Any,
    model: str,
    dpi: int,
    timeout: float,
    max_pages: int | None = 1,
) -> tuple[list[tuple[str, list[OCRPage]]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    ensure_dir(output_dir)
    processed_docs: list[tuple[str, list[OCRPage]]] = []
    document_meta: list[dict[str, Any]] = []
    doc_summaries: dict[str, dict[str, Any]] = {}
    for label, pdf_path in documents:
        render_pages = render_pdf_to_pngs(
            doc_label=label,
            pdf_path=pdf_path,
            output_dir=output_dir / label,
            dpi=dpi,
            max_pages=max_pages,
        )
        ocr_pages = process_rendered_pages(
            client=client,
            doc_label=label,
            pdf_path=pdf_path,
            pages=render_pages,
            model=model,
            timeout=timeout,
        )
        processed_docs.append((label, ocr_pages))
        document_meta.append({"label": label, "path": str(pdf_path), "pages": len(ocr_pages)})
        doc_summaries[label] = build_ocr_document_summary(label, ocr_pages)
    return processed_docs, document_meta, doc_summaries


def compare_ocr_pages(
    *,
    label_a: str,
    page_a: OCRPage | None,
    label_b: str,
    page_b: OCRPage | None,
    client: Any | None,
    model: str,
    timeout: float,
) -> dict[str, Any]:
    ref_page = page_a or page_b
    if ref_page is None:
        raise ValueError("compare_ocr_pages 需要至少一个页面输入。")

    width = ref_page.image_width
    height = ref_page.image_height
    if page_a is not None and page_b is not None:
        page_diff = compare_page_units(page_a.units, page_b.units)
        _, refinement_a = refine_page_diff_for_side(
            page_diff,
            page=page_a,
            side="a",
            client=client,
            model=model,
            timeout=timeout,
        )
        _, refinement_b = refine_page_diff_for_side(
            page_diff,
            page=page_b,
            side="b",
            client=client,
            model=model,
            timeout=timeout,
            secondary_ocr_budget=MAX_SECONDARY_OCR_BLOCKS_PER_PAGE,
        )
        page_diff["refinement_summary"] = {
            key: int(refinement_a.get(key, 0)) + int(refinement_b.get(key, 0))
            for key in _page_refinement_summary()
        }
    elif page_a is not None:
        page_diff = _page_only_diff(label_a, page_a.page_index, width, height, side="a")
    else:
        page_diff = _page_only_diff(label_b, page_b.page_index if page_b is not None else 0, width, height, side="b")

    annotations_a, annotations_b = build_page_annotations(page_diff)
    for item in annotations_a:
        item["source"] = f"ocr_{item.get('unit_type', 'item')}"
    for item in annotations_b:
        item["source"] = f"ocr_{item.get('unit_type', 'item')}"

    return {
        "page_index": int(ref_page.page_index),
        "summary": page_diff["summary"],
        "refinement_summary": page_diff.get("refinement_summary", _page_refinement_summary()),
        "table_row": page_diff["table_row"],
        "text_line": page_diff["text_line"],
        "ocr_annotations_a": annotations_a,
        "ocr_annotations_b": annotations_b,
        "page_only_in": page_diff.get("page_only_in"),
    }


def compare_ocr_documents(
    *,
    doc_a: tuple[str, list[OCRPage]],
    doc_b: tuple[str, list[OCRPage]],
    client: Any | None,
    model: str,
    timeout: float,
) -> dict[str, Any]:
    label_a, pages_a = doc_a
    label_b, pages_b = doc_b
    pages_by_index_a = {page.page_index: page for page in pages_a}
    pages_by_index_b = {page.page_index: page for page in pages_b}
    page_indexes = sorted(set(pages_by_index_a) | set(pages_by_index_b))
    pages_out: list[dict[str, Any]] = []
    for page_index in page_indexes:
        pages_out.append(
            compare_ocr_pages(
                label_a=label_a,
                page_a=pages_by_index_a.get(page_index),
                label_b=label_b,
                page_b=pages_by_index_b.get(page_index),
                client=client,
                model=model,
                timeout=timeout,
            )
        )
    return {
        "pair": [label_a, label_b],
        "pages": pages_out,
        "summary": _summary_from_pages(pages_out),
    }


def build_three_way_ocr_context(
    *,
    doc_summaries: dict[str, dict[str, Any]],
    pairwise_results: Sequence[dict[str, Any]],
) -> str:
    doc_sections: list[str] = []
    for label, summary in doc_summaries.items():
        doc_sections.append(
            (
                f"【{label}】页数={summary.get('page_count', 0)}，"
                f"text_line={summary.get('text_line_count', 0)}，"
                f"table_row={summary.get('table_row_count', 0)}\n"
                f"标题栏候选(前8): {summary.get('title_block_candidates', [])[:8]}\n"
                f"BOM样例(前8): {summary.get('bom_samples', [])[:8]}\n"
                f"正文样例(前8): {summary.get('text_samples', [])[:8]}"
            )
        )

    pair_sections: list[str] = []
    for pair in pairwise_results:
        la, lb = pair["pair"]
        summary = pair["summary"]
        page = pair["pages"][0] if pair.get("pages") else {}
        pair_sections.append(
            (
                f"【{la} vs {lb}】"
                f"表格独有 A/B={summary.get('table_only_in_a', 0)}/{summary.get('table_only_in_b', 0)}，"
                f"文本独有 A/B={summary.get('text_only_in_a', 0)}/{summary.get('text_only_in_b', 0)}，"
                f"近似文本={summary.get('total_near_mismatch', 0)}\n"
                f"A表格独有样例: {[(item.get('text')) for item in page.get('table_row', {}).get('only_in_a', [])[:6]]}\n"
                f"B表格独有样例: {[(item.get('text')) for item in page.get('table_row', {}).get('only_in_b', [])[:6]]}\n"
                f"A文本独有样例: {[(item.get('text')) for item in page.get('text_line', {}).get('only_in_a', [])[:6]]}\n"
                f"B文本独有样例: {[(item.get('text')) for item in page.get('text_line', {}).get('only_in_b', [])[:6]]}\n"
                f"近似文本样例: {[(item.get('a', {}).get('text')) for item in page.get('text_line', {}).get('near_mismatch', [])[:6]]}"
            )
        )
    return "=== OCR 文档摘要 ===\n" + "\n\n".join(doc_sections) + "\n\n=== OCR 两两差异 ===\n" + "\n\n".join(pair_sections)


def build_static_three_way_ocr_summary(
    *,
    doc_summaries: dict[str, dict[str, Any]],
    pairwise_results: Sequence[dict[str, Any]],
) -> str:
    lines = ["## 一、图纸 OCR 概览对比", ""]
    lines.append("| 机型 | 页数 | 文本行数 | 表格行数 | 标题栏候选 |")
    lines.append("|------|------|----------|----------|------------|")
    for label, summary in doc_summaries.items():
        title_hint = " / ".join(summary.get("title_block_candidates", [])[:3]) or "无"
        lines.append(
            f"| {label} | {summary.get('page_count', 0)} | {summary.get('text_line_count', 0)} | "
            f"{summary.get('table_row_count', 0)} | {title_hint} |"
        )

    lines.extend(["", "## 二、两两 OCR 差异摘要", ""])
    for pair in pairwise_results:
        la, lb = pair["pair"]
        summary = pair["summary"]
        lines.append(
            f"### {la} ↔ {lb}\n"
            f"- 表格独有 A/B：{summary.get('table_only_in_a', 0)} / {summary.get('table_only_in_b', 0)}\n"
            f"- 文本独有 A/B：{summary.get('text_only_in_a', 0)} / {summary.get('text_only_in_b', 0)}\n"
            f"- 近似文本：{summary.get('total_near_mismatch', 0)}"
        )

    lines.extend(["", "## 三、三机型横向规律总结", ""])
    counts = {label: summary.get("table_row_count", 0) + summary.get("text_line_count", 0) for label, summary in doc_summaries.items()}
    if counts:
        max_label = max(counts, key=counts.get)
        min_label = min(counts, key=counts.get)
        lines.append(f"- OCR 可见文字量：{max_label} 最多（{counts[max_label]}），{min_label} 最少（{counts[min_label]}）。")
    lines.append("- 三机型差异以 OCR 识别到的正文与表格行为基础，近似文本仅做统计，不参与框选。")

    lines.extend(["", "## 四、风险提示", ""])
    for pair in pairwise_results:
        la, lb = pair["pair"]
        summary = pair["summary"]
        if summary.get("table_only_in_a", 0) or summary.get("table_only_in_b", 0) or summary.get("text_only_in_a", 0) or summary.get("text_only_in_b", 0):
            lines.append(f"- **{la} vs {lb}**：存在 OCR 独有文字/表格差异，需结合标注图人工复核。")

    lines.extend(["", "## 五、综合评审结论", ""])
    total_only = sum(pair["summary"].get("total_only_in_a", 0) + pair["summary"].get("total_only_in_b", 0) for pair in pairwise_results)
    total_near = sum(pair["summary"].get("total_near_mismatch", 0) for pair in pairwise_results)
    lines.append(
        f"当前三机型在 OCR 文字层面共识别到 {total_only} 项明确独有差异、{total_near} 项近似差异。"
        "建议以最终合并标注图为主进行人工复核。"
    )
    return "\n".join(lines)


def build_three_way_ocr_messages(
    *,
    doc_summaries: dict[str, dict[str, Any]],
    pairwise_results: Sequence[dict[str, Any]],
) -> tuple[str, str]:
    context = build_three_way_ocr_context(
        doc_summaries=doc_summaries,
        pairwise_results=pairwise_results,
    )
    system_prompt = """你是一名资深机械结构工程师，专注于组件爆炸图与工程图差异审查。

当前输入来自 OCR 抽取后的三机型摘要与两两差异统计。请基于这些信息输出：

## 一、图纸 OCR 概览对比
- 三份图纸的页数、正文文字量、表格/BOM 文字量、标题栏候选信息

## 二、关键差异点（两两对比）
- 各组 pair 的表格独有项
- 各组 pair 的正文独有项
- 近似文本项的含义与人工复核建议

## 三、三机型横向规律总结
- 共同点
- 机型间演进趋势
- 可能的设计或文档表达差异

## 四、风险提示
- 需要结合最终标注图重点复核的区域或文字差异

## 五、综合评审结论
- 用 2-3 句话给出总结

语言：中文，专业严谨，尽量用表格和清晰小节。"""
    user_prompt = f"请基于以下 OCR 文档摘要与两两差异结果，完成三机型横向差异分析：\n\n{context}"
    return system_prompt, user_prompt


def build_multi_doc_summary(
    documents: Sequence[tuple[str, list[OCRPage]]],
    pairwise: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    presence: dict[str, dict[str, Any]] = {}
    all_labels = [label for label, _ in documents]
    for label, pages in documents:
        seen_keys: set[str] = set()
        for page in pages:
            for unit in page.units:
                key = _unit_presence_key(unit)
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                entry = presence.setdefault(
                    key,
                    {
                        "unit_type": unit.get("unit_type"),
                        "text_norm": unit.get("text_norm"),
                        "sample_text": unit.get("text"),
                        "documents": [],
                    },
                )
                entry["documents"].append(label)

    common_to_all: list[dict[str, Any]] = []
    shared_by_subset: list[dict[str, Any]] = []
    unique_by_doc: dict[str, list[dict[str, Any]]] = {label: [] for label in all_labels}
    for entry in presence.values():
        doc_list = sorted(set(str(v) for v in entry["documents"]))
        item = {
            "unit_type": entry["unit_type"],
            "text_norm": entry["text_norm"],
            "sample_text": entry["sample_text"],
            "documents": doc_list,
        }
        if len(doc_list) == len(all_labels):
            common_to_all.append(item)
        elif len(doc_list) == 1:
            unique_by_doc[doc_list[0]].append(item)
        else:
            shared_by_subset.append(item)

    pairwise_counts: dict[str, Any] = {}
    for pair in pairwise:
        la, lb = pair["pair"]
        pairwise_counts[f"{la}_vs_{lb}"] = pair["summary"]

    return {
        "common_to_all": sorted(common_to_all, key=lambda d: (d["unit_type"], d["text_norm"])),
        "shared_by_subset": sorted(shared_by_subset, key=lambda d: (d["unit_type"], d["text_norm"])),
        "unique_by_doc": {
            label: sorted(items, key=lambda d: (d["unit_type"], d["text_norm"]))
            for label, items in unique_by_doc.items()
        },
        "pairwise_counts": pairwise_counts,
    }


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def process_rendered_pages(
    *,
    client: Any,
    doc_label: str,
    pdf_path: Path,
    pages: Sequence[RenderedPage],
    model: str,
    timeout: float,
) -> list[OCRPage]:
    out: list[OCRPage] = []
    for page in pages:
        raw_response = call_layout_parsing(
            client,
            model=model,
            image_path=page.image_path,
            timeout=timeout,
        )
        layout_details = raw_response.get("layout_details") or []
        units = units_from_layout_details(
            doc_label=doc_label,
            page_index=page.page_index,
            layout_details=layout_details,
            image_width=page.image_width,
            image_height=page.image_height,
        )
        out.append(
            OCRPage(
                doc_label=doc_label,
                pdf_path=pdf_path,
                page_index=page.page_index,
                image_path=page.image_path,
                image_width=page.image_width,
                image_height=page.image_height,
                raw_response=raw_response,
                units=units,
            )
        )
    return out


def _summary_from_pages(pages: Sequence[dict[str, Any]]) -> dict[str, int]:
    keys = (
        "table_only_in_a",
        "table_only_in_b",
        "table_near_mismatch",
        "text_only_in_a",
        "text_only_in_b",
        "text_near_mismatch",
        "total_only_in_a",
        "total_only_in_b",
        "total_near_mismatch",
    )
    summary = {key: 0 for key in keys}
    for page in pages:
        page_summary = page["summary"]
        for key in keys:
            summary[key] += int(page_summary.get(key, 0))
    return summary
