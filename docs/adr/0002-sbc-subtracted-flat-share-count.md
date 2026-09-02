# 0002. Stock-based compensation is subtracted from FCFF; the share count stays flat

## Context

FCFF is rebuilt from CFO. Reported CFO already treats stock-based
compensation as a non-cash add-back to net income. Whether to also subtract
it as a real cash cost, and whether to separately model the future dilution
it funds, changes both the DCF's base_cash_flow input and, through
shares_outstanding, the per-share result.

## Decision

SBC is subtracted from FCFF at full value - it is already tax-affected
inside net income, so no further tax adjustment applies. Diluted share
count is held flat: not adjusted for the future dilution SBC funds.

## Alternative rejected

Leaving SBC inside FCFF (not subtracting it) and instead modelling the
share dilution it funds in the share count; and, considered and rejected as
double-counting, doing both - subtracting SBC from cash flow and also
modelling the dilution it funds.

## What settled it

SBC is a large, direct share of free cash flow: 24.6% of Uber's pre-SBC
FCFF and 28.5% of Lyft's (UBER_FY2024, LYFT_FY2025), verifiable from each
filer's FCFF reconstruction. Diluted share counts, by contrast, grew at a
compound 0.7% to 5.8% a year within each filing's own disclosed history,
first period to last (UBER_FY2024 4.35%, UBER_FY2025 0.66%, LYFT_FY2025
4.11%, DASH_FY2025 5.78%) - the rate a ten-year DCF should care about, not
one year's noise. Year over year the swings are wider still, -1.4% to 9.5%
across the same four filers, including one buyback year where Uber's count
fell outright. Subtracting SBC in cash terms captures most of its economic
cost directly, through the larger channel; modelling dilution on top would
double-count that same cost through a second, smaller one. See #16.
