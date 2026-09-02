# 0004. Net debt blocks until an analyst writes a policy and a reason

## Context

net_debt is assembled from several balance-sheet line items, each
individually extracted and gate-verified. Whether Python can safely combine
them automatically, or whether an analyst must state the policy explicitly,
determines whether the equity bridge and WACC's capital structure can run
without a human decision.

## Decision

net_debt always blocks - regardless of how complete the extracted
balance-sheet facts look - until an analyst records a policy and a written
rationale as an override in data/overrides.json.

## Alternative rejected

Deriving net_debt automatically from the extracted balance-sheet facts by
matching component line items on their wording.

## What settled it

The wording is not stable even within one filer's own history, let alone
across filers. DoorDash's FY2024 10-K prints "Short-term marketable
securities" for an account its FY2025 10-K calls "Short-term investments" -
the same account, the same $1,322 FY2024 comparative value in both filings,
two different captions. Uber discloses restricted cash as two separate
lines (current and non-current) that a single-line query would miss
entirely. No fixed set of component queries survives contact with a second
filer, or even a second year of the same filer. See #26.
