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
    bridged = build_dcf_inputs(ranges, market)
except BridgeError as exc:
    print(f"\nBRIDGE FAILED: {exc}")
    sys.exit(1)

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