from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from itertools import combinations
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ocr as OCR
import pipeline as PIPELINE
import run_pdf_drawing_diff as CLI


class TestPdfDrawingDiffCore(unittest.TestCase):
    def test_build_documents_auto_labels_and_dedupes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            a = root / "same name-Model.pdf"
            b = root / "same name-Model(2).pdf"
            a.write_bytes(b"%PDF-1.0")
            b.write_bytes(b"%PDF-1.0")

            args = argparse.Namespace(label=[], pdf=[str(a), str(b)], dwg=[])
            docs = CLI._build_documents(args)

        self.assertEqual(len(docs), 2)
        self.assertEqual(docs[0][0], "same name")
        self.assertEqual(docs[1][0], "same name-Model(2)")

    def test_pairwise_count_for_four_inputs(self) -> None:
        docs = [(f"doc-{idx}", Path(f"/tmp/doc-{idx}.pdf")) for idx in range(4)]
        pair_count = len(list(combinations([label for label, _ in docs], 2)))
        self.assertEqual(pair_count, 6)

    def test_discover_dwg_for_model_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            pdf = root / "P229A_组件爆炸图_V0.1_20240708-Model.pdf"
            dwg = root / "P229A_组件爆炸图_V0.1_20240708.dwg"
            pdf.write_bytes(b"%PDF-1.0")
            dwg.write_bytes(b"dwg")

            found = PIPELINE.discover_dwg_for_pdf(pdf)

        self.assertEqual(found, dwg)

    def test_build_page_annotations_excludes_near_mismatch(self) -> None:
        unit = {
            "doc_label": "A",
            "page_index": 0,
            "unit_type": "text_line",
            "text": "特别说明",
            "text_norm": OCR.normalize_text("特别说明"),
            "ocr_label": "text",
            "parent_region_index": 1,
            "bbox_px": [10, 10, 100, 30],
            "bbox_2d": [10, 10, 100, 30],
            "ocr_block_bbox_px": [10, 10, 100, 30],
            "ocr_block_bbox_2d": [10, 10, 100, 30],
            "bbox_scope": "projection_row",
            "bbox_source": "projection_row",
            "row_index_in_block": 0,
            "block_row_count": 1,
        }
        page_diff = {
            "table_row": {"only_in_a": [], "only_in_b": [], "near_mismatch": []},
            "text_line": {
                "only_in_a": [],
                "only_in_b": [],
                "near_mismatch": [{"a": unit, "b": {**unit, "doc_label": "B"}, "similarity": 0.95}],
            },
        }

        ann_a, ann_b = OCR.build_page_annotations(page_diff)

        self.assertEqual(ann_a, [])
        self.assertEqual(ann_b, [])

    def test_save_report_md_contains_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cfg = PIPELINE.PipelineConfig(
                base_url="https://example.com/v1",
                api_key="test-key",
                vl_model="qwen-vl",
                text_model="gpt-4.1",
                ocr_model="glm-ocr",
                output_dir=root,
            )
            result = {
                "pair": ["A", "B"],
                "diff_stats": {"diff_pct": 1.23},
                "grounding_method": "vlm_dual_image",
                "roi_callout_a": [[1, 2, 3, 4]],
                "roi_callout_b": [],
                "roi_pixel_a": [],
                "roi_pixel_b": [[5, 6, 7, 8]],
                "roi_geometry_a": [[9, 10, 11, 12]],
                "roi_geometry_b": [],
                "ocr_pair_diff": {
                    "summary": {
                        "table_only_in_a": 2,
                        "table_only_in_b": 1,
                        "text_only_in_a": 3,
                        "text_only_in_b": 4,
                        "total_near_mismatch": 5,
                    },
                    "table_row": {
                        "only_in_a": [{"text": "1 | A 件"}],
                        "only_in_b": [{"text": "1 | B 件"}],
                        "near_mismatch": [],
                    },
                    "text_line": {
                        "only_in_a": [{"text": "A 标题"}],
                        "only_in_b": [{"text": "B 标题"}],
                        "near_mismatch": [{"a": {"text": "近似样例"}}],
                    },
                },
                "vlm_coarse": "这里是视觉粗分析。",
                "verdict": "这里是综合结论。",
                "paths": {
                    "overlay": "A_vs_B/A_vs_B_overlay.png",
                    "heatmap": "A_vs_B/A_vs_B_heatmap.png",
                    "annotated_a": "A_vs_B/A_annotated.png",
                    "annotated_b": "A_vs_B/B_annotated.png",
                },
            }
            summaries = {
                "A": {
                    "page_count": 1,
                    "text_line_count": 10,
                    "table_row_count": 5,
                    "title_block_candidates": ["零件名称 A"],
                    "bom_samples": ["1 | A 件"],
                    "text_samples": ["A 标题"],
                },
                "B": {
                    "page_count": 1,
                    "text_line_count": 11,
                    "table_row_count": 6,
                    "title_block_candidates": ["零件名称 B"],
                    "bom_samples": ["1 | B 件"],
                    "text_samples": ["B 标题"],
                },
            }

            report_path = PIPELINE.save_report_md(
                cfg,
                results=[result],
                n_way_text="多文档 OCR 综合分析正文。",
                ts="20260420_000000",
                run_dir=root,
                ocr_doc_summaries=summaries,
            )
            text = report_path.read_text(encoding="utf-8")

        self.assertIn("## OCR 综合分析", text)
        self.assertIn("### OCR 文字差异摘要", text)
        self.assertIn("近似文本（仅 JSON/报告，不参与标注）：5", text)
        self.assertIn("A_vs_B/A_annotated.png", text)

    def test_run_pair_merges_vlm_and_ocr_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            cfg = PIPELINE.PipelineConfig(
                base_url="https://example.com/v1",
                api_key="test-key",
                vl_model="qwen-vl",
                text_model="gpt-4.1",
                ocr_model="glm-ocr",
                output_dir=tmpdir_path,
                vlm_timeout=30.0,
                ocr_timeout=30.0,
            )
            img_a = PIPELINE.np.full((120, 120, 3), 255, dtype=PIPELINE.np.uint8)
            img_b = PIPELINE.np.full((120, 120, 3), 245, dtype=PIPELINE.np.uint8)
            page_a_path = tmpdir_path / "A.png"
            page_b_path = tmpdir_path / "B.png"
            self.assertTrue(PIPELINE.cv2.imwrite(str(page_a_path), img_a))
            self.assertTrue(PIPELINE.cv2.imwrite(str(page_b_path), img_b))

            ocr_unit_a = {
                "doc_label": "A",
                "page_index": 0,
                "unit_type": "text_line",
                "text": "A 独有说明",
                "text_norm": OCR.normalize_text("A 独有说明"),
                "ocr_label": "text",
                "parent_region_index": 1,
                "bbox_px": [10, 10, 50, 30],
                "bbox_2d": [83, 83, 417, 250],
                "ocr_block_bbox_px": [10, 10, 60, 40],
                "ocr_block_bbox_2d": [83, 83, 500, 333],
                "bbox_scope": "projection_row",
                "bbox_source": "projection_row",
                "row_index_in_block": 0,
                "block_row_count": 1,
            }
            ocr_unit_b = {
                **ocr_unit_a,
                "doc_label": "B",
                "text": "B 独有说明",
                "text_norm": OCR.normalize_text("B 独有说明"),
            }
            page_a = OCR.OCRPage(
                doc_label="A",
                pdf_path=Path("/tmp/A.pdf"),
                page_index=0,
                image_path=page_a_path,
                image_width=120,
                image_height=120,
                raw_response={},
                units=[ocr_unit_a],
            )
            page_b = OCR.OCRPage(
                doc_label="B",
                pdf_path=Path("/tmp/B.pdf"),
                page_index=0,
                image_path=page_b_path,
                image_width=120,
                image_height=120,
                raw_response={},
                units=[ocr_unit_b],
            )
            ocr_pair_result = {
                "pair": ["A", "B"],
                "pages": [
                    {
                        "summary": {
                            "table_only_in_a": 0,
                            "table_only_in_b": 0,
                            "text_only_in_a": 1,
                            "text_only_in_b": 1,
                            "total_near_mismatch": 1,
                        },
                        "table_row": {"only_in_a": [], "only_in_b": [], "near_mismatch": []},
                        "text_line": {
                            "only_in_a": [ocr_unit_a],
                            "only_in_b": [ocr_unit_b],
                            "near_mismatch": [
                                {
                                    "a": {**ocr_unit_a, "text": "近似 A"},
                                    "b": {**ocr_unit_b, "text": "近似 B"},
                                    "similarity": 0.95,
                                    "unit_type": "text_line",
                                }
                            ],
                        },
                        "ocr_annotations_a": [
                            {
                                **ocr_unit_a,
                                "label": "文本独有: A 独有说明",
                                "source": "ocr_text_line",
                                "diff_kind": "only_in_a",
                            }
                        ],
                        "ocr_annotations_b": [
                            {
                                **ocr_unit_b,
                                "label": "文本独有: B 独有说明",
                                "source": "ocr_text_line",
                                "diff_kind": "only_in_b",
                            }
                        ],
                    }
                ],
            }

            with (
                mock.patch.object(
                    PIPELINE.cvl,
                    "compute_visual_diff",
                    return_value=(img_a.copy(), img_b.copy(), {"diff_pct": 1.5, "diff_regions": 2}),
                ),
                mock.patch.object(
                    PIPELINE.cvl,
                    "diff_dwg_strings",
                    return_value={
                        "file_size_diff_kb": 0,
                        "layers_only_in_a": [],
                        "layers_only_in_b": [],
                        "text_only_in_a": [],
                        "text_only_in_b": [],
                    },
                ),
                mock.patch.object(PIPELINE.cvl, "call_vl_model", return_value="视觉粗分析"),
                mock.patch.object(
                    PIPELINE,
                    "vl_grounding_primary_vs_reference",
                    side_effect=[
                        ([{"bbox_2d": [600, 600, 880, 880], "label": "结构差异", "source": "model"}], "raw-a"),
                        ([{"bbox_2d": [620, 620, 900, 900], "label": "结构差异", "source": "model"}], "raw-b"),
                    ],
                ),
                mock.patch.object(PIPELINE, "infer_roi_verdict", return_value="综合结论"),
            ):
                result = PIPELINE.run_pair(
                    cfg,
                    la="A",
                    lb="B",
                    rendered={"A": img_a, "B": img_b},
                    dwg_info={
                        "A": {"total_strings": 0, "likely_layers": [], "chinese_text": [], "file_size_mb": 0},
                        "B": {"total_strings": 0, "likely_layers": [], "chinese_text": [], "file_size_mb": 0},
                    },
                    ocr_pages_by_label={"A": [page_a], "B": [page_b]},
                    ocr_doc_summaries={"A": {"page_count": 1}, "B": {"page_count": 1}},
                    ocr_pair_result=ocr_pair_result,
                    run_dir=tmpdir_path,
                )

            self.assertIn("ocr_pair_diff", result)
            self.assertIn("ocr_annotations_a", result)
            self.assertIn("render_annotations_a", result)
            self.assertEqual(len(result["ocr_annotations_a"]), 1)
            self.assertEqual(len(result["ocr_annotations_b"]), 1)
            self.assertTrue(any(item["source"] == "model" for item in result["render_annotations_a"]))
            self.assertTrue(any(item["source"] == "ocr_text_line" for item in result["render_annotations_a"]))
            self.assertEqual(result["ocr_pair_diff"]["summary"]["total_near_mismatch"], 1)
            self.assertTrue((tmpdir_path / "A_vs_B" / "A_annotated.png").is_file())
            self.assertTrue((tmpdir_path / "A_vs_B" / "B_annotated.png").is_file())


if __name__ == "__main__":
    unittest.main()
