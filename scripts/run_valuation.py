"""Run the valuation: extract, derive, bridge, value. Nothing else.

Blocked assumptions stop the run. A valuation built on a smoothed-over blocked
input looks exactly like one built on evidence.

Targets are resolved per filing rather than hardcoded: note numbering differs
between filers, so a fixed number reads the wrong note without complaint.

The orchestration itself lives in aleph.valuation.pipeline so that every
caller runs the same sequence. This file owns argv, presentation, and the
exit code - nothing else.

WHAT THIS FILE PRINTS, and why the list is short. Everything here is a step a
valuation NUMBER depends on: the data contract, the bottom-up WACC, the
bridge, the assumptions, the result, the tornado and the reverse DCF. It ran
to 522 lines because seven diagnostic layers had accumulated below the reverse
DCF, each wrapped in a bare `except Exception`, and a reader could not tell
which half of the output was the valuation.

Those layers moved to scripts/diagnose_valuation.py, same arguments. They are
still real work, still tested, and still change no number here - see
README.md, "Diagnostic layers (not in the base DCF)", and docs/adr/0009.
"""
import sys

from _filings import exit_on_missing_filing
from aleph.valuation.bridge import BridgeError
from aleph.valuation.pipeline import (
    BlockedError,
    ContractBlockedError,
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
except ContractBlockedError as exc:
    print("\n" + "=" * 74)
    print("DATA CONTRACT")
    print("=" * 74)
    print(exc.result.as_table())
    sys.exit(1)
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
except FileNotFoundError as exc:
    # The filings are deliberately not distributed. That is a documented,
    # expected state of a fresh clone, and it used to arrive here as a
    # 39-line pypdf traceback from the first command README lists.
    exit_on_missing_filing(exc)

bridged = run.bridged
result = run.result

if run.contract is not None:
    print("\n" + "=" * 74)
    print("DATA CONTRACT")
    print("=" * 74)
    for row in run.contract.rows:
        flag = "  [ANALYST OVERRIDE]" if row.override else ""
        print(f"  {row.field:<26} {row.state.value}{flag}")
    print(f"  STATUS: {run.contract.status.value} "
          f"({run.contract.verified_count} of "
          f"{run.contract.expected_count} required inputs satisfied)")
    for note in run.contract.notes:
        print(f"  {note}")

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

def bound_text(value, spec):
    """A bound the engine refused is named, not blanked and not printed.

    `spec` is the caller's original format spec, kept exactly so a filing
    with no refused bound prints byte-identically to before this existed.
    """
    return format(value, spec) if value is not None else "NOT_APPLICABLE"


bound = bridged.base_cash_flow_bound
if bound["available"]:
    print(f"  Value per share      : {bound_text(run.low_vps, '>7,.2f')} to "
          f"{bound_text(run.high_vps, '<7,.2f')}  "
          f"(range across {bound['low_period']}-{bound['high_period']} FCFF)")
    # A NOT_APPLICABLE end of the range says more than the number it replaced,
    # and only if the reason is printed with it. The engine's own message is
    # quoted rather than paraphrased.
    for end, value, note, period in (
        ("low", run.low_vps, run.low_vps_note, bound["low_period"]),
        ("high", run.high_vps, run.high_vps_note, bound["high_period"]),
    ):
        if value is None:
            print(f"      range {end}: NOT_APPLICABLE ({period} FCFF "
                  f"{bound[f'{end}_fcff']:,.0f})")
            print(f"        {note}")
    print(f"  Latest-period basis  : {result.value_per_share:>17,.2f}  "
          f"({bound['high_period']} FCFF, the base case)")
    if market_price and run.low_vps is not None and run.high_vps is not None:
        position = range_position(
            market_price, min(run.low_vps, run.high_vps), max(run.low_vps, run.high_vps)
        )
        print(f"  Market price         : {market_price:>17,.2f}  {position}")
    elif market_price:
        print(f"  Market price         : {market_price:>17,.2f}  "
              "no range to place it in - one end is NOT_APPLICABLE")
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
            # Which END was refused matters: "base_cash_flow NOT_APPLICABLE ->
            # 49.06" says the low bound cannot be valued at all, which is a
            # larger statement about anchor sensitivity than any swing figure.
            # Note these rows sort LAST (no comparable swing), so a driver that
            # dominates the valuation can appear at the bottom of this list.
            print(f"  {row['param']:<22} "
                  f"{bound_text(row['low'], '>9.2f')} -> "
                  f"{bound_text(row['high'], '>9.2f')}"
                  "   swing NOT_APPLICABLE (a bound violates a consistency guard)")
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

# Everything the pipeline computes but does not need in order to value the
# filing - accounting quality, valuation robustness, and the five EXPERIMENTAL
# layers - prints from scripts/diagnose_valuation.py, with the same arguments.
if market_price:
    print(f"\n(diagnostics: python scripts\\diagnose_valuation.py {doc_id} "
          f"{market_price:g})")
else:
    print(f"\n(diagnostics: python scripts\\diagnose_valuation.py {doc_id})")
