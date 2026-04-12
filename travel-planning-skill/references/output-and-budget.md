# Output And Budget

## Recommended Output Shapes

Choose the smallest output that satisfies the request:

### Quick answer

Use when the user wants a short recommendation.

Include:

- recommended route
- why it wins
- rough hard-cost total

### Side-by-side comparison

Use when the user asks about multiple transport styles or route variants.

Good examples:

- 火车 + 打车 vs 火车 + 租车
- 机票 vs 高铁
- 市区连住 vs 景区边住宿

### Day-by-day itinerary

Use when the user wants full planning.

Include:

- day label
- where to go
- where to stay
- main transfer
- ticket and local movement notes

### Bookable checklist

Use when the user is close to purchase.

Include:

- transport first
- hotels next
- scenic tickets next
- local mobility notes

### DOCX / PDF handbook

Use when the user asks to save, export, archive, keep, or print the plan.

Default structure:

- cover
- overview
- daily pages
- budget
- sources

## Budget Structure

Split costs into layers.

### Hard confirmed

- long-distance transport
- hotel
- base scenic tickets

### Local mobility

Include when it can be estimated realistically:

- metro or bus fares
- taxi estimate ranges
- rental-day reference rates

### Explicitly excluded

Always call out excluded items, such as:

- meals
- dynamic upgrade tickets
- ropeway / shuttle add-ons
- fuel / toll / parking for self-drive

## Price Language

Use these labels consistently:

- `已核实金额`
- `估算区间`
- `参考实时价`

Do not mix them.

## Travel-Handbook Quality Bar

If generating a document:

- keep all dates absolute
- insert local images instead of hotlinking them in the document
- keep prices source-backed
- state the query date
- explain why one hotel or route is preferred

## Closing Pattern

When the answer is long, end with one clear takeaway:

- best option
- budget range
- next action

Example:

- `最推荐的是火车 + 市区连住版，原因是总价更稳、移动更轻。`
- `如果你愿意，我下一步可以把它整理成最终下单顺序。`
