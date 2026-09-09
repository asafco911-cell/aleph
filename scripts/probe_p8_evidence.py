"""P8 - run the evidence-depth layer on the live filings. Read-only."""
import sys

import aleph.valuation.pipeline as pipeline
from aleph.valuation.evidence_depth import assess_evidence_depth

CASES = sys.argv[1:] or ["UBER_FY2024", "UBER_FY2025", "LYFT_FY2025", "DASH_FY2025"]

for doc in CASES:
    run = pipeline.value_filing(doc, None)
    r = assess_evidence_depth(run)
    print("=" * 82)
    print(f"{doc}   periods {r.oldest_period}..{r.newest_period}   "
          f"reduces_uncertainty={r.reduces_uncertainty.value}")
    print("=" * 82)

    print("\n  PERIOD SCORECARD:")
    print(f"    {'period':<8}{'type':<10}{'score':<24}{'CFO rep':>12}"
          f"{'CFO recon':>12}{'residual':>10}{'recon':>22}")
    for pe in r.period_evidence:
        cr = "n/a" if pe.cfo_reported is None else f"{pe.cfo_reported:,.0f}"
        cx = "n/a" if pe.cfo_reconstructed is None else f"{pe.cfo_reconstructed:,.0f}"
        rs = "n/a" if pe.residual is None else f"{pe.residual:,.0f}"
        print(f"    {pe.period:<8}{pe.period_type:<10}{pe.score.value:<24}"
              f"{cr:>12}{cx:>12}{rs:>10}{pe.reconciliation_status.value:>22}")

    print("\n  WORKING-CAPITAL BY SUBCATEGORY (USD millions of the period scale):")
    subs = sorted({k for pe in r.period_evidence for k in pe.wc_by_subcategory})
    print(f"    {'subcategory':<28}" + "".join(f"{pe.period:>12}" for pe in r.period_evidence))
    for s in subs:
        row = "".join(f"{pe.wc_by_subcategory.get(s, 0.0):>12,.0f}"
                      for pe in r.period_evidence)
        print(f"    {s:<28}{row}")
    for pe in r.period_evidence:
        if pe.unclassified_wc:
            print(f"    [{pe.period}] UNCLASSIFIED: {pe.unclassified_wc}")

    print("\n  P6 IMPACT (working-capital total, same lines, richer lineage):")
    print(f"    P6 wc_total : {r.p6_wc_total_by_period}")
    print(f"    P8 sum(sub) : {r.p8_wc_component_sum_by_period}")
    print(f"    agree       : {r.p6_p8_wc_agree}")

    print(f"\n  CAPEX EVIDENCE : {r.capex_evidence.status.value}")
    print(f"    disclosed lines: {r.capex_evidence.disclosed_lines}")
    print(f"    reason: {r.capex_evidence.reason}")

    print(f"\n  ONE-OFF EVIDENCE : {r.one_off_evidence.tier.value}")
    print(f"    explicit    : {r.one_off_evidence.explicit_items}")
    print(f"    corroborating: {r.one_off_evidence.corroborating_items}")
    print(f"    pattern     : {r.one_off_evidence.pattern_items}")
    print(f"    note: {r.one_off_evidence.note}")

    print(f"\n  CAPTION MAPPINGS ({len(r.caption_mappings)}):")
    for m in r.caption_mappings:
        sub = f"/{m.wc_subcategory.value}" if m.wc_subcategory else ""
        print(f"    [{m.category.value}{sub}] ({m.mapping_confidence.value}) "
              f"{m.source_caption}")

    print(f"\n  VERDICT REASON: {r.reduces_uncertainty_reason}")
    print()
