"""P9 - run the driver-based operating model + DCF on the live filings.
Read-only. The base DCF is not touched.
"""
import sys

import aleph.valuation.pipeline as pipeline
from aleph.valuation.driver_based_dcf import driver_based_dcf
from aleph.valuation.operating_model import build_scenarios, historical_drivers

CASES = sys.argv[1:] or ["UBER_FY2024", "UBER_FY2025", "LYFT_FY2025", "DASH_FY2025"]

for doc in CASES:
    run = pipeline.value_filing(doc, None)
    print("=" * 84)
    print(f"{doc}   live DCF = {run.result.value_per_share:,.2f}/share   "
          f"WACC {run.wacc.wacc:.2%}   g_T {run.bridged.inputs.terminal_growth:.1%}")
    print("=" * 84)
    print("  HISTORICAL DRIVERS:")
    for d in historical_drivers(run):
        vals = ", ".join(
            (f"{v:+.1%}" if d.unit == "decimal" else f"{v:,.0f}") for v in d.values)
        med = ("n/a" if d.median is None else
               (f"{d.median:+.1%}" if d.unit == "decimal" else f"{d.median:,.0f}"))
        print(f"    {d.name:<28} [{d.shape.value:<22}] {d.periods} = {vals}   "
              f"median {med}")

    scen = build_scenarios(run)
    print("\n  SCENARIOS:")
    for name, f in scen.items():
        print(f"\n    --- {name}  support={f.support.value}  "
              f"unsupported={list(f.unsupported_drivers)}")
        if not f.years:
            for n in f.notes:
                print(f"        {n}")
            continue
        print(f"        base FCFF (yr0) = {f.base_fcff:,.0f}   base revenue "
              f"{f.base_revenue:,.0f} ({f.base_period})")
        print(f"        {'yr':<4}{'revenue':>12}{'g':>8}{'op margin':>11}"
              f"{'NOPAT':>10}{'+D&A':>9}{'+WC':>10}{'-capex':>9}{'-SBC':>9}{'FCFF':>11}")
        for y in f.years:
            print(f"        {y.year:<4}{y.revenue:>12,.0f}{y.revenue_growth:>8.1%}"
                  f"{(y.operating_margin or 0):>11.1%}{(y.nopat or 0):>10,.0f}"
                  f"{y.dna:>9,.0f}{y.wc_cash_effect:>10,.0f}{y.capex:>9,.0f}"
                  f"{y.sbc:>9,.0f}{(y.fcff or 0):>11,.0f}")
        r = driver_based_dcf(
            f, discount_rate=run.wacc.wacc,
            terminal_growth=run.bridged.inputs.terminal_growth,
            net_debt=run.bridged.inputs.net_debt,
            shares_outstanding=run.bridged.inputs.shares_outstanding)
        v = "n/a" if r.value_per_share is None else f"{r.value_per_share:,.2f}"
        print(f"        DRIVER DCF: {r.status.value}  value/share = {v}   ({r.note})")

    # comparison
    base = scen["BASE"]
    rd = driver_based_dcf(
        base, discount_rate=run.wacc.wacc,
        terminal_growth=run.bridged.inputs.terminal_growth,
        net_debt=run.bridged.inputs.net_debt,
        shares_outstanding=run.bridged.inputs.shares_outstanding)
    try:
        from aleph.valuation.sustainable_fcff import (
            assess_sustainable_fcff, sustainable_scenario_valuation)
        s = assess_sustainable_fcff(run)
        sv = sustainable_scenario_valuation(run.bridged.inputs, s)
        srow = {x.label: x.value_per_share for x in sv}
        sust = (f"low {srow.get('sustainable_low')} / central "
                f"{srow.get('sustainable_central')} / high {srow.get('sustainable_high')}"
                if s.status.value == "SUPPORTED_RANGE" else s.status.value)
    except Exception as exc:  # noqa: BLE001
        sust = f"(sustainable layer error: {exc})"
    print(f"\n  VALUATION PATHS:")
    print(f"    A. LIVE (latest FCFF)      : {run.result.value_per_share:,.2f}")
    print(f"    B. P6 SUSTAINABLE          : {sust}")
    print(f"    C. P9 DRIVER (BASE)        : "
          f"{'n/a - ' + rd.status.value if rd.value_per_share is None else f'{rd.value_per_share:,.2f}'}")
    print()
