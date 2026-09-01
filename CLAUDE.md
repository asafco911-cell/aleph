# Aleph — Autonomous Multi-Document Financial Analyst

Capstone of a 14-chapter course (chapters 1-13 archived, read-only, under
`experiments/`). Owner: Asi, 23, Tel Aviv, building toward running a fund.
Status: capstone nearly done. Remaining work is correctness, then packaging
for GitHub. Two open tasks are tracked in the current session, not here:
the LYFT_FY2025 unit-scale bug and a silent net-debt clamp in WACC.

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
- A fix is not finished until a command proves it. Every change reports the
  command run and its output. `python scripts\run_valuation.py UBER_FY2024
  76.95` must still print `Value per share: 102.40` after any change to
  extraction, assumptions, bridge, wacc, or dcf_engine.

## Environment

Windows, VS Code, PowerShell, Python 3.14.3, venv inside `aleph/`, package
installed editable (`pip install -e .`), `src/` layout. `anthropic` SDK 1.0.0
removed `temperature`/`top_p`/`top_k` from `messages.create()` — passing them
raises `TypeError`. Model in use: `claude-sonnet-5`. `.env` holds
`ANTHROPIC_API_KEY`, gitignored. `data/aleph_cache.db` (SQLite, content-
addressed LLM cache) is gitignored. Never commit either.

The DCF engine's internal unit is MILLIONS. Filings declare their own unit —
Uber reports in millions, Lyft in thousands — and `bridge.py` is responsible
for converting every quantity from its declared unit to millions before it
reaches the engine. This is the intended contract, not a description of
current behaviour: see Task 2 in the working session for where it breaks.

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
8. Five gates check that what was copied is correct; one gate (`coverage`)
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
  extraction/    extractor.py (bounded LLM call), gates.py (5 validation +
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
python scripts\run_valuation.py UBER_FY2024 76.95   # must print Value per share: 102.40
python scripts\test_regression.py                    # gate over cached extraction targets, exit(1) on shortfall
python scripts\test_gates.py
python scripts\test_dcf_engine.py
python scripts\test_schemas.py
python scripts\test_sections.py
python scripts\test_multicompany.py
```

`.github/workflows/eval-gate.yml` runs `experiments/ch05_evaluation/02_ab_test.py`
against the golden dataset on PRs to main (separate from the capstone gates
above — it evaluates the ch05 retrieval work, not the valuation pipeline).

## Known open issues (see ISSUES.md for full detail)

- #13: dispersion limit (`MAX_RELATIVE_SPREAD = 1.0` in `assumptions.py`) is
  a single global ratio; scale-dependent for rate quantities near zero.
- #12: column detection is note-scoped, not table-scoped (year columns from
  one table can misapply to a same-note segment table with matching cell count).
- #11: BM25 tokenisation of typographic apostrophes is unmeasured.
- #10: section ordering only enforces `page >= floor`, not offset, within a
  shared page.

Found this session, not yet numbered in ISSUES.md:
- `data/market.json` UBER_FY2024 `country_risk_premium`: the rationale opens
  "ASSUMED ZERO" but the value is 0.0064, and it cites the Note 13 geographic
  split (US 48% / UK 19% / other 32%) while the pipeline now selects the
  more granular Note 2 split (US&CAN 54%). A committed file whose rationale
  contradicts its own value.
- `data/market.json`: `discount_rate` 0.09 with source "integration test" is
  still present in both `UBER_FY2024` and `LYFT_FY2025` blocks. Determine
  whether the loader requires the key; if not, delete it from both.
- Revenue now has two independent sources (`statement:operations` total
  revenue, and the Total row in the segment note). They agree for Uber. If
  they ever disagree, no gate would see it. Candidate for a cross-source
  consistency check.
- LYFT_FY2025 `revenue_growth` is an override at 9.2%, which is TOTAL, not
  organic: it contains roughly half a year of Freenow and one quarter of
  TBR. Reported Q2 2026 growth was 16.1% and sell-side consensus for FY2026
  is about 15%. Both are deliberately excluded from the base case because
  UBER_FY2024 derives its growth from the filing; importing a consensus
  forecast for one company and not the other would break comparability.
  They belong in sensitivity.

Documented residual risk from the unit-scale fix (not a to-do — deliberate
scope boundaries, recorded so they are not mistaken for oversights):
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

## Repository hygiene

Checked before this repo is made public (`git log --all --full-history --
.env` and `git ls-files | Select-String "aleph_cache.db|\.env|\.pdf"`):

- `.env` was never committed. Clean.
- `data/uber_10k.pdf` (1.77 MB) IS tracked in git, added in the chapter 2
  commit (`24454c7`), before `data/*.pdf` existed in `.gitignore`. The
  ignore rule does not retroactively untrack it.
- `experiments/ch12_production/aleph_cache.db` (20 KB) IS tracked in git,
  added in the chapter 12 commit (`a3a9be5`). Not covered by the
  `data/aleph_cache.db` ignore rule, which only names the path under `data/`.

Neither contains a secret, but both are exactly the kind of file this
project's own gitignore says should never be committed, and a public repo
should not ship a full 10-K PDF or a cache database as tracked history. This
needs Asi's decision before any history rewrite — untracking going forward
(`git rm --cached`) is not the same as removing them from history, and
rewriting history is not something to do without being asked.
