"""P6 - run the sustainable-FCFF framework on the live filings and print the
decomposition, regime, range and the sustainable-anchor scenario valuation.
Read-only. The base DCF is not touched.
"""
import sys

import aleph.valuation.pipeline as pipeline
from aleph.valuation.sustainable_fcff import (
    assess_sustainable_fcff,
    sustainable_scenario_valuation,
)

CASES = sys.argv[1:] or [
    "UBER_FY2024:76.95", "UBER_FY2025:79.00",
    "LYFT_FY2025:17.35", "DASH_FY2025:215.00",
]

for case in CASES:
    doc, _, px = case.partition(":")
    price = float(px) if px else None
    run = pipeline.value_filing(doc, price)
    s = assess_sustainable_fcff(run)
    print("=" * 78)
    print(f"{doc}   base DCF point value = {run.result.value_per_share:,.2f}/share")
    print("=" * 78)
    print(f"  status : {s.status.value}")
    print(f"  regime : {s.regime.value}")
    print(f"  reconciliation_ok={s.reconciliation_ok}  double_count_ok={s.double_count_ok}")
    print(f"\n  per-period decomposition (USD millions):")
    print(f"    {'period':<8} {'CFO':>10} {'opcash_bWC':>12} {'WC_total':>10} "
          f"{'i*(1-t)':>9} {'capex':>8} {'SBC':>8} {'FCFF':>10} {'FCFF_exWC':>11} "
          f"{'recon':>6} {'resid':>8}")
    for p in s.periods:
        print(f"    {p.period:<8} {p.cfo:>10,.0f} {p.operating_cash_before_wc:>12,.0f} "
              f"{p.working_capital_total:>10,.0f} {p.interest_tax_shield:>9,.0f} "
              f"{p.capex:>8,.0f} {p.sbc:>8,.0f} {p.reconstructed_fcff:>10,.0f} "
              f"{p.fcff_ex_working_capital:>11,.0f} {str(p.reconciles):>6} "
              f"{p.residual:>8,.0f}")
    print(f"\n  latest reconstructed FCFF ({s.latest_period}) = "
          f"{s.latest_reconstructed_fcff:,.0f}")
    if s.status.value == "SUPPORTED_RANGE":
        print(f"  SUSTAINABLE FCFF   low={s.low:,.0f}   central={s.central:,.0f}   "
              f"high={s.high:,.0f}")
        print(f"    {s.low_basis}")
        print(f"    {s.central_basis}")
        print(f"    {s.high_basis}")
    for r in s.reasons:
        print(f"    - {r}")
    print(f"\n  sustainable-anchor scenario valuation (all else fixed):")
    for row in sustainable_scenario_valuation(run.bridged.inputs, s):
        v = "REJECTED" if row.value_per_share is None else f"{row.value_per_share:>9,.2f}"
        d = "" if row.delta_vs_current is None else f"  (delta {row.delta_vs_current:+,.2f})"
        print(f"    {row.label:<20} FCFF {row.base_fcff:>10,.0f}  ->  {v}/share{d}")
    print()
