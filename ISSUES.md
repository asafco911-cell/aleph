# Aleph - Open Issues

## Blocking future work

**#1 Connect extractor to DCF engine (Ch8 + Ch9)**
LLM extracts verified figures from the filing (normalized owner earnings,
diluted share count, effective tax rate, revenue geography, industry);
Python derives the assumption RANGES from that data (industry beta
percentiles, historical growth dispersion, GDP cap on terminal growth).
The LLM must never pick a range directly - it extracts, Python derives.
Every derived range carries source + rationale.
Target: Chapter 14 (full system assembly).

**#2 Pydantic schemas not serializable by LangGraph checkpointer (Ch8)**
Schemas defined inside numbered scripts trigger
"Deserializing unregistered type" warnings. Harmless with MemorySaver,
blocking with a persistent checkpointer.
Fix: move all schemas to a shared schemas.py.
Blocks: real cross-session resume.

## Quality improvements

**#3 Golden dataset is 14 questions, target 30 (Ch5)**
Especially need more trap questions - the A/B test showed a real
regression there with n=3, too small to conclude from.
Blocks: reliable measurement of future pipeline changes.

**#4 Hybrid retrieval increases hallucination risk on unanswerable
questions (Ch5)**
BM25 matches "Lyft" inside Uber's competition/litigation sections,
producing plausible-looking context that tempts the model to answer
instead of refusing. Investigate against a larger trap sample.

**#5 Critic drift - unbounded quality demands (Ch8)**
The critic kept finding medium-severity issues while the plan grew
19 -> 24 steps without converging.
Fix options: constrain the mandate to available data, or accept when
the issue count stops falling between rounds.

**#6 Inconsistent period granularity in the knowledge graph (Ch7)**
Some edges carry period "2024" (point), others "2024 to 2025" (range).
A query filtering period == "2025" silently misses the ranges.
Fix: add period_type, or split into period_start / period_end.

**#7 Language forensics needs two filings (Ch10)**
Currently compared two sections of the SAME 10-K, which only proves the
mechanism works - the output has no forensic meaning. Real tone/omission
analysis requires the 2024 and 2025 10-K, extracting the SAME section
(Item 7 MD&A) from each.
Note: forensic tools always return numbers. Validity of the comparison is
the analyst's responsibility, not the tool's.

## #10 Section ordering constraint is page-level only

`scripts/locate_sections.py` enforces `page >= floor` when selecting a
heading candidate. Seven items share PDF page 131 in `uber_10k_fy2024.pdf`
(9B, 9C, 10, 11, 12, 13, 14). Their character offsets happen to increase
(1473 -> 4573), but nothing in the code enforces that. A within-page
misidentification would pass silently.

Fix: when the candidate page equals the previous item's page, require
`char_offset > previous_offset`. Track both page and offset as the floor.

Status: open. Detected via `distinct deltas: [2]` on Uber FY2024, which
passed by luck rather than by design.

## #11 Typographic look-alikes break raw string matching across the pipeline

Documents printed from SEC HTML contain U+2019 (right single quotation mark),
not U+0027. Measured: `"Management's Discussion and Analysis"` returns False
against `uber_10k_fy2024.pdf` page 3 with raw matching and True after
normalisation. `scripts/textnorm.py` now handles this for manifest work.

Unverified: whether the BM25 index built in ch04 tokenises `management's` and
`management’s` as distinct terms. If so, every query containing an apostrophe
behaves differently than assumed, and this may explain retrieval behaviour
not previously understood. Needs measurement, not assumption.

Fix (pending measurement): route all BM25 indexing and query text through
`textnorm.normalise` before tokenisation.

Status: open, unmeasured.

## #12 Column detection is note-scoped, not table-scoped

`column_periods` scans the entire source region for the longest year run. Note
13 of Uber's 10-K contains a geography table with year columns AND a segment
table with segment columns (mobility/delivery/freight/total) for a single year.
Year columns detected from the first are applied to rows of the second.

A segment row with exactly as many numbers as detected year columns produces a
FALSE ACCEPT: correct quote, correct number, wrong meaning, no red flag. Rows
with a differing count are caught by the columns_undetermined guard, which is
incidental, not protective.

Fix direction: scope column detection to the nearest preceding header above the
quoted row rather than to the whole region. Alternative: cross-footing, since
components must sum to their stated total.

Status: open, unmeasured.