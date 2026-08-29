"""Run the full pipeline: extract, derive, bridge, value.

Blocked assumptions stop the run. A valuation built on a smoothed-over blocked
input looks exactly like one built on evidence.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path("src/aleph/valuation")))  # engine imports by bare name

from aleph.extraction import extract
from aleph.schemas import DocumentRecord
from aleph.schemas.valuation import MarketAssumption, Override
from aleph.valuation import derive_all
from aleph.valuation.bridge import BridgeError, build_dcf_inputs
from aleph.valuation import build_wacc

from dcf_engine import DCFConsistencyError, reverse_dcf, run_dcf, sensitivity_tornado

TARGETS = [
    ("note:13", "Extract revenue by reportable segment for each year."),
    ("note:11", "Extract the effective tax rate and the provision for income taxes."),
    ("statement:cash_flows",
     "Extract net cash provided by operating activities and purchases of "
     "property and equipment."),
    ("statement:operations",
     "Extract diluted weighted-average shares outstanding, interest expense, "
     "and net income attributable to Uber Technologies, Inc."),
    ("statement:balance_sheet",
     "Extract cash and cash equivalents, short-term investments, restricted "
     "cash, and long-term debt net of current portion."),
    ("note:13", "Extract revenue by geography."),
]

doc_id = sys.argv[1]
market_price = float(sys.argv[2]) if len(sys.argv) > 2 else None

record = next(
    DocumentRecord(**r)
    for r in json.loads(Path("data/manifest.json").read_text(encoding="utf-8"))
    if r["doc_id"] == doc_id
)

facts = []
for target, question in TARGETS:
    accepted, rejected, _ = extract(record, target, question)
    if rejected:
        print(f"  WARNING {target}: {len(rejected)} facts rejected by gates")
    facts.extend(accepted)

overrides = {
    name: Override(**payload)
    for name, payload in json.loads(
        Path("data/overrides.json").read_text(encoding="utf-8")
    ).get(doc_id, {}).items()
}
market = {
    name: MarketAssumption(**payload)
    for name, payload in json.loads(
        Path("data/market.json").read_text(encoding="utf-8")
    ).get(doc_id, {}).items()
}

ranges = {a.name: a for a in derive_all(facts, overrides)}
blocked = [a.name for a in ranges.values() if a.status == "blocked"]
if blocked:
    print(f"\nBLOCKED: {blocked}")
    for name in blocked:
        print(f"  {name}: {ranges[name].rationale}")
    sys.exit(1)

try:
    wacc = build_wacc(ranges, market)
except BridgeError as exc:
    print(f"\nWACC NOT BUILT: {exc}")
    wacc = None

if wacc:
    print("\n" + "=" * 74)
    print("WACC (bottom-up)")
    print("=" * 74)
    for note in wacc.notes:
        print(f"  {note}")

    market["discount_rate"] = MarketAssumption(
        name="discount_rate", value=wacc.wacc, unit="decimal",
        as_of=market["risk_free_rate"].as_of, source="derived bottom-up",
        rationale=" | ".join(wacc.notes[:3]),
    )

    # Once the discount rate is derived, a hand-picked band around it is
    # arbitrary and hides the component actually driving it. Bounds are
    # recomputed by rerunning WACC at the beta bounds instead.
    beta_base = market["unlevered_industry_beta"].value
    beta_bounds = []
    for label, beta in (("low", beta_base * 0.75), ("high", beta_base * 1.45)):
        trial = dict(market)
        trial["unlevered_industry_beta"] = market["unlevered_industry_beta"].model_copy(
            update={"value": beta}
        )
        beta_bounds.append(build_wacc(ranges, trial).wacc)
    print(f"  WACC at beta {beta_base * 0.75:.2f} / {beta_base:.2f} / "
          f"{beta_base * 1.45:.2f}: {beta_bounds[0]:.2%} / {wacc.wacc:.2%} / "
          f"{beta_bounds[1]:.2%}")

try:
    bridged = build_dcf_inputs(ranges, market)
except BridgeError as exc:
    print(f"\nBRIDGE FAILED: {exc}")
    sys.exit(1)
if wacc:
    bridged.tornado_ranges["discount_rate"] = (beta_bounds[0], beta_bounds[1])
    
print("\n" + "=" * 74)
print("BRIDGE NOTES")
print("=" * 74)
for note in bridged.notes:
    print(f"  {note}")

print("\n" + "=" * 74)
print("ASSUMPTIONS")
print("=" * 74)
for assumption in bridged.inputs.assumptions:
    print(f"  {assumption}")

try:
    result = run_dcf(bridged.inputs)
except DCFConsistencyError as exc:
    print(f"\nENGINE GUARD FIRED: {exc}")
    sys.exit(1)

print("\n" + "=" * 74)
print("RESULT")
print("=" * 74)
print(f"  PV explicit forecast : {result.pv_explicit:>14,.0f}")
print(f"  PV terminal value    : {result.pv_terminal:>14,.0f}")
print(f"  Enterprise value     : {result.enterprise_or_equity_value:>14,.0f}")
print(f"  Equity value         : {result.equity_value:>14,.0f}")
print(f"  Value per share      : {result.value_per_share:>14,.2f}")
print(f"  Terminal value is {result.terminal_pct:.0%} of total")

if bridged.tornado_ranges:
    print("\n" + "=" * 74)
    print("TORNADO (bounds from observed dispersion, not hand-picked)")
    print("=" * 74)
    for row in sensitivity_tornado(bridged.inputs, bridged.tornado_ranges):
        if row["swing"] is None:
            print(f"  {row['param']:<22} (a bound violates a consistency guard)")
        else:
            print(f"  {row['param']:<22} {row['low']:>9.2f} -> {row['high']:>9.2f}"
                  f"   swing {row['swing']:>8.2f} ({row['swing_pct']:>5.0%})")

if market_price:
    implied = reverse_dcf(bridged.inputs, market_price)
    print("\n" + "=" * 74)
    print("REVERSE DCF")
    print("=" * 74)
    if implied is None:
        print(f"  No growth rate in range justifies ${market_price}")
    else:
        print(f"  At ${market_price}/share the market implies {implied:.1%} "
              f"annual growth for {len(bridged.inputs.growth_rates)} years")