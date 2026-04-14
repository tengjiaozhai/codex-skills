# Tool Orchestration

## Skill Routing

Choose the minimum set of installed travel skills needed for the task.

| Need | Preferred skill |
| --- | --- |
| Exact train checks, seat logic, 12306 workflow | `12306-train-assistant` |
| Broad travel search: flights, trains, hotels, attractions | `fliggy-travel` |
| Domestic flight workflow and booking details | `flightAI` |
| Hotel detail cross-check, tags, room pricing | `rollinggo-searchhotel` |
| Any route choice or local movement | `didi-ride-skill` |
| Rental-car live reference pricing in China | `china-rental-price` |
| Reusable travel handbook template and standardized trip rendering | `travel-handbook-generator` |
| DOCX/PDF export | `doc` |

## Transport Comparison Rules

For destination access, compare only the options that materially change the trip:

- train
- flight
- train + taxi
- train + rental
- flight + rental

Do not create fake variety just to have three tables.

## Local Mobility Rules

Always inspect the city type before choosing movement defaults.

### Metro-rich cities

Prefer:

1. metro + walk
2. metro + taxi for first/last mile
3. taxi-only only if timing is much better

### Ordinary cities without dense rail

Prefer:

1. direct bus + walk if it is straightforward
2. taxi if bus adds too much time or too many transfers

### Scenic / suburban / mountain / island segments

Taxi or rental is often the realistic default.

Prefer taxi or rental when public transit:

- adds more than about `30-45` minutes versus taxi
- needs more than `2` transfers
- requires long uphill or luggage-unfriendly walking
- is too sparse for the day’s rhythm

## Hotel Screening Rules

Within budget, rank hotels by:

1. hygiene risk
2. review stability
3. standardization / brand reliability
4. route fit
5. traveler fit
6. price

Do not recommend a clearly low-trust guesthouse without saying why it was still kept.

If a better option exists just slightly above budget, mention it as an `upgrade reference`.

## Scenic Ticket Rules

Verify major scenic tickets one by one.

Record:

- adult base ticket
- whether it includes ropeway / shuttle / package
- double-person total when relevant
- query date
- source link or source note

If only dynamic or package pricing exists, say that explicitly.

## Source Handling

Prefer source-backed statements for:

- train / flight price
- hotel price
- scenic ticket
- taxi estimate
- rental-day rate

Label each as:

- exact
- estimated
- reference
