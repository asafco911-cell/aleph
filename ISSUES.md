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

## #26 Derivation queries match on wording measured against two filers only

`derive_net_debt` (assumptions.py) looked for the substring
"short-term investments". DoorDash's FY2024 10-K prints "Short-term
marketable securities" for the same account - a fully extracted,
gate-verified fact, invisible to the derivation purely because its name
does not contain the query's substring. Uber and Lyft each use stable
wording across both of their own filed years; DoorDash does not, which
makes this worse than the five cross-filer assumptions already documented
in CLAUDE.md - wording is not even stable within one company over time,
let alone across companies.

net_debt still blocked correctly (it always blocks pending an override),
so the pipeline never valued DoorDash on a wrong number. The danger was the
component list PRINTED under that block, which an analyst reads to set the
override: it showed "none extracted" for short-term investments and
implied net_debt was Cash (4,019) less Restricted cash (190) = roughly
-4,019, when the true figure, including the security that was extracted
all along under its other name, is -5,341. Both filings agree the FY2024
short-term balance is 1,322. A block correctly stopped the run and still
handed the analyst an incomplete evidentiary basis, with nothing to flag
that the list was short - a new failure class for this project:
**a block is not protection if the evidence it prints is incomplete.**

FIXED for net_debt specifically: its blocked rationale now lists every
fact extracted from the balance_sheet target that none of the four
component queries matched, by name and value. Verified on DASH_FY2024, the
block now prints, directly under the existing components list: "Extracted
from the balance sheet but matched by none of the queries above:
Short-term marketable securities FY2023=1,422; Short-term marketable
securities FY2024=1,322". Verified on UBER_FY2024 and LYFT_FY2025 (forced
through the blocked path with no override to see it): the extra line is
absent when nothing is unmatched - no change to either's behavior.

The substring query "short-term investments" is DELIBERATELY NOT patched
to also match "marketable securities". A wider substring list only
relocates this exact bug to the next filer that phrases it a third way.
The mechanism that surfaces the miss - printing what the queries did not
match - is the fix; the query stays exactly as narrow, and exactly as
fallible, as it always was, by design.

NOT fixed - a second, live instance of the same bug class, in a different
derivation, found by the same unconsumed-facts measurement that found the
net_debt instance: DoorDash's own income-tax-provision caption is "Total
provision for (benefit from) income taxes" - the inserted "(benefit from)"
breaks derive_tax_rate's computed-fallback substring query "provision for
income taxes" (confirmed: the substring does not match), which is why
DASH_FY2024's effective_tax_rate blocks as "no facts extracted" rather than
computing a rate from real, extracted, gate-verified components.
derive_tax_rate has no equivalent unmatched-evidence line. Deliberately not
fixed here - Task 1c decided against a repo-wide gate, so the fix applies
only where it was measured to have caused real harm (a wrong number an
analyst could have acted on), not to every derivation with the same shape
of latent risk.

Status: open - the net_debt instance is fixed; the derive_tax_rate instance
is not, and the general pattern (a derivation query written against wording
measured on too few filers) remains a real risk in any derive_* function
not yet audited this way.

## #27 check_coverage cannot see a row the model never quoted

Confirmed by a direct synthetic test, not inferred from reading the code: a
fixture with one row fully quoted and extracted across both periods,
alongside a second row never referenced in any Fact's quote at all, run
through the real `validate()`, produces zero coverage rejections for the
second row. `check_coverage` groups facts by `fact.quote` and only ever
examines rows that appear in at least one quote; a row absent from every
quote produces no group, so there is nothing for the gate to iterate over.
This is a structural limitation of the gate as designed, not a bug in one
run of it.

No concrete instance found across the six filings tested tonight.
DASH_FY2024's short-term-securities row (see #26) looked like a candidate
but was not one: the model quoted and extracted that row completely: the
loss happened one layer downstream, in derivation, not here.

Status: open, unmeasured beyond the synthetic proof above.

## #29 A ten-year DCF anchored on one year's FCFF is the wrong instrument for a company mid-inflection

base_cash_flow is a LEVEL quantity (build_level, assumptions.py), taken
from the single most recent period by design. For operating_cash_flow,
this means one year's entire CFO flows into FCFF and the DCF at full
value, with no normalisation step anywhere in the pipeline.
dcf_engine.py's own field comment calls it "most recent normalized FCF"
(DCFInputs.base_cash_flow); nothing normalises anything - the comment
describes an intent the code has never executed. Separately,
base_cash_flow's only tornado bound is built from capex dispersion alone
(build_dcf_inputs, bridge.py) - the sensitivity analysis this project
relies on to surface risk does not carry this risk at all.

MEASURED, not assumed: UBER_FY2024 and UBER_FY2025 value the same
company, at the same $76.95 market price, on the same day, one filing
apart - $77.08 versus $119.95, a 56% move. In the same year: revenue grew
18.3%, net income grew 2.5%, CFO grew 41.5% - three different pictures of
one company. Decomposed directly from the cash flow statement, the whole
gap is non-cash reconciliation: net income and working capital each moved
under 3% of CFO; nearly the entire +2,962 CFO increase (7,137 -> 10,099)
is two lines - deferred income taxes (+1,248) and unrealized gain/loss on
marketable securities (+1,929). These are the SAME valuation-allowance
mechanics already documented as forcing the effective_tax_rate override
(Note 11) - one accounting event distorts two separate inputs to this
valuation, and only one of them was ever blocked pending analyst judgement.

TESTED WHETHER AVERAGING FIXES IT. IT DOES NOT - IT MAKES THE INSTABILITY
WORSE, NOT BETTER: Uber's own four-year FCFF series is -957 (2022), 1,927
(2023), 5,512 (2024), 8,285 (2025). Latest-period basis: 77.08 (FY2024
filing) -> 119.95 (FY2025 filing), +56%. Three-year-average basis: 30.22
-> 75.89, +151%. This is not a general property of averages - it is the
specific composition of this window: moving from the FY2024 filing's
average to the FY2025 filing's, -957 (2022) leaves the three-year window
and +8,285 (2025) enters it, a swing of 9,242 across the window, against
a 2,773 swing in the latest single point alone (5,512 -> 8,285). The
window's composition amplifies the swing already present in the series;
it does not smooth it. There is no stable base to normalise to. Uber's
FCFF went from negative to +8,285 in four years - that is real business
inflection, not measurement noise, and a ten-year DCF anchored on any
single year (or any short average) is the wrong instrument for it.

Computed directly from each quantity's own per-period observations
(CFO, interest, capex, SBC - all already extracted, all already
period-aligned within each filing) and re-run through run_dcf with only
base_cash_flow varied, holding the discount rate, terminal growth, shares
and net debt fixed: UBER_FY2025's three disclosed years imply a value-per-
share range of $26.86 to $119.95. LYFT_FY2025: -$39.37 to $49.06 - the low
bound is negative, because Lyft's FY2023 CFO was itself negative.
DASH_FY2025: $54.85 to $124.27 - the narrowest range of the three, both in
FCFF terms and as a share of the base case.

THE CONTRAST MATTERS: DoorDash does not show this pattern. Its CFO growth
(+299, FY2024->FY2025) is real net income growth (+815) net of a
working-capital drag (-661), not a non-cash swing. Uber's CFO growth is
~97% two non-cash lines. Lyft's reported $1.168B CFO rests on net income
built almost entirely from a $2.897B non-cash tax benefit against a
disclosed PRE-TAX LOSS of $53M, with insurance reserves (41% of CFO) and
accrued/other liabilities (33%) accounting for roughly three-quarters of
the reported figure.

The three FY2025 valuations, at the SAME market date, rank as: Uber
$76.95 market / $119.95 model = 0.64x; Lyft $17.35 / $49.06 = 0.35x;
DoorDash $231.89 / $124.27 = 1.87x. This is the SAME order as CFO
contamination, most to least: Lyft (nearly all of reported CFO is
non-operating) > Uber (nearly all of the YEAR-OVER-YEAR INCREASE is
non-operating) > DoorDash (CFO growth is real). The more contaminated the
base year, the further the model's answer sits below market price. Three
data points is not proof, and this is flagged as a pattern worth
investigating, not a established relationship - but it should be stated,
not left for a reader to notice on their own.

This is not a bug in any single component. Every extraction gate passed,
every unit converted correctly, every override applied as intended - SBC
subtraction, the geography reconciliation, and derive_net_debt's
override-ordering all worked exactly as designed on these same runs. It
is a modelling choice - one year of CFO stands for sustainable owner
earnings - that was never stated as a choice and carries no sensitivity
analysis that would reveal how much the answer depends on it.

Status: open. This is Asi's judgement: whether the honest output is a
range this wide (computed above, from data already in the pipeline), some
other treatment of the disclosed one-off items, or a conclusion that a
single-anchor ten-year DCF is not the right instrument for a company
whose FCFF has moved from negative to positive within its own disclosed
history. Not a code defect to patch.

## Closed

**#1 Connect extractor to DCF engine (Ch8 + Ch9) — CLOSED**
`python scripts\run_valuation.py UBER_FY2024 76.95` -> `Value per share:
77.08`. `python scripts\run_valuation.py LYFT_FY2025 17.35` -> `Value per
share: 49.06`. Both run the full pipeline: extract, derive, bridge, value.
Closed by `a17c103` "Complete extract-to-DCF pipeline (issue #1)",
2026-08-29.

These numbers were 102.40 and 67.79 when this issue closed. The anchor
moved deliberately, once, when #16 closed: stock-based compensation was
decided to be a cash cost and subtracted from FCFF, which lowered both
values by construction. This is not the pipeline drifting - a future
session diffing this file against an old run should look for #16, not for
a regression.

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

**#18 UBER_FY2024 country_risk_premium rationale contradicted its own value — CLOSED**
The rationale opened "ASSUMED ZERO, WHICH IS A DIRECTIONAL ASSUMPTION, NOT
A NEUTRAL ONE" above a committed value of 0.0064, and justified that figure
against the Note 13 geographic split (US 48% / UK 19% / other 32%) the
pipeline no longer selects, having moved to the more granular Note 2 split.
The VALUE was not the problem and was not changed: rewritten against the
mix the pipeline actually reports (US&CAN 54%, LatAm 6%, EMEA 28%, APAC
11%), the same two judgements - which revenue is non-mature (LatAm + APAC
at 17%, plus half of undisaggregated EMEA, giving 31%) and what premium
that weight carries (an assumed 2%, undisclosed) - recompute to 0.0062,
within rounding of the committed 0.0064. The number survived the change of
source data, which is why it was kept rather than restated. `UBER_FY2024`
confirmed unchanged at $102.40 after the rewrite.

**#16 FCFF counts stock-based compensation as free cash flow while the share count carries no dilution model — CLOSED**
Decided: SBC is a cash cost. Subtracted from FCFF at full value - it is
already tax-affected inside net income, so no further `(1 - tax)`
adjustment applies. Share count held FLAT, deliberately: subtracting SBC
from cash flow and also modelling the dilution it funds would double-count
the same cost. The cash_flows extraction target now asks for it directly
(same bounded region, no new target needed); `"capitalized"` excludes
DoorDash's second line, "Stock-based compensation included in capitalized
software and website development costs," which was capitalised into an
asset and already leaves through capex. SBC is a REQUIRED quantity - a
filer where it does not resolve blocks the run rather than valuing at the
old, higher number.

Results: `UBER_FY2024` 102.40 -> **77.08**. `LYFT_FY2025` 67.79 -> **49.06**.
Reverse DCF: at $76.95, the market now implies 10.5% annual growth for ten
years for Uber (was 6.8%); at $17.35, -8.5% for Lyft (was -13.2%).

CAUTION, do not read the 13-cent gap between Uber's $77.08 and its $76.95
market price as validation. It is a consequence of one analyst decision,
not evidence the model is right. It also makes the reverse DCF close to
tautological for UBER_FY2024 specifically: a linear fade from 17.5% to 2.5%
over ten years has an arithmetic mean of 10.0% and a compound CAGR of 9.9%,
and the market-implied 10.5% is essentially that number, not a figure to
agree or disagree with - once value and price coincide, the market is by
construction asking for close to the model's own base case. The tornado is
the informative output now:

`UBER_FY2024` - at the regression-beta end of the tested range the value is
$60.57 against the $76.95 market, 21% below; at the industry-beta base it
is $77.08, on the market. There is no third case tested. Uber is fairly
priced if its systematic risk is the industry's, and 21% expensive if it is
the stock's own - a sentence, not a number.

`LYFT_FY2025` - $17.35 sits 55% BELOW the low end of its own discount-rate
band ($38.57 to $57.85). No discount rate inside the tested range explains
the price. The disagreement between model and market is about cash flow,
not the price of risk - the market is pricing either autonomous
substitution or a CFO of $1.13 billion that is not durable cash (insurance
reserves, working capital) against a pre-tax loss. This also settles the
industry-beta decision (#25) after the fact: bending Lyft's beta to close
this gap would have concealed exactly this result, since the answer is
demonstrably not inside that band.

**#28 derive_geographic_revenue silently merged two overlapping revenue breakdowns for UBER_FY2025 — CLOSED**
"Pick the more granular extraction TARGET" worked only as long as a filing's
two geographic breakdowns arrived from two different notes, which is what
UBER_FY2024 does (standalone Revenue note for the continent split, Segment
Information and Geographic Information for the country split). UBER_FY2025
dropped the standalone Revenue note and merged both breakdowns into Note 13
- confirmed directly in the note's raw text, both tables back to back, each
with its own "Total Revenue $52,017" row. With both breakdowns now arriving
from ONE target, "most granular target" had nothing left to disambiguate:
all 7 regions from two 4-and-3-way partitions were treated as one, and
`geographic_mix()` printed them summing to 100% by coincidence of
arithmetic - the "US at 12 percent instead of 49" failure class recurring
in a new shape, this time inside a single note rather than across two.

Fixed by reconciling against the filing's own stated total revenue
(statement:operations) instead of trusting note or target boundaries: if a
period's geography components sum to roughly the stated total, one
breakdown is present; if they sum to roughly twice it, two breakdowns are
mixed and the two-way split is found by search and the more granular half
kept; anything else is not guessed at and blocks, naming what was found.
This is a superset of the old target-based logic, not a special case of
it: it now also correctly explains why UBER_FY2024's two SEPARATE targets
should combine into the continent breakdown, arriving at the identical
answer as before through reconciliation rather than target-counting.

Verified on all six doc_ids. UBER_FY2024 unchanged: US&CAN 54% / LatAm 6% /
EMEA 28% / APAC 11%. UBER_FY2025 now resolves to the continent breakdown
alone: US&CAN 51% / LatAm 6% / EMEA 31% / APAC 11%, summing to the stated
52,017. LYFT_FY2025, DASH_FY2025, DASH_FY2024 unchanged (single clean
breakdown, no split needed). LYFT_FY2024 unchanged (still blocked, no
geographic note found - pre-existing, unrelated).

A same-size tie (two breakdowns with an equal number of regions) was found
during review to record the one real split twice and block on a
manufactured "2 different splits" disagreement, because the ordered-list
pair key `(group, complement)` is not order-independent when the two
halves are the same length. Fixed with a canonical `frozenset`-of-names
identity for dedup, and a deterministic sorted-name tie-break when sizes
are equal. `scripts/test_assumptions.py` proves it: an equal-sized split
now resolves rather than blocks, alongside cases for the unequal split, no
split needed, and two ways of failing to reconcile.

Does not close #20 (segment-note-total vs statement-total, a different
code path) - only the geography-note case is fixed here.
