# Aleph — Autonomous Multi-Document Financial Analyst

Aleph reads 10-K filings and produces a defensible valuation range: an LLM
copies figures from bounded regions of the document, deterministic Python
gates check that the copying is correct, and everything downstream - the
assumption ranges, the bottom-up WACC, the DCF - is arithmetic with no model
in the loop.

Built with AI assistance (Claude) throughout, under the working discipline
recorded in [CLAUDE.md](CLAUDE.md).

## What this is, and what it is not

This repository is the capstone of a fourteen-chapter course, and the name
covers less than the course syllabus does. Stating that plainly is cheaper
than letting a reader discover it.

**What runs in `src/aleph/`** is a valuation pipeline, end to end, on six
real filings: document structure (table of contents, Item ranges, statements
and notes resolved by title), bounded extraction with seven gates, assumption
derivation that blocks rather than guesses, a bottom-up WACC, a DCF that
reports a range with a tornado and a reverse DCF, and year-over-year language
forensics on MD&A and Risk Factors. Four filings are valued end to end.

**What is course work, not the capstone**, lives in
[`experiments/`](experiments/) - thirteen archived chapters covering
embeddings, chunking, vector stores, hybrid retrieval and re-ranking, RAG
evaluation, grounding, knowledge graphs, multi-agent orchestration, forensic
scores, cross-document comparison, production concerns and CI. Each chapter
runs and has a reference document. **None of it is wired into the pipeline
above.** Aleph does not do retrieval, does not build a knowledge graph, and
is not a multi-agent system - by design, since principle 5 of its
architecture is that the LLM never searches, navigates, computes or chooses
a source. That is a narrower system than the chapter list implies, and the
narrowing was the point.

**What it is not, at all**: investment advice. It is a measurement
instrument with documented and material limitations, the largest of which
([ISSUES.md #29](ISSUES.md)) is that a ten-year DCF anchored on one year's
cash flow is arguably the wrong instrument for the companies it is pointed
at. That finding is in the repository because the system produced it.

## The result

Three companies, one fiscal year, one trading day, one method. `UBER_FY2025`,
`LYFT_FY2025` and `DASH_FY2025` are all priced as of the same market close -
2026-08-27 - and run through the identical pipeline: extract, derive a
bottom-up WACC, rebuild FCFF from CFO, discount.

| filing | value-per-share range (FCFF basis) | latest-period basis | market price | where it sits | reverse-DCF implied growth |
|---|---|---|---|---|---|
| UBER_FY2025 | $26.86 – $119.95 (FY2023–FY2025) | $119.95 | $76.95 | inside, 53.8% of the way up | 5.1%/yr for 10 years |
| LYFT_FY2025 | -$39.37 – $49.06 (FY2023–FY2025) | $49.06 | $17.35 | inside, 64.1% of the way up | -8.5%/yr for 10 years |
| DASH_FY2025 | $54.85 – $124.27 (FY2023–FY2025) | $124.27 | $231.89 | 86.6% above the top | 23.5%/yr for 10 years |

Reproduce any row with `python scripts\run_valuation.py <doc_id> <price>`.

Be precise about what that table's middle columns are: the tool prints
"inside the range, 53.8% of the way up" or "86.6% ABOVE the top of the
range" - a description of where a price sits against a range built from the
filing's own disclosed cash flows. It does not print a verdict. Reading
Uber's and Lyft's rows as **insufficient basis to conclude** - the market
price sits inside a range wide enough that both a bull and a bear case are
consistent with the same filing - is this write-up's conclusion, not a
string the code emits. DoorDash's row is the one place that reading
doesn't apply: 86.6% above the top of what three years of its own cash
flow history can support is the one unambiguous verdict of the three.

The system also produces evidence against itself. `UBER_FY2024` and
`UBER_FY2025` value the same company, at the same $76.95 price, on the
same date, one filing year apart: $77.08 versus $119.95, a 56% swing.
Every gate passed on both runs; every override applied as designed. The
gap is almost entirely two non-cash items in one year's CFO (deferred
income taxes, unrealized gains on marketable securities) - one year's
accounting items being read as durable cash flow. [ISSUES.md #29](ISSUES.md)
has the full decomposition.

The reverse DCF is the cleanest cross-company line the system produces:
one number per company instead of a range. It is not free of the same
base-cash-flow dependency described above - it holds the latest-period
FCFF fixed and solves only for the growth rate, held for ten years, that
the current market price already implies at that base: 5.1% for Uber,
-8.5% for Lyft, 23.5% for DoorDash. Lyft's is the sharpest read: its market
price is not pricing growth at all under this model's assumptions, and
that implied decline runs against Lyft's own recent trajectory - FCFF of
-712 (FY2023), 458 (FY2024), 810 (FY2025).

## The decision that changed a conclusion

Whether stock-based compensation is a cash cost is a judgement call, not a
fact in the filing. Before that decision, UBER_FY2024 valued at $102.40
against a $76.95 market price: roughly 33% undervalued. Treating SBC as a
cash cost, subtracted from FCFF at full value, brought it to $77.08:
effectively at market. Nothing about Uber's filing changed between those
two numbers - one analyst decision did, worth $25.32 a share on its own.

It is still not the largest source of variation in the model. UBER_FY2024's
own tornado puts base_cash_flow's swing at $91.20 (-$14.13 to $77.08)
against discount_rate's $29.83 - the same base-cash-flow instability behind
section 1's 56% swing between UBER_FY2024 and UBER_FY2025. One analyst
decision moved the conclusion from "33% undervalued" to "fairly priced,"
and the single largest lever in the model is still which year's cash flow
an analyst treats as representative, not that decision. See
[ISSUES.md #16](ISSUES.md) for the SBC reasoning, applied identically to
all three filers - the system measures the consequence of a decision; it
does not manufacture a number on its own.

## What the language forensics found

Comparing Item 1A (Risk Factors) year-over-year surfaces omissions no
financial statement carries. Uber's FY2024→FY2025 filing drops language on
its 2025 climate and EV goals in seven places (three full sentences, four
phrases inside sentences that otherwise survive as rewrites) - including
the explicit admission, present in the earlier filing and gone from the
later one: *"we may not be able to achieve all of our 2025 goals as
originally anticipated."* Lyft's driver-classification risk factor loses
the phrase *"and we may incur significant expenses to resolve the matters
at issue in the litigation"* from an otherwise-surviving sentence about
that same litigation. Neither shows up in a cash flow number. Reproduce
with `python scripts\probe_forensics.py UBER_FY2024 UBER_FY2025 1A` and
the Lyft equivalent; a null control (a filing diffed against itself) reads
zero on every bucket before either result means anything.

## How it works

Extraction is bounded and probabilistic: an LLM copies one figure at a
time from one located region of the filing, never searches or chooses a
source. Everything after that is deterministic Python. Six gates in
[gates.py](src/aleph/extraction/gates.py) check that what was copied is
correct - has a source, quotes real text, the value appears in the quote,
the unit matches the filing's own scale caption, rows cross-foot, columns
align to the right period. A seventh, separate gate checks that copying
*finished* - that a required quantity wasn't silently skipped. Quantities
like net debt BLOCK until an analyst records a policy and a reason in
[data/overrides.json](data/overrides.json); there is no default.

Five rules that looked like general "10-K facts" turned out to be "Uber
facts," and broke the first time a second or third filer was added - a
table-of-contents format, a note-heading style, a statement title, a page
offset, where geography sits in the segment note. Every extraction target
is now resolved by section title, never by number or position, because of
exactly those five failures. The full list is in
[CLAUDE.md](CLAUDE.md#five-10-k-facts-that-were-actually-uber-facts).

## What is broken

[ISSUES.md](ISSUES.md) is the honest state of the project, not a changelog.
Closed issues stay in the file rather than being deleted, because every
closed entry still carries the measurement that closed it - exact
before/after numbers, not "fixed." Every open issue carries a measurement
or a concrete reproduction, not a feeling: a wrong count, a specific
filing that breaks a rule, a swing computed from real runs. Read it before
trusting any number this pipeline produces.

## Repository layout

```
src/aleph/        the pipeline. documents/ (structure, notes, statements),
                  extraction/ (bounded LLM call, gates, per-filing targets),
                  valuation/ (assumptions, bridge, wacc, dcf_engine,
                  pipeline), forensics/ (language), schemas/, infra/
                  (textnorm, cache, units)
scripts/          run_valuation.py (the CLI), test_*.py (one per stage),
                  probe_*.py (ad hoc measurement - the "measure, don't
                  guess" tool), capture_baseline.py, build_manifest.py
app.py            Streamlit UI over the same pipeline. Every number carries
                  a provenance grade; a composite inherits the weakest.
data/             manifest.json, market.json, overrides.json, anchors.json.
                  The PDFs and the cache are gitignored - see data/README.md
docs/adr/         six decisions that had a real rejected alternative
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
pip install -e .
```

That installs four packages: `anthropic`, `pydantic`, `pypdf`,
`python-dotenv`. Add the UI with `pip install -e .[ui]` (Streamlit), or the
archived chapters with `pip install -e .[experiments]`.

Built and verified on Python 3.14.3; `pip install -e .` needs 3.11 or
later. Extraction needs a `.env` with `ANTHROPIC_API_KEY` - though not on a
warm cache, since [infra/cache.py](src/aleph/infra/cache.py) is
content-addressed and a cached target makes no call. The six filing PDFs
are not distributed with this repository - see
[data/README.md](data/README.md) for the source on SEC EDGAR for each one,
and read its hash-verification section before assuming a mismatch means
something is broken.

Ten commands prove the pipeline works, verbatim from
[CLAUDE.md](CLAUDE.md#commands-that-verify-the-system-works):

```
python scripts\run_valuation.py UBER_FY2024 76.95   # must print Latest-period basis: 77.08 (was 102.40 pre-SBC, see #16)
python scripts\run_valuation.py LYFT_FY2025 17.35   # must print Latest-period basis: 49.06 (was 67.79 pre-SBC, see #16)
python scripts\test_regression.py                    # gate over cached extraction targets, exit(1) on shortfall
python scripts\test_gates.py
python scripts\test_dcf_engine.py
python scripts\test_schemas.py
python scripts\test_sections.py
python scripts\test_multicompany.py
python scripts\test_assumptions.py
python scripts\test_pipeline_callback.py
```

Five of those ten run in CI on every push
([pipeline-tests.yml](.github/workflows/pipeline-tests.yml)) - the ones
that need only fixtures and arithmetic. The other five need the filings,
which this repository does not distribute, so a green badge here does not
mean the anchor above still holds. That check is local and manual, and the
workflow says so in its own comments rather than leaving the badge to
imply otherwise.

`streamlit run app.py` opens the same pipeline in a browser.

## Licence

[MIT](LICENSE), covering the code only. The SEC filings are not distributed
here and the licence grants no rights to them. Nothing this code prints is
investment advice.
