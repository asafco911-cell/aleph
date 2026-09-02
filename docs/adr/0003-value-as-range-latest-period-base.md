# 0003. Value is reported as a range across disclosed periods, latest period labelled as the base

## Context

The DCF needs one base_cash_flow figure to project forward. A filing
discloses the components of FCFF (CFO, capex, interest, SBC) for several
periods, so the analyst must choose whether to anchor on the single most
recent period, an average across periods, or some other summary - and
whether to report the result as one point or a range.

## Decision

Value is reported as a range spanning the FCFF each disclosed, reconcilable
period implies (the tornado bound on base_cash_flow), with the single most
recent period's FCFF labelled as the base case ("Latest-period basis").

## Alternative rejected

A multi-year average of base_cash_flow as the single point fed into the
DCF, instead of the latest period alone.

## What settled it

MEASURED, not assumed. Averaging amplified the instability it was meant to
smooth. UBER_FY2024 and UBER_FY2025 value the same company, at the same
$76.95 market price, one filing year apart: 77.08 on a latest-period basis
versus 119.95 - a 56% move. On a three-year-average basis the same two runs
move from 30.22 to 75.89 - a 151% move - because Uber's four-year FCFF
series (-957 in 2022, 1,927 in 2023, 5,512 in 2024, 8,285 in 2025) means
-957 leaves the averaging window and +8,285 enters it between the two
filings: a 9,242 swing across the window, against a 2,773 swing in the
latest single point alone. See #29.
