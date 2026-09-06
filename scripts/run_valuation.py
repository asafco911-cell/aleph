"""Run the full pipeline: extract, derive, bridge, value.

Blocked assumptions stop the run. A valuation built on a smoothed-over blocked
input looks exactly like one built on evidence.

Targets are resolved per filing rather than hardcoded: note numbering differs
between filers, so a fixed number reads the wrong note without complaint.

The orchestration itself lives in aleph.valuation.pipeline so that every
caller runs the same sequence. This file owns argv, presentation, and the
exit code - nothing else.
"""
import sys

from aleph.valuation.bridge import BridgeError
from aleph.valuation.pipeline import (
    BlockedError,
    DCFConsistencyError,
    range_position,
    value_filing,
)

doc_id = sys.argv[1]
market_price = float(sys.argv[2]) if len(sys.argv) > 2 else None


def show_target(target_result):
    """Print each extraction target as it completes, not after the loop."""
    if target_result.skipped:
        print(f"  SKIP {target_result.key}: not disclosed by this filer")
        return
    print(f"  {target_result.key:<14} {target_result.target:<12} "
          f"accepted={target_result.accepted:>2} "
          f"rejected={target_result.rejected:>2}")


try:
    run = value_filing(doc_id, market_price, on_target=show_target)
except BlockedError as exc:
    print(f"\nBLOCKED: {[a.name for a in exc.blocked]}")
    for item in exc.blocked:
        print(f"  {item.name}: {item.rationale}")
    sys.exit(1)
except BridgeError as exc:
    print(f"\nBRIDGE FAILED: {exc}")
    sys.exit(1)
except DCFConsistencyError as exc:
    print(f"\nENGINE GUARD FIRED: {exc}")
    sys.exit(1)

bridged = run.bridged
result = run.result

if run.wacc_error:
    print(f"\nWACC NOT BUILT: {run.wacc_error}")

if run.wacc:
    print("\n" + "=" * 74)
    print("WACC (bottom-up)")
    print("=" * 74)
    for note in run.wacc.notes:
        print(f"  {note}")
    print(f"  WACC at beta {run.beta_base * 0.75:.2f} / {run.beta_base:.2f} / "
          f"{run.beta_base * 1.45:.2f}: {run.wacc_at_beta_bounds[0]:.2%} / "
          f"{run.wacc.wacc:.2%} / {run.wacc_at_beta_bounds[1]:.2%}")

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

print("\n" + "=" * 74)
print("RESULT")
print("=" * 74)

bound = bridged.base_cash_flow_bound
if bound["available"]:
    print(f"  Value per share      : {run.low_vps:>7,.2f} to {run.high_vps:<7,.2f}  "
          f"(range across {bound['low_period']}-{bound['high_period']} FCFF)")
    print(f"  Latest-period basis  : {result.value_per_share:>17,.2f}  "
          f"({bound['high_period']} FCFF, the base case)")
    if market_price:
        position = range_position(
            market_price, min(run.low_vps, run.high_vps), max(run.low_vps, run.high_vps)
        )
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
    for row in run.tornado_rows:
        if row["swing"] is None:
            print(f"  {row['param']:<22} (a bound violates a consistency guard)")
        else:
            print(f"  {row['param']:<22} {row['low']:>9.2f} -> {row['high']:>9.2f}"
                  f"   swing {row['swing']:>8.2f} ({row['swing_pct']:>5.0%})")

if market_price:
    print("\n" + "=" * 74)
    print("REVERSE DCF")
    print("=" * 74)
    if run.implied_growth is None:
        print(f"  No growth rate in range justifies ${market_price}")
    else:
        print(f"  At ${market_price}/share the market implies "
              f"{run.implied_growth:.1%} "
              f"annual growth for {len(bridged.inputs.growth_rates)} years")
