"""Bottom-up WACC. Deterministic arithmetic over declared inputs.

Nothing here is estimated. Every input either comes from the filing (tax rate,
net debt, share count, geographic revenue mix) or is a declared market or
judgment input carrying an as_of date. The module refuses to invent the ones
that are neither.

Country risk premium is the clearest case. Note 13 discloses revenue by
geography, but revenue is not a risk profile, and Uber's largest non-US bucket
is an undisaggregated "all other countries". Weighting it requires per-country
revenue that is not disclosed, so Python cannot derive a CRP without inventing
the weights - and a fabricated weighted average carries a precision that
implies a derivation which never happened.
"""
from dataclasses import dataclass

from ..schemas.valuation import AssumptionRange, MarketAssumption
from .bridge import BridgeError, as_decimal, to_millions

REQUIRED_MARKET = (
    "risk_free_rate",
    "equity_risk_premium",
    "unlevered_industry_beta",
    "debt_spread",
    "country_risk_premium",
    "share_price",
)


@dataclass
class WACCResult:
    wacc: float
    cost_of_equity: float
    cost_of_debt_after_tax: float
    levered_beta: float
    equity_weight: float
    debt_weight: float
    notes: list[str]


def _get(market: dict[str, MarketAssumption], name: str) -> MarketAssumption:
    found = market.get(name)
    if found is None:
        raise BridgeError(
            f"'{name}' is required to build WACC bottom-up and is not derivable "
            "from the filing. Add it to data/market.json with a source, an "
            "as_of date, and a rationale."
        )
    if found.source.strip().lower() in ("placeholder", "todo", "tbd"):
        raise BridgeError(f"'{name}' is still a placeholder")
    return found


def geographic_mix(ranges: dict[str, AssumptionRange]) -> list[str]:
    """Report the disclosed revenue mix so a CRP judgement is made against it.

    Shares are computed against the sum of the components themselves, which is
    only meaningful because derive_geographic_revenue guarantees a single
    breakdown with stated totals removed.
    """
    mix = ranges.get("geographic_revenue")
    if mix is None or not mix.observations:
        return ["geographic revenue mix not disclosed"]
    total = sum(abs(o.value) for o in mix.observations)
    if not total:
        return ["geographic revenue mix sums to zero"]
    return [
        f"{o.fact_name}: {o.value:,.0f} ({abs(o.value) / total:.0%})"
        for o in mix.observations
    ]

def build_wacc(
    ranges: dict[str, AssumptionRange],
    market: dict[str, MarketAssumption],
) -> WACCResult:
    """Compute WACC from declared components. No component is estimated here."""
    missing = [name for name in REQUIRED_MARKET if name not in market]
    if missing:
        raise BridgeError(
            f"cannot build WACC bottom-up; missing declared inputs: {missing}. "
            "Each needs a value, source, as_of date and rationale in "
            "data/market.json."
        )

    risk_free = _get(market, "risk_free_rate").value
    erp = _get(market, "equity_risk_premium").value
    beta_u = _get(market, "unlevered_industry_beta").value
    spread = _get(market, "debt_spread").value
    crp = _get(market, "country_risk_premium").value
    price = _get(market, "share_price").value

    tax = as_decimal(ranges["effective_tax_rate"])
    shares = to_millions(ranges["diluted_shares"])
    net_debt = to_millions(ranges["net_debt"])

    equity_value = price * shares
    if equity_value <= 0:
        raise BridgeError("market equity value must be positive")

    # Weights use NET debt, matching the net_debt policy already recorded for
    # the equity bridge. Using gross debt here and net debt there would apply
    # two different capital structures to one company.
    debt_value = max(net_debt, 0.0)
    total = equity_value + debt_value
    equity_weight = equity_value / total
    debt_weight = debt_value / total

    # Hamada: relever the industry's unlevered beta at this company's structure.
    levered_beta = beta_u * (1 + (1 - tax) * (debt_value / equity_value))

    cost_of_equity = risk_free + levered_beta * erp + crp
    cost_of_debt_after_tax = (risk_free + spread) * (1 - tax)
    wacc = equity_weight * cost_of_equity + debt_weight * cost_of_debt_after_tax

    notes = [
        f"levered beta = {beta_u:.2f} x (1 + (1 - {tax:.1%}) x "
        f"{debt_value:,.0f}/{equity_value:,.0f}) = {levered_beta:.3f}",
        f"cost of equity = {risk_free:.2%} + {levered_beta:.3f} x {erp:.2%} "
        f"+ {crp:.2%} CRP = {cost_of_equity:.2%}",
        f"after-tax cost of debt = ({risk_free:.2%} + {spread:.2%}) x "
        f"(1 - {tax:.1%}) = {cost_of_debt_after_tax:.2%}",
        f"weights at market: equity {equity_weight:.1%}, debt {debt_weight:.1%} "
        f"(net debt basis, matching the equity bridge)",
        f"WACC = {wacc:.2%}",
        "Disclosed revenue mix behind the CRP judgement: "
        + "; ".join(geographic_mix(ranges)),
    ]
    return WACCResult(
        wacc=wacc,
        cost_of_equity=cost_of_equity,
        cost_of_debt_after_tax=cost_of_debt_after_tax,
        levered_beta=levered_beta,
        equity_weight=equity_weight,
        debt_weight=debt_weight,
        notes=notes,
    )