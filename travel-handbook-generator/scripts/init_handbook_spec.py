#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = SKILL_DIR / "assets" / "handbook_spec_template.json"


def load_template() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def build_route_cards(start_date: date, day_count: int) -> list[dict]:
    cards = []
    for index in range(day_count):
        current = start_date + timedelta(days=index)
        cards.append(
            {
                "day": f"D{index + 1}",
                "date": f"{current.month}月{current.day}日",
                "city": "待补充",
                "detail": "待补充",
            }
        )
    return cards


def build_images(day_count: int) -> dict:
    images = {}
    for index in range(day_count):
        key = f"day{index + 1}"
        images[key] = {
            "title": f"景点{index + 1}",
            "image": "https://example.com/day.jpg",
            "page": "https://example.com/source",
            "caption": "待补充图片说明。",
        }
    return images


def build_days(day_count: int) -> list[dict]:
    days = []
    for index in range(day_count):
        key = f"day{index + 1}"
        day_label = f"D{index + 1}"
        hotel_card = None if index == day_count - 1 else {"card_title": "今晚住哪里", "hotel_key": "main_hotel"}
        days.append(
            {
                "title": f"{day_label} | 待补充日期 | 待补充城市/景点",
                "subtitle": "待补充这一天的节奏说明。",
                "image_key": key,
                "timeline": [
                    ["上午", "待补充"],
                    ["下午", "待补充"],
                ],
                "summary_boxes": [
                    {
                        "title": "当天要点",
                        "lines": ["待补充门票、路费或取舍说明。"],
                        "fill": "gold",
                    }
                ],
                "hotel_card": hotel_card,
            }
        )
    return days


def default_filename(title: str, suffix: str) -> str:
    safe = title.replace("/", "-").replace(" ", "")
    return f"{safe}.{suffix}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Scaffold a JSON spec for travel-handbook-generator.")
    parser.add_argument("--workspace", required=True, help="Workspace root, usually the current project root.")
    parser.add_argument("--slug", required=True, help="Spec slug, also used for temp render folders.")
    parser.add_argument("--title", required=True, help="Handbook title.")
    parser.add_argument("--subtitle", required=True, help="Handbook subtitle.")
    parser.add_argument("--start-date", required=True, help="Trip start date in YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, help="Trip end date in YYYY-MM-DD.")
    parser.add_argument("--query-date", default=str(date.today()), help="Verification date in YYYY-MM-DD.")
    parser.add_argument("--output-dir", help="Override output/doc path.")
    parser.add_argument("--spec-path", help="Absolute output path for the spec JSON.")
    parser.add_argument("--docx-filename", help="Final DOCX filename.")
    parser.add_argument("--pdf-filename", help="Final PDF filename.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing spec file.")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)
    if end_date < start_date:
        raise SystemExit("end-date must be on or after start-date")
    day_count = (end_date - start_date).days + 1

    spec = deepcopy(load_template())
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else workspace / "output" / "doc"
    spec_path = Path(args.spec_path).expanduser().resolve() if args.spec_path else workspace / "travel_specs" / f"{args.slug}.json"

    spec["meta"]["slug"] = args.slug
    spec["meta"]["title"] = args.title
    spec["meta"]["subtitle"] = args.subtitle
    spec["meta"]["query_date"] = args.query_date
    spec["meta"]["output_dir"] = str(output_dir)
    spec["meta"]["docx_filename"] = args.docx_filename or default_filename(args.title, "docx")
    spec["meta"]["pdf_filename"] = args.pdf_filename or default_filename(args.title, "pdf")
    spec["overview"]["route_cards"] = build_route_cards(start_date, day_count)
    spec["images"] = build_images(day_count)
    spec["days"] = build_days(day_count)
    spec["cover"]["hero_keys"] = list(spec["images"].keys())[:3]

    spec_path.parent.mkdir(parents=True, exist_ok=True)
    if spec_path.exists() and not args.force:
        raise SystemExit(f"Spec already exists: {spec_path}. Use --force to overwrite.")

    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(spec_path)


if __name__ == "__main__":
    main()
