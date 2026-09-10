# Aleph - Open Issues

Closed issues are kept here, not deleted, once resolved: the reasoning that
closed them is part of what this repository demonstrates.

## Contents

Numbered issues below are sorted by number, open before closed; the state
is read from the heading. Three thematic sections keep entries that were
never written as `## #N` headings: Decisions (#25), Quality improvements
(#3, #4, #5) and Closed (#1, #2, #6, #7 and the rest of the early run).

OPEN (7)

- #11 Typographic look-alikes break raw string matching across the pipeline
- #22 Item 1A sentence-retention rate is a cross-filer signal, not a calibrated metric
- #29 A ten-year DCF anchored on one year's FCFF is the wrong instrument for a company mid-inflection
- #32 Accounting-quality diagnostics (P4) - built, diagnostic only
- #33 P4.7 + P5 - robustness and economic-correctness audit of the valuation
- #39 Capex excludes capitalized software; DoorDash capitalises more of it than it spends on hardware
- #40 Net debt credits all cash but omits the current portion of debt

CLOSED (15)

- #13 Dispersion test is scale-dependent for rate quantities — CLOSED
- #19 A failed WACC valued the filing off the leftover integration-test discount rate — CLOSED
- #20 Revenue has two independent sources with no cross-check between them — CLOSED
- #21 market.json is keyed by doc_id, duplicating pure market inputs per company — CLOSED
- #23 Three "unexplained" rejections are one fact, one cause, and three correct gates — CLOSED
- #24 DASH_FY2024 has never been valued — CLOSED as out of scope
- #26 Derivation queries match on wording measured against two filers only — CLOSED
- #27 check_coverage cannot see a row the model never quoted — CLOSED
- #30 sha256 is recorded as content identity but never used to detect a replaced document — CLOSED
- #31 eval-gate.yml could only ever fail on a fresh clone — CLOSED
- #34 `pytest tests/` could not pass on a fresh clone, for the same reason #31 could not — CLOSED
- #35 The extraction prompt was outside the cache key AND outside every check — CLOSED
- #36 Eleven places under `src/aleph/` each decided where `data/` is — CLOSED
- #37 `data/README.md` quoted the anchor under the range's label — CLOSED
- #38 The engine grew a negative FCFF for ten years and called it a valuation — CLOSED


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

STRENGTHENED, not reversed, once #16's tornado fix landed: LYFT_FY2025's
discount_rate swing measured 39% - the figure this decision was made
against - and looked like the dominant driver only because
base_cash_flow's own bound tested capex dispersion, which carries none of
the risk #16 measures. With that fixed, base_cash_flow's own swing is
180%, the largest of any driver in any of the four runs tested. Bending
beta to close a 39% gap while the real, larger driver went unmeasured
would have hidden the actual problem, not solved it - the decision to
hold beta constant stands on firmer evidence now than when it was made.

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
normalisation. `src/aleph/infra/textnorm.py` now handles this for manifest
work. (This line said `scripts/textnorm.py` until 2026-09-06 - the module
moved into the package during the src/ layout change and the reference did
not follow. Found by a sweep that resolved every documented script path
against the filesystem; it was the only one of fifteen that did not exist.)

Unverified: whether the BM25 index built in ch04 tokenises `management's` and
`management's` as distinct terms. If so, every query containing an apostrophe
behaves differently than assumed, and this may explain retrieval behaviour
not previously understood. Needs measurement, not assumption.

Fix (pending measurement): route all BM25 indexing and query text through
`textnorm.normalise` before tokenisation.

Status: open, unmeasured.

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

The reverse DCF is not an independent check on this instability - it
inherits the same base_cash_flow dependency rather than escaping it.
`run_valuation.py` calls `reverse_dcf(bridged.inputs, market_price)`,
which holds `base_cash_flow` fixed at the latest-period value and searches
only over `growth_rates`; the base is never varied. The implied growth
rate it reports is conditional on which year's FCFF happened to be the
latest-period basis, same as the point valuation is. Confirmed by reading
`reverse_dcf` (`dcf_engine.py`) and its call site directly, after an
initial claim to the contrary - that it "doesn't touch the contaminated
cash-flow base at all" - turned out to be wrong and was caught before it
reached the README.

## #32 Accounting-quality diagnostics (P4) - built, diagnostic only

`src/aleph/valuation/accounting_quality.py`. The pipeline could say "this
number was extracted correctly" but not "how economically informative is
this number". P4 adds that second layer, and ONLY that: it reads verified
facts and reports what they imply about how well reported earnings and cash
flow represent sustainable earning power. It changes no FCFF, no WACC, no
growth rate, no share count, no value.

WHAT WAS BUILT. Ten deterministic diagnostics across eight dimensions -
earnings vs cash, accrual intensity, working-capital quality, revenue
quality (a cash-collection proxy), capital intensity, maintenance-capex
verifiability, SBC materiality, SBC dilution, large non-cash earnings
adjustments, and cash one-offs. Each returns a `Diagnostic` with separate
FACT / DIAGNOSTIC / INTERPRETATION / VALUATION-RELEVANCE fields, a state
(`FLAGGED` / `ASSESSED_NO_ISSUE` / `INSUFFICIENT_DATA` / `NOT_APPLICABLE` /
`NOT_ASSESSED`), a horizon (`LATEST_PERIOD` / `HISTORICAL_PATTERN` /
`TREND` / `SINGLE_YEAR_ANOMALY`), a qualitative
`potential_valuation_impact` (`NONE`..`HIGH`/`UNKNOWN`), and `Evidence`
rows carrying the source fact's quote and page reference. `converging_risks`
LISTS the flags that point the same way - it is a sentence, never a number,
and `test_convergence_is_not_a_number` asserts it has no score attribute.

NO SYNTHETIC SCORE. There is deliberately no "73/100". A company can have
clean earnings and weak cash conversion at once; the dimensions are kept
apart.

NO LLM. Every number is Python over gate-verified `Fact` objects. The LLM
extracted and quoted those; it computes no ratio, picks no threshold,
decides no impact here.

NO FRAUD LANGUAGE. The strongest wording is "accounting-quality risk". A
`_FORBIDDEN` guard plus `has_forbidden_language()` plus tests over the
converging and real-like reports enforce it.

THRESHOLDS carry rationale + economic interpretation + limitation at their
definition (`SBC_TO_REVENUE_MATERIAL` etc.) and are echoed on the
`Diagnostic.threshold` field. `MATERIAL_DEVIATION = 0.25` is reused verbatim
from `historical_fcff` / `cfo_normalization` so the three modules cannot
drift on "materially different". A threshold gates a FLAG and nothing else;
the underlying series is always printed so a reader is not taking the flag
on trust.

CANNOT TOUCH VALUATION - the P4 invariant, tested three ways in
`tests/test_accounting_quality.py::TestP4CannotTouchValuation`:
`assess_accounting_quality` runs LAST in `value_filing`, after `run_dcf`
and `reverse_dcf` (asserted against source order); an all-HIGH-impact
report monkeypatched in leaves `value_per_share`, `enterprise_value`,
`equity_value`, `wacc` and `base_cash_flow` byte-identical; and the
UBER_FY2024 77.08 anchor holds with P4 present.

WHAT P4 CANNOT SEE, measured and surfaced rather than hidden:
- Balance-sheet receivable / inventory / deferred-revenue LEVELS are not
  extracted, so revenue-quality works off the cash-flow "change in accounts
  receivable" as a collection-lag PROXY, stated as such in every such
  diagnostic. Where even that line is absent (LYFT_FY2025), the state is
  `INSUFFICIENT_DATA`, not a pass.
- A one-time CASH cost never appears as its own reconciliation caption
  (see #29 and cfo_normalization.py). P4 identifies non-cash earnings
  adjustments from the reconciliation; a cash one-off is identified ONLY
  from analyst-supplied `CashOneOff` evidence, else
  `NO_CASH_ONE_OFF_IDENTIFIED` - explicitly NOT `NO_CASH_ONE_OFF_EXISTS`.

CROSS-FILER, measured on the cached extractions: UBER_FY2024, UBER_FY2025,
LYFT_FY2025 and DASH_FY2025 all run without a company-specific branch.
UBER_FY2024 and LYFT_FY2025 both raise `CONVERGING_ACCOUNTING_QUALITY_RISKS`
(HIGH_ACCRUAL_COMPONENT, ONE_YEAR_WORKING_CAPITAL_SWING, HIGH_SBC) - the
same picture #29 and the tax-rate overrides describe from a different angle.
DASH_FY2025 flags HIGH_SBC and REVENUE_CASH_DIVERGENCE and does not
converge.

Fact wording is resolved by tolerant substring, the way `assumptions.py`
does it, not one exact caption: measured, Uber writes "Net cash provided by
operating activities" and Lyft writes "Net cash provided by (used in)
operating activities", and an exact match on the first silently drops every
Lyft period into INSUFFICIENT_DATA. Caught during P4 cross-filer testing,
before it shipped.

Tests: `tests/test_accounting_quality.py`, 39 cases - a positive case and a
negative control for every dimension, the #13 CFO/NI examples both ways, the
#14/#15/#16/#17 adversarial cases, insufficient-data, convergence, the
no-fraud-language guard, traceability, and the cannot-touch-valuation
regression. Suite: 179 -> 218.

P4.5 HARDENING PASS, 2026-09-07 - three weaknesses from P4's own report, no
new diagnostics, no redesign:

1. SINGLE-PERIOD SEMANTICS. `Diagnostic` gains `confidence` (`NORMAL` /
   `LIMITED`). A diagnostic assessed from fewer than three periods is
   `LIMITED`; an `ASSESSED_NO_ISSUE` from one period additionally gets
   `horizon=SINGLE_YEAR` and its interpretation rewritten to "No issue
   identified in the observed data ... historical persistence cannot be
   assessed" - the strings "historically clean", "structurally normal",
   "no accounting-quality concern" are now in an `_OVERCLAIM` guard with
   `has_overclaiming_language()` and a standing test. A `FLAGGED` finding
   from thin history KEEPS its flag (a real one-year signal is still a
   signal) but is marked `LIMITED` and says persistence is untested.

2. WORKING-CAPITAL CLASSIFICATION FAILS CLOSED. `_classify_wc_line` returns
   a bucket, `UNKNOWN_OPERATING_COMPONENT`, `EXCLUDED_NON_OPERATING`,
   `STRUCTURAL`, or `NO_CHANGE_MARKER`. A cash-flow line counts as working
   capital only if its caption carries a change marker ("change in ...",
   "(change)") - measured: Uber/Lyft write the first, DoorDash the second -
   which stops capex and the net-change subtotal being swept in. A
   change-marked line that matches no bucket is `UNKNOWN_OPERATING_COMPONENT`:
   summed into the net total (never dropped) and named in a
   `WorkingCapitalCoverage` (`FULL` / `PARTIAL` / `NO`, with `classified`,
   `unclassified`, `coverage_ratio`, `unknown_components`). Below
   `WC_COVERAGE_SUFFICIENT` (0.85) or with no bucket at all, the diagnostic
   returns `INSUFFICIENT_DATA` - the movement SIZE is still reported, the
   composition claim is withheld. An unmarked cash-flow line that is not
   clearly non-cash is listed as an `unmarked_candidate` and downgrades
   `FULL`->`PARTIAL` when material (>10% of the movement). Buckets were
   widened generically (insurance/loss reserves, `lease liabilit`,
   `right-of-use`, `customer-related`, `other operating`) - no issuer
   name appears in the module, asserted by a test that greps the source.
   Synthetic fifth-company fixture with captions like "Operating assets and
   liabilities, net (change)" leaves that line UNKNOWN, visible, counted,
   and blocks a FULL-attribution claim.

3. REVENUE QUALITY - EPISTEMIC LABEL, NOT A STRONGER CLAIM. Every
   revenue-quality output now carries `_REVENUE_PROXY_LIMITATION`: "This is
   REVENUE_CASH_DIVERGENCE, not a full REVENUE_QUALITY_ASSESSMENT" - the
   AR balance, contract assets, contract liabilities / deferred revenue and
   the allowance are not extracted, so the flag rests on the cash-flow
   receivables-change proxy and "is not sufficient by itself to establish a
   revenue-recognition issue". A flagged divergence is stated as a
   single-year move explicitly NOT called structural deterioration; when
   the series shows an earlier drag spike that reversed, that is named as
   timing. The flag key stays `REVENUE_CASH_DIVERGENCE`; there is no
   `REVENUE_QUALITY_PROBLEM` / `REVENUE_QUALITY_ASSESSMENT` key.

DATA EXPANSION (P4.5 item 4): NOT done. Adding `accounts_receivable`,
`contract_assets`, `contract_liabilities`, `deferred_revenue`,
`allowance_for_doubtful_accounts` to `targets.py` would need a cold
re-extraction of every filing against the live API and a changed committed
cache, and carries an unmeasured collision risk in `derive_net_debt` across
filers - outside a narrow hardening pass. Recorded as a P5/P8 candidate:
the balance-sheet extraction target would gain those fields, the P3
contract would mark them OPTIONAL (missing stays explicitly missing), and
revenue quality would upgrade from proxy to a receivables-turnover /
deferred-revenue analysis.

Suite: 218 -> 240 (`tests/test_accounting_quality_p45.py`, 22 cases).
Anchors unchanged (77.08 / 49.06); `TestP45CannotTouchValuation` asserts
per-share, EV-equity consistency and WACC are untouched with the confidence
and coverage fields present.

RESIDUAL (documented, not a defect to patch): a single-period LEVEL ratio
(SBC/revenue, capex/CFO) still reaches `ASSESSED_NO_ISSUE` with one year of
data - but now `confidence=LIMITED`, `horizon=SINGLE_YEAR`, and an
interpretation that explicitly declines to speak about persistence. A
working-capital line with no change marker and no non-cash marker
(DoorDash's "Funds held at payment processors") is excluded from the net
total by rule and surfaced as an `unmarked_candidate` rather than counted -
a deliberate fail-closed choice that can undercount WC for a filer whose
captions omit the marker; the coverage line makes the omission visible.

P4.6 ADVERSARIAL AUDIT, 2026-09-07 - a hostile validation pass over
P1-P4.5. No new diagnostics. Nine vulnerabilities found, eight fixed, one
documented. Mutation-tested: 18 mutations of the safeguards, all killed
after two follow-up tests were added for survivors.

- F1 (HIGH, FIXED) - the convergence engine called correlated diagnostics
  "independent". A single synthetic receivables build raised four flags
  (`CASH_EARNINGS_DIVERGENCE`, `HIGH_ACCRUAL_COMPONENT`,
  `REVENUE_CASH_DIVERGENCE`, plus a WC flag) and the summary said "4
  independent diagnostics point the same way" - they are four measurements
  of one NI<->CFO event. Fix: `_CONVERGENCE_FAMILY` groups every eligible
  flag into an accounting RELATIONSHIP (`cash_vs_earnings`,
  `equity_compensation`, `capital_intensity`, `one_off_cash`); convergence
  now requires >= CONVERGENCE_MIN_FLAGS flags spanning >=
  CONVERGENCE_MIN_FAMILIES (2) distinct families, and the summary lists the
  families and states "Flags within one dimension are different measurements
  of the same relationship, not independent signals." Uber/Lyft still
  converge (cash_vs_earnings + equity_compensation); the pure single-family
  case no longer does.
- F2 (MEDIUM, FIXED) - convergence counted single-period LIMITED-confidence
  flags silently alongside NORMAL ones. `ConvergingRisks.limited_flag_count`
  is now reported and the summary discloses "N of M contributing flags rest
  on single-period (LIMITED-confidence) evidence".
- F3 (HIGH, FIXED) - the working-capital classifier routed financing and
  investing "change in" lines (`Change in long-term debt`, `Change in
  short-term borrowings`, `Change in marketable securities`, `Change in
  restricted cash`, `Change in cash and cash equivalents`) to
  `UNKNOWN_OPERATING_COMPONENT`, which summed them into the net WC total,
  distorting the CFO-dependence magnitude and mislabelling a financing flow
  as operating. `_WC_NOT` extended with a generic financing/investing block
  (no issuer aliases). The real corpus is unchanged.
- F4 (HIGH, FIXED) - P4 ratios did not verify numerator and denominator
  share a unit scale. `_monetary_scale` (bare "USD" resolves to 1e-6, not
  None, unlike `infra.units.resolve_scale`) plus `_scale_conflict` detect a
  mixed-scale set up front; every cross-metric diagnostic
  (`CASH_EARNINGS_DIVERGENCE`, `HIGH_ACCRUAL_COMPONENT`,
  `HIGH_CAPITAL_INTENSITY`, `HIGH_SBC`,
  `LARGE_NON_CASH_EARNINGS_ADJUSTMENTS`) is forced to `INSUFFICIENT_DATA`
  with an explicit reason (ISSUES.md #15 class).
- F5 (MEDIUM, FIXED) - `_series` detected conflicting facts (same period,
  different value) but every caller discarded the clash set: first-seen
  won silently. `assess_accounting_quality` now collects the clashes; a
  metric with a conflict forces every diagnostic that consumes it to
  `INSUFFICIENT_DATA` and the report carries a `CONFLICTING SOURCE FACTS`
  note. No conflict exists in the current corpus - this is a latent guard.
- F6 (LOW, DOCUMENTED) - a flag one microstep past a threshold is already
  hedged ("Not a quality verdict on its own", `threshold` field states the
  rule, `_OVERCLAIM` blocks "proven"). A `TestThresholdLanguage` test pins
  the hedge. No wording change made.
- F7 (LOW, FIXED) - P4 read raw facts with no period-label guard. `_series`
  now ignores anything but an annual `FY####` label, so a quarterly or
  stub-period figure cannot be mixed into an annual series (the P3 gate's
  equivalent, for the diagnostic path).
- F8 (LOW, FIXED) - `SBC/revenue` and `SBC/CFO` were computed against a
  possibly-negative denominator. Now gated on a positive denominator;
  when neither revenue nor CFO is positive the diagnostic is
  `INSUFFICIENT_DATA`, not `ASSESSED_NO_ISSUE`.
- F9 (HIGH, FIXED, self-inflicted) - a mutation-testing harness timed out
  under SIGKILL mid-run and its `finally` restore did not execute, leaving
  `_classify_wc_line` returning `"receivables"` for every unbucketed line.
  Caught by the P4.6 tests within minutes, reverted, and the harness
  rewritten to back up outside the tree and restore unconditionally.
- Non-finite values: `_series` drops any fact whose value is NaN or inf
  (corrupt data) so it cannot propagate into a ratio.
- Valuation isolation re-verified: `accounting_quality.py` imports only
  stdlib; `assess_accounting_quality` runs last in `value_filing`, after
  `run_dcf`/`reverse_dcf`, and nothing reads its result back. An absurd
  (inf-valued, all-HIGH) monkeypatched report leaves per-share, EV, equity,
  WACC, terminal value and implied growth byte-identical.
- Test-suite reality check (P4.6 section 9, documented not fixed): P4 runs
  UNGUARDED in `value_filing`. An exception inside `assess_accounting_quality`
  currently propagates and takes down an otherwise-valid valuation.
  `test_p4_exception_does_not_take_down_a_valid_valuation` pins this
  behaviour so a future try/except is a deliberate decision, not an
  accident. This is the one CURRENT weakness and it is a robustness gap,
  not an economic-correctness or isolation gap.

Suite: 240 -> 301 (`tests/test_accounting_quality_p46.py`, 61 cases).
Anchors unchanged (77.08 / 49.06). All 11 standalone scripts pass.

## #33 P4.7 + P5 - robustness and economic-correctness audit of the valuation

P4.7 (the one open P4.6 item) and a P5 robustness pass on the DCF engine
itself. Diagnostic layers only; no anchor moved; the LLM is not involved in
any of it.

P4.7 - `assess_accounting_quality` in `value_filing` is now wrapped: an
exception is captured with provenance and surfaced as
`AccountingQualityReport.not_assessed(reason=...)` (field
`not_assessed_reason`, CLI prints `ACCOUNTING QUALITY: NOT ASSESSED`). The
valuation is already final when P4 runs and is NOT recomputed; a test
proves per-share / EV / equity / WACC / FCFF / terminal / implied-growth
are byte-identical to a clean run and that `run_dcf` is called the same
number of times (3), i.e. no downstream recomputation. A clean run is
unchanged.

P5 DCF-ENGINE GUARDS (`dcf_engine.validate`) - fail closed, never emit a
NaN / inf / crash dressed as a valuation. Measured before: `base_cash_flow`
0 -> ZeroDivisionError; inf / NaN -> leaked to `value_per_share`;
`discount_rate <= -1` -> ZeroDivisionError; `net_debt` inf -> `-inf`
per-share. Added Guard 0 (all numeric inputs finite), 0b
(`discount_rate > -100%`), 0c (`base_cash_flow != 0` -> else NOT_SOLVABLE),
and a `total == 0 / non-finite` guard in `run_dcf`. The 77.08 / 49.06
anchors are unaffected - their inputs are finite and well-posed. `WACC <= g`
was already caught by Guard 1; boundary tests (g == r, g == r ± ε) pin it.

P5 ROBUSTNESS LAYER (`src/aleph/valuation/robustness.py`) - a new
DIAGNOSTIC module, isolated like P4: imports only `dcf_engine` (to re-run
the PURE engine on COPIES) and stdlib; never the bridge, WACC, assumptions
or accounting-quality. `value_filing` attaches a `RobustnessReport` LAST,
wrapped like P4.7. It measures and EXPOSES, never adjusts:
  - ANCHOR_SENSITIVITY: value under latest / mean / median / each disclosed
    FCFF year. UBER_FY2024 spans -$14.13 to $77.08 (290% of midpoint) ->
    `HIGH`. LYFT_FY2025 spans -$39.37 to $49.06 (1826%) -> `HIGH`. No anchor
    is promoted; averaging is labelled a STATISTIC and #29's warning that it
    can widen the instability is carried in the interpretation.
  - TERMINAL_VALUE_DEPENDENCE: `result.terminal_pct`, categorised
    (>90% extreme, >80% high). Both live filings sit at ~60%.
  - ASSUMPTION_SENSITIVITY / PRIMARY VALUE DRIVER: reads the tornado the
    pipeline already builds. For both filings `base_cash_flow` dominates
    (UBER 118% swing vs 39% discount_rate; LYFT 180% vs 39%).
  - REVERSE_DCF_CONSISTENCY: feeds the implied growth back into the forward
    engine and checks it reproduces the market price (1% tolerance). Both
    round-trip (UBER 0.03%, LYFT 0.09%) - and the interpretation states this
    is a restatement under the SAME assumptions, "not an independent check".
    `implied_growth is None` -> `NOT_SOLVABLE`, never an invented rate.
  - VALUE_BRIDGE_INTEGRITY: asserts `equity == EV - net_debt` and
    `per_share == equity / shares` to 1e-9, plus scale sanity (per-share
    outside 1e-2..1e6, or net-debt > 50x EV -> `SCALE ANOMALY`, the
    ISSUES.md #15 1000x class).
  - HISTORICAL_REGIME: sign change / monotonic trend / tight-band-then-jump
    over the FCFF series. Both live filings change sign -> `HIGH`, "series
    may NOT be comparable across time"; a comparable series is explicitly
    "NOT a statement that the level is right".
  - VALUATION_METHOD_LIMITATION: negative base FCFF -> `HIGH`, "a Gordon
    DCF on a negative cash flow compounds a loss; the output is arithmetic,
    not a valuation".
`FailureCategory` (Phase 14): `categorize_failure(exc)` maps each pipeline
exception to one of ten categories + a usability note. A valuation is never
just "failed".

MUTATION TESTED (Phase 12): 20 mutations of the DCF guards and robustness
safeguards, all killed after four follow-up tests were added for survivors
(zero-base guard, total==0 guard, reverse-DCF tolerance, EV/equity link -
each was a defence-in-depth survivor caught only once a test pinned the
specific check).

Suite: 301 -> 371 (`tests/test_robustness.py`, 69 cases). Anchors 77.08 /
49.06 unchanged. All 11 scripts pass.

THE HEADLINE FINDING, stated plainly: the anchor and regime instability
that #29 identified is REAL, LARGE, and now MEASURED IN THE OUTPUT. For
UBER_FY2024 the valuation is anywhere from -$14/share to $77/share
depending on which disclosed year's FCFF is taken as run-rate, and
`base_cash_flow` swings the answer more than every other assumption
combined. P5 does not resolve this - #29 established that no single anchor
or statistic can - it makes it impossible to read the $77.08 point estimate
without also seeing that range and that dependence. That is the correct
outcome for an economic sensitivity: expose it, do not eliminate it.

P5 CONTROLLED IMPLEMENTATION, 2026-09-08 - after a full Phase 2 forensic
audit (V1-V14) the following controls were built. None moved the point
value: UBER_FY2024 $77.08, LYFT_FY2025 $49.06 unchanged.

- P5.1 PROVENANCE INTEGRITY (V3, genuine defect). `bridge.build_dcf_inputs`
  hard-coded `Assumption(source="filing")` for every input. It now reads
  `ranges[name].status`: an override -> `analyst_judgment`; a computed
  statistic or the FCFF composite -> `derived`; a single gate-verified
  level -> `filing`. `dcf_engine.Assumption.source` Literal widened to
  {filing, derived, market, analyst_judgment, model_convention, peer_group};
  `app.py` GRADES updated. Measured before/after: `net_debt` filing ->
  analyst_judgment (both filings, always an override); LYFT `growth_year_1`
  filing -> analyst_judgment (a 9.2% override); UBER `growth_year_1` filing
  -> derived (a median); `base_cash_flow` filing -> derived with a LINEAGE
  note naming the effective_tax_rate assumption it embeds. `terminal_growth`
  stays analyst_judgment, `discount_rate` stays market.

- P5.2 MODEL CONVENTIONS FIRST-CLASS (V14). `robustness.model_conventions()`
  returns a 10-entry registry of `ModelConvention(name, value, rationale,
  location, effect, classification=MODEL_CONVENTION)`, values read live where
  possible (forecast horizon 10, growth statistic median, linear fade
  17.46%->2.50%, terminal growth 0.025, cap 0.03, beta factors 0.75/1.45,
  reverse-DCF window -50%/+100% and tolerance 0.001, SBC full-value + flat
  shares, net-cash WACC clamp). Attached to `ValuationRun.robustness`; the
  CLI prints it. A reader can now enumerate every convention from the run.

- P5.4 HISTORY COMPARABILITY (V2). `_history_comparability` - a deterministic
  LIMITATION framework, not a regime classifier. Conditions: FCFF sign
  change, any YoY FCFF change > 100%, a missing fiscal year, < 3 years,
  a revenue-growth band > 15 points, historical FCFF reconstructed with an
  assumption (the flat-interest substitution). Taxonomy: `HIGH_CONCERN` /
  `LIMITED` / `NO_DETERMINABLE_CONCERN` / `NO_DETERMINABLE_CONCLUSION`. It
  NEVER says "the business entered a new regime" - only "the series is not
  clearly one regime". Both live filings -> HIGH_CONCERN (sign change).

- P5.6 WACC INPUT QUALITY (V6/V7). `_wacc_input_quality` separates
  MATHEMATICAL validity from MARKET-INPUT integrity. Deterministic checks:
  missing / non-finite input -> `BLOCKED`; a source or rationale marked
  UNVERIFIED -> `INSUFFICIENT_EVIDENCE`; stale (rf/ERP as_of months differ),
  extreme (beta outside 0.2-3.0, ERP outside 2-10%, rf > 15%), or
  undisclosed-judgement input -> `LIMITED`; else `OK`. It NEVER clamps and
  NEVER picks a new WACC. Measured: UBER -> LIMITED (Jan-2026 ERP with
  Aug-2026 rf; undisclosed CRP method); LYFT and DASH ->
  INSUFFICIENT_EVIDENCE (debt_spread marked UNVERIFIED FOR THIS FILER).

- P5.7 REVERSE DCF CORRECTNESS (V4, genuine math defect).
  `dcf_engine.reverse_dcf` rewritten: it samples value(g) across the
  window, establishes monotonicity DIRECTION (rises with g for a positive
  anchor, FALLS for a negative anchor), checks the target price is bracketed
  by the attainable range, then bisects with the correct orientation. A
  non-monotonic / near-flat value(g), an unattainable target, or an invalid
  interior point returns None (NOT_SOLVABLE) - it never guesses and never
  blindly shrinks the bracket. The forward faded-growth DCF is NOT inverted;
  the docstring and the output label it "the uniform-growth equivalent
  implied by the market price under current non-growth assumptions". UBER
  10.5% and LYFT -8.5% are unchanged (positive anchors, monotone
  increasing, target bracketed).

- P5.8 VALUE-BRIDGE INPUT INTEGRITY (V5, genuine 1000x defect).
  `assumptions.build_level` gains `require_unit`; `derive_diluted_shares`
  passes it. A diluted-share fact with no unit string now BLOCKS with
  `INVALID_UNIT` instead of falling back to an assumed "thousands" - the one
  quantity `gates.check_unit_matches_source` deliberately skips. `net_debt`
  override units were already fail-closed at `to_millions` (a token-free
  unit raises BridgeError); a wrong-but-valid-scale typo is caught only by
  the robustness magnitude check - documented residual.

- P5.12 FAILURE TAXONOMY. `FailureCategory` (10 values) + `categorize_failure`
  map every pipeline exception to a category + a usability note; each
  `RobustnessFinding` carries an optional `category`.

MUTATION TESTED (P5, round 1): 22 mutations of the P5 controls. 19 killed;
3 survived - all three over-determined internal guards in `reverse_dcf`
(attainability, non-monotonic, invalid-mid). Resolved in P5.1 closure below.

Suite: 371 -> 408 (`tests/test_p5_controls.py` 37 cases, plus 2 cross-sector
fixtures). All 11 scripts pass. Anchors unchanged.

---

P5.1 CLOSURE PASS, 2026-09-08. Goal: make P5 internally complete - a
mathematically correct valuation must also state whether it is economically
usable. No new valuation method; no anchor selection; no clamp; negative
values are shown, not hidden. Point values unchanged: UBER_FY2024 $77.08,
UBER_FY2025 $119.95, LYFT_FY2025 $49.06, DASH_FY2025 $124.27 (EV, equity,
WACC, terminal-value share and reverse-DCF implied growth all byte-stable).

- REVERSE-DCF SURVIVORS RESOLVED (Part 1). `reverse_dcf` rewritten around a
  closed-form monotonicity proof in its docstring: with K = (1+g_T)/(r-g_T)
  and run_dcf having already enforced r > g_T and S > 0, Phi(x) is strictly
  increasing in x hence in g, so value(g) is strictly increasing for B > 0,
  strictly decreasing for B < 0, and undefined for B = 0. There is no
  non-monotonic case and no partial-validity pocket. The non-monotonic guard
  and the invalid-mid guard were therefore DEAD and were removed. The two
  remaining runtime checks - window well-posed, target bracketed - are
  genuine bisection preconditions, each now isolated by a mutation-killing
  test (`test_ill_posed_window_returns_none_not_a_type_error`,
  `test_target_just_above_the_attainable_max_is_not_solvable`). The solver
  also no longer aliases its argument (was `trial = inputs` under mutation;
  now `deepcopy`, pinned by `test_reverse_dcf_does_not_mutate_its_input`).

- NEGATIVE / ZERO EQUITY (Part 2). `_negative_equity` -> a first-class
  `NEGATIVE_EQUITY_VALUE` finding (Severity.HIGH, category
  ECONOMIC_MODEL_FAILURE). Interpretation is "MATHEMATICALLY VALID,
  ECONOMICALLY LIMITED ... NOT an ordinary bear-case intrinsic value". The
  DCF arithmetic is untouched; the negative per-share number is still
  returned. equity ~ 0 is reported as the break-even case.

- NET-DEBT UNIT INTEGRITY (Part 3). Two layers. (a) `derive_net_debt` blocks
  INVALID_UNIT when `infra.units.resolve_scale(override.unit)` is None - a
  bare "USD", empty, "percent", or two scale tokens is rejected; the scale
  is never inferred. (b) `bridge.build_dcf_inputs` cross-checks the net_debt
  scale against the operating-cash-flow scale and raises BridgeError on a
  mismatch - this is what catches a magnitude-plausible thousands/millions
  typo that passes `to_millions` (both are valid single tokens). "Magnitude
  sanity is not unit verification."

- SHARE-UNIT SWEEP (Part 4). `build_level(require_unit=True)` +
  `resolve_scale`: thousands / millions / billions / "USD thousands" derive;
  blank / "each" / "widgets" / "thousands millions" / "USD" BLOCK with
  INVALID_UNIT; a conflicting duplicate share caption is an ambiguous-
  selection block. No magnitude rescue, no diagnostic rescue - the value
  never reaches the DCF.

- VALUATION APPLICABILITY (Parts 5-10). New categorical status on every run
  (NOT a confidence score): `Applicability` in {USABLE,
  USABLE_WITH_LIMITATIONS, LIMITED_APPLICABILITY, NOT_SOLVABLE, BLOCKED}.
  `_applicability(findings)` consumes only evidence already computed and
  applies EXPLICIT rules (documented as the `valuation_applicability_rules`
  ModelConvention). Correlated findings are grouped into economically-
  distinct FAMILIES via a single map `_LIMITATION_FAMILY` / `_family()`:
  anchor sensitivity + historical regime + history comparability all fold to
  `cash_flow_representativeness`; the several WACC sub-reasons from one stale
  ERP fold to `market_input_evidence`. One root cause escalates applicability
  once, never five times. Part 7 rule is literal: ANCHOR_SENSITIVITY HIGH
  AND HISTORY_COMPARABILITY HIGH_CONCERN -> LIMITED_APPLICABILITY, and the
  point value stays the latest-anchor value.

- CENTRAL CONCLUSION (Part 16). `RobustnessReport.headline_conclusion`, a
  machine-readable, euphemism-free sentence, surfaced in the CLI above the
  robustness block. For the cash-flow-family case it reads exactly: "The
  valuation is mathematically valid, but the choice of the latest FCFF year
  is a dominant economic assumption and historical cash-flow comparability
  is limited." Not "valuation confidence is medium".

- LIVE FILINGS (Part 11). UBER_FY2024 LIMITED_APPLICABILITY (families:
  cash_flow_representativeness, market_input_evidence). UBER_FY2025
  USABLE_WITH_LIMITATIONS (history only LIMITED, not HIGH_CONCERN).
  LYFT_FY2025 and DASH_FY2025 LIMITED_APPLICABILITY (anchor HIGH + history
  HIGH_CONCERN + WACC INSUFFICIENT_EVIDENCE from the UNVERIFIED debt spread).

- DEAD-CODE / EXPERIMENTAL MARKERS (Part 15). `historical_fcff.py`,
  `cfo_normalization.py`, `normalization.py`, `sensitivity.py` carry a
  "STATUS: EXPERIMENTAL - NOT IN THE LIVE VALUATION PATH" banner. Measured:
  none is imported by `valuation/pipeline.py` or `scripts/run_valuation.py`;
  each is exercised only by its own test file. The live valuation is
  extraction -> assumptions -> contract -> wacc -> bridge -> dcf_engine,
  with accounting_quality and robustness as diagnostic-only layers. The
  research is kept, not deleted; wiring any of it in needs an ADR.

MUTATION TESTED (P5.1 closure, round 2): 19 mutations across bridge,
dcf_engine, assumptions, robustness (provenance, negative-equity finding +
rule, net-debt unit gate x2, share-unit gate x2, anchor / comparability / TV
thresholds, WACC-quality propagation, evidence-family de-dup x2, reverse-DCF
orientation / attainability / well-posed probe / input isolation, central
conclusion). 19 / 19 KILLED. Combined with round 1's material kills, every
retained safeguard on the P5 surface is now isolated by a test; the two
guards that could not be isolated in round 1 were removed as provably dead,
not reclassified.

Suite: 408 -> 451. All 11 standalone scripts pass. Anchors unchanged.

VERDICT: P5 SOLVED. The latest-FCFF-anchor / historical-non-comparability
economic sensitivity is NOT resolved (ISSUES.md #29 - it is inherent, and
averaging makes it worse). It is now CLASSIFIED: those filings report
LIMITED_APPLICABILITY with the reason stated in plain language. A
mathematically correct valuation that is economically fragile no longer
looks identical to one that is not.

---

P6 - SUSTAINABLE FCFF FRAMEWORK, 2026-09-08. EXPERIMENTAL, not wired in.
Question: can Aleph move from "latest reported FCFF" toward an
evidence-defensible SUSTAINABLE FCFF without manufacturing certainty?

- NEW MODULE `src/aleph/valuation/sustainable_fcff.py` (EXPERIMENTAL banner).
  Deterministic. Imports stdlib + dcf_engine + infra.units + (lazily)
  bridge. NOT imported by pipeline.py or run_valuation's base path; a
  regression test asserts `"sustainable_fcff" not in pipeline source`.
  run_valuation.py calls it directly in a clearly-fenced EXPERIMENTAL block
  AFTER the base valuation is printed.

- METHOD. For every disclosed period it splits reported CFO into
  (CFO - working capital) and (working capital), where working capital is
  the sum of the "change in <account>" reconciliation lines the extractor
  already pulls. It then VALIDATES that net income + every non-cash add-back
  (SBC included) + working capital reproduces reported CFO within 3.5% /
  $75m, and REFUSES the decomposition for that period otherwise. No LLM
  decides recurring vs one-off. No regression, no score, no smoothing.

- SEVEN OBJECTS kept distinct: reported cash flow; reconstructed FCFF;
  normalized FCFF; sustainable FCFF (a RANGE); transition-period FCFF;
  analyst assumption; model convention.

- REGIME is deterministic: <3 years -> INSUFFICIENT_HISTORY; FCFF sign
  change -> REGIME_UNCERTAIN; a missing/non-reconciling component ->
  REGIME_UNCERTAIN; tight band (<=25% of median) ->
  EVIDENCE_CONSISTENT_WITH_STRUCTURAL_CHANGE; an UPWARD isolated final spike
  (>100% above the tight prior band) -> EVIDENCE_CONSISTENT_WITH_TEMPORARY;
  a monotonic non-sign-changing trend -> REGIME_UNCERTAIN. A downward step
  is never called "temporary" - that would argue the company is better than
  it looks.

- RANGE (only when the latest period reconciles): HIGH = latest
  reconstructed FCFF exactly as disclosed (never more); LOW =
  min(reconstructed, FCFF ex working capital); CENTRAL = FCFF ex WC + the
  MEDIAN disclosed WC contribution, clamped to [LOW, HIGH]. Otherwise
  SUSTAINABLE_FCFF: INSUFFICIENT_EVIDENCE - no number is manufactured.

- LIVE RESULTS (base point values UNCHANGED: 77.08 / 119.95 / 49.06 /
  124.27). UBER_FY2024: SUPPORTED_RANGE, REGIME_UNCERTAIN (sign change);
  FCFF low 3,138 / central 3,473 / high 5,512; scenario value 43.61 / 48.33
  / 77.08. The FY2024 FCFF of 5,512 is ~half operating improvement and ~half
  a one-year $2,374m working-capital tailwind, 6x the prior two years,
  dominated by the accrued-insurance-reserve build. UBER_FY2025:
  SUPPORTED_RANGE, REGIME_UNCERTAIN (monotonic); low 6,058 / central 8,285
  (3-yr WC median is large and positive) / high 8,285; value 87.34 / 119.95
  / 119.95. LYFT_FY2025: SUPPORTED_RANGE, REGIME_UNCERTAIN (sign change);
  low -19 / central 434 / high 810; value 0.88 / 27.25 / 49.06 - the base
  valuation rests almost entirely on the WC tailwind. DASH_FY2025:
  INSUFFICIENT_EVIDENCE - two of three periods miss the reconciliation
  tolerance (no interest line disclosed; a small line unextracted). The
  framework returned no range rather than a forced one.

- MUTATION TESTED (Phase 17): 18 mutations of the module - adjustment
  omission, double-count check, unit scaling, residual definition,
  sign-change rule, WC sign, capex sign, SBC double-subtraction, tax applied
  twice, TIGHT_BAND / SPIKE thresholds, evidence-less normalization,
  scenario aliasing, median-ignoring range, provenance loss, inferred-
  interest label, the 2-of-3 reconciliation gate, and the tolerance.

- ARCHITECTURAL DECISION: OPTION A - KEEP_LATEST_BASE_PLUS_SUSTAINABLE_
  SCENARIOS. The base DCF still anchors on the latest reconstructed FCFF.
  Promotion to base needs an ADR and is not warranted: three of four live
  filings are REGIME_UNCERTAIN with only 3 disclosed FCFF years, one of
  which is negative, so structural inflection and an unfinished ramp are not
  separable from the evidence.

- VERDICT: P6 PARTIALLY SOLVED. The framework is built, sourced, ledgered,
  reconciliation-gated, mutation-tested, and correctly refuses to
  manufacture a point where the evidence is a 3-year non-comparable series.
  It CANNOT establish a defensible sustainable-FCFF POINT for the live
  filings from that evidence - which is the honest state, not a failure of
  the framework.

---

P7 - MARKET-IMPLIED EXPECTATIONS (INVESTOR DECISION LAYER), 2026-09-08.
EXPERIMENTAL, not wired in. Question: what expectations does the current
market price embed, and how demanding are they versus the company's own
historical evidence and the current DCF?

- NEW MODULE `src/aleph/valuation/market_expectations.py` (EXPERIMENTAL
  banner). Reads a finished ValuationRun + the P6 sustainable layer, re-runs
  the PURE engine on COPIES, NEVER writes back. `assess_market_expectations`
  is called directly from run_valuation.py (only when a market price is
  given), NOT from pipeline.py; a test asserts `"market_expectations" not in
  pipeline source`.

- TWO SOLVERS. (1) implied UNIFORM growth = the existing dcf_engine.reverse_dcf
  (no second DCF); labelled "uniform-growth equivalent, all other inputs
  fixed" - NOT "expected revenue growth", NOT the inverse of the faded-vector
  forward DCF. (2) implied BASE FCFF - NEW, closed form: value/share is
  exactly linear in base FCFF with the growth path fixed, so
  B* = (price*shares + net_debt) / Phi where Phi = EV/base_FCFF; verified by
  re-running the engine at B*, else NOT_SOLVABLE. This directly attacks the
  P6 anchor problem.

- ANTI-CIRCULARITY (Phase 17). Market price in -> analytical outputs out.
  Nothing modifies inputs, the run, or any valuation number. Regression test
  proves the point value byte-identical with the layer present.

- FCFF-ANCHOR SCENARIOS: implied uniform growth re-solved under latest /
  sustainable-low / -central / -high, everything else fixed. No anchor is
  chosen. WACC and terminal-growth sensitivity re-solve implied growth at
  the EXISTING beta-derived WACC bounds and the EXISTING terminal-growth
  tornado band - neither rate is altered.

- CLASSIFICATION (deterministic, no score). vs_evidence:
  MARKET_EXPECTATIONS_{BELOW,ALIGNED,ABOVE}_EVIDENCE / INSUFFICIENT_EVIDENCE,
  from implied base FCFF vs the P6 sustainable range (+-5% of range width).
  level: EXPECTATIONS_{MODEST,DEMANDING,EXTREME} / NOT_CLASSIFIED, from
  implied FCFF vs the sustainable CENTRAL and range top; when P6 is
  INSUFFICIENT, graded against the latest FCFF only and labelled as such.

- LIVE RESULTS (base point values UNCHANGED: 77.08 / 119.95 / 49.06 /
  124.27). UBER_FY2024 @ 76.95 ~ DCF 77.08: implied uniform growth 10.5%,
  implied base FCFF 5,503 (~ latest 5,512). ALIGNED / DEMANDING - the price
  mainly requires the current (working-capital-inflated) FCFF to persist,
  not heroic growth. UBER_FY2025 @ 79.00 vs DCF 119.95: implied growth 5.4%,
  implied base FCFF 5,488 - BELOW the sustainable floor 6,058 ->
  BELOW_EVIDENCE / MODEST; the market has already discounted FCFF below the
  evidence range. LYFT_FY2025 @ 17.35 vs DCF 49.06: implied growth -8.5%,
  implied base FCFF 264 (< 33% of the latest 810), within the sustainable
  range -> ALIGNED / MODEST; the market does NOT require the WC-inflated
  FCFF and prices in a decline. DASH_FY2025 @ 215 vs DCF 124.27: implied
  growth 22.4%, implied base FCFF 1,987 (1.8x latest); P6 INSUFFICIENT ->
  vs_evidence INSUFFICIENT_EVIDENCE, level EXTREME graded against latest
  only.

- MUTATION TESTED (Phase 19): 16 mutations - reverse-DCF direction,
  implied-FCFF net-debt sign, shifted price target, dropped fixed-input,
  input aliasing x2, sensitivity setattr no-op, swapped bounds, blanked
  equation, classification inversion, NOT_SOLVABLE-guard drop x2,
  verification skip, unit error, level-threshold sign, circular write-back.

- ARCHITECTURAL DECISION: KEEP_EXPECTATIONS_LAYER_EXPERIMENTAL. It reuses
  the reverse-DCF maths and one closed-form solve, produces
  economically-interpretable investor output, and never touches a valuation
  number - but it depends on the P6 sustainable layer (itself EXPERIMENTAL /
  PARTIALLY SOLVED), and its "vs evidence" classification is only as strong
  as that dependency. Promotion needs an ADR.

- VERDICT: P7 SOLVED. Aleph now explains, deterministically and with full
  provenance: what the market price requires (uniform-growth equivalent AND
  base-FCFF level), what the company's evidence supports (the P6 range or
  INSUFFICIENT_EVIDENCE), and where the gap is - without a rating, a score,
  or a cheap/expensive claim. Where the evidence cannot support the check
  (DASH) it says so rather than inventing an expectation.

---

P8 - EVIDENCE DEPTH, MULTI-PERIOD ACCOUNTING & CASH-FLOW DATA QUALITY,
2026-09-08. EXPERIMENTAL, not wired in, promotes neither P6 nor P7.
Question: does Aleph have enough verified, multi-period accounting evidence
to support the economic conclusions it is being asked to make? The honest
answer is allowed to be "the filing does not disclose enough to know."

- NEW MODULE `src/aleph/valuation/evidence_depth.py` (EXPERIMENTAL banner).
  Deterministic, no LLM in the classification. Not imported by pipeline.py
  (test asserts). run_valuation.py calls it in a fenced EXPERIMENTAL block.

- CAPTION -> CATEGORY MAP. Every extracted cash-flow line maps to
  NON_CASH_RECONCILIATION / WORKING_CAPITAL[12 subcategories] /
  OPERATING_CASH_ITEM / CFO_SUBTOTAL / CASH_BALANCE / CAPEX / SBC /
  NET_INCOME / NON_OPERATING / UNCLASSIFIED, with a sign-semantics tag
  (CASH_EFFECT: the CFO reconciliation already presents the cash effect) and
  a mapping confidence. A caption that does not map confidently is
  UNCLASSIFIED, never a guess (DASH's "Payments for operating lease
  liabilities" is UNCLASSIFIED and downgrades its period).

- SIGN INTEGRITY. `wc_sign_semantics` separates cash direction from the
  implied balance-sheet direction (an AR increase is a cash OUTFLOW). Nine
  movements tested (AR/AP/accrued/prepaid up & down, mixed, zero).

- RECONCILIATION. NI + non-cash + working capital = CFO per period, P6's
  tolerance UNCHANGED (3.5% / $75m; a test pins it equal to
  sustainable_fcff's). RECONCILIATION_FAILED retains the residual as
  evidence. Live: UBER/LYFT all annual periods RECONCILED; DASH_FY2023 and
  FY2025 RECONCILIATION_FAILED (residuals -113 / -114), matching P6.

- PER-PERIOD SCORECARD (categorical, no score): FULLY_EVIDENCED /
  PARTIALLY_EVIDENCED / INFERRED_COMPONENTS / RECONCILIATION_FAILED /
  INSUFFICIENT_EVIDENCE. Non-annual periods are INSUFFICIENT.

- CAPEX SPLIT: CAPEX_SPLIT_NOT_SUPPORTED for all four filings - one capex
  line per period (LYFT even bundles "and scooter fleet" into it); no
  maintenance/growth/replacement split is a disclosed number. A split would
  be estimated, not evidenced.

- ONE-OFF TIERS: EXPLICIT / CORROBORATING / PATTERN_ONLY / NONE. Live:
  EXPLICIT one-off language appears only on NON-CASH add-backs (impairments,
  revaluations, gain on lease termination) already inside CFO; ZERO
  corroborating one-off CASH events. Pattern evidence informs
  REGIME_UNCERTAIN only, never an adjustment.

- P6 IMPACT: P8's sum of subcategory working-capital equals P6's
  `wc_total` for every period on every filing (agree = True). P6's
  sustainable range and regime are byte-unchanged - P8 adds labels, sign
  semantics and provenance to the SAME numbers.

- UBER DEEP-DIVE (FY2022-FY2024): CFO 642 / 3,585 / 7,137; operating cash
  before WC 307 / 3,420 / 4,763; WC contribution 335 / 165 / 2,374, of which
  insurance reserves 730 / 2,230 / 2,819 (WC ex-insurance is a small USE of
  cash). The FY2024 FCFF LEVEL is ~57% operating-cash-before-WC and ~43%
  working capital; the FY2022->FY2024 FCFF INCREASE is ~69% operating and
  ~31% working capital. P6's "approximately half / half" was a level
  statement about FY2024 and is SHARPENED, not retracted. The recurrence of
  the insurance-reserve build is disclosure-bound -> REGIME_UNCERTAIN holds.

- LYFT DEEP-DIVE (FY2023-FY2025): CFO -98 / 850 / 1,168; operating cash
  before WC -306 / 396 / 339; FCFF ex-WC ~ -436 / +4 / -19. P6's finding
  that FCFF ex-WC ~ $0 and the positive FCFF is working-capital /
  deferred-tax driven is CONFIRMED and now component-attributed: FY2025 WC
  829 = insurance reserves 479 + accrued & other 386 + the rest. LYFT is
  still operating-loss-making every year. Whether the insurance / accrued
  build is recurring float or timing is not disclosed -> REGIME_UNCERTAIN
  holds.

- MUTATION TESTED (Phase 21): 16 mutations - WC category map, WC sign, WC
  omission, WC double-count, reconciliation tolerance, period typing, unit
  scale, non-USD currency guard, duplicate handling, missing-year handling,
  one-off requirement, capex split requirement, mapping confidence,
  inferred-period status, P6/P8 marker parity, regression isolation.

- Phase 23 HONESTY VERDICT: reduces_uncertainty = NO_DISCLOSURE_BOUND for
  all four filings. Richer extraction is a real gain in ATTRIBUTION
  (component labels, sign semantics, provenance, per-period scorecard) but
  NOT in RESOLUTION: no filing adds a fourth annual year, a capex split, or
  a corroborating cash one-off. The structural-vs-temporary question is
  bounded by what the 10-Ks disclose.

- ARCHITECTURAL DECISION: KEEP_CURRENT_EVIDENCE_ARCHITECTURE. The evidence
  layer is EXPERIMENTAL; it enriches P6's lineage without changing P6's
  numbers or rules, and it does not promote P6/P7. Promotion needs an ADR.

- VERDICT: P8 PARTIALLY SOLVED. The evidence layer is built, tested (70
  cases, 20 adversarial fixtures, 16 mutations), and it answers the
  question honestly: the accounting evidence is component-attributable and
  every annual period reconciles for UBER/LYFT, but it is NOT deep enough
  to resolve structural vs temporary - and that ceiling is set by SEC
  disclosure, not by the extractor.

---

P9 - DRIVER-BASED OPERATING MODEL & FORECAST FCFF, 2026-09-08. EXPERIMENTAL,
not wired in, promotes nothing. Question: can Aleph forecast future FCFF
from EXPLICIT business drivers rather than implicitly assuming that one
historical year's reconstructed FCFF is the run-rate?

- NEW MODULES `src/aleph/valuation/operating_model.py` (historical driver
  series + scenario-separated forecast) and `driver_based_dcf.py` (feeds the
  forecast FCFF path into the EXISTING run_dcf). Deterministic, no LLM/ML.
  Neither imported by pipeline.py (test asserts). run_valuation.py has a
  fenced EXPERIMENTAL block.

- BRIDGE (Phase 11): revenue_t = revenue_{t-1}(1+g_t); operating_income_t =
  revenue_t * operating_margin_t; nopat_t = operating_income_t * (1 - 0.21);
  fcff_t = nopat_t + D&A_t + wc_cash_effect_t - capex_t - sbc_t. Every value
  carries a DriverAssumption (year, name, value, source, scenario,
  historical_ref, formula, lineage). D&A / capex / SBC are ratios to
  revenue, held at the historical median. Tax 21% is a MODEL_CONVENTION.

- SERIES SHAPE (describes the observed series, does NOT predict): STABLE /
  TRENDING / INFLECTING / CYCLICAL / INSUFFICIENT_EVIDENCE. A straight-line
  growth fade to terminal 2.5% is represented explicitly as a
  MODEL_CONVENTION, never hidden in an array.

- OPERATING MARGIN (Phase 7): STABLE -> held at the median (source
  HISTORICAL) -> FULLY_SUPPORTED possible. TRENDING / CYCLICAL -> held at
  the LATEST value, source ANALYST_ASSUMPTION, caps support at
  PARTIALLY_SUPPORTED. INFLECTING (crosses zero) -> OPERATING_MARGIN:
  INSUFFICIENT_EVIDENCE, scenario bracket only. No margin is ever fabricated.

- WORKING CAPITAL (Phase 8): NEVER a point (P8: recurrence not disclosed).
  It is a SCENARIO dimension - BEAR 0 (no tailwind), BASE historical-median
  cash-effect/revenue, BULL the latest ratio. The model NEVER assumes the
  insurance-reserve build repeats.

- CAPEX (Phase 9): TOTAL capex / revenue only - no maintenance/growth split
  is invented (P8: NOT_SUPPORTED). SBC: full cash cost / revenue (ADR 0002).

- SBC DOUBLE-COUNT (found and corrected in P10, Phase 3/23). The first P9
  bridge was `NOPAT + D&A + WC - capex - sbc_t`. Stock-based compensation is
  a GAAP operating expense already inside income-from-operations, hence
  inside NOPAT; the separate `- sbc_t` term subtracted it a SECOND time -
  total FCFF drag was 1.21x SBC (0.79x via NOPAT + 1.0x explicit). Corrected
  to `NOPAT + D&A + WC - capex`; SBC is charged once through the P&L. sbc_t
  is still reported for transparency. This is a genuine accounting defect,
  not a preference - it is fixed, tests updated, regression re-run.

- LIVE RESULTS (base point values UNCHANGED: 77.08 / 119.95 / 49.06 /
  124.27). Driver DCF, BASE scenario, AFTER the SBC correction: UBER_FY2024
  $47.03 (vs live $77.08, P6 central $48.33 - NOW CONVERGES with P6);
  UBER_FY2025 $103.84 (vs $119.95, P6 $119.95); LYFT_FY2025 $26.29 (vs
  $49.06, P6 $27.25 - NOW CONVERGES with P6); DASH_FY2025 n/a -
  INSUFFICIENT_EVIDENCE (margin INFLECTING AND P8 reconciliation failures).
  BEAR: UBER_FY2024 and LYFT NOT_REPRESENTABLE (FCFF path negative);
  UBER_FY2025 $22.44. BULL: $80 / $163 / $110. The SBC double-count was the
  main reason P9 looked "dramatically" lower than P6 - after fixing it the
  P9 BASE and P6 CENTRAL agree to within ~$1-2 for UBER_FY2024 and LYFT.

- WHY THE DRIVER BASE IS BELOW LIVE (after the SBC fix): two explicit
  assumptions the live reconstruction hides - (a) 21% tax applied to
  operating income, where the filers' actual effective CASH tax has been
  near zero (DTA releases); (b) working capital at the historical median,
  not the latest peak. It does NOT recreate the latest-FCFF assumption under
  new labels - the dependence moves to the operating-margin path and the tax
  convention, each labelled. After correcting the SBC double-count the P9
  BASE lands on the P6 CENTRAL, so P6 and P9 are a CONVERGENCE on cash-flow
  representativeness, not a divergence.

- LYFT (Phase 19): without the working-capital tailwind (BEAR), driver FCFF
  is NEGATIVE - the model CANNOT justify positive sustainable FCFF
  independent of WC. It does not manufacture a turnaround.

- ANTI-OVERFITTING (Phase 28): two synthetic companies with near-identical
  historical FCFF but different economics (a high-margin low-WC SaaS vs a
  thin-margin marketplace running a WC float) - the SaaS BEAR is
  representable, the marketplace BEAR collapses to NOT_REPRESENTABLE. The
  model captures economics, not just FCFF extrapolation.

- MUTATION TESTED (Phase 26): 20 mutations across both modules - growth /
  margin provenance, WC sign, capex sign, SBC double-count, tax application,
  scenario ordering, missing-driver handling, unsupported-margin handling,
  provenance loss, historical/forecast mixing, scenario contamination,
  sign-change classification, capex-magnitude, tax convention, bridge
  reconciliation, DCF-integration growth path, live-DCF isolation, and the
  "nothing changed" claim.

- PROMOTION DECISION: KEEP_DRIVER_MODEL_EXPERIMENTAL. It is more transparent
  than the latest-FCFF extrapolation, but it introduces a new dominant
  assumption (the operating-margin path) that is itself only an
  ANALYST_ASSUMPTION for the trending/inflecting filers, and its base case
  diverges sharply from both the live and P6 valuations. Promotion needs an
  ADR and independent validation.

- VERDICT: P9 PARTIALLY SOLVED. Aleph CAN forecast FCFF from explicit
  drivers with full provenance, scenario separation, and honest
  INSUFFICIENT_EVIDENCE / NOT_REPRESENTABLE where the economics do not hold
  (DASH entirely; every BEAR case). It improves interpretability and
  separates historical evidence from forecast assumptions. It does NOT
  eliminate assumption dependence - it makes it auditable and moves it from
  one opaque number to several labelled ones.

---

P10 - MODEL ARBITRATION, ASSUMPTION GOVERNANCE & VALUATION RECONCILIATION,
2026-09-08. EXPERIMENTAL. A governance + falsification layer, not a new
model. Question: how should Aleph evaluate competing economic
interpretations without picking the one that produces the most attractive
valuation?

- P9 SBC DOUBLE-COUNT FOUND AND FIXED (Phase 3/23, mandatory gate). The P9
  bridge subtracted SBC a second time after it was already inside NOPAT
  (total drag 1.21x SBC). Corrected in operating_model.py:
  `fcff_t = nopat_t + dna_t + wc_t - capex_t`. sbc_t stays reported. This
  moved the P9 BASE from $14.85 -> $47.03 (UBER_FY2024) and $5.29 -> $26.29
  (LYFT), which now CONVERGE with the P6 CENTRAL ($48.33 / $27.25). The
  earlier "dramatic P9 divergence" was largely an accounting bug, not an
  economic disagreement. LIVE anchors unchanged (P9 is experimental);
  test_operating_model updated, regression re-run.

- NEW MODULE `src/aleph/valuation/model_governance.py` (EXPERIMENTAL). Not
  imported by pipeline.py (test asserts). run_valuation.py has a fenced
  block. Its applicability / arbitration classification takes NO market
  price - a structural guarantee (Phase 20).

- RECONCILIATION LIVE -> P9: a sequential counterfactual, order-dependent
  (every step says so), residual retained. UBER_FY2024: LIVE FCFF 5,512
  ($77.08) -> operating basis + 21% tax + no working capital: 2,919
  ($40.52) -> + historical-median working capital: 3,381 ($47.03) = P9
  BASE. The gap is the ~0% cash tax and the working-capital contribution
  the latest-FCFF anchor embeds.

- SBC AUDIT: reads the actual bridge line, reports double_count =
  NOT_PRESENT (post-fix). TAX AUDIT: 21% classified
  CONSERVATIVE_BUT_SUPPORTED - the statutory upper bound, applied to
  operating income, while UBER/LYFT actual cash tax is near zero (DTA
  releases). statutory / cash / effective are three separately labelled
  things, never conflated. DASH: no disclosed effective rate extracted ->
  INSUFFICIENTLY_SUPPORTED, treat as unverified.

- BASE-CASE ASSUMPTION REGISTER: every P9 base driver with a 1-5 evidence
  hierarchy (L1 filing -> L5 model convention; NOT a score), a value
  sensitivity, an evidence band x sensitivity band 2-D (never combined),
  and a contradiction check. UBER_FY2024: tax_rate L5; operating_margin L4
  (held at the latest of an INFLECTING series); revenue_growth L3;
  D&A/capex/SBC ratios L2. wc_cash_effect_over_revenue is
  ASSUMPTION_CONTRADICTED_BY_EVIDENCE (latest far above its median) and is
  the single DOMINANT assumption - HIGH sensitivity x WEAK evidence.

- MODEL APPLICABILITY (not "correctness"): LIVE LIMITED_APPLICABILITY
  (anchor sensitivity HIGH, no explicit margin/tax assumption); P6
  CONDITIONAL_APPLICABILITY; P9 LIMITED_APPLICABILITY (dominant assumption
  is a weak L4 margin judgement). More detailed is not more applicable;
  lower valuation is not more applicable.

- ARBITRATION: UBER_FY2024 and LYFT -> MODEL_DIVERGENCE_WITH_EVIDENCE_BASIS.
  The disagreement is fully attributed: (1) P9 and P6 CONVERGE after the SBC
  fix; (2) LIVE sits above because it anchors on the latest FCFF (WC
  contribution + ~0% cash tax); (3) the driver that most moves P9 rests on
  weak evidence. DASH -> MODEL_DIVERGENCE_UNRESOLVED (only LIVE produces a
  value).

- ANTI-MARKET-FIT (Phase 20): applicability and arbitration are identical
  for market prices in {1, 5, 47, 77, 250, 5000} - the classifiers take no
  price. ANTI-CONSERVATISM (Phase 21): P9 ($47 < LIVE $77) is NOT ranked
  higher for valuing lower. ANTI-COMPLEXITY (Phase 22): P9 (more detailed)
  does not outrank LIVE on applicability.

- MUTATION TESTED (Phase 25): 16 mutations across model_governance +
  operating_model - SBC double-count regression, SBC audit blindness, tax
  detection, WC / capex double-count in the bridge, evidence-level and
  evidence-band calibration, contradiction detection, sensitivity ranking,
  arbitration forced to convergence, market-price leakage, conservative-bias
  leakage, complexity-bias leakage, scenario contamination, reconciliation
  anchor. 16 / 16 KILLED. First pass left 4 alive - the SBC audit could not
  see a re-introduced `- sbc_t` (its clean value and the mutant's are both
  False, so only a poisoned-source test kills it); the reconciliation added
  the median WC term twice / subtracted capex twice with no step-level
  assertion; the dominant-assumption sort could invert with only one HIGH
  entry to order. Four tests added (poisoned-bridge SBC detection, step-1 and
  step-2 arithmetic pinned to independently recomputed parts, full
  sensitivity-ranked order), `_dominant` now emits the complete ranking not
  just the HIGH band. P9's 20 mutations re-run post-SBC-fix: 20 / 20 KILLED,
  including P9m5 (the `- sbc_t` double-count regression).

- ARCHITECTURAL DECISION: KEEP_MULTI_MODEL_EXPERIMENTAL. After the SBC fix
  LIVE / P6 / P9 are a reconcilable family: P6 and P9 converge on cash-flow
  representativeness, and LIVE's premium over them is a single identified
  question (does the latest working-capital contribution recur - P8: not
  disclosed). No model is promoted; each carries its own applicability and
  dominant assumption.

- VERDICT: P10 PARTIALLY SOLVED. Aleph can now say, per filing: these models
  disagree because of X, Y, Z; evidence is stronger for A than B; no model
  is preferred for being more complex, more conservative, or closer to the
  market. It found and fixed a real SBC accounting defect in P9. It does NOT
  fully resolve the disagreement - the working-capital recurrence question
  is disclosure-bound (P8) - but it makes the disagreement legible and
  attributable rather than a choice of number.

---

P10.5 - EVIDENCE RESOLUTION, WORKING-CAPITAL ECONOMIC CLASSIFICATION &
UNRESOLVED-DIVERGENCE AUDIT, 2026-09-09. EXPERIMENTAL, observational only.
Question: can the remaining LIVE/P6/P9 disagreements be resolved from the
existing filing evidence, or are they genuinely DISCLOSURE_BOUND?

- NEW MODULE `src/aleph/valuation/evidence_resolution.py` (EXPERIMENTAL). Not
  imported by pipeline.py (test asserts). NO function takes a market price -
  structural, checked by reflection + a 7-price sweep that must produce
  byte-identical classifications. No new score; the P10 evidence x sensitivity
  two-axis frame is preserved.

- MY P10 PROSE MISSTATED ONE NUMBER. The P10 report said UBER_FY2024's latest
  working-capital contribution was "~$2,005m". The extracted facts say the
  FY2024 WC total is $2,374m (insurance-reserve change alone +$2,819m); the
  median is $335m (P6, median of dollar totals) / $462m (P9, median of
  revenue ratios x latest revenue). ISSUES.md #33 P10 reconciliation figures
  (5,512 -> 2,919 -> 3,381) were already correct. No LIVE number affected.

- WC EVIDENCE MAP + PERSISTENCE (deterministic rules, documented). Per
  "change in <account>" line: normalized category, cash direction, signed
  amount, recurrence evidence (EXPLICIT_RECURRING / EXPLICIT_ONE_OFF /
  MULTI_YEAR_REPEATED / SINGLE_YEAR_OBSERVATION / ECONOMICALLY_AMBIGUOUS /
  NOT_DISCLOSED), disclosure status. Persistence exposes latest / prior /
  median / mean / sign-consistency / magnitude-stability / revenue-, CFO- and
  FCFF-scaled histories SEPARATELY, then a class (STRONGLY_PERSISTENT /
  PERSISTENT_BUT_VOLATILE / RECURRENT_WITH_HIGH_VARIANCE / NON_PERSISTENT /
  INSUFFICIENT_HISTORY). UBER_FY2024 wc_total: sign consistency 100%,
  magnitude min/max 0.07 -> RECURRENT_WITH_HIGH_VARIANCE.

- INSURANCE / SELF-INSURANCE FLOAT AUDIT. UBER accrued insurance reserves
  cash change: +730 / +2,230 / +2,819 / +2,660 across FY2022-FY2025 - like-
  signed every year. Verdict UBER_FY2024 MIXED_SUPPORTED (direction recurs,
  level disclosure-bound), UBER_FY2025 RECURRING_SUPPORTED (tighter window),
  LYFT_FY2025 AMBIGUOUS (one sign flip: -79 / +364 / +479), DASH_FY2025
  DISCLOSURE_BOUND (no insurance line - payment-processor float instead).
  No filing discloses a reserve roll-forward or claims-development table.

- SEQUENTIAL BRIDGE LIVE -> P9 (every step start + delta == end, deterministic;
  ARITHMETICALLY_RECONCILED kept separate from ECONOMICALLY_EXPLAINED). Three
  named steps: WC normalization (actual -> P9 median), tax normalization (21%
  statutory on operating income), accounting-basis residual (operating-income
  basis vs CFO-derived FCFF - tax-basis, CFO nets the deferred-tax movement).
  UBER_FY2024: dominant delta is the WC median-vs-latest choice (-1,912),
  economically_explained PARTIAL (methodology 6.7%). UBER_FY2025: WC medians
  coincide, so the WHOLE gap is the tax normalization (-1,169), methodology
  0.8% -> economically_explained FULLY. LYFT: dominant WC (-334), methodology
  12% -> PARTIAL.

- UBER_FY2025 IS NOT UNRESOLVED. P10 arbitrate() labels it
  MODEL_DIVERGENCE_UNRESOLVED; the P10.5 bridge shows the LIVE<->P9 gap is
  entirely the 21% tax normalization. That is a gap in P10's arbitration
  reason-set (no tax-normalization branch), not a model-methodology defect.
  Architectural decision for UBER_FY2025: P10.5_REQUIRES_TARGETED_EVIDENCE_FIX
  (a ~5-line reason branch in arbitrate(), NOT made here - P10.5 is
  observational). Other filers: KEEP_P10_AS_FINAL_GOVERNANCE_LAYER.

- TAX EVIDENCE LADDER (the 21% convention is graded, NOT changed).
  UBER/LYFT: EFFECTIVE_DISCLOSED (rates 1.9 / 9.2 / -139.6 for UBER; -2.6 /
  10.1 for LYFT), NO cash-taxes-paid line, deferred-tax swings up to -$6,027m,
  no normalized rate derivable -> TAX_NORMALIZATION_DISCLOSURE_BOUND. DASH:
  STATUTORY_ONLY. 21% stands as a held-identical MODEL ASSUMPTION over a
  disclosure-bound question.

- FACT vs ECONOMIC_INTERPRETATION vs MODEL_ASSUMPTION separated explicitly
  (per-period WC movements = FACT; "the insurance change is recurring float" =
  INTERPRETATION; "sustainable WC = its median" and "21% forward rate" =
  ASSUMPTION). DISCLOSURE_BOUNDARY engine (RESOLVED / PARTIALLY_RESOLVED /
  DISCLOSURE_BOUND) - a DISCLOSURE_BOUND result is a successful output.

- LYFT operating cash independent of working capital is NOT demonstrably
  positive: fcff-ex-WC = -436 / +4.5 / -19.2. Hypothesis "recurring positive
  operating cash" RULED_OUT; evidence sits between "structurally breakeven,
  WC-financed" and "transitional ramp" - 3 years cannot separate them.

- REGRESSION: 798 tests pass (738 + 60 new); 11/11 standalone scripts OK;
  LIVE anchors 77.08 / 119.95 / 49.06 / 124.27 unchanged. MUTATION TESTED
  (Section 17): 16 mutations of evidence_resolution.py - recurrence flip,
  persistence-history removal, insurance-evidence removal, WC sign flip, WC
  amount doubled, tax reclassification, bridge tax-step suppression,
  disclosure-bound forced to resolved, price leakage, irrelevant-evidence
  contamination, magnitude-stability inversion, explained/reconciled
  conflation, bridge-step arithmetic, hard-wired decision, insurance
  threshold, epistemic mislabel. 16 / 16 KILLED.

- VERDICT: P10.5 PARTIALLY SOLVED (UBER_FY2024, UBER_FY2025, LYFT_FY2025);
  P10.5 DISCLOSURE-BOUND (DASH_FY2025 - no second model). Attribution
  improved materially: the UBER_FY2025 divergence is RESOLVED (tax), the
  insurance float DIRECTION is recurring, LYFT's operating-cash question is
  answered (not independently positive). The remaining disagreement is
  PRIMARILY an evidence problem: the sustainable LEVEL of the insurance float
  and the normalized forward tax rate are disclosure-bound and no model
  change resolves them. The one model-side item is P10 arbitrate()'s missing
  tax-normalization reason branch.

P10.5.1 - TARGETED GOVERNANCE FIX, 2026-09-09. Closes the one model-side item
P10.5 left open: a ~20-line reason branch in arbitrate() (commit 7dd54fd).

- WHEN the P10.5 bridge for a filer FULLY reconciles (arithmetically AND the
  dominant named delta is tax) AND that delta is the tax step, arbitrate()
  now appends a reason and returns MODEL_DIVERGENCE_WITH_EVIDENCE_BASIS
  instead of MODEL_DIVERGENCE_UNRESOLVED. Verified live: UBER_FY2025 fires
  (bridge economically_explained=FULLY); UBER_FY2024 and LYFT_FY2025 do NOT
  fire (their bridges are only PARTIAL - negative controls hold); DASH_FY2025
  unchanged (no P9, still MODEL_DIVERGENCE_UNRESOLVED, nothing invented).
  DIVERGENCE ATTRIBUTION = RESOLVED is kept explicitly separate from FORWARD
  NORMALIZED TAX RATE = DISCLOSURE_BOUND - the reason text says so, and a
  test proves the 21% convention is never called "verified"/"validated".

- A REAL GIT DEFECT, found and fixed during the P10/P10.5/P10.5.1 closeout
  (2026-09-09): commit 7dd54fd added model_governance.py's new import of
  evidence_resolution and tests/test_evidence_resolution.py (which imports
  it directly) but never added evidence_resolution.py itself. A fresh clone
  at that commit alone would fail test_evidence_resolution.py at import, and
  arbitrate()'s try/except would silently swallow the ImportError and fall
  back to the pre-fix UNRESOLVED behavior for UBER_FY2025 - a "sounds right,
  isn't" failure with no red flag, the exact pattern this file exists to
  catch. Fixed in f0547d4 (git housekeeping, no logic changed); the working
  tree was never broken since the file existed on disk, untracked.

- STALE SBC DOCSTRING, found and fixed the same day: operating_model.py's own
  module docstring still listed "- sbc_t ... full cash cost, ADR 0002" as a
  subtracted bridge term, even though the P10 fix (this section, above) had
  removed that subtraction from the CODE months earlier. The formula-in-two-
  places pattern is exactly ISSUES.md #30's shape; scripts/test_docs_
  consistency.py now checks the docstring's structured formula lines against
  the actual `fcff_t =` line (negative-controlled: a reintroduced `- sbc_t`
  in the docstring makes the check fail, exit 1).

- REGRESSION at closeout: 809 tests pass; 11/11 standalone scripts OK; LIVE
  anchors 77.08 / 119.95 / 49.06 / 124.27 unchanged; mutation-tested (18/18
  KILLED: the 16 P10 mutations + 2 new P10.5.1-branch mutations - the FULLY
  guard weakened to "is not None", and the "does NOT establish 21%" caveat
  dropped from the reason text).

## #39 Capex excludes capitalized software; DoorDash capitalises more of it than it spends on hardware

`derive_capex` matches on the single string `"property and equipment"`.
DoorDash's cash-flow statement carries a SECOND investing line the pipeline
never sees.

MEASURED, from the filings themselves via `pypdf` - no API call, no new
extraction:

```
DASH_FY2025 cash flow (columns FY2023 FY2024 FY2025, confirmed against CFO
1,673 / 2,132 / 2,431 and the pipeline's own FY2025 FCFF of 1,123):

  Purchases of property and equipment                    (123)  (104)  (257)
  Capitalized software and website development costs     (201)  (226)  (348)
  SBC included in capitalized software and website costs   161    165    193

LYFT_FY2025 cash flow: no capitalized-software line exists.
UBER: no capitalized-software line exists.
```

DoorDash capitalised MORE software ($348m) in FY2025 than it spent on
property and equipment ($257m). The pipeline subtracts the 257 and not the
348.

EFFECT, measured by re-running the pure engine with only `base_cash_flow`
changed:

```
DASH_FY2025   FCFF 1,123 -> 775      value/share 124.27 -> 87.72   -$36.55  (-29.4%)
```

That moves DoorDash from "86.6% above the top of the range" to a smaller but
still substantial premium. It does not reverse the conclusion; it is 29% of
the answer.

THE INCONSISTENCY WITH SBC, which is the part that makes this a defect
rather than a scope choice. `derive_stock_based_compensation` excludes
DoorDash's "Stock-based compensation included in capitalized software and
website development costs" with the written rationale that the amount "was
capitalised into an asset and already leaves through capex, so subtracting
it here too would double count it." It does not leave through capex - capex
is `"property and equipment"` only. The $193m is excluded from SBC on the
grounds that capex catches it, and capex does not catch it. It leaves
through neither.

Also measured: no fact whose name or quote contains "capitalized",
"software" or "website" exists anywhere in the 99-entry cache. The
`exclude=("capitalized",)` filter is a no-op today, guarding against a fact
the extraction never requests - which is why the asymmetry was invisible.

OPEN - out of scope for the closed version; fix requires re-running the
anchor and restating the README table.

## #40 Net debt credits all cash but omits the current portion of debt

`derive_net_debt`'s policy is debt NET OF CURRENT PORTION, less cash and
equivalents, less short-term investments. The current portion is therefore
omitted from the debt side while 100% of cash is credited on the other -
asymmetric by construction, and understating net debt by whatever the
current portion is.

MEASURED, from each balance sheet, with the column order resolved from the
sheet's own header (they differ - Lyft prints 2025 then 2024; DoorDash prints
2024 then 2025):

```
LYFT_FY2025   "Convertible senior notes, current"    FY2025: —     FY2024: 390,175 (USD thousands)
UBER_FY2024   no separately captioned current-debt line on the face of the
              balance sheet, although the caption "Long-term debt, net of
              current portion" states that one exists
DASH_FY2025   no current-debt line; "Convertible notes, net" 2,724 is
              non-current (FY2024: —, FY2025: 2,724)
```

So the FY2025 effect is ZERO for all three filers: Lyft's current portion
went to nil, and neither Uber nor DoorDash separately captions one. The gap
is LATENT, not active - which is exactly why it survived review.

EFFECT, measured on the engine rather than asserted:

```
LYFT_FY2025   net debt -834.8 -> -444.6 (adding back Lyft's OWN FY2024
              current portion of 390.175)    value/share 49.06 -> 48.13   -$0.93
UBER_FY2024   $1m of net debt = $0.000465/share, so $1bn of undisclosed
              current debt would be $0.47/share
```

The UBER runs are the ones the question asks about and the ones where no
figure exists to substitute: Uber discloses no current portion on the face of
its balance sheet, so the effect there is UNKNOWN, not zero, and quantifying
it needs a new extraction target against the debt note - an API call this
entry deliberately does not make.

OPEN - out of scope for the closed version; fix requires re-running the
anchor and restating the README table.

## #13 Dispersion test is scale-dependent for rate quantities — CLOSED

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

FIXED, exactly as that direction specified. `DispersionLimit` (span, unit,
rationale) with one entry per TREND quantity in `DISPERSION_LIMITS`, declared
beside the derivations that use them. `_dispersion_problem` takes the
quantity name, checks sign change first, then compares an ABSOLUTE span
against that quantity's own limit. `MAX_RELATIVE_SPREAD` is gone, and with
it the "median is zero; relative spread is undefined" branch, which only ever
existed to guard the division the relative test needed.

MEASURED FIRST, before choosing any number - the real spans on every filing:
UBER_FY2025 0.3, UBER_FY2024 1.0, DASH_FY2025 3.8, DASH_FY2024 7.0,
LYFT_FY2025 22.2, LYFT_FY2024 23.9 percentage points. Nothing lands between
7.0 and 22.2 - a factor of three with no filing in it - so revenue_growth's
limit of 12.0 points sits in an empty gap with 5 points of margin below and
10 above. That is a calibration against observed data with the reasoning
recorded, not a number chosen in the abstract; the difference from the
constant it replaces is that nobody ever wrote down why that one was 1.0.

TWO FINDINGS THE ISSUE DID NOT ANTICIPATE:

Its own motivating example no longer reproduces. `effective_tax_rate` never
reaches the span check on any filing - UBER_FY2024/FY2025, LYFT_FY2024/FY2025
and DASH_FY2025 all block on SIGN CHANGE first (1.9/9.2/-139.6,
-2.6/10.1, -5.8/25.0/0.7). The "1.9 and 9.2 blocked at 1.3x" case described a
two-value set that the current extraction no longer produces. A limit is
declared for it anyway (21.0 points, anchored on the US federal statutory
rate: periods spanning more than the entire statutory rate are not one tax
regime), so a future filer with same-signed rates meets a stated limit rather
than none - and it is labelled in the code as never reached.

An undeclared quantity now BLOCKS rather than passing. The old global
constant applied to everything by default, so adding a TREND quantity
silently inherited a limit nobody chose for it. Declaring the limit is now
part of declaring the derivation.

Verified. All twelve status outcomes are unchanged across six filings and
both TREND quantities - Uber and DoorDash derive growth, Lyft blocks in both
years, every tax rate blocks on sign change. `capture_baseline.py` diffed
against the pre-session baseline: identical, byte for byte. Six new tests in
test_assumptions.py, including #13's exact example in both halves (1.9/9.2 at
7.3 points apart and 45/52 at 7.0 points apart now get the SAME answer, which
is the whole point), a near-zero median that no longer blocks a tenth of a
point, a negative control requiring LYFT_FY2025's real 22.2-point spread to
still block, and a check that every declared limit carries reviewable
reasoning - a bare number is the old bug.

## #19 A failed WACC valued the filing off the leftover integration-test discount rate — CLOSED

Retitled on measurement. This was filed as a cosmetic leftover of unknown
necessity - four market.json blocks carrying discount_rate 0.09 under source
"integration test", each rationale reading "NOT A VALUATION INPUT",
superseded because run_valuation.py overwrites the key with the derived
bottom-up figure. The open question was whether any caller needed the key
at all.

It was not cosmetic. pipeline.py overwrites market["discount_rate"] only
`if wacc:`, then calls build_dcf_inputs unconditionally. When build_wacc
raised, the run fell through to the 0.09 sitting in the JSON.

MEASURED, not inferred: removing debt_spread from UBER_FY2024's market block
makes build_wacc fail. The pipeline printed one warning line - "WACC NOT
BUILT" - and then a complete RESULT block valuing the filing at $73.54 per
share against its real $77.08, on an invented rate, with every gate passed
and every unit converted correctly. The project's own named failure mode, in
its own pipeline: a result that sounds right and is not, carrying no red
flag.

The root cause was not the key. `_market`'s placeholder message told the
reader, in the error text itself, to set a source to 'integration test' to
get past the placeholder check - which is exactly what all four blocks did.
A guard that advertises its own escape hatch is not a guard.

FIXED, three parts:
  - discount_rate deleted from all four market.json blocks (32 lines, the
    only deletions in the file). It is derived, never authored, so its
    absence is now what stops a run whose WACC failed.
  - PLACEHOLDER_SOURCES gained "integration test". It appears on no other
    input in market.json, checked before adding it.
  - Both of `_market`'s messages rewritten. The placeholder message names no
    bypass. The missing-key message special-cases discount_rate to say it is
    derived and must NOT be added to market.json - the old text instructed
    the reader to do the thing that caused this.

Verified four ways: the anchor still prints 77.08 with WACC 7.87/8.72/10.26%
at the beta bounds; the same crippled-market reproduction now raises
BridgeError instead of valuing; `_market` blocks 'integration test', 'TODO'
and 'placeholder' while still accepting 'NYSE close'; capture_baseline.py
diffed against a pre-change baseline is identical byte for byte on all four
filings.

This is a fourth member of the class named in #26 and #30: a mechanism that
looks like protection and is not. #26 was a block printing incomplete
evidence; #30 was a documented guarantee no code enforced; this was a guard
naming its own bypass in its error message.

## #20 Revenue has two independent sources with no cross-check between them — CLOSED

Total revenue is available from two places: the statement:operations target
(the income statement total) and the Total row in the segment and geography
notes. derive_growth excludes the note targets to avoid a collision with the
statement total rather than reconciling them, so nothing compared the two.

MEASURED FIRST, across all six filings and every period: they agree
everywhere. UBER_FY2024 across four targets (operations, segments,
geography_n2, geography_n13), UBER_FY2025 across three, LYFT_FY2025 across
two, DASH_FY2025 and DASH_FY2024 across three each. LYFT_FY2024 has one
source only - no geography note resolves for it, pre-existing and unrelated,
noted in #28.

FIXED. `_revenue_source_disagreements` (assumptions.py) groups every
'total revenue' fact by period and target and blocks revenue_growth on a
mismatch, naming each source and what it stated. It excludes nothing
deliberately: it wants exactly the restatements derive_growth filters out.

The tolerance is not an invented constant - the failure #13 names in
MAX_RELATIVE_SPREAD. Two values agree when they differ by less than one unit
of the COARSER of the two declared scales, because a figure printed in
millions cannot resolve anything finer than a million. The bound is the
filing's own reported precision.

So this check is a no-op today, which is the point: it costs nothing while
the sources agree and is the only thing that would see the day they do not.

Four tests in test_assumptions.py, one a negative control
(test_agreeing_sources_report_nothing, on the real UBER_FY2025 figures)
requiring silence - without it the other three would pass equally against a
function that flagged everything. The tolerance test checks both directions:
millions against thousands differing by 400 thousand passes, the same pair
differing by a full million is caught.

Does not close the geography-note case, which #28 already closed by a
different mechanism (reconciling components against the stated total).

## #21 market.json is keyed by doc_id, duplicating pure market inputs per company — CLOSED

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

FIXED - but the split is drawn in a different place than that direction
proposed, and the direction was wrong on one input. It put
`unlevered_industry_beta` in the company-level group, "each its own
judgement per company". ADR 0001 and #25 say the opposite: the beta is held
identical across every filer ON PURPOSE, and a per-company block for it
would reintroduce exactly the drift this issue is about.

The line that actually matters is not "market data vs company data" but
"held identical by policy vs legitimately different", which is what
CLAUDE.md's Cross-company comparability section already says:

  shared      risk_free_rate, equity_risk_premium, terminal_growth,
              unlevered_industry_beta
  per_filing  country_risk_premium, debt_spread, share_price

`debt_spread` is per-filing even though all four currently carry 0.0111: it
is a company's own credit spread and is not on CLAUDE.md's held-identical
list, so making it shared would be a policy change, not a refactor.

`load_market` merges shared into per_filing and RAISES `MarketDriftError`
if a per-filing block redefines a shared key. The structure now enforces
what discipline used to.

THE DRIFT THIS ISSUE PREDICTED HAD ALREADY HAPPENED, and the migration's
own assertion found it rather than a person looking for it. LYFT_FY2025's
`unlevered_industry_beta` cited "Aswath Damodaran - Betas by Sector (US),
Business and Consumer Services" while the other three cited the same table's
"unlevered beta corrected for cash" column. All four carry 0.81 - which IS
the cash-corrected figure; Damodaran's plain unlevered beta is 0.77, as
UBER_FY2024's own rationale states. Lyft's citation, read literally, pointed
at the column that gives the other number. The value was never wrong; the
provenance was, silently, in a committed file.

Migrated programmatically, never by hand: this issue itself records that a
full-file paste dropped a required source field once already (#15). The
script asserted every shared input identical on name/value/unit/source/as_of
before moving anything, and asserted afterwards that merging reproduces each
original block field for field. The four shared rationales are MERGED from
the four originals - every clause is from one of them - minus the sentence
saying the value is "duplicated here only because market.json is keyed by
doc_id, which is a known structural gap", which this change makes false.

Verified. All eleven test scripts pass. Both anchors hold. app.py runs
through AppTest and reproduces README's UBER_FY2025 row. `capture_baseline.py`
against the pre-session baseline differs on exactly FOUR lines out of four
files - the terminal_growth rationale text, in the ASSUMPTIONS block - and
the RESULT, TORNADO, REVERSE DCF and WACC blocks are byte-identical on all
four filings. No number moved.

`scripts/test_market.py` (7 tests, in CI) holds the structure, including a
negative control that writes a redefinition into the file and requires
`load_market` to raise - without it every other assertion would pass against
a loader that merged a collision silently, which is the behaviour this issue
exists to remove.

Status: CLOSED.

## #23 Three "unexplained" rejections are one fact, one cause, and three correct gates — CLOSED

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

CLOSED, measured. The three are not three problems. They are one fact -
`Effective income tax rate FY2025` - rejected in three filings for one
reason, and the gates are RIGHT in all three cases.

All three FY2025 filers adopted ASU 2023-09, which changed the tax-rate
reconciliation disclosure. Each FY2025 note therefore contains TWO tables:
a new-format one for FY2025 alone, and a legacy one for the earlier years,
introduced verbatim as "in accordance with the guidance prior to the
adoption of ASU 2023-09". Read directly from the note text:

  UBER_FY2025  "...for the years ended December 31, 2023 and 2024:"
               row: 'Effective income tax rate 9.2 % (139.6)%'   (2 cells)
               "...for the years ended December 31, 2025 (in millions):"
               row: 'Effective income tax rate $ (4,346) (74.8)%'
  LYFT_FY2025  same shape, legacy table for 2024 and 2023
  DASH_FY2025  new format only, columns literally ['Amount', 'Percent']

The FY2025 row is not two years. It is an amount and a percentage, which is
why DASH_FY2025 rejects on `column_alignment` against ['Amount', 'Percent']
and the other two on `columns_undetermined` for a 2-cell row. Compare
UBER_FY2024, one filing year earlier, whose single table gives a clean
3-cell row and three accepted facts.

LYFT_FY2025's is the informative one: the nearest header above the row
reported `years=['FY2025', 'FY2024', 'FY2023']` while the row held two
cells. A laxer gate would have mapped 10.1% to FY2025 when the filing means
FY2024 - a year-shifted tax rate, with nothing downstream able to see it.
The gate prevented a wrong number, not a cosmetic one.

Measured downstream effect: none. effective_tax_rate blocks for every filing
regardless, on sign change across periods (UBER_FY2024 1.9/9.2/-139.6,
LYFT_FY2025 -2.6/10.1, DASH_FY2025 -5.8/25.0/0.7), and is supplied by
override as 21% statutory by cross-company policy. Confirmed by running
derive_all with NO overrides on all five filings: every one blocks.
CLAUDE.md's residual-risk note that derive_tax_rate's computed branch never
runs still holds.

Deliberately NOT fixed. Teaching extraction the Amount/Percent format would
change no valuation, since the quantity is overridden by policy in every
filing. Per #26's own reasoning, the fix applies where harm was measured,
not to every latent risk of the same shape. What this issue produced instead
is a sixth entry for CLAUDE.md's "10-K facts that were actually Uber facts"
list: one reconciliation table per note, with columns that are years. An
accounting standard adoption broke it, mid-filer, between two years of the
same company.

## #24 DASH_FY2024 has never been valued — CLOSED as out of scope

DASH_FY2025 is resolved: it has a `market.json` block and `overrides.json`
entries (`effective_tax_rate`, `net_debt`, `interest_expense`), has been
run end to end repeatedly (`python scripts\run_valuation.py DASH_FY2025
231.89`), and appears in `README.md`'s own three-company table alongside
UBER_FY2025 and LYFT_FY2025. The cross-company comparison this project
argues for (see CLAUDE.md, "Cross-company comparability") now has all
three FY2025 data points the manifest suggests.

DASH_FY2024 does not. It has no `market.json` block and no
`overrides.json` entries (`net_debt`, `effective_tax_rate` would both
block), and `run_valuation.py` has never been run against it end to end.
Extraction and gates do pass for it (`test_multicompany.py` exercises it
alongside the other five filings), so the remaining gap is entirely in
the judgement layer - market inputs and override policy - not extraction.

CLOSED as out of scope, not as done. DASH_FY2024 is deliberately not valued.

The comparison this project argues for is three companies at ONE market
date on ONE method - UBER_FY2025, LYFT_FY2025, DASH_FY2025, all priced at
the 2026-08-27 close. UBER_FY2024 exists alongside them for a different and
stated reason: it is the evidence against the model, the same company one
filing year apart producing $77.08 against $119.95 (#29). DASH_FY2024 serves
neither purpose, and valuing it would require two new analyst judgements -
a share price at a date nobody has chosen, and a country risk premium
weighted on its own geographic mix - manufactured to fill a gap in a table
rather than to answer a question.

What was never in doubt: extraction and gates pass for DASH_FY2024, and
test_multicompany.py exercises it alongside the other five on every run. The
gap was only ever in the judgement layer, and the judgement is to leave it.

Decided by Asi, 2026-09-06. Retitled from "DoorDash has never been valued" -
found stale while checking a README claim about ISSUES.md's own honesty,
not while looking for it.

## #26 Derivation queries match on wording measured against two filers only — CLOSED

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

THE derive_tax_rate INSTANCE IS NOW FIXED TOO, 2026-09-06, and the harm was
worse than "no unmatched-evidence line". Reproduced on DASH_FY2024: three
`Total provision for (benefit from) income taxes` facts (FY2022=-31,
FY2023=31, FY2024=39) are extracted and pass every gate, and none of
derive_tax_rate's three queries sees them. The rate then blocked through
build_trend's generic path with the message **"no facts extracted for this
quantity; check extraction gates"** - which is false twice over: facts WERE
extracted, and the gates are exactly where the problem is not. It sent the
analyst to audit a component that had worked perfectly.

derive_tax_rate now blocks on its own when nothing resolves, naming the
queries it tried, listing every fact from the taxes target that none of them
matched, and saying in words that this is not an extraction failure.

The query is still NOT widened to match "(benefit from)", for the same
reason net_debt's was not: a longer substring list only relocates the bug to
the next filer that phrases it a third way. A test asserts the block, so
"fixing" it by broadening the query fails the suite.

The mechanism is now shared rather than copied. `_unmatched_note(facts,
target_key, matched, where)` is used by both derivations; the second
instance would otherwise have been a second inline implementation that could
drift from the first. net_debt's output was captured before the refactor and
compared after: byte-for-byte identical on DASH_FY2024, UBER_FY2024 and
LYFT_FY2025.

Status: CLOSED for both measured instances. The general pattern - a
derivation query written against wording measured on too few filers -
remains a real risk in any derive_* function not yet audited this way, and
is deliberately not swept: per this issue's own rule, the fix applies where
harm was measured. `_unmatched_note` exists to make that fix cheap the next
time harm IS measured.

Six tests in test_assumptions.py, including a negative control
(test_matching_wording_still_computes_a_rate) that requires a derivation to
SUCCEED on ordinary wording - every other assertion here demands a block,
and without it they would all pass against a derivation that never works.

## #27 check_coverage cannot see a row the model never quoted — CLOSED

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

RESOLVED by the required-data contract (`src/aleph/valuation/contract.py`,
`contract_adapter.py`), which does not extend the gate - it moves the
question upstream of it. `REQUIREMENTS` is a static list read off the real
code path (`bridge.require`, `wacc.REQUIRED_MARKET`, the substring each
`derive_*` queries). `evaluate()` compares it against what the run holds:
a field the contract declares and the run never produced is `MISSING`,
which is a state the system carries whether or not extraction ever
mentioned it. That is the structural fix - the omission cannot vanish
because the requirement existed before extraction ran.

`value_filing` calls `evaluate()` after derivation and before `build_wacc`,
the bridge and the engine, and raises `ContractBlockedError` on
`Status.BLOCKED`. The gate order is asserted against the source by
`tests/test_contract_hardening.py::TestGateOrder` (spies on all three
downstream functions, plus a negative control proving the spies fire on a
clean run).

HARDENING PASS, 2026-09-07:
- Period integrity is wired INTO the gate: `_period_problems` delegates to
  `extraction.identities.check_period_alignment` (one definition of "these
  periods do not line up", shared with the cross-statement checks) and adds
  an annual-vs-quarterly frequency check. CFO FY2025 against capex FY2024,
  and an annual figure against a quarterly one, both block with
  `Reason.PERIOD_MISMATCH`; two annual figures on one period pass.
- The failure CAUSE survives the aggregate `BLOCKED`. `Reason` is a typed
  enum (`MISSING`, `AMBIGUOUS`, `PERIOD_MISMATCH`, `INVALID_UNIT`,
  `DEPENDENCY_UNMET`, `INSUFFICIENT_HISTORY`, `DERIVATION_BLOCKED`) carried
  on every `Observed`. The pre-gate `BlockedError` (a blocked derivation
  never reaches `evaluate()`) now carries a structured `.reasons`
  `{field: Reason}`, classified by the same `row_for_range` the gate uses,
  so an ambiguous collision reads as `AMBIGUOUS` on that path too, not as
  prose in a rationale string.
- `State.LOCATED` and `State.EXTRACTED` were removed. The adapter reads
  post-gate state; nothing in this pipeline observes region resolution or a
  pre-gate return, so they were documented lifecycle stages no code could
  reach. `tests/test_contract_adversarial.py::TestLifecycleStates` locks
  the enum to the seven reachable states. They return only with a real
  transition that reaches them.
- `tests/test_contract_adversarial.py` runs the eight adversarial cases
  through `pipeline.value_filing` on the cached UBER_FY2024 extraction:
  missing field -> BLOCKED/MISSING; conflicting observations -> the final
  error names AMBIGUOUS; wrong unit -> BLOCKED/INVALID_UNIT; wrong period ->
  BLOCKED/PERIOD_MISMATCH; valid zero -> PASS; analyst override -> PASS,
  labelled, reaches the 77.08 anchor; missing WACC input -> PATH_WACC
  blocked and `discount_rate` BLOCKED/DEPENDENCY_UNMET. Every blocked case
  also asserts `build_wacc`, `build_dcf_inputs` and `run_dcf` never ran.
  Insufficient history is exercised at the gate directly: `value_filing`
  fixes its path set to (DCF, PER_SHARE, WACC) and does not select
  PATH_HISTORICAL, and wiring it in would be a contract redesign this pass
  did not undertake.

Test count: 166 -> 179. All anchors hold (UBER_FY2024 77.08, LYFT_FY2025
49.06). #14 (coverage gate returned the wrong type) and #15 (1000x unit
bug) stay covered - the contract adds INVALID_UNIT as a second line of
defence on the latter.

Status: CLOSED. The structural completeness gap is fixed; the residual
economic weakness in the base FCFF itself is #29, a separate issue.

## #30 sha256 is recorded as content identity but never used to detect a replaced document — CLOSED

`schemas/documents.py` states the principle directly: `doc_id` is a
"Human-authored stable id" (line 74) and `sha256` is "Content identity. The
file name is metadata; this is not." (line 79). The design intent - same
doc_id, different hash, means the document was replaced - is never checked
anywhere in the pipeline.

`_sha256(path)` and `build_manifest()` (`src/aleph/documents/manifest.py`)
compute a fresh hash from whatever bytes currently sit at `data/<file_name>`,
and `scripts/build_manifest.py`'s `main()` writes it straight into
`data/manifest.json`, unconditionally. Nothing in that path reads the hash
already committed for that `doc_id` before overwriting it, and nothing
compares old to new. The only checks inside `inspect()` that can raise
`DocumentError` at all are unrelated to bytes: `_exactly_one` on the
form-type regex, `_exactly_one` on the fiscal-year regex, and
`_check_anchors` matching specific verified-figure strings in the extracted
text. Replace `data/uber_10k.pdf` under `UBER_FY2025` with a corrected
filing, a re-print, or simply the wrong document - as long as it is still a
10-K, states a parseable fiscal year, and contains the same anchor
strings - and every one of those checks can still pass while the hash
silently changes underneath the same doc_id.

This is the second instance this session of documentation describing an
intent the code has never executed. The first is #29's finding that
`DCFInputs.base_cash_flow`'s field comment calls it "most recent normalized
FCF" while nothing normalises anything. There the gap was a missing
computation; here it is a missing check, but the shape is the same: a
comment or a field description states what the system is supposed to
guarantee, and no code path enforces it.

Not yet observed to cause harm: no filing has actually been replaced under
an existing doc_id in this project's history, so this has not produced a
wrong valuation that a reader trusted. It is a latent gap in an explicitly
stated architectural guarantee, found while answering a direct question
about README wording (see build_manifest's behaviour on a re-rendered PDF,
data/README.md), not from a failure in the field.

Fix direction: `build_manifest()` (or its caller) should read the
already-committed `data/manifest.json` before writing the new one, compare
the new sha256 against the old one for each doc_id, and treat a mismatch as
a decision rather than a silent overwrite - consistent with principle #5 (a
library raises; the CLI decides the exit code). The library signals the
mismatch; `scripts/build_manifest.py` decides whether that means `exit(1)`
or a printed warning that still allows the new manifest to be written when
the replacement was deliberate (a corrected 10-K/A superseding an
original, for instance).

DECIDED and IMPLEMENTED, 2026-09-06: raise, and require an explicit flag.
build_manifest() reads the committed manifest, compares per doc_id, and
raises DocumentError naming both hashes; build_manifest.py turns that into
exit(1), or proceeds with --allow-replacement while still printing every
replacement it waved through. A missing manifest is not a mismatch, and a
new doc_id is not a replacement. Reasoning and the rejected alternative
(hard block with no override, which forces hand-editing the very file whose
integrity is being protected) in docs/adr/0007.

The first attempt to prove it measured the wrong thing and is worth
recording: substituting a DIFFERENT filing at the path was caught by
DocumentRecord's fiscal-year validator before sha256 was ever compared,
which demonstrates nothing about this issue. The real case is a document
that passes every other check. Re-serialising data/uber_10k_fy2024.pdf
through pypdf gives exactly that - identical text, still a 10-K, still
fiscal year 2024, all four anchors present - and a different hash:
ab5f074a -> e29543aa. That run exits 1 and prints both hashes; with
--allow-replacement it exits 0 and prints REPLACED UBER_FY2024. Everything
restored afterwards, all six hashes re-verified.

That attempt also found a live defect it was not looking for:
build_manifest.py caught DocumentError but not pydantic's ValidationError,
which DocumentRecord's own validators raise, so a bad filing ended in a
traceback rather than a decision - not what principle 5 means by "the CLI
decides the exit code". Fixed in the same commit.

Two instances in one session make this a class worth naming, not a
coincidence: a docstring, field comment or schema description states a
guarantee, and no code path enforces it. Both were found by reading the
code to answer an unrelated question, not by a failing test - nothing in
the suite can detect the gap, because the suite tests what the code does,
not what the documentation claims it does. A sweep of the remaining
docstrings and field descriptions against the code they describe is worth
doing before this repository is public.

A third instance turned up while drafting the README's outline, not while
looking for one: CLAUDE.md stated the extraction gate count as "5
validation + 1 coverage gate" (file layout) and "Five gates check that
what was copied is correct" (principle 8), both stale since
`check_unit_matches_source` was added earlier this session, making the
true count six correctness gates plus coverage. A stale count in a project
instructions file is the cheapest possible version of this bug - no
runtime consequence, caught by an outline instead of a test - and it
strengthens rather than weakens the case for the sweep above.

A fourth instance is a variant of the same class, not a docstring this
time: CLAUDE.md's "Commands that verify the system works" documents
`python scripts\test_dcf_engine.py` as one of nine commands that prove the
pipeline works. Run exactly as written, it raised `ModuleNotFoundError: No
module named 'dcf_engine'` - the script never added `src/aleph/valuation`
to `sys.path` itself, unlike `run_valuation.py`, which imports the same
module by the same bare name. Found the same way as the other three:
auditing CLAUDE.md's own claims against what actually runs, before writing
the README's running-it section, not by a test catching it - there is no
test of the test runner. Fixed on its own, adding the same
`sys.path.insert` line `run_valuation.py` already uses; verified passing
with no `PYTHONPATH` set, exactly as documented. This widens the sweep
already recommended above: not only docstrings and field descriptions
against their code, but every command CLAUDE.md tells a reader to run,
against what happens when it is actually run.

A fifth instance surfaced one hour after the fourth, in the same
verification block, this time in CLAUDE.md itself rather than a script:
the working-agreement bullet ("...must still print `Value per share:
77.08`...") and the "Commands that verify the system works" comments
("# must print Value per share: 77.08") were stale, not just quoted stale
by the README. Since the RESULT block was rewritten to lead with the range
(`99172d9`), `run_valuation.py` has never printed a bare "Value per share:
77.08" line - it prints "Latest-period basis: 77.08" inside a labelled
range. The README's own copy of the same two lines, written as "verbatim
from CLAUDE.md," faithfully reproduced CLAUDE.md's staleness rather than
inventing a new one of its own. Fixed in both places at once - the
working-agreement bullet, the verification-commands block, and the
README's copy of the same two lines - so "verbatim from CLAUDE.md" is true
again. Five instances of the same class in one session is no longer a
case for recommending the pre-push sweep; it is the case for treating it
as required before this repository is public, not optional.

THE SWEEP, run in full: every docstring and Pydantic field description in
`src/aleph/` stating a guarantee, count, unit, or behaviour; every command
CLAUDE.md, README.md or `data/README.md` tells a reader to run, actually
run; every count, threshold or file-layout line in CLAUDE.md against the
code; every closed-entry result in ISSUES.md that a command could
re-verify, re-run where it could.

Five instances found by accident. Thirteen more found by looking - nine of
them in one file (CLAUDE.md), two low-stakes (`graph.py`'s unenforced
`Node.type`/`Edge.relation`, consumed only by archived experiments), two
in the final docstring pass (`statements.py`'s stale equity-matching
description plus dead code, `cache.py`'s undercounted key description).
Categories 2 and 4 (documented commands; ISSUES.md's re-runnable claims)
came back clean everywhere sampled - the failure mode this issue names is
concentrated in prose that describes state, not in commands or results.

The cause, not just the count: nine of the thirteen were all STATUS -
"two open tasks in the current session," "see Task 2 for where it
breaks," "found this session, not yet numbered," "IS tracked in git" -
each true the night it was written and false within hours, because
CLAUDE.md mixed durable architecture with perishable state in one file,
and state rots faster than anyone edits architecture. Fixed structurally,
not line by line: CLAUDE.md now carries no status at all - every section
describing what is in progress, currently broken, or found this session
was deleted, replaced with one line pointing at ISSUES.md and git log as
the maintained record of current state. The three remaining factual
errors (an unreproducible number, an undercounted filer list, an
undercounted guard list) were fixed directly. `graph.py` got a sentence
stating its constraints are documentation, not enforcement, rather than a
validator bolted onto types the live pipeline never touches.
`statements.py` and `cache.py` close category 1.

The count alone is a number; the cause is the finding. A durable document
that also carries perishable status will always drift, no matter how
carefully any one edit is checked - the fix has to be structural
(state lives elsewhere) or the tenth instance is only a matter of time.

THE SECOND STRUCTURAL FIX, 2026-09-06. Moving state out of CLAUDE.md
addressed the nine status instances. It does nothing for the other kind:
a count stated in two places, where neither place is status and both are
durable. `scripts/test_docs_consistency.py` checks those mechanically, on
every push:

  - README's command list is byte-identical to CLAUDE.md's, which is what
    the word "verbatim" in README claims (this was instance 5).
  - Every documented `scripts\*.py` command exists (instance 4).
  - README's prose count matches the length of the list it introduces.
  - CI runs only scripts that exist and appear in the documented list.
  - CI's own statement of what it does NOT cover matches what it runs.
  - The gate count in README, CLAUDE.md twice, and gates.py agree
    (instance 3).

It cannot tell whether a sentence is true. It checks whether a number
stated in two places still agrees with the thing it counts - which is the
shape every instance above had.

The tenth instance arrived on schedule and was caught by the checker rather
than by accident, twice within one commit: adding test_manifest.py to the
command list left "Ten commands" stale, and adding the checker itself to CI
left three coverage counts stale.

Six drifts were then injected one at a time to prove it has teeth, each
confirmed to have actually landed in the file before the checker ran -
diverged command lists, a documented script that does not exist, a stale
gate count, an inflated CI coverage number, a wrong uncovered count, a
wrong prose count. All six caught; with no drift, clean. A first attempt at
this control used a shell heredoc that silently collapsed a backslash, so
the "passing" run had never modified anything - a negative control that
does not verify its own injection proves nothing, which is the same lesson
as the fiscal-year validator above.

Status: CLOSED. The sha256 half is enforced; the documentation half has a
test instead of a recommendation. What remains uncovered is prose that
states a guarantee no count can express - that class is still checked by
reading, and the ADRs in docs/adr/ are where those guarantees now live.

## #31 eval-gate.yml could only ever fail on a fresh clone — CLOSED

`.github/workflows/eval-gate.yml` ran `experiments/ch05_evaluation/02_ab_test.py`
on every pull request to main. That script opens `data/uber_10k.pdf` at module
level, line 34, unconditionally - and the filings are deliberately not
distributed (docs/adr/0006), a decision made true of every commit when history
was rewritten on 2026-09-06.

MEASURED on a fresh `git clone` of the public repository, not on a local
working copy: `PdfReader("data/uber_10k.pdf")` raises `FileNotFoundError`. The
script dies before any evaluation runs and before its dependencies matter.

The workflow's only successful run is `eb8940f3`, 2026-08-13. The PDF was
untracked in `350ac47` on 2026-09-02, AFTER that run, so the green result
predates the condition that breaks it - and neither SHA exists in this history
any more, since the rewrite changed all of them. The sole evidence this gate
ever worked points at a history that is gone.

DELETED, not taught to skip. A conditional step would have put a green
"Evaluation Gate" check on pull requests where nothing was evaluated, which is
this project's own worst failure mode wearing a tick mark. `pipeline-tests.yml`
already states the same position for the three tests it cannot run, and
`test_manifest.py` for shallow clones. Reasoning and both rejected
alternatives in docs/adr/0008.

`experiments/ch05_evaluation/02_ab_test.py` is NOT modified: `experiments/` is
archived course work, read-only by the working agreement, and editing an
archived chapter to accommodate a CI decision would falsify what that chapter
was. `requirements-eval.txt` is kept - it is how the evaluation is run locally,
which is still supported.

The gap is now checked, not just recorded.
`test_docs_consistency.py::test_no_workflow_needs_a_file_the_repository_does_not_ship`
walks every script any workflow runs and fails on a referenced path that exists
locally but is untracked - the exact shape of this bug, and the exact reason it
survived: it worked on the author's machine. Deliberately narrow: a path that
exists nowhere is a fixture string, not this bug, and the first version of the
check flagged `test_manifest.py`'s own `"data/does-not-exist"` before that was
fixed. Verified by reintroducing the deleted workflow verbatim - caught, exit 1
- and removing it again.

Note for anyone reinstating this: #3, #4 and #5, the findings this gate would
protect, are all in the retrieval layer, which README.md states is course work
and not part of the capstone pipeline.

## #34 `pytest tests/` could not pass on a fresh clone, for the same reason #31 could not — CLOSED

Found in the closing pass, 2026-09-10. `pipeline-tests.yml` runs
`python -m pytest tests/` on every push. The filings are not distributed
(docs/adr/0006), so the runner has none of them.

MEASURED, with `data/*.pdf` and `data/aleph_cache.db` moved aside:

```
python -m pytest tests/   ->  181 failed, 628 passed
```

Every one of the 181 a `FileNotFoundError` on `data/uber_10k_fy2024.pdf` or a
sibling. No `conftest.py` existed and no test carried a skip condition, so this
step was red on every push since the tests were added - and #31, the workflow
that could only ever fail, was closed while a second one sat next to it doing
the same thing at a different granularity. Deleting a whole workflow is easier
to notice than a suite that fails 181 of 809.

FIXED structurally, and NOT by making the tests pass without documents: 181 of
them assert on real numbers from real filings, and faking the filings would
leave 181 green checks that prove nothing.

`tests/conftest.py` reads `data/manifest.json`, checks every filing it lists,
and skips the tests marked `needs_filings` when one is absent, naming the
missing file. The marker is registered in `pyproject.toml` so a typo is a
warning rather than a silent no-op.

Which tests carry it was MEASURED, not chosen by reading file names: the 181
failing node ids map to 158 test functions - and to check that mapping is
sound, every parametrised case was examined: none is mixed, each
parametrisation fails wholly or not at all, so the marker sits on functions and
no `pytest.param(marks=...)` is needed.

The skip is LOUD, which is the whole point and the difference between this and
the "make it skip" alternative docs/adr/0008 rejected.
`pytest_terminal_summary` prints, above pytest's own summary line:

```
========================== NOT VERIFIED BY THIS RUN ===========================
SKIPPED 181 tests that need the filings; they are NOT verified by this run.
```

VERIFIED both ways, which is what makes the marking falsifiable rather than
merely plausible:

```
data/*.pdf and data/aleph_cache.db moved aside:  635 passed, 181 skipped, 0 failed
filings present:                                 816 passed, 0 skipped
```

Zero skipped with the filings present is the load-bearing half. A marker on a
test that never needed a filing would silently remove that test from CI
forever, and nothing else in the mechanism would notice.

## #35 The extraction prompt was outside the cache key AND outside every check — CLOSED

`Cache.key` includes `PROMPT_VERSION`, a hand-maintained string, not the prompt
itself. That is deliberate and stays: hashing the prompt into the key would
change every key on every wording change and force a paid re-extraction of all
six filings.

The cost of that choice went unrecorded. Edit `SYSTEM_PROMPT`, forget to bump
`PROMPT_VERSION`, and every cached answer is served against a prompt that no
longer produced it - silently, with no red flag, which is this project's named
worst failure mode.

The second half is worse because no one edits anything: `ExtractedFacts`'
JSON schema is pasted into the user message, so `pydantic`'s
`model_json_schema()` rendering is part of the prompt. A pydantic upgrade
changes what the model was asked without touching this repository at all.
`pyproject.toml` pins `pydantic>=2.0`, so CI installs whatever is current.

FIXED without touching the cache key. `extractor.py` records
`PROMPT_FINGERPRINT`, the sha256 of `SYSTEM_PROMPT + SCHEMA_JSON`, and checks
it at import - `raise`, not `assert`, because `python -O` strips asserts and a
guard that disappears under a flag is not a guard. The message says which
constant to bump. Current value:
`2377308fe04a7392a6369a72ab5486bd728badb9ec0e35ea678c6a16de47116d`, computed
under pydantic 2.13.4.

`SCHEMA_JSON` is now a module constant used both by the fingerprint and by the
message actually sent, so the fingerprint is provably over the bytes the model
receives rather than over a second rendering of them.

OPEN, and deliberately left open rather than papered over: the consequence in
CI. `pyproject.toml` pins `pydantic>=2.0`, so the runner installs whatever is
current, and the workflow's "Import the package" step imports `extractor`. If a
future pydantic renders the schema differently, that step goes red on a
dependency bump nobody made deliberately. That is the CORRECT signal - the
prompt did change and the cache is stale against it - but it is a decision
whether to keep the loose pin and accept a red badge as the notification, or
pin pydantic exactly and make the schema move only when someone chooses it.
Not decided here; whoever decides should record it as an ADR, because both
options have a real cost.

Also fixed alongside it: `json.loads` on the model's reply was unwrapped. A
reply that is not JSON surfaced as a bare `JSONDecodeError` naming a character
offset in a string the reader cannot see, and naming neither the filing nor the
target. It now raises `ExtractionError` with `doc_id`, the target, and the
first 200 characters of the reply - the same treatment the `max_tokens`
truncation already had, including not caching the failure.

Tests in `tests/test_extractor_prompt.py`, seven of them, none needing a
filing: the positive control, two negative controls (the fingerprint moves when
the system prompt moves, and when the schema moves), the import-time raise
exercised by re-executing the module source with the recorded constant
tampered, and three on the malformed reply - that it is named, that nothing is
cached, and that a well-formed reply still parses. Without that last one, a
wrapper that rejected every reply would pass the other two.

## #36 Eleven places under `src/aleph/` each decided where `data/` is — CLOSED

`Path("data") / record.file_name`, `Path("data/manifest.json")` and
`Path("data/aleph_cache.db")` appeared across `extraction/extractor.py`,
`valuation/pipeline.py`, `infra/cache.py` and `forensics/language.py`. A
relative path is not a location; it is a location plus an assumption about the
current working directory.

The assumption held because every documented command is run from the repository
root. Run one from anywhere else and it fails with
`FileNotFoundError: data/manifest.json` - a path that does exist, reported from
a directory the reader is not looking at.

FIXED with `src/aleph/infra/paths.py`: `DATA_DIR`, resolved once from
`ALEPH_DATA_DIR` if set, otherwise from the package file's own location
(`src/aleph/infra/paths.py` -> repo root), never from the CWD. The env var
exists because the filings are not distributed, so someone holding them
elsewhere needs a way to say so that is not a source edit.

VERIFIED by running the anchor from a different working directory:

```
cd $env:TEMP; python <abs path>\scripts\run_valuation.py UBER_FY2024 76.95
```

Same output as from the repository root, byte for byte - `Latest-period basis:
77.08` included.

The "before" is measured too, from that same directory, rather than asserted:

```
the old literal 'data\manifest.json' resolves to
  C:\Users\asafc\AppData\Local\Temp\data\manifest.json   exists = False
DATA_DIR now:
  C:\Users\asafc\...\aleph\data                          exists = True
```

Note what that failure looks like to a reader: `FileNotFoundError` naming
`data/manifest.json`, a file that is sitting right there in the repository.

## #37 `data/README.md` quoted the anchor under the range's label — CLOSED

Small, and the same shape as everything else in this file. It said the six
PDFs reproduce "the `Value per share: 77.08` / `49.06` anchors". The CLI prints
two different lines:

```
  Value per share      :  -14.13 to 77.08    (range across FY2022-FY2024 FCFF)
  Latest-period basis  :             77.08  (FY2024 FCFF, the base case)
```

`Value per share` is the RANGE. 77.08 is the `Latest-period basis`. Quoting a
single number under the range's label is the point-estimate reading the seventh
settled principle exists to refuse - in the file whose job is telling a reader
what output to expect.

Fixed, and checked:
`test_docs_consistency.py::test_the_anchor_is_quoted_under_the_label_the_cli_prints`
requires any document that mentions 77.08 to also name `Latest-period basis`,
and requires that label to be one `run_valuation.py` actually prints.

## #38 The engine grew a negative FCFF for ten years and called it a valuation — CLOSED

`run_dcf` multiplies `base_cash_flow` by (1 + g) each forecast year and
capitalises the final year with Gordon. Guard 0c refused a ZERO base as
NOT_SOLVABLE and said nothing about the SIGN, so a negative base went
straight through: the loss compounded for ten years and the present value of
a deepening loss was reported as a value per share.

MEASURED. Two of the four valued filings, not one:

```
LYFT_FY2025   FY2023 FCFF  -712   ->  range low  -$39.37
UBER_FY2024   FY2022 FCFF  -957   ->  range low  -$14.13
UBER_FY2025   FY2023 FCFF  1,927  ->  positive, unaffected
DASH_FY2025   FY2023 FCFF    462  ->  positive, unaffected
```

The task that opened this named only Lyft. UBER_FY2024 was found by running
all four filings and reading the bound, and its -$14.13 was quoted in
CLAUDE.md's SEVENTH SETTLED PRINCIPLE and in README's "the decision that
changed a conclusion" - the number was load-bearing in the documentation
while being a number the model should never have produced.

DECIDED: option (A) of two. `validate()` gets Guard 0d - a negative
`base_cash_flow` raises `DCFConsistencyError(... NOT_APPLICABLE)`. Rejected
alternative: keep the arithmetic and label it loudly wherever it is printed.
Rejected because the number stays in the file, in the app and in the README
table, where a reader can quote it without the label - which is this
project's own worst failure mode.

No tolerance band. -0.01 is a loss; there is no amount of loss small enough
to grow into a valuation, and a threshold would be a number nobody could
defend.

WHAT CHANGED BEYOND THE LOW, because the cascade was larger than the request
assumed and every step of it was measured:

- the tornado row for `base_cash_flow` loses its swing. `sensitivity_tornado`
  sorts on `(swing is not None, swing or 0)`, so the row now sorts LAST.
- `robustness._assumption_sensitivity` filtered `swing is None` rows out and
  crowned the runner-up. Left alone it would have printed "the valuation is
  controlled by discount_rate" for BOTH affected filings - reversing this
  project's own central finding (#25, #29) with a sentence that is false
  about the world and carries no red flag. FIXED in the same change: a
  refused bound is reported as `PRIMARY VALUE DRIVER: base_cash_flow (bound
  NOT_APPLICABLE)`, severity HIGH, with the interpretation stating that
  unquantifiable is not small.
- `model_governance` formatted P6's scenario values with `:.2f`. A refused
  scenario is None, `f"{None:.2f}"` raises TypeError, and the broad
  `except Exception` turned that into `value=error` / `NOT_SUPPORTED` -
  discarding the two scenarios that DID value and reporting a formatting
  failure as an evidence failure. FIXED: NOT_APPLICABLE per scenario, P6
  stays CONDITIONAL_APPLICABILITY.
- anchor spread narrows because the refused anchor leaves the set:
  UBER_FY2024 290% -> 98%, LYFT_FY2025 1826% -> 117%. The spread is now
  "across the anchors that can be valued", which is what it always measured.

UNCHANGED, and checked by diffing every run against its own pre-change
output: `Latest-period basis` 77.08 and 49.06, the high end of both ranges,
PV explicit / PV terminal / enterprise / equity value, the reverse DCF
(-8.5% for Lyft), and UBER_FY2025 and DASH_FY2025 byte-for-byte.

Fifteen `run_dcf` call sites were read. Fourteen already caught
`DCFConsistencyError`; ONE did not - `pipeline.py`'s range-bound re-run - and
that one would have taken down an otherwise-valid valuation. That is now
guarded, and `tests/test_negative_base_fcff.py` walks the AST of every module
under `valuation/` and fails on a sixteenth unguarded re-run, with the two
base-case sites allowlisted by name and reason.

TEN EXISTING TESTS FAILED on the first full run and every one was a test
asserting the OLD behaviour, not a defect in the change. They were rewritten
to assert the refusal rather than deleted, because what they encode - that a
negative anchor must not silently produce a plausible number - is the same
property, now enforced one layer earlier:

  test_p5_controls    2  the P5.7 reverse-DCF orientation proof for B < 0
  test_market_expect. 4  sectors priced off their own negative-anchor DCF
  test_robustness     3  a negative base listed as "finite output allowed",
                         and two findings built on a run_dcf(-500) result
  three more          1  see below - not about the guard at all

That last one is worth its own line. `test_pipeline_has_no_*_import` in
three files greps `pipeline.py`'s SOURCE for the names of the diagnostic
modules, to prove they are not wired into the orchestrator. A COMMENT added
in this change happened to list four of them by name and failed all three.
The comment was reworded; the tests are right, and the next person to write
a comment in that file should know they are reading it.

TWO THINGS LEFT DEAD BY THIS, recorded rather than removed:
`reverse_dcf`'s B < 0 direction branch (the window probe returns
NOT_SOLVABLE first), and `robustness._method_limitation`'s negative-base
finding (a filing whose LATEST FCFF is negative now stops at the pipeline's
own `run_dcf` and the CLI exits 1). Both are kept, tested where the contract
is observable - the second by handing robustness a CONSTRUCTED DCFResult,
since the engine will no longer produce one - and documented in place.

ONE THING DELIBERATELY NOT CHANGED: `market_expectations.implied_base_fcff`
can still report a NEGATIVE implied base FCFF when the market price is low
enough, and that is not a valuation - it is a statement about what the price
implies, solved in closed form and never fed back through the engine. Its
docstring's claim that "a re-run at B* cannot raise" is now false in
principle (Guard 0d is a new guard keyed on base_cash_flow), but no re-run
happens, so nothing is broken. None of the four filings produces a negative
B* today.

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

REVISED once #29's fix landed (see #29): this framing was written against
a tornado whose base_cash_flow bound only tested capex dispersion, so
discount_rate's 39% swing looked like the largest lever there was. With
the real bound in place, base_cash_flow's own swing is 78% for Uber and
180% for Lyft - larger than discount_rate in every run - so "fairly priced
at the industry beta, 21% expensive at the regression beta, no third case"
understated the dominant variable rather than describing it. The corrected
comparison is #29's: which year's FCFF the analyst treats as
representative moves the answer further than any beta choice does.

**#17 build_wacc clamped negative net debt to zero with no note in the output — CLOSED**
Decided: keep the clamp, print it. `debt_value = max(net_debt, 0.0)` is a
defensible treatment for a net-cash company - Hamada's formula is not
well-defined for negative leverage - but a silent clamp is not, in a system
whose whole design principle is that a judgement is recorded, not smoothed
over. wacc.py now prints a note naming the actual net debt figure whenever
the clamp changes the value, in the same style as the other WACC notes, and
stays silent when it does not fire. No new blocking gate: the clamp is a
convention, not an analyst decision, so recording it in the output is
enough. Confirmed firing on `LYFT_FY2025` ("net debt clamped to zero for
relevering: net_debt=-835") and `DASH_FY2025` ("net_debt=-2,782"); confirmed
silent on `UBER_FY2024`, whose net debt is positive.

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
