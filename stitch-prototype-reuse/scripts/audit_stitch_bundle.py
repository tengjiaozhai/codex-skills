#!/usr/bin/env python3
"""Validate and summarize a Stitch prototype triplet bundle."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REQUIRED_FILES = ("code.html", "DESIGN.md", "screen.png")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def parse_png_size(path: Path) -> dict[str, int] | None:
    try:
        with path.open("rb") as fh:
            if fh.read(8) != b"\x89PNG\r\n\x1a\n":
                return None
            _chunk_len = fh.read(4)
            if fh.read(4) != b"IHDR":
                return None
            width = int.from_bytes(fh.read(4), "big")
            height = int.from_bytes(fh.read(4), "big")
            return {"width": width, "height": height}
    except OSError:
        return None


def extract_html_metrics(html: str) -> dict[str, Any]:
    lower = html.lower()

    title_match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else ""

    colors: dict[str, str] = {}
    color_block = re.search(r"colors\s*:\s*\{(.*?)\}\s*,\s*fontFamily", html, flags=re.DOTALL)
    if color_block:
        for key, value in re.findall(r"['\"]([^'\"]+)['\"]\s*:\s*['\"]([^'\"]+)['\"]", color_block.group(1)):
            colors[key] = value

    return {
        "title": title,
        "has_viewport_meta": bool(re.search(r"<meta[^>]+name=[\"']viewport[\"']", html, flags=re.IGNORECASE)),
        "has_tailwind_cdn": "cdn.tailwindcss.com" in lower,
        "has_tailwind_config": "tailwind.config" in html,
        "section_count": len(re.findall(r"<section\b", lower)),
        "form_control_count": len(re.findall(r"<(input|textarea|select)\b", lower)),
        "radio_count": len(re.findall(r"type=[\"']radio[\"']", lower)),
        "has_header": "<header" in lower,
        "has_main": "<main" in lower,
        "has_footer": "<footer" in lower,
        "tailwind_color_token_count": len(colors),
        "tailwind_color_tokens_sample": sorted(list(colors.keys()))[:12],
    }


def extract_markdown_metrics(markdown: str) -> dict[str, Any]:
    headings = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(stripped)

    lowered = markdown.lower()

    return {
        "heading_count": len(headings),
        "headings_sample": headings[:10],
        "word_count": len(re.findall(r"\S+", markdown)),
        "mentions_no_line_rule": "no-line" in lowered,
        "mentions_typography": "typography" in lowered,
        "mentions_spacing": "spacing" in lowered,
        "mentions_dos_donts": "do:" in lowered and "don't" in lowered,
    }


def audit_bundle(root: Path) -> dict[str, Any]:
    files = {name: root / name for name in REQUIRED_FILES}
    exists = {name: path.exists() for name, path in files.items()}
    missing = [name for name, present in exists.items() if not present]

    report: dict[str, Any] = {
        "root": str(root.resolve()),
        "status": "ok" if not missing else "missing_required_files",
        "required_files": exists,
        "missing_files": missing,
    }

    html_path = files["code.html"]
    if html_path.exists():
        report["html"] = extract_html_metrics(read_text(html_path))

    md_path = files["DESIGN.md"]
    if md_path.exists():
        report["design_md"] = extract_markdown_metrics(read_text(md_path))

    png_path = files["screen.png"]
    if png_path.exists():
        report["screen_png"] = {
            "size_bytes": png_path.stat().st_size,
            "dimensions": parse_png_size(png_path),
        }

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a Stitch html/md/png bundle")
    parser.add_argument("--dir", default=".", help="Target directory containing code.html/DESIGN.md/screen.png")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args()

    root = Path(args.dir)
    report = audit_bundle(root)

    if args.pretty:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False))

    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    sys.exit(main())
