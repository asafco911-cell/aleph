"""Run the full pipeline: extract, derive, bridge, value.

Blocked assumptions stop the run. A valuation built on a smoothed-over blocked
input looks exactly like one built on evidence.

Targets are resolved per filing rather than hardcoded: note numbering differs
between filers, so a fixed number reads the wrong note without complaint.
"""
import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path("src/aleph/valuation")))  # engine imports by bare name

from aleph.extraction import extract
from aleph.extraction.targets import resolve_targets
from aleph.schemas import DocumentRecord
from aleph.schemas.valuation import MarketAssumption, Override
from aleph.valuation import build_wacc, derive_all
from aleph.valuation.bridge import BridgeError, build_dcf_inputs

from dcf_engine import DCFConsistencyError, reverse_dcf, run_dcf, sensitivity_tornado

doc_id = sys.argv[1]
market_price = float(sys.argv[2]) if len(sys.argv) > 2 else None

record = next(
    DocumentRecord(**r)
    for r in json.loads(Path("data/manifest.json").read_text(encoding="utf-8"))
    if r["doc_id"] == doc_id
)

facts = []
for key, target, question, required in resolve_targets(record):
    if target.startswith("UNRESOLVED"):
        print(f"  SKIP {key}: not disclosed by this filer")
        continue
    accepted, rejected, _ = extract(record, target, question, target_key=key)
    print(f"  {key:<14} {target:<12} accepted={len(accepted):>2} "
          f"rejected={len(rejected):>2}")
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
blocked = [a for a in ranges.values() if a.status == "blocked"]
if blocked:
    print(f"\nBLOCKED: {[a.name for a in blocked]}")
    for item in blocked:
        print(f"  {item.name}: {item.rationale}")
    sys.exit(1)

try:
    wacc = build_wacc(ranges, market)
except BridgeError as exc:
    print(f"\nWACC NOT BUILT: {exc}")
    wacc = None

beta_bounds = None
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
    # arbitrary and hides the component actually driving it. Bounds come from
    # rerunning WACC at the beta bounds instead.
    beta_base = market["unlevered_industry_beta"].value
    beta_bounds = []
    for factor in (0.75, 1.45):
        trial = dict(market)
        trial["unlevered_industry_beta"] = market["unlevered_industry_beta"].model_copy(
            update={"value": beta_base * factor}
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

if beta_bounds:
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

def _range_position(price, low, high):
    """Describe where a market price sits relative to a value-per-share
    range - inside it, or how far outside on either side. "Inside" is
    measured as a share of the range's own width; outside either end is
    measured as a plain ratio to that end, since there is no range width
    left to measure against beyond it.
    """
    if low <= price <= high:
        span = high - low
        pct = (price - low) / span * 100 if span else 0.0
        return f"inside the range, {pct:.1f}% of the way up"
    if price > high:
        pct = (price / high - 1) * 100 if high else float("inf")
        return f"{pct:.1f}% ABOVE the top of the range"
    pct = (1 - price / low) * 100 if low else float("inf")
    return f"{pct:.1f}% BELOW the bottom of the range"


print("\n" + "=" * 74)
print("RESULT")
print("=" * 74)

bound = bridged.base_cash_flow_bound
if bound["available"]:
    low_trial, high_trial = deepcopy(bridged.inputs), deepcopy(bridged.inputs)
    low_trial.base_cash_flow = bound["low_fcff"]
    high_trial.base_cash_flow = bound["high_fcff"]
    low_vps = run_dcf(low_trial).value_per_share
    high_vps = run_dcf(high_trial).value_per_share
    print(f"  Value per share      : {low_vps:>7,.2f} to {high_vps:<7,.2f}  "
          f"(range across {bound['low_period']}-{bound['high_period']} FCFF)")
    print(f"  Latest-period basis  : {result.value_per_share:>17,.2f}  "
          f"({bound['high_period']} FCFF, the base case)")
    if market_price:
        position = _range_position(market_price, min(low_vps, high_vps), max(low_vps, high_vps))
        print(f"  Market price         : {market_price:>17,.2f}  {position}")
    print("  (PV, enterprise, and equity value below use the latest-period basis)")
else:
    print(f"  Value per share      : {result.value_per_share:>14,.2f}")
    print(f"  (multi-year range unavailable: {bound['reason']})")

print(f"  PV explicit forecast : {result.pv_explicit:>14,.0f}")
print(f"  PV terminal value    : {result.pv_terminal:>14,.0f}")
print(f"  Enterprise value     : {result.enterprise_or_equity_value:>14,.0f}")
print(f"  Equity value         : {result.equity_value:>14,.0f}")
print(f"  Terminal value is {result.terminal_pct:.0%} of total")

if bridged.tornado_ranges:
    print("\n" + "=" * 74)
    print("TORNADO")
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
