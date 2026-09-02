# 0001. The industry beta is held identical across every filer

## Context

Comparing filers requires a discount rate; CAPM needs a beta. A beta can be
tuned per company (a regression against that stock's own trading history) or
held at one industry-wide level, relevered per company's own capital
structure via Hamada. Under the industry-beta approach, LYFT_FY2025's
bottom-up WACC (8.10%) comes out below UBER_FY2024's (8.72%) - a ranking
that looks backwards if Lyft is assumed the riskier business.

## Decision

The unlevered industry beta (0.81, Damodaran Business and Consumer Services)
is held identical across every filer valued, relevered per company via
Hamada using that company's own capital structure. No filer's beta is
adjusted to move its value closer to its market price.

## Alternative rejected

A per-company regression beta - Lyft's own trading-volatility-derived beta -
as the base for its cost of equity, in place of the shared industry beta.

## What settled it

At $17.35, Lyft's market price sits 55% BELOW the low end of its own tested
discount-rate band ($38.57 to $57.85) - no discount rate inside the range
tested reaches the market price. Bending the beta, or replacing it with a
stock-specific regression beta chosen to close that gap, would have
concealed that the disagreement between model and market is about cash
flow, not the price of systematic risk. See #16, #25.
