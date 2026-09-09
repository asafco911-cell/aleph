"""P7 - run the market-implied expectations layer on the live filings.
Read-only. The base DCF is not touched.
"""
import sys

import aleph.valuation.pipeline as pipeline
from aleph.valuation.market_expectations import assess_market_expectations

CASES = sys.argv[1:] or [
    "UBER_FY2024:76.95", "UBER_FY2025:79.00",
    "LYFT_FY2025:17.35", "DASH_FY2025:215.00",
]

for case in CASES:
    doc, _, px = case.partition(":")
    price = float(px)
    run = pipeline.value_filing(doc, price)
    me = assess_market_expectations(run)
    print("=" * 80)
    print(f"{doc}   market {price:,.2f}   forward DCF {run.result.value_per_share:,.2f}")
    print("=" * 80)
    print(f"  WACC {me.wacc:.2%}   terminal g {me.terminal_growth:.1%}   "
          f"base FCFF {me.base_fcff:,.0f}   n={me.forecast_years}")
    iug, ibf = me.implied_uniform_growth, me.implied_base_fcff
    print(f"  IMPLIED UNIFORM GROWTH : "
          f"{iug.value:.2%}" if iug.value is not None else
          "  IMPLIED UNIFORM GROWTH : NOT_SOLVABLE")
    print(f"  IMPLIED BASE FCFF      : "
          f"{ibf.value:,.0f}  [{ibf.solvability.value}]" if ibf.value is not None else
          f"  IMPLIED BASE FCFF      : {ibf.solvability.value}")
    print(f"  sustainable FCFF       : {me.sustainable_status}  "
          f"low={me.sustainable_fcff_low}  central={me.sustainable_fcff_central}  "
          f"high={me.sustainable_fcff_high}")
    print(f"\n  ANCHOR SCENARIOS (implied uniform growth per FCFF anchor):")
    for a in me.anchor_scenarios:
        g = "NOT_SOLVABLE" if a.implied_uniform_growth is None else f"{a.implied_uniform_growth:+.2%}"
        d = "" if a.delta_vs_latest_anchor is None else f"  (delta vs latest {a.delta_vs_latest_anchor:+.2%})"
        f = "n/a" if a.anchor_fcff is None else f"{a.anchor_fcff:,.0f}"
        print(f"    {a.anchor_label:<20} FCFF {f:>10}  ->  implied g {g}{d}")
    print(f"\n  WACC SENSITIVITY of implied uniform growth:")
    for r in me.wacc_sensitivity:
        g = "NOT_SOLVABLE" if r.implied_uniform_growth is None else f"{r.implied_uniform_growth:+.2%}"
        print(f"    {r.label:<6} WACC {r.param_value:.2%}  ->  implied g {g}")
    print(f"\n  TERMINAL-GROWTH SENSITIVITY of implied uniform growth:")
    for r in me.terminal_growth_sensitivity:
        g = "NOT_SOLVABLE" if r.implied_uniform_growth is None else f"{r.implied_uniform_growth:+.2%}"
        print(f"    {r.label:<6} g_T {r.param_value:.2%}  ->  implied g {g}")
    print(f"\n  EXPECTATIONS GAP:")
    for gp in me.gaps:
        print(f"    {gp.quantity:<22} implied={gp.market_implied}")
        print(f"      historical : {gp.historical_evidence}")
        print(f"      DCF now    : {gp.current_dcf_assumption}")
        print(f"      sustainable: {gp.sustainable_scenario}   [{gp.direction}]")
    print(f"\n  VS EVIDENCE : {me.vs_evidence.value}")
    print(f"  LEVEL       : {me.level.value}")
    print(f"  APPLICABILITY: {me.applicability}")
    print(f"\n  INTERPRETATION:\n    {me.interpretation}")
    print()
