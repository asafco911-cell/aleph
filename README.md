# Aleph — A bounded-extraction DCF over 10-K filings

*An LLM copies, Python gates, arithmetic values.*

[![Pipeline tests](https://github.com/asafco911-cell/aleph/actions/workflows/pipeline-tests.yml/badge.svg)](https://github.com/asafco911-cell/aleph/actions/workflows/pipeline-tests.yml)

Aleph reads a 10-K, has an LLM copy figures out of one bounded region at a
time, checks every copy with deterministic Python gates, and runs a DCF that
reports a range instead of a point.

It holds six filings - Uber, Lyft and DoorDash, FY2024 and FY2025 - of which
four are valued end to end; the other two stop at extraction, because valuing
them would take analyst judgements manufactured to fill a gap in a table
rather than to answer a question
([ISSUES.md #24](ISSUES.md#24-dash_fy2024-has-never-been-valued--closed-as-out-of-scope)). Built with AI
assistance (Claude) under [CLAUDE.md](CLAUDE.md).

## The result

Three companies, one method, at the same close of 2026-08-27.

| filing | value-per-share range (FCFF basis) | latest-period basis | market price | where it sits | reverse-DCF implied growth |
|---|---|---|---|---|---|
| UBER_FY2025 | $26.86 – $119.95 (FY2023–FY2025) | $119.95 | $76.95 | inside, 53.8% of the way up | 5.1%/yr for 10 years |
| LYFT_FY2025 | NOT_APPLICABLE – $49.06 (FY2023–FY2025) | $49.06 | $17.35 | no range to place it in | -8.5%/yr for 10 years |
| DASH_FY2025 | $54.85 – $124.27 (FY2023–FY2025) | $124.27 | $231.89 | 86.6% above the top | 23.5%/yr for 10 years |

Reproduce a row: `python scripts/run_valuation.py <doc_id> <price>`. The
[cache](src/aleph/infra/cache.py) is time and money, not the source of the
number: measured 2026-09-10, with `data/aleph_cache.db` moved aside, seven
live LLM calls for `UBER_FY2024` produced output identical line for line to
the cached run, 77.08 included.

"Where it sits" places a price against a range built from the filing's own
cash flows; it is not a verdict. Reading Uber's row as **insufficient basis to
conclude** is this write-up's judgement, not a string the code emits.
DoorDash is the one row where it does not hold.

Lyft has no low end, and that is a finding, not a missing number: its FY2023
FCFF was -$712m, and the engine refuses to grow a negative cash flow for ten
years and call the result a valuation
([ISSUES.md #38](ISSUES.md#38-the-engine-grew-a-negative-fcff-for-ten-years-and-called-it-a-valuation--closed)).

The system also produces evidence against itself. `UBER_FY2024` and
`UBER_FY2025` value the same company at the same $76.95 price one filing year
apart: $77.08 versus $119.95, a 56% swing with every gate passing - almost
entirely two non-cash items in one year's CFO read as durable cash flow
([ISSUES.md #29](ISSUES.md#29-a-ten-year-dcf-anchored-on-one-years-fcff-is-the-wrong-instrument-for-a-company-mid-inflection)).

## What this is, and what it is not

**What runs in `src/aleph/`**: document structure, bounded extraction with
seven gates, assumption derivation that blocks rather than guesses, a
bottom-up WACC, a DCF reporting a range, and language forensics.

**What is course work, not the capstone**, lives in
[`experiments/`](experiments/) - thirteen archived chapters on retrieval, RAG
evaluation, knowledge graphs and multi-agent orchestration. **None of it is
wired in.** Aleph does not retrieve, does not build a graph and is not a
multi-agent system, by design: the LLM never searches, navigates, computes or
chooses a source.

**What it is not, at all**: investment advice. Its largest documented
limitation
([ISSUES.md #29](ISSUES.md#29-a-ten-year-dcf-anchored-on-one-years-fcff-is-the-wrong-instrument-for-a-company-mid-inflection))
- a ten-year DCF anchored on one
year's cash flow is arguably the wrong instrument for these companies - is
here because the system produced it.

## How it works

The model copies one figure at a time out of one located region; everything
after that is deterministic Python. Six gates in
[gates.py](src/aleph/extraction/gates.py) check the copy: a source, a real
quote, the value inside it, the filing's own unit scale, rows that cross-foot,
columns on the right period. A seventh, separate gate checks that copying
*finished*, so a required quantity cannot be silently skipped.

Net debt BLOCKS until an analyst records a policy and a reason in
[data/overrides.json](data/overrides.json). A judgement the pipeline cannot
derive is one it refuses to invent.

Six rules that looked like general "10-K facts" turned out to be "Uber facts"
- a table-of-contents format, a note heading, a statement title, a page
offset, where geography sits, a tax table that changed shape between two years
of one filer. Every target is now resolved by section title, because of
exactly those six failures
([CLAUDE.md](CLAUDE.md#six-10-k-facts-that-were-actually-uber-facts)).

## What it found

**One analyst decision, worth $25.32 a share.** Whether stock-based
compensation is a cash cost is a judgement, not a fact in the filing. Before
it, UBER_FY2024 valued at $102.40 against a $76.95 price. Subtracting SBC
from FCFF at full value brought it to $77.08 - effectively at market, nothing
in the filing changed.

**Language no financial statement carries.** Year-over-year, Uber's
FY2024→FY2025 Item 1A drops its 2025 climate and EV goals in seven places:
three full sentences and four phrases inside sentences that survive as
rewrites. A null control, a filing diffed against itself, reads zero on every
bucket first.

## Diagnostic layers (not in the base DCF)

Most of this repository is not the valuation. Measured on
`src/aleph/valuation/`, 12,346 lines across 20 modules: **2,786 lines are
code a valuation number depends on**; the other 9,560 are diagnostic layers
that read a finished valuation, re-run the *pure* engine on copies, and report
what the answer rests on. Enforced, not promised: regression tests feed a
layer garbage and assert the per-share value is byte-identical.

| module | lines | the question it answers |
|---|---|---|
| `accounting_quality.py` | 1,902 | Is the reported earnings-to-cash relationship deteriorating, and where? |
| `evidence_resolution.py` | 1,330 | When two layers disagree about a number, which evidence wins, and why? |
| `robustness.py` | 1,289 | How much of the answer is a choice rather than a fact? |
| `evidence_depth.py` | 803 | What accounting evidence is actually present, and where does it run out? |
| `model_governance.py` | 769 | Why do the LIVE, P6 and P9 valuations disagree, and which assumption is responsible? |
| `sustainable_fcff.py` | 738 | Which part of the latest FCFF is a recurring cash-generating capability? |
| `operating_model.py` | 638 | What does revenue → margin → working capital → capex imply, driver by driver? |
| `market_expectations.py` | 587 | What must be true for today's market price to be right? |
| `cfo_normalization.py` | 474 | How much of CFO's composition can be accounted for at all? |
| `historical_fcff.py` | 445 | How far does the answer move across every starting year an analyst could defend? |
| `normalization.py` | 277 | What would capitalising R&D do to the operating result? |
| `sensitivity.py` | 211 | What does the answer look like across a WACC × growth grid? |
| `driver_based_dcf.py` | 97 | Can a driver-built FCFF path be expressed as growth the existing engine accepts? |

Run: `python scripts/diagnose_valuation.py UBER_FY2024 76.95`.

**None of these changes a number, and none was promoted, deliberately.** The
strongest candidate - P6, a sustainable FCFF range instead of one disclosed
year - was rejected as the base anchor because its central case rests on a
historical median, a convention chosen inside this repository
([docs/adr/0009](docs/adr/0009-diagnostic-layers-not-promoted.md)).

Note how far the split goes: **it is the PRINTING that moved, not the
computation.** `accounting_quality` and `robustness` still run inside
`value_filing`, behind **2** deliberate `except Exception` handlers in
[pipeline.py](src/aleph/valuation/pipeline.py) that stay: a failed diagnostic
must become a NOT_ASSESSED report, never a failed valuation.

One of them explains why the live path does the *less* clever thing: across
six filings and 71 cash-flow captions, zero name a one-time cash cost, so the
statement alone cannot separate a representative year from an unusual one
([cfo_normalization.py](src/aleph/valuation/cfo_normalization.py)).

## What is broken

[ISSUES.md](ISSUES.md) is the honest state of the project, not a changelog.
Closed issues stay, because each carries the measurement that closed it -
before/after numbers, not "fixed."

Every open issue carries a measurement or a reproduction. Read it first.

## Repository layout

```
src/aleph/        the pipeline. documents/ (structure, notes, statements),
                  extraction/ (bounded LLM call, gates, per-filing targets),
                  valuation/ (assumptions, bridge, wacc, dcf_engine,
                  pipeline), forensics/ (language), schemas/, infra/
                  (textnorm, cache, units)
scripts/          run_valuation.py (the valuation CLI),
                  diagnose_valuation.py (the layers that change no number),
                  test_*.py (one per stage), probe_*.py (ad hoc measurement -
                  the "measure, don't guess" tool), capture_baseline.py,
                  build_manifest.py
app.py            Streamlit UI over the same pipeline. Every number carries
                  a provenance grade; a composite inherits the weakest.
data/             manifest.json, market.json (shared + per-filing market
                  inputs), overrides.json, anchors.json.
                  The PDFs and the cache are gitignored - see data/README.md
docs/adr/         nine decisions that had a real rejected alternative
experiments/      ch01-ch13, archived course chapters. Reference only; see
                  "What this is, and what it is not" above
CLAUDE.md         architecture and working agreement. Carries no status
ISSUES.md         the honest state, open and closed, each with its
                  measurement
```

## Running it

```
python -m venv venv
venv\Scripts\activate
pip install -e .[dev]
```

Four runtime packages plus pytest, Python 3.11 or later. The extra is not
optional for the commands below: measured on a fresh clone, `pip install -e .`
alone breaks two of them. `python -m pytest tests/` fails with `No module
named pytest`, and `python scripts/test_docs_consistency.py` exits 1, because
it counts what the `needs_filings` marker selects by shelling out to `pytest
--collect-only`. Add the UI with `pip install -e .[ui]`.

Extraction needs `ANTHROPIC_API_KEY` in `.env`, though not on a warm
[cache](src/aleph/infra/cache.py). The six PDFs are not distributed here -
[data/README.md](data/README.md) has the EDGAR source of each.

Thirteen commands prove the pipeline works, verbatim from
[CLAUDE.md](CLAUDE.md#commands-that-verify-the-system-works):

```
python scripts/run_valuation.py UBER_FY2024 76.95   # must print Latest-period basis: 77.08 (was 102.40 pre-SBC, see #16)
python scripts/run_valuation.py LYFT_FY2025 17.35   # must print Latest-period basis: 49.06 (was 67.79 pre-SBC, see #16)
python scripts/test_regression.py                    # gate over cached extraction targets, exit(1) on shortfall
python scripts/test_gates.py
python scripts/test_dcf_engine.py
python scripts/test_schemas.py
python scripts/test_sections.py
python scripts/test_multicompany.py
python scripts/test_assumptions.py
python scripts/test_pipeline_callback.py
python scripts/test_manifest.py
python scripts/test_market.py
python scripts/test_docs_consistency.py
```

Eight run in CI
([pipeline-tests.yml](.github/workflows/pipeline-tests.yml)); the other five
need the filings, so the badge covers neither them nor the 77.08 anchor. It is
the only workflow - two others were deleted rather than taught to skip
([docs/adr/0008](docs/adr/0008-eval-gate-removed-from-ci.md)).

CI also runs `python -m pytest tests/`, which without the filings would fail
rather than skip. [tests/conftest.py](tests/conftest.py) skips the marked
tests when a filing in the manifest is absent, printing

```
========================== NOT VERIFIED BY THIS RUN ===========================
SKIPPED 185 tests that need the filings; they are NOT verified by this run.
```

because skipped is not passed. Today
185 tests carry the marker, on 159 test functions - a parametrised function
produces several tests from one decorator - and both counts are checked
against the code. With the filings, 0 skipped - and the suite takes roughly
ten minutes rather than the few seconds it takes without them, because the
tests that skip are exactly the ones that open a PDF.

`streamlit run app.py` opens the pipeline in a browser.

## Licence

[MIT](LICENSE), covering the code here and not the SEC filings it reads.

Nothing here is investment advice. Read [ISSUES.md](ISSUES.md) before trusting
a number.
