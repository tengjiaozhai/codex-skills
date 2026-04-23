# pdf-drawing-diff

通用「PDF 图纸两两差异对比」技能（VLM 多模态 + GLM-OCR 文字 + DWG 字符串辅助）。

支持 **N >= 2** 张 PDF 图纸，自动生成所有成对组合（`itertools.combinations`），
对每一对输出标注图、像素 overlay/heatmap、JSON、Markdown 与多页 PDF 报告。

## 安装

```bash
pip install -r requirements.txt
cp .env.example .env   # 然后填入 OPENAI_API_KEY / OPENAI_BASE_URL / ZAI_API_KEY 等
```

## 调用

```bash
# 自动从文件名取 label
python scripts/run_pdf_drawing_diff.py \
  --pdf /abs/path/A.pdf \
  --pdf /abs/path/B.pdf

# 显式命名 label（推荐）
python scripts/run_pdf_drawing_diff.py \
  --label P229A=/abs/path/P229A.pdf \
  --label P329A=/abs/path/P329A.pdf \
  --label P329C=/abs/path/P329C.pdf

# 4 个或更多 PDF：自动生成全部成对组合
python scripts/run_pdf_drawing_diff.py \
  --label A=/abs/A.pdf --label B=/abs/B.pdf \
  --label C=/abs/C.pdf --label D=/abs/D.pdf
```

DWG 自动发现：每个 PDF 会在同目录下查找同名 `.dwg`（也兼容 `xxx-Model.pdf` ↔ `xxx.dwg`）。
若需手动指定，使用 `--dwg LABEL=/path/to.dwg`。

完整 CLI 选项见 `SKILL.md` 与 `scripts/run_pdf_drawing_diff.py --help`。

## 输出

```
reports/output/pipeline_run_<ts>/
├── pipeline_result_<ts>.json
├── pipeline_annotated_<ts>.pdf
├── report.md
├── rendered/<label>/page_001.png
└── <la>_vs_<lb>/
    ├── <la>_annotated.png
    ├── <lb>_annotated.png
    ├── <la>_vs_<lb>_overlay.png
    └── <la>_vs_<lb>_heatmap.png
```

## 模块

- `scripts/http_client.py` — OpenAI 兼容 HTTP 客户端（urllib + 回退）
- `scripts/io_utils.py`    — CJK 字体、bbox 绘制、PDF 导出
- `scripts/ocr.py`         — GLM-OCR layout_parsing + 文本差异
- `scripts/vlm.py`         — PDF 渲染、像素差分、DWG 抽取、VLM 粗分析
- `scripts/pipeline.py`    — 主流水线，参数化的 `PipelineConfig` + `run_pipeline()`
- `scripts/run_pdf_drawing_diff.py` — CLI 入口
