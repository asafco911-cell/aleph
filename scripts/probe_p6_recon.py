"""P6 - debug the CFO reconciliation: for one filing/period, show every
cash-flows fact and how the decomposition classifies it."""
import sys

import aleph.valuation.pipeline as pipeline
from aleph.infra.units import resolve_scale
from aleph.valuation.sustainable_fcff import (
    _is_wc, _norm, _NOT_A_RECON_LINE, _pick_net_income,
)

doc = sys.argv[1] if len(sys.argv) > 1 else "UBER_FY2024"
run = pipeline.value_filing(doc, None)
facts = run.facts

periods = sorted({f.period for f in facts
                  if f.source and f.source.target_key == "cash_flows" and f.period})
ni = _pick_net_income(facts)
print(f"net income (incl NCI) by period: {ni}")

for period in periods:
    print("\n" + "=" * 74)
    print(f"{doc}  {period}")
    print("=" * 74)
    cfo = wc = noncash = 0.0
    cfo_seen = False
    for f in sorted((f for f in facts
                     if f.source and f.source.target_key == "cash_flows"
                     and f.period == period),
                    key=lambda x: x.name):
        nm = _norm(f.name)
        s = resolve_scale(f.unit) or 0.0
        val = f.value * s
        low = nm.lower()
        excluded = any(rx.search(low) for rx in _NOT_A_RECON_LINE)
        is_ni = low.startswith("net income") or low.startswith("net loss")
        if "operating activities" in low:
            cfo, cfo_seen = val, True
            tag = "CFO SUBTOTAL"
        elif is_ni:
            tag = "NI (start)"
        elif excluded:
            tag = "excluded"
        elif _is_wc(nm):
            wc += val
            tag = f"WC   (run {wc:>10,.0f})"
        else:
            noncash += val
            tag = f"NON  (run {noncash:>10,.0f})"
        print(f"  {val:>13,.1f}  {tag:<26} {nm}")
    n = ni.get(period)
    if n is not None and cfo_seen:
        recon = n + noncash + wc
        print(f"\n  NI {n:,.0f} + noncash {noncash:,.0f} + WC {wc:,.0f} = {recon:,.0f}")
        print(f"  CFO reported = {cfo:,.0f}   residual = {cfo - recon:,.0f}")
