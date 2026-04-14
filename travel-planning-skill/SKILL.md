---
name: travel-planning-skill
description: End-to-end travel planning with verified prices, transport comparison, hotel screening, scenic-ticket budgeting, local transit design, attraction pruning, and optional DOCX/PDF handbook output. Use when users ask for trips, itineraries, travel guides, multi-day route design, budgeted transport + hotel + ticket combinations, attraction筛选, or bookable travel checklists, especially requests like “帮我规划旅行/攻略/几天怎么玩/预算多少/住哪里/怎么去/门票多少/火车还是飞机/租车还是打车/生成旅行文档”.
---

# Travel Planning Skill

## Overview

Use this skill to turn vague travel ideas into realistic, multi-day travel plans with live prices, explicit dates, source-backed costs, and route-aware pruning.

Keep the body lean. Read only the reference file needed for the current step.

## File Map

Read these files on demand:

| File | Use when |
| --- | --- |
| `references/intake-and-scoping.md` | The request is vague, missing trip basics, or dates/days/budget are inconsistent |
| `references/selection-and-pruning.md` | There are too many attractions for the available days, or you need to explain what to keep or drop |
| `references/tool-orchestration.md` | You need to decide which installed travel skill to use, or how to compare flight/train/hotel/local transit/rental options |
| `references/output-and-budget.md` | You need to build the final plan, budget table, bookable checklist, or DOCX/PDF travel handbook |

## Core Rules

1. Use live checks for unstable data.
   Long-distance transport, hotels, scenic tickets, rental prices, and local transfers are all time-sensitive. Verify them with the relevant installed skills instead of relying on memory.

2. Convert relative time into absolute dates before presenting any plan.
   If the user says “五一”“明天”“下周”, rewrite it using explicit calendar dates in the final answer.

3. Distinguish `exact`, `estimated`, and `reference` prices.
   - `exact`: current bookable or quoted price from a live source
   - `estimated`: taxi or local transfer estimate that may fluctuate
   - `reference`: rental-day rate or dynamic item that is not a locked checkout total

4. Do not invent scenic ticket prices.
   If only a package ticket, flexible-entry ticket, or dynamic price is available, say so plainly.

5. Do not optimize hotels by price alone.
   Treat budget as a hard constraint, but rank within that budget using hygiene risk, review stability, standardization, location, and couple/family fit.

6. Treat esports hotels as conditional candidates, not automatic rejects.
   Keep them only if the room is clearly double/couple-oriented, the listing is clean, and there is no obvious “网吧感”, heavy smoke, or strong noise risk.

## Workflow

### 1. Scope the trip first

If the user is not explicit enough, read `references/intake-and-scoping.md` and ask concise targeted questions.

At minimum, fill these slots before doing a serious itinerary:

- destination
- departure city, when relevant
- start date and end date
- total trip days if not obvious
- total budget

If the user’s request is vague, you must ask about:

- `哪天到哪天玩`
- `玩几天`
- `预算多少`

If dates and day-count disagree, ask which one should govern the plan.

### 2. Build the feasible attraction set

List candidate attractions, then test whether they fit the available days.

If the plan is overfilled, read `references/selection-and-pruning.md`.

When attractions exceed capacity:

- do not silently delete them
- group them into `recommended`, `optional`, and `overflow/conflict`
- give a brief plain-language intro for each conflicting attraction
- ask the user which ones to keep

If the user says “你来定”, prune by route smoothness, uniqueness, crowd tolerance, ticket value, and overall trip rhythm.

### 3. Verify transport and stay options

Read `references/tool-orchestration.md` and use the smallest skill set that fits the ask.

Default routing:

- trains or exact rail booking logic: `12306-train-assistant`
- broad travel search for flights/hotels/attractions/trains: `fliggy-travel`
- domestic flight workflow details: `flightAI`
- hotel cross-checks and room details: `rollinggo-searchhotel`
- local route choice, walking/bus/metro/taxi comparison, or any “怎么走/多少钱”: `didi-ride-skill`
- rental-car reference pricing in China: `china-rental-price`
- standardized handbook spec + DOCX/PDF travel handbook generation: `travel-handbook-generator`
- DOCX/PDF export verification and layout review: `doc`

### 4. Design local mobility like a real traveler would

Do not default every segment to taxi.

Use `didi-ride-skill` to compare local movement and choose the realistic combination:

- metro-rich city: prefer metro + walk first
- ordinary city: prefer direct bus if it is reasonable
- suburban/scenic/mountain/island transfers: taxi or rental is often more realistic

When public transit exists but adds too much time or too many transfers, say why taxi or rental is the better tradeoff.

### 5. Produce the final artifact

Read `references/output-and-budget.md` before composing the answer.

Common deliverables:

- quick recommendation
- side-by-side transport options
- day-by-day itinerary
- hotel and scenic-ticket budget
- bookable checklist
- DOCX/PDF travel handbook

If the user asks to save, export, archive, or keep the plan, use the `doc` skill and produce a real file instead of only chat text.
If the ask is for a reusable handbook template or repeatable handbook generation workflow, use `travel-handbook-generator` first, then use `doc` for final layout checks.

## Output Expectations

Always try to include:

- explicit dates
- day-by-day routing
- where to stay each night
- hard costs first
- local transit cost strategy
- source links or source notes

When helpful, summarize with:

- `recommended option`
- `why it wins`
- `what is excluded from total budget`

Keep the final answer concise, but do not skip price labels or source clarity.
