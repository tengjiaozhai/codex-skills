# Selection And Pruning

## Capacity Heuristic

Estimate attraction load before finalizing the route.

Use these rough weights:

- `1.0 day`: mountain, canyon, island, large scenic area, theme park, major trail
- `0.5 day`: old town, temple, museum, market, citywalk district, small lakefront
- `0.5 day tax`: cross-city transfer around 1-2 hours
- `1.0 day tax`: cross-city transfer above about 2.5 hours or complex repositioning

Arrival day and departure day usually hold only `0.5-1.0` scenic units.

## When The Plan Overflows

If candidate attractions exceed feasible capacity:

1. Keep the route skeleton.
2. Split attractions into:
   - `must-keep`
   - `optional`
   - `overflow / conflict`
3. Briefly explain each overflow attraction in one sentence.
4. Ask the user which ones to keep.

## Brief Attraction Intro Format

Use one-line intros with decision value, not brochure fluff.

Good format:

- `天台山大瀑布`：自然景观强、体力消耗中等、适合单独占半天到一天。
- `国清寺`：人文向、节奏慢、门槛低，适合作为天台山当天的轻量搭配。
- `神仙居`：核心山景目的地，值得整天保留，不适合和别的大景点硬拼。

## User Choice Rule

If there are more meaningful sights than available days, do not silently remove the leftovers.

Explicitly tell the user:

- why everything装不下
- which spots are competing for the same time block
- what each one gives up or gains

Example pattern:

1. 你这次想去的 9 个景点，按 4 天来排会明显过满。
2. 山岳类大景点每个基本都要 1 天，古城 / 寺庙 / 夜景才更适合拼半天。
3. 下面这 3 个是冲突位，请选保留哪 2 个。

## If The User Says “You Decide”

Then prune by:

1. route smoothness
2. uniqueness
3. ticket value
4. weather sensitivity
5. crowd sensitivity
6. fit with traveler type

Prefer removing:

- duplicated景观类型
- far detours with weak uniqueness
- expensive but low-distinction spots
- attractions that force repeated hotel moves

## Couple / Family / Parent-Friendly Nudges

Use traveler type to break ties.

- couple: scenic rhythm, night view, hotel comfort, photo value
- family with kids: low-transfer rhythm, easy logistics, room practicality
- older travelers: reduce stairs, reduce long uphill segments, reduce repeated hotel changes
