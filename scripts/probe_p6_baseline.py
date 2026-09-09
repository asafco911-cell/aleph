"""P6 Phase 0 - forensic read-only inventory of every extracted fact that
could bear on sustainable FCFF. Nothing here derives, adjusts, or values.
It dumps the ACTUAL cached facts per filing, grouped by statement target,
so the inventory is measured, not assumed.
"""
import sys
from collections import defaultdict

import aleph.valuation.pipeline as pipeline
from aleph.valuation.bridge import _per_period_fcff
from aleph.valuation.assumptions import derive_all

DOCS = sys.argv[1:] or ["UBER_FY2024", "UBER_FY2025", "LYFT_FY2025", "DASH_FY2025"]

# Keywords for the line items P6 Phase 0 must inventory.
BUCKETS = {
    "CFO":                 ("net cash provided by operating", "cash provided by operating",
                            "operating activities"),
    "capex":               ("purchases of property", "property and equipment"),
    "SBC":                 ("stock-based compensation",),
    "D&A":                 ("depreciation", "amortization"),
    "deferred_tax":        ("deferred income tax", "deferred tax"),
    "unrealized":          ("unrealized",),
    "impairment":          ("impairment",),
    "gain_loss_sale":      ("gain", "loss on", "divestiture", "sale of"),
    "wc_receivables":      ("receivable",),
    "wc_payables":         ("payable",),
    "wc_prepaid":          ("prepaid",),
    "wc_accrued":          ("accrued",),
    "wc_deferred_rev":     ("deferred revenue", "unearned"),
    "wc_inventory":        ("inventor",),
    "wc_other_assets":     ("other assets", "operating assets"),
    "wc_other_liab":       ("other liabilities", "operating liabilities"),
    "wc_generic_change":   ("changes in", "change in assets"),
    "revenue":             ("total revenue", "revenue"),
    "interest_expense":    ("interest expense",),
    "income_from_ops":     ("income from operations", "loss from operations",
                            "operating income"),
    "net_income":          ("net income", "net loss"),
    "pretax":              ("before income tax", "before provision"),
    "tax_provision":       ("provision for income tax",),
    "tax_rate_pct":        ("effective", "tax rate"),
    "R&D":                 ("research and development",),
    "total_costs":         ("total costs and expenses",),
    "cash_balance":        ("cash, cash equivalents", "end of period", "beginning of period"),
    "lt_debt":             ("long-term debt",),
    "st_investments":      ("short-term investment",),
    "restricted_cash":     ("restricted cash",),
    "total_assets":        ("total assets",),
    "total_liabilities":   ("total liabilities",),
    "total_equity":        ("stockholders' equity", "shareholders' equity"),
}


def classify(fname):
    low = fname.lower()
    hits = [b for b, kws in BUCKETS.items() if any(k in low for k in kws)]
    return hits


for doc in DOCS:
    print("=" * 78)
    print(doc)
    print("=" * 78)
    rec = pipeline.load_record(doc)
    facts, rejected = pipeline.extract_facts(rec)
    print(f"{len(facts)} accepted facts, {len(rejected)} rejected\n")

    by_target = defaultdict(list)
    for f in facts:
        tk = f.source.target_key if f.source else "?"
        by_target[tk].append(f)

    for tk in sorted(by_target):
        print(f"--- target: {tk}  ({len(by_target[tk])} facts)")
        for f in sorted(by_target[tk], key=lambda x: (x.name, x.period or "")):
            tags = classify(f.name)
            tagstr = ("  <" + ",".join(tags) + ">") if tags else ""
            print(f"    {f.period or '(no period)':<8} {f.value:>16,.2f} {f.unit:<16} "
                  f"{f.name}{tagstr}")
        print()

    # what the live reconstruction actually uses, per period
    overrides = pipeline.load_overrides(doc)
    ranges = {a.name: a for a in derive_all(facts, overrides)}
    tax_r = ranges.get("effective_tax_rate")
    tax = None
    if tax_r is not None and tax_r.base is not None:
        tax = tax_r.base / 100.0 if tax_r.base > 1 else tax_r.base
    print(f"  effective_tax_rate range: status={getattr(tax_r,'status',None)} "
          f"base={getattr(tax_r,'base',None)} unit={getattr(tax_r,'unit',None)}")
    if tax is not None:
        fbp, note = _per_period_fcff(ranges, tax)
        print(f"  _per_period_fcff -> {fbp}")
        print(f"  note: {note or '(none)'}")
    for nm in ("operating_cash_flow", "capex", "stock_based_compensation",
               "interest_expense"):
        r = ranges.get(nm)
        if r is None:
            print(f"  {nm}: MISSING")
            continue
        obs = [(o.period, round(o.value, 1), o.unit) for o in r.observations]
        print(f"  {nm}: status={r.status} unit={r.unit} obs={obs}")
    print()
