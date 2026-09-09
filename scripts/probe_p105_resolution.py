"""P10.5 - evidence resolution / disclosure-boundary audit. Read-only."""
import sys

import aleph.valuation.pipeline as pipeline
from aleph.valuation.evidence_resolution import assess_evidence_resolution

CASES = sys.argv[1:] or ["UBER_FY2024", "UBER_FY2025", "LYFT_FY2025", "DASH_FY2025"]

for doc in CASES:
    run = pipeline.value_filing(doc, None)
    r = assess_evidence_resolution(run)
    print("=" * 96)
    print(f"{doc}   ->   {r.verdict}   [{r.architectural_decision}]")
    print("=" * 96)

    print("\n-- A. WORKING-CAPITAL EVIDENCE MAP (latest period) --")
    latest = max((e.period for e in r.wc_map), default=None)
    for e in r.wc_map:
        if e.period != latest:
            continue
        print(f"  {e.caption:<44} {e.signed_amount:>12,.0f}  {e.cash_flow_direction:<8} "
              f"{e.normalized_category:<20} {e.recurrence_evidence.value:<22} {e.disclosure_status.value}")

    print("\n-- B. PERSISTENCE --")
    for p in r.persistence:
        print(f"  {p.name:<44} latest={p.latest:>10,.0f} prior={str(p.prior):>10} "
              f"median={p.median:>10,.0f}  sign={p.sign_consistency}  magstab={p.magnitude_stability}  "
              f"-> {p.classification.value}")
        print(f"      rule: {p.rule}")
        print(f"      rev-scaled: {p.revenue_scaled_history}")

    print("\n-- C. INSURANCE FLOAT AUDIT --")
    i = r.insurance
    print(f"  changes_by_period={i.changes_by_period}  sign_consistency={i.sign_consistency} "
          f"mag_stability={i.magnitude_stability}")
    print(f"  mechanism_disclosed={i.mechanism_disclosed} rollforward_disclosed={i.rollforward_disclosed}")
    print(f"  VERDICT: {i.verdict.value}")
    print(f"  {i.rationale}")

    print("\n-- CFO ATTRIBUTION (latest period) --")
    for ca in r.cfo_attribution:
        if ca.period != latest:
            continue
        print(f"  period {ca.period}  cfo={ca.cfo}  majority={ca.majority_categories}  residual={ca.residual}")
        for row in ca.rows:
            print(f"    {row.category:<22} signed={row.signed_amount:>10,.0f}  "
                  f"rev%={row.revenue_scaled}  {row.recurrence.value}")

    print("\n-- D. WC LEVEL HYPOTHESES --")
    for h in r.wc_level_hypotheses:
        print(f"  [{h.status.value:<10}] {h.hypothesis}")
        for s in h.supporting_evidence:
            print(f"       + {s}")
        for c in h.contradicting_evidence:
            print(f"       - {c}")

    print("\n-- E. SEQUENTIAL BRIDGE LIVE -> P9 --")
    b = r.bridge
    if b.live_fcff is None:
        print(f"  n/a: {b.note}")
    else:
        for s in b.steps:
            print(f"  [{s.order}] {s.name:<52} start={s.start:>10,.0f} d={s.delta:>+11,.0f} "
                  f"end={s.end:>10,.0f}  ({s.kind})")
            print(f"        {s.note}")
        print(f"  residual={b.residual}  arithmetically_reconciled={b.arithmetically_reconciled}")
        print(f"  economically_explained={b.economically_explained.value}  dominant={b.dominant_cause}  "
              f"methodology%={b.methodology_pct_of_fcff}")

    print("\n-- F. OPERATING BASIS WITHOUT WC --")
    ob = r.operating_basis_without_wc
    print(f"  status={ob.get('status')}")
    if ob.get("status") == "CLASSIFIED":
        print(f"  fcff_ex_wc_history={ob['fcff_ex_wc_history']}  n_nonpositive={ob['n_nonpositive']}")
        for h in ob["hypotheses"]:
            print(f"    [{h.status.value:<10}] {h.hypothesis}")
        print(f"  verdict: {ob['verdict']}")
        print(f"  anchor: {ob['deterministic_anchor']}")

    print("\n-- G. TAX EVIDENCE --")
    t = r.tax
    print(f"  classification={t.classification.value}  normalization={t.normalization_verdict.value}")
    print(f"  effective_by_period={t.effective_by_period}  cash_taxes_paid_disclosed={t.cash_taxes_paid_disclosed}")
    print(f"  deferred_tax_by_period={t.deferred_tax_by_period}  normalized_rate_derivable={t.normalized_rate_derivable}")
    print(f"  {t.rationale}")

    print("\n-- (epistemic tags) --")
    for tg in r.epistemic_tags:
        print(f"  [{tg.epistemic_class.value:<24}] {tg.item}")

    print("\n-- H. DISCLOSURE BOUNDARIES --")
    for db in r.boundaries:
        print(f"  [{db.verdict.value:<18}] {db.question}")
        print(f"       ruled out: {db.hypotheses_ruled_out}")
        print(f"       remaining: {db.hypotheses_remaining}")

    print("\n-- I/J. MODEL CONSEQUENCE / DECISION --")
    for k, v in r.model_consequence.items():
        print(f"  {k}: {v}")
    print(f"  ARCHITECTURAL DECISION: {r.architectural_decision}")
    for n in r.notes:
        print(f"  note: {n}")
    print()
