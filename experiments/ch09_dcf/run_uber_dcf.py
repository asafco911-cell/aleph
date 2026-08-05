from dcf_engine import DCFInputs, Assumption, run_dcf, sensitivity_tornado, reverse_dcf

# NOTE: these are illustrative inputs for learning the engine, not a real valuation.
# Only base_cash_flow-adjacent figures trace to the verified page 58 data.
assumptions = [
    Assumption("base_fcf", 7000, "filing",
               "Illustrative normalized FCF - replace with a reconciled owner-earnings figure"),
    Assumption("discount_rate", 0.09, "market",
               "Illustrative WACC - should be built bottom-up from industry beta"),
    Assumption("terminal_growth", 0.025, "analyst_judgment",
               "Below long-run nominal GDP growth, per the g<3% constraint"),
    Assumption("shares_outstanding", 2100, "filing",
               "Diluted share count - replace with the figure from the filing"),
]

inputs = DCFInputs(
    cash_flow_type="FCFF",
    base_cash_flow=7000,                       # USD millions
    growth_rates=[0.15, 0.13, 0.11, 0.09, 0.07, 0.06, 0.05, 0.04, 0.035, 0.03],
    terminal_growth=0.025,
    discount_rate=0.09,
    net_debt=3000,
    shares_outstanding=2100,
    assumptions=assumptions,
)

result = run_dcf(inputs)

print("=" * 70)
print("ASSUMPTIONS")
print("=" * 70)
for a in inputs.assumptions:
    print(f"  {a}")

print("\n" + "=" * 70)
print("RESULT")
print("=" * 70)
print(f"  PV of explicit forecast : {result.pv_explicit:>12,.0f}")
print(f"  PV of terminal value    : {result.pv_terminal:>12,.0f}")
print(f"  Enterprise value        : {result.enterprise_or_equity_value:>12,.0f}")
print(f"  Equity value            : {result.equity_value:>12,.0f}")
print(f"  Value per share         : {result.value_per_share:>12,.2f}")
print(f"  >> Terminal value is {result.terminal_pct:.0%} of total <<")

print("\n" + "=" * 70)
print("SENSITIVITY TORNADO (widest swing first)")
print("=" * 70)
ranges = {
    "discount_rate": (0.07, 0.11),
    "terminal_growth": (0.015, 0.03),
    "growth_rates_shift": (-0.03, 0.03),
    "base_cash_flow": (6000, 8000),
}
for row in sensitivity_tornado(inputs, ranges):
    if row["swing"] is None:
        print(f"  {row['param']:<22} (a bound violates a consistency guard)")
    else:
        print(f"  {row['param']:<22} {row['low']:>8.2f} -> {row['high']:>8.2f}"
              f"   swing {row['swing']:>7.2f}  ({row['swing_pct']:>5.0%} of base)")

print("\n" + "=" * 70)
print("REVERSE DCF")
print("=" * 70)
market_price = 75.0
implied = reverse_dcf(inputs, market_price)
if implied is None:
    print(f"  No growth rate in range justifies ${market_price}")
else:
    print(f"  At ${market_price}/share, the market implies "
          f"{implied:.1%} annual growth for {len(inputs.growth_rates)} years")
    print(f"  Question to ask: is {implied:.1%} sustained growth plausible for this business?")