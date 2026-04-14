# Spec Schema

Use this file when filling or reviewing a handbook JSON spec for `travel-handbook-generator`.

## 1. Required top-level keys

```json
{
  "meta": {},
  "theme": {},
  "cover": {},
  "overview": {},
  "images": {},
  "hotels": {},
  "days": [],
  "budget": {},
  "sources": []
}
```

`theme` and `hotels` may stay minimal, but the keys should remain present.

## 2. `meta`

Required fields:

- `slug`
- `title`
- `subtitle`
- `query_date`
- `output_dir`
- `docx_filename`
- `pdf_filename`

Rules:

- `slug` should be filesystem-safe and stable.
- `query_date` should be the actual verification date, not the trip date.
- `output_dir` should usually be the workspace `output/doc`.

## 3. `cover`

Required fields:

- `tagline`
- `hero_keys`

Rules:

- `hero_keys` must reference keys already present in `images`.
- Use 3 keys when possible so the cover collage feels balanced.

## 4. `overview`

Recommended fields:

- `intro`
- `summary`
- `image_caption`
- `route_cards`
- `summary_boxes`

### `route_cards`

Each card should contain:

- `day`
- `date`
- `city`
- `detail`

Keep `detail` short enough to fit one route card.

### `summary_boxes`

Each box should contain:

- `title`
- `lines`
- optional `fill`

Allowed `fill` values:

- `blue`
- `gold`
- `green`
- `white`

Use summary boxes for:

- recommended strategy
- budget logic
- why one route or hotel choice wins

## 5. `images`

Each image item should contain:

- `title`
- `image`
- `page`
- `caption`

Rules:

- `image` must be a direct image URL that can be downloaded.
- `page` should be the human-facing source page for attribution.
- `caption` should explain why this image or attraction matters in the trip.

## 6. `hotels`

Each hotel item should contain:

- `title`
- `price`
- `note`
- `page`
- `image`

Use `note` for the real selection logic:

- hygiene or review stability
- why it wins inside the budget
- whether it is a compromise versus a brand option

## 7. `days`

Each day item should contain:

- `title`
- `subtitle`
- `image_key`
- `timeline`

Optional:

- `summary_boxes`
- `hotel_card`

### `timeline`

Use an array of `[time_text, detail]` pairs.

Good examples:

- `["06:58-09:00", "G3027 南京南 -> 黄山北，二等座 ¥148/人"]`
- `["下午", "逛屯溪老街和黎阳in巷，夜里再回酒店"]`

### `hotel_card`

Use:

```json
{
  "card_title": "今晚住哪里",
  "hotel_key": "main_hotel"
}
```

`hotel_key` must exist in `hotels`.

## 8. `budget`

Recommended fields:

- `title`
- `items`
- `total`
- `note`
- `reference_title`
- `reference_items`
- `exclusions_title`
- `exclusions`

### `items`

Each row is:

```json
["分类", "说明", "价格"]
```

Use this section for the main budget table.

### `reference_items`

Use this for:

- upgrade references
- sold-out brand context
- dynamic ticket variants
- optional add-ons

### `exclusions`

Use this to explicitly call out what is not included, such as:

- meals
- dynamic package tickets
- self-drive fuel / toll / parking
- optional ropeway upgrades

## 9. `sources`

Each row is:

```json
["类别", "说明", "链接"]
```

Rules:

- Keep one claim per row when possible.
- If the source is a live tool result without a public URL, the third field may be an empty string, but the label must say what was checked.

## 10. Writing conventions

- Use absolute dates.
- Use Chinese for the handbook body unless the user explicitly asks otherwise.
- Prefer short, judgment-rich copy over long descriptions.
- If a price is dynamic or interpreted, write the caveat in the `说明` or `note` field instead of pretending it is exact.
