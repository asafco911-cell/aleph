"""P10 - model governance / arbitration on the live filings. Read-only."""
import sys

import aleph.valuation.pipeline as pipeline
from aleph.valuation.model_governance import assess_model_governance

CASES = sys.argv[1:] or ["UBER_FY2024", "UBER_FY2025", "LYFT_FY2025", "DASH_FY2025"]

for doc in CASES:
    run = pipeline.value_filing(doc, None)
    g = assess_model_governance(run)
    print("=" * 88)
    print(g.headline)
    print("=" * 88)
    print(f"  LIVE {g.live_value:,.2f}   P6 {g.p6_low}/{g.p6_central}/{g.p6_high}   "
          f"P9 bear/base/bull {g.p9_bear}/{g.p9_base}/{g.p9_bull}")
    print(f"\n  RECONCILIATION LIVE -> P9 (sequential counterfactual, order-dependent):")
    for s in g.reconciliation:
        dv = "n/a" if s.delta_value is None else f"{s.delta_value:+,.2f}"
        fv = "n/a" if s.fcff_after is None else f"{s.fcff_after:,.0f}"
        vv = "n/a" if s.value_after is None else f"{s.value_after:,.2f}"
        print(f"    [{s.order}] {s.name:<44} FCFF {fv:>10}  value {vv:>9}  d {dv}")
        print(f"          {s.change}")
    print(f"\n  SBC AUDIT: double_count = {g.sbc_audit['double_count']}")
    print(f"    {g.sbc_audit['verdict']}")
    print(f"\n  TAX AUDIT: {g.tax_audit['classification']}")
    print(f"    disclosed effective rate %: {g.tax_audit['disclosed_effective_rate_pct']}")
    print(f"    {g.tax_audit['verdict']}")
    print(f"\n  BASE-CASE ASSUMPTION REGISTER:")
    print(f"    {'variable':<28}{'value':>9}{'evidence':>34}{'sens':>9}{'contradiction':>36}")
    for e in g.register:
        v = "n/a" if e.value is None else f"{e.value:+.3f}"
        s = "n/a" if e.value_sensitivity is None else f"{e.value_sensitivity:.2f}"
        print(f"    {e.variable:<28}{v:>9}{e.evidence_level.value:>34}{s:>9}  "
              f"{e.contradiction.value}")
        print(f"        [{e.evidence_band.value} evidence x {e.sensitivity_band.value} "
              f"sensitivity]  independently_supported={e.independently_supported}")
        if e.contradiction.value == "ASSUMPTION_CONTRADICTED_BY_EVIDENCE":
            print(f"        !! {e.contradiction_detail}")
    print(f"\n  DOMINANT ASSUMPTIONS (high sensitivity first):")
    for d in g.dominant_assumptions:
        print(f"    - {d}")
    print(f"\n  MODEL APPLICABILITY:")
    for m in g.applicability:
        print(f"    {m.model}")
        print(f"        value={m.value_per_share}  applicability={m.applicability.value}")
        print(f"        dominant assumption: {m.dominant_assumption}")
        print(f"        evidence: {m.evidence_basis}")
        for lim in m.known_limitations:
            print(f"        limitation: {lim}")
    print(f"\n  ARBITRATION: {g.arbitration.value}")
    for r in g.arbitration_reasons:
        print(f"    - {r}")
    print()
