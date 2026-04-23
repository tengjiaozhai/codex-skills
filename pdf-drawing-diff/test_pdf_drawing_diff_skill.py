from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class TestPdfDrawingDiffSkillFiles(unittest.TestCase):
    def test_skill_frontmatter(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: pdf-drawing-diff", text)
        self.assertIn("description:", text)
        self.assertIn("at least 2", text.lower())

    def test_openai_yaml_metadata(self) -> None:
        text = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
        self.assertIn('display_name: "PDF Drawing Diff"', text)
        self.assertIn('short_description: "多 PDF 图纸差异分析与 bbox 标注"', text)
        self.assertIn("$pdf-drawing-diff", text)

    def test_skill_layout(self) -> None:
        self.assertTrue((ROOT / "scripts" / "run_pdf_drawing_diff.py").is_file())
        self.assertTrue((ROOT / "scripts" / "pipeline.py").is_file())
        self.assertTrue((ROOT / "scripts" / "ocr.py").is_file())
        self.assertTrue((ROOT / "scripts" / "vlm.py").is_file())
        self.assertTrue((ROOT / "scripts" / "io_utils.py").is_file())
        self.assertTrue((ROOT / "scripts" / "http_client.py").is_file())
        self.assertTrue((ROOT / ".env.example").is_file())


if __name__ == "__main__":
    unittest.main()
