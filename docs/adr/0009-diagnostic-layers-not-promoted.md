# 0009. The diagnostic layers stay diagnostic; P6 does not become the base anchor

## Context

`src/aleph/valuation/` is 12,346 lines across 20 modules. Measured by import
reachability from `pipeline.py` and by line count:

```
 2,786  a valuation number depends on it
        pipeline, assumptions, contract, contract_adapter, bridge, wacc,
        dcf_engine
 3,191  diagnostic, imported BY pipeline.py and attached to ValuationRun
        accounting_quality (1,902), robustness (1,289)
 4,962  diagnostic, marked EXPERIMENTAL, computed by the CLI only
        evidence_resolution, evidence_depth, model_governance,
        sustainable_fcff, operating_model, market_expectations,
        driver_based_dcf
 1,407  wired to nothing; exercised only by their tests
        cfo_normalization, historical_fcff, normalization, sensitivity
```

77.4% of the package is diagnostic. Until 2026-09-10 all of it printed from
`scripts/run_valuation.py`, which had grown to 522 lines, and none of it was
mentioned in `README.md`. A reader could not tell which half of the output was
the valuation, and the repository looked like a larger claim than it makes.

The strongest candidate for promotion is P6, `sustainable_fcff.py`. The base
DCF anchors on ONE disclosed year's reconstructed FCFF; ISSUES.md #29 measures
that choice as the largest single lever in the model - larger than the
discount rate in every run tested. P6 exists precisely because that is
unsatisfying: it decomposes each period's FCFF into an operating component and
a working-capital contribution, and produces an evidence-based low / central /
high range instead of one year's number.

Measured, at the same prices and on the same day:

```
UBER_FY2024   LIVE 77.08   P6 low 43.61 / central 48.33 / high 77.08
LYFT_FY2025   LIVE 49.06   P6 low NOT_APPLICABLE / central 27.25 / high 49.06
```

P6-central is 37% below LIVE for Uber and 44% below for Lyft. P9, the
independent driver-based model, lands at 47.03 and 26.29 - within about 1.30
and 0.96 of P6-central. Two models built from different inputs converge, and
both sit far below the number the repository reports.

## Decision

Neither P6 nor any other diagnostic layer is promoted. The base DCF continues
to anchor on the latest disclosed reconstructed FCFF. The layers move to
`scripts/diagnose_valuation.py`, are documented in `README.md` under
"Diagnostic layers (not in the base DCF)", and keep changing no number.

## Alternative rejected

**Make P6-central the base anchor**, replacing the latest disclosed FCFF. The
convergence with P9 is a real argument and it was taken seriously.

Rejected because of what P6-central is MADE of. Its central case holds the
working-capital contribution at the historical MEDIAN of the disclosed
periods. A median across three years is a convention - it is not disclosed,
not derived from a gate-verified fact, and not defensible over any other
central-tendency choice. The pipeline's own provenance vocabulary grades it
`analyst_judgment`, the weakest grade it has, and `model_governance` already
reports `wc_cash_effect_over_revenue` as `L4_PLAUSIBLE_ANALYST_ASSUMPTION` and
flags it CONTRADICTED for UBER_FY2024.

So promotion would replace an anchor whose defect is KNOWN, NAMED and MEASURED
(one disclosed year, ISSUES.md #29, provenance `derived` from gate-verified
facts) with one whose defect is a convention chosen inside this repository. The
headline number would become more plausible and less evidenced at the same
time - and a number that sounds right and is not is the failure this project
is built against. The convergence of P6 and P9 does not fix that: both take
the same working-capital median as an input, so their agreement is partly the
agreement of one assumption with itself, which `model_governance` says in
those terms.

Two smaller reasons, neither decisive alone. LYFT_FY2025's P6 low case is a
negative FCFF the engine now refuses outright (ISSUES.md #38), so the promoted
range would have had an unreportable end for one of four filings. And the
cross-company comparability rule in `CLAUDE.md` requires any METHOD choice to
be held identical across filers; a median-based anchor is a method choice
whose behaviour differs by filer in a way a statutory "latest disclosed year"
does not.

**Also rejected: deleting the layers.** They are 9,560 lines of tested work
that produced this repository's most useful findings - the SBC decision
(#16), the 56% UBER_FY2024/FY2025 swing (#29), the negative-base guard (#38),
and the capex and current-debt gaps (#39, #40). None of those came from the
DCF. Deleting them to make the repository look tidier would delete the
evidence that the valuation is fragile.

## Consequence

`run_valuation.py` is 197 lines and prints only what a valuation number
depends on. Verified: its output plus `diagnose_valuation.py`'s output
reconstructs the pre-split output byte-for-byte for UBER_FY2024 and
LYFT_FY2025, 450 lines each.

The split is also what made the exception handling honest. Each layer sat
behind a bare `except Exception` printing "not assessed", because a
diagnostic must not take down a valuation. Measured: no layer raises on any
of the four valued filings, and no diagnostic module contains a single
`raise`. Those handlers caught nothing they were written for while being able
to swallow any bug in the layer - and one already had, a `TypeError` from
formatting `None` reported as an evidence failure (#38). They are now
`(DCFConsistencyError, BridgeError)`, the complete set of exception types
raised anywhere under `valuation/`, and anything else propagates. That is
affordable only because the valuation is a different command.

What would reopen this: a disclosure that makes the working-capital
contribution's recurrence an observed fact rather than a median. ISSUES.md #33
(P8) records that no filer discloses it today.

Decided by Asi, 2026-09-10.
