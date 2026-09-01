# Aleph - Open Issues

Closed issues are kept here, not deleted, once resolved: the reasoning that
closed them is part of what this repository demonstrates.

## Decisions

Decisions taken and closed - not open questions. Recorded so the reasoning
is not silently reopened by a future session that only sees the outcome.

**#25 Industry beta held identical across all filers, not tuned to market price — DECIDED**
LYFT_FY2025's bottom-up WACC (8.10%) comes out below UBER_FY2024's (8.72%).
This is not an error: it is driven entirely by capital structure. Lyft
holds net cash and carries no leverage risk, and Hamada is doing exactly
what it should with that fact. What CAPM does not express is competitive
position - Lyft is the number two operator in one market facing autonomous
substitution - and the discount rate is the price of systematic risk, not a
drawer for every concern an analyst has about a company. Tuning beta until
the model agrees with the market price is unfalsifiable, and market.json's
own rationale already argues that an industry beta beats a single-stock
regression beta - doubly true for a stock with heavy short interest whose
volatility reflects trading rather than business risk.

Lyft's competitive risk belongs in the cash flows and in scenarios, not in
the discount rate. The reverse DCF already reports the honest output: at
$17.35/share the market implies -13.2% annual growth for ten years. That
gap, and what would have to be true for the market to be right, is the
finding - not a beta chosen to close it.

Decided by Asi, 2026-09-01. See CLAUDE.md, "Cross-company comparability."

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

## #11 Typographic look-alikes break raw string matching across the pipeline

Documents printed from SEC HTML contain U+2019 (right single quotation mark),
not U+0027. Measured: `"Management's Discussion and Analysis"` returns False
against `uber_10k_fy2024.pdf` page 3 with raw matching and True after
normalisation. `scripts/textnorm.py` now handles this for manifest work.

Unverified: whether the BM25 index built in ch04 tokenises `management's` and
`management's` as distinct terms. If so, every query containing an apostrophe
behaves differently than assumed, and this may explain retrieval behaviour
not previously understood. Needs measurement, not assumption.

Fix (pending measurement): route all BM25 indexing and query text through
`textnorm.normalise` before tokenisation.

Status: open, unmeasured.

## #13 Dispersion test is scale-dependent for rate quantities

MAX_RELATIVE_SPREAD = 1.0 in valuation/assumptions.py is an invented constant,
the same class of error as the fixed header-search window already corrected in
gates.py. Relative spread divides by the median, so any quantity whose median
sits near zero blows past the limit regardless of economic materiality:
effective tax rates of 1.9 and 9.2 percent are 7.3 percentage points apart and
were blocked at 1.3x, while 45 and 52 percent would pass comfortably.

The block was correct here but for the wrong reason, so the stated rationale is
misleading - a message that sounds right and is not.

Fix direction: dispersion limits should be per-quantity and declared alongside
the derivation, expressed in the quantity's own units (percentage points for
rates, percent for levels), rather than one global ratio.

Status: open.

## #16 FCFF counts stock-based compensation as free cash flow while the share count carries no dilution model

FCFF is rebuilt in bridge.py as CFO + interest x (1 - tax) - capex. CFO
already adds back stock-based compensation as a non-cash reconciling item,
so SBC counts as free cash flow in the DCF. Measured directly from each
filing's cash flow statement (not yet an extracted Fact - see below):
LYFT_FY2025 stock-based compensation is 322,268 thousand against an FCFF of
approximately 1,132,000 thousand - about 28 percent. UBER_FY2024 stock-based
compensation is 1,796 million against an FCFF of approximately 7,308
million - about 25 percent.

Meanwhile shares_outstanding is a LEVEL quantity (derive_diluted_shares,
assumptions.py), taken from the single most recent period with no dilution
model. The share count SBC pays for never grows in the ten-year forecast,
while the cash SBC would otherwise cost is treated as available to today's
shareholders.

SBC is not currently extracted as a Fact for either filer - the cash_flows
target's question does not ask for it, so the numbers above were read
directly from the source region text, not from the pipeline's own output.

Three standard treatments exist and each moves both valuations differently:
leave SBC in FCFF and model dilution in the share count; subtract SBC from
FCFF and hold shares flat; or do both, which double-counts the cost.

This is an analyst judgement, not a code defect, and it changes both
UBER_FY2024 and LYFT_FY2025 materially.

Status: open, investigated, not fixed.

## #17 build_wacc clamps negative net debt to zero with no note in the output

wacc.py computes `debt_value = max(net_debt, 0.0)` before Hamada relevering.
LYFT_FY2025 has net CASH: assumptions print net_debt=-834.8, but the WACC
block prints "levered beta = 0.81 x (1 + (1 - 21.0%) x 0/7,246) = 0.810" -
the negative net debt has silently become zero in the numerator, with
nothing in the printed output saying so.

Clamping may be the right treatment for a net-cash company (Hamada's formula
is not well-defined for negative leverage under some conventions), but a
silent clamp is not acceptable in a system whose entire design principle is
that a judgement is recorded, not smoothed over.

Fix direction: either print the treatment explicitly in the WACC notes
("net debt clamped to zero for relevering: net-cash company"), or require
an explicit market.json/override acknowledgement of the treatment before
proceeding.

Status: open.

## #18 UBER_FY2024 country_risk_premium rationale contradicts its own value

data/market.json's country_risk_premium rationale for UBER_FY2024 opens
"ASSUMED ZERO, WHICH IS A DIRECTIONAL ASSUMPTION, NOT A NEUTRAL ONE" but the
committed value is 0.0064, not zero. The rationale also justifies the figure
against the Note 13 geographic split (US 48% / UK 19% / other 32%), while the
pipeline now selects the more granular Note 2 split (US&CAN 54%) as the
geographic mix it actually reports elsewhere - the rationale's own arithmetic
frame no longer matches the breakdown the code uses.

Status: open.

## #19 market.json carries a leftover integration-test discount_rate in both blocks

Both UBER_FY2024 and LYFT_FY2025 blocks in data/market.json carry a
discount_rate of 0.09 with source "integration test," each rationale noting
it is "NOT A VALUATION INPUT" and superseded once build_wacc is wired in -
which it now is; run_valuation.py overwrites market["discount_rate"] with the
derived bottom-up figure before use. Whether the loader or any other caller
requires the key to be present at all has not been checked.

Fix direction: determine whether MarketAssumption construction or
build_dcf_inputs requires a discount_rate key to exist even though it is
always overwritten; if not, delete both.

Status: open, unmeasured.

## #20 Revenue has two independent sources with no cross-check between them

Total revenue is available from two places: the statement:operations target
(the income statement total) and the Total row in the segment note. They
agree for Uber. If they ever disagreed for some filer, no gate or derivation
step would see it - derive_growth excludes the geography/segment target
explicitly to avoid a collision with the statement total, rather than
reconciling the two.

Fix direction: a cross-source consistency check, analogous to cross-footing
within one table, comparing the two totals per period and blocking or
flagging on disagreement.

Status: open, unmeasured (not observed to disagree on either registrant
tested so far).

## #21 market.json is keyed by doc_id, duplicating pure market inputs per company

risk_free_rate and equity_risk_premium are properties of the market on a
given date, not of the company being valued, but market.json's schema keys
every input under doc_id. UBER_FY2024 and LYFT_FY2025 currently carry
identical values for both by discipline, not by structure - nothing stops
the two from drifting apart silently if one block is edited and the other is
not. This nearly happened this session in a different field: a full-file
paste to add the LYFT_FY2025 block dropped a required source field from the
UBER_FY2024 block sitting right next to it (see #15).

Fix direction: split market.json into market-level inputs (risk_free_rate,
equity_risk_premium - dated, not company-keyed) and company-level inputs
(unlevered_industry_beta, debt_spread, country_risk_premium, share_price -
each its own judgement per company).

Status: open.

## #22 Item 1A sentence-retention rate is a cross-filer signal, not a calibrated metric

Language forensics measured LYFT_FY2024->FY2025 Item 1A (Risk Factors)
retaining 67% of its sentences year over year (746 of 1,112), against
UBER_FY2024->FY2025 Item 1A retaining 91% (974 of 1,070). The difference is
real and measured, but retention rate is not calibrated across filers: it is
sensitive to ordinary changes in filing length, wording style, and section
reorganization, none of which is itself a forensic signal. Reporting the bare
percentage as a cross-company comparison ("Lyft changed its risk factors
three times more than Uber") overstates what one run of two filer pairs
demonstrates.

Status: open. The module's own docstring already carries the equivalent
caution for the analyst using its output ("forensic tools always return
numbers... validity of the comparison is the analyst's responsibility, not
the tool's"); this issue makes that caution concrete for this specific
number.

## #23 Three unexplained rejections in the multi-company gate run

`test_multicompany.py` passes overall but three targets carry a rejection
nobody has investigated, none of them unit-related:
  - UBER_FY2025 taxes note:11: `columns_undetermined`, "row has 2 cells;
    nearest header gave unknown=none; mapping cannot be verified"
  - LYFT_FY2025 taxes note:13: `columns_undetermined`, "row has 2 cells;
    nearest header gave years=['FY2025', 'FY2024', 'FY2023']; mapping cannot
    be verified"
  - DASH_FY2025 taxes note:12: `column_alignment`, "name matches 0 of the
    column labels ['Amount', 'Percent']"

All three are on tax-reconciliation tables and all three ultimately pass
their target's minimum threshold, so they have never blocked a run - which
is exactly how a real problem could sit unexamined.

Status: open, unmeasured.

## #24 DoorDash has never been valued

Extraction and gates pass for all six filings (`test_multicompany.py`
exercises DASH_FY2024 and DASH_FY2025 alongside Uber and Lyft), but
`run_valuation.py` has only ever been run end to end for UBER_FY2024 and
LYFT_FY2025. DASH_FY2024 and DASH_FY2025 have no market.json block, no
overrides.json entries (net_debt, effective_tax_rate would both block), and
no confirmed value per share. The cross-company comparison this project
argues for (see CLAUDE.md, "Cross-company comparability") has one data point
fewer than the manifest suggests.

Status: open.

## Closed

**#1 Connect extractor to DCF engine (Ch8 + Ch9) — CLOSED**
`python scripts\run_valuation.py UBER_FY2024 76.95` -> `Value per share:
102.40`. `python scripts\run_valuation.py LYFT_FY2025 17.35` -> `Value per
share: 67.79`. Both run the full pipeline: extract, derive, bridge, value.
Closed by `a17c103` "Complete extract-to-DCF pipeline (issue #1)",
2026-08-29.

**#2 Pydantic schemas not serializable by LangGraph checkpointer (Ch8) — CLOSED**
`src/aleph/schemas/` is a package (`agents.py`, `documents.py`, `evidence.py`,
`graph.py`, `validation.py`, `valuation.py`), and `__init__.py`'s own
docstring states the intent: "Import everything from here, never from a
chapter script, so that LangGraph and Python see exactly one type per name."
Closed by `b0f9bcf` "Add canonical schema package (issue #2)", 2026-08-25.

**#6 Inconsistent period granularity in the knowledge graph (Ch7) — CLOSED**
`Edge` (`schemas/graph.py`) carries `period_start`/`period_end` as an
explicit interval with a validator and a `covers()` method
(`start <= period <= end`), replacing the free-text field that mixed points
and ranges. `test_schemas.py` proves it: `edge covers FY2025: True
FY2023: False`. Closed by the same commit as #2, `b0f9bcf`, 2026-08-25.

**#7 Language forensics needs two filings (Ch10) — CLOSED**
Run for real: UBER_FY2024->UBER_FY2025 and LYFT_FY2024->LYFT_FY2025, Item 7
(MD&A) and Item 1A (Risk Factors). Null control (a filing diffed against
itself) reads zero on every bucket - Uber and Lyft, Item 7 and Item 1A,
checked independently. Real findings surfaced on both: Uber's Item 1A drops
language on its 2025 climate/EV goals in seven places (three full sentences,
four phrases inside sentences that otherwise survive as rewrites), all
concerning the assumption of "strong regulatory measures" and "aggressive
action from policymakers" that had not materialized by 2025. Lyft's
driver-classification risk factor loses the phrase "and we may incur
significant expenses to resolve the matters at issue in the litigation" from
an otherwise-surviving sentence. Validity of the comparison remains the
analyst's responsibility, per the original note; the tool's job - finding
the differences - is now demonstrated on real, forensically meaningful
pairs, not a self-comparison. See #22 for a caution on over-reading the
retention-rate summary statistic this same run produces.

**#10 Section ordering constraint is page-level only — CLOSED**
`documents/structure.py`'s `build_sections` tracks `(floor_page,
floor_offset)` across every located item and only accepts a candidate
position where `c[0] > floor_page or (c[0] == floor_page and c[1] >
floor_offset)` - exactly the fix the original issue specified. Closed by
`71d2299` "...enforce within-page ordering (issue #10)", 2026-08-26.

**#12 Column detection is note-scoped, not table-scoped — CLOSED**
`gates.py`'s `resolve_axis` resolves the axis from the nearest header ABOVE
the quoted row with no distance ceiling, climbing row by row until it finds
a header or a data row that ends the block - exactly the fix direction this
issue proposed ("scope column detection to the nearest preceding header
above the quoted row rather than to the whole region"). Closed by `7da0bb4`
(2026-08-26) and refined to be fully unbounded by `0af2781` (2026-08-27) -
**neither commit message cites issue #12**; this was closed without being
marked closed, and stayed open in this file for that reason alone.

**#14 Coverage gate returned the wrong type — CLOSED**
`gates.py` defined `check_coverage` twice. Python silently kept only the
second definition, which returned `Gap` objects into a list `validate()`'s
contract and every caller (`test_regression.py`, `run_valuation.py`) typed
and used as `Rejection`. No coverage gap had yet co-occurred with a caller
inspecting `.gate`/`.detail`, so nothing had crashed - but the first time one
did, it would have raised `AttributeError` mid-run instead of failing
cleanly. Fixed by deleting the duplicate `check_coverage` (kept the
`Rejection`-returning original) and the now-unreferenced `Gap` dataclass,
confirmed by grep before deletion.

**#15 Unit-scale bug: LYFT_FY2025 valued at 1000x — CLOSED**
`assumptions.py` stamped every derived `AssumptionRange` with a hardcoded
literal unit ("USD millions", "thousands"), regardless of the unit the LLM
actually declared on each `Fact` and the gates verified. Invisible for Uber,
which reports natively in millions; for Lyft, which reports in thousands,
`bridge.py`'s `to_millions()` treated already-in-thousands cash flow figures
as already-in-millions and applied no conversion, producing `Value per
share: 65,792.00` against a $17.35 market price. Fixed by propagating each
fact's declared unit through `Observation`, deriving `AssumptionRange.unit`
from the observations that actually fed it (blocking if periods disagree on
scale), and adding `check_unit_matches_source` to verify the declared unit
against the filing's own scale caption at extraction time.
`UBER_FY2024` unchanged at $102.40; `LYFT_FY2025` corrected to $67.79.
