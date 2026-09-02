# Aleph — Autonomous Multi-Document Financial Analyst

Capstone of a 14-chapter course (chapters 1-13 archived, read-only, under
`experiments/`). Owner: Asi, 23, Tel Aviv, building toward running a fund.
Status: capstone nearly done. Remaining work is correctness, then packaging
for GitHub.

Current state lives in ISSUES.md and git log, both of which are maintained;
this file is architecture and working agreement only. Nothing that can go
stale in a week belongs here.

## Working agreement (non-negotiable)

- Do NOT guess. Measure. Before writing a regex or parser, inspect the real
  text with `repr()` or codepoints. Before claiming a cause, run something
  that distinguishes it from the alternatives.
- When a file needs substantial correction, rewrite the whole file — partial
  patches have landed half-applied three times on this project.
- If Asi's reasoning is wrong, say so in the first line. Do not flatter.
- Code comments in English only. Prose and explanations in Hebrew.
- Terminal commands one line at a time — multi-line pastes break PowerShell.
- Never invent numbers, sources, or citations. Say "I don't know" for a rate,
  beta, or price you don't have.
- Before editing `src/aleph/valuation/`, `src/aleph/extraction/`,
  `data/overrides.json`, or `data/market.json`, show the diff or full file
  first. Asi reviews those personally.
- After any `git rm --cached`, verify with `git ls-tree HEAD`, never with
  `git status` alone. `git status` looks clean once the deletion is staged;
  passing that same path explicitly to a later `git commit <path>` re-adds
  the working-tree copy (still on disk - `rm --cached` never touches it)
  and silently reverses the staged deletion, and `git status` will not show
  it happened. Only `git ls-tree HEAD` proves the path actually left the
  tree.
- A fix is not finished until a command proves it. Every change reports the
  command run and its output. `python scripts\run_valuation.py UBER_FY2024
  76.95` must still print `Latest-period basis: 77.08` after any change to
  extraction, assumptions, bridge, wacc, or dcf_engine. This anchor was
  102.40 before the SBC decision (ISSUES.md #16); it moved deliberately,
  once, on that decision - it is not evidence of drift.

## Environment

Windows, VS Code, PowerShell, Python 3.14.3, venv inside `aleph/`, package
installed editable (`pip install -e .`), `src/` layout. `anthropic` SDK 1.0.0
removed `temperature`/`top_p`/`top_k` from `messages.create()` — passing them
raises `TypeError`. Model in use: `claude-sonnet-5`. `.env` holds
`ANTHROPIC_API_KEY`, gitignored. `data/aleph_cache.db` (SQLite, content-
addressed LLM cache) is gitignored. Never commit either.

## Architecture, and why

Pipeline: read 10-K PDFs -> map Item 8 to statements and notes -> extract
facts with an LLM constrained to ONE bounded region -> validate with
deterministic Python gates -> derive assumption ranges -> build a bottom-up
WACC -> run a DCF that reports a RANGE, not a point.

Governing principle: probabilistic where allowed, deterministic where
required. The LLM copies; Python checks that copying happened and that what
was copied is right. The LLM never searches, navigates, computes, or chooses
a source.

## Eight settled principles — do not relitigate

1. File names are not an interface; `doc_id` is. `data/uber_10k.pdf` is
   historically misnamed on purpose (it is UBER_FY2025) and is not renamed.
2. Verification numbers pass through files, never argv — PowerShell silently
   turned `25,087` into the string `25,87`.
3. Normalisation is infrastructure, not tidying (`infra/textnorm.py`). U+2019
   broke a string comparison that looked fine. `repr()` does not protect
   against printable look-alikes.
4. Column semantics are resolved locally, from the nearest header above the
   quoted row, no distance ceiling. Column order is never assumed.
5. A library raises; the CLI decides the exit code. `sys.exit()` inside a
   library killed a Streamlit session instead of failing one request.
6. The content-addressed cache (`infra/cache.py`) is the only reproducibility
   mechanism. `temperature=0` never guaranteed determinism, and the SDK
   removed it anyway.
7. Value is a range derived from explicit judgements, never a point with a
   caveat. Uber moves between $80.51 and $114.99 on two decisions alone.
8. Six gates check that what was copied is correct; one gate (`coverage`)
   checks that copying finished. Reporting `accepted=4 rejected=0` while
   silently omitting a required quantity is the worst failure mode here.

## Five "10-K facts" that were actually "Uber facts"

Every rule below is now resolved by title, never by number or position,
because of these:
- Separate table-of-contents lines (Lyft puts them on one line).
- `"Note 13 - Title"` as a heading (Lyft and DoorDash write `"13. Title"`).
- `"and equity"` in the equity statement title (DoorDash: `"and
  stockholders' equity"`).
- A fixed page offset (three companies, three different values).
- Geography inside the segment note (DoorDash puts it in the revenue note).

The recurring failure across the whole course, in one sentence: **a result
that sounds right and is not is the most dangerous outcome, because it
carries no red flag.** Seen as faithfulness failures, JSON that validated on
garbage, a hidden `.pdf.pdf` extension, a typographic apostrophe, a company
name read as a column header, a geographic mix showing the US at 12% instead
of 49%, and a valuation off by a factor of one thousand.

## Cross-company comparability

Any input that is a METHOD choice rather than a company fact must be held
identical across filers, or the comparison measures the choice instead of
the businesses. Currently held identical between UBER_FY2024 and
LYFT_FY2025: unlevered industry beta (0.81, Damodaran Business and Consumer
Services), risk-free rate, ERP, terminal growth, effective tax rate policy
(21% statutory), and net-debt policy (LT debt net of current portion, less
cash and equivalents, less short-term investments; restricted cash and
operating leases excluded). Company facts that legitimately differ: share
price, country risk premium, growth.

Holding beta identical is deliberate even when it produces a WACC ranking
that looks wrong: LYFT_FY2025's bottom-up WACC (8.10%) sits below
UBER_FY2024's (8.72%), driven entirely by Lyft's net-cash capital structure
under Hamada, not by a beta tuned to make the model agree with the market.
Competitive risk belongs in the cash flows and in scenarios, not in a
discount rate quietly adjusted until the answer looks right - see
ISSUES.md #25.

## File layout

```
src/aleph/
  documents/     structure.py (TOC + Item ranges), notes.py, statements.py
                 (page-classified statutory headings), manifest.py, errors.py
  extraction/    extractor.py (bounded LLM call), gates.py (6 correctness +
                 1 coverage gate), targets.py (resolve targets per filing,
                 by title/keyword, never by number)
  schemas/       documents.py (DocumentRecord, versioned, crosses time —
                 written to data/manifest.json), evidence.py (Fact,
                 GroundedClaim), valuation.py (AssumptionRange, Override,
                 MarketAssumption), agents.py, graph.py, validation.py
  valuation/     assumptions.py (derive ranges, block on dispersion/
                 collision), bridge.py (assemble DCFInputs, unit
                 conversion), wacc.py (bottom-up WACC), dcf_engine.py
                 (pure arithmetic, no LLM; run_dcf/reverse_dcf/tornado)
  forensics/     language.py (year-over-year MD&A omission detection —
                 FINISHED, validated on both registrants, do not modify)
  infra/         textnorm.py (Unicode look-alike normalisation, matching
                 only, never sent to the LLM), cache.py (SQLite, sha256 of
                 every input that can change an answer)

data/            manifest.json (6 filings: UBER/LYFT/DASH x FY2024/FY2025),
                 market.json (WACC market inputs, per doc_id), overrides.json
                 (analyst decisions, versioned, rationale required),
                 anchors.json, aleph_cache.db (gitignored), *.pdf (gitignored)

scripts/         run_valuation.py (full pipeline CLI), test_*.py (regression,
                 gates, schemas, sections, multicompany, dcf_engine), probe_*.py
                 (ad hoc measurement scripts — the "measure, don't guess" tool)

app.py           Streamlit UI. Every number carries a provenance grade;
                 a composite inherits the WEAKEST grade in its chain.
experiments/     ch01-ch13, archived course chapters. Read for reference only.
ISSUES.md        open issues, several already fixed (#10-13 open, #1-2 closed
                 by this capstone's extract-to-DCF wiring).
```

## Data flow for one filing (`scripts/run_valuation.py DOC_ID [price]`)

1. `resolve_targets(record)` — per-filing target list (statements always,
   notes by keyword match against `record.notes[].title`, geography asked of
   every note whose title contains "segment" or "revenue").
2. `extract(record, target, question)` — one bounded LLM call per target,
   cached by sha256+prompt_version+model+target+question; returns
   `(accepted, rejected, cache_hit)` after `gates.validate()`.
3. `derive_all(facts, overrides)` — one `AssumptionRange` per quantity
   (`assumptions.py`). TREND quantities (growth, tax rate) use median +
   min/max across periods and BLOCK on dispersion or collision. LEVEL
   quantities (cash flow, shares, net debt) take the latest period only.
   `net_debt` is always blocked until an override states a cash/debt policy —
   it is a judgement, not a derivation.
4. `build_wacc(ranges, market)` — bottom-up: Hamada-relevered industry beta,
   CAPM cost of equity + country risk premium, after-tax cost of debt,
   market-value weights. Every market input requires a source + as_of date
   in `data/market.json`; a "placeholder"/"todo"/"tbd" source blocks the run.
5. `build_dcf_inputs(ranges, market)` — rebuilds FCFF from CFO (a levered
   figure) so WACC discounting doesn't double-count interest; converts every
   quantity to millions from its **declared unit**; blocks on a placeholder
   discount rate.
6. `run_dcf` / `sensitivity_tornado` / `reverse_dcf` — pure arithmetic,
   `dcf_engine.py`, three consistency guards (terminal growth < discount
   rate, terminal growth <= 3%, FCFE never carries net debt).

## Commands that verify the system works

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
```

`.github/workflows/eval-gate.yml` runs `experiments/ch05_evaluation/02_ab_test.py`
against the golden dataset on PRs to main (separate from the capstone gates
above — it evaluates the ch05 retrieval work, not the valuation pipeline).

## Documented residual risk (deliberate scope boundaries)

Not a to-do — recorded so these are not mistaken for oversights:
- Share-count facts are exempt from unit-scale verification by name
  (`check_unit_matches_source` in `gates.py` skips any fact whose name
  contains "share"). Measured reason: Uber's operations statement caption
  declares two scales in one sentence — "(In millions, except share amounts
  which are reflected in thousands, and per share amounts)" — and comparing
  a share-count fact against the caption's primary (dollar) scale token
  would false-reject it. A share count is the divisor of the entire
  per-share result, so a wrong share unit still produces a wrong valuation
  with no gate catching it.
- `derive_tax_rate` (`assumptions.py`), when a filer does not state its tax
  rate as a percentage, computes it as provision for income taxes divided
  by pretax income, without checking that the two components share a unit
  scale. Not exercised today — both UBER_FY2024 and LYFT_FY2025 state the
  rate directly as a percentage, so this computed branch never runs for
  either — but latent for a future filer that does not state the rate.
