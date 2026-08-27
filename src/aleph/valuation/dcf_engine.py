"""Deterministic DCF engine. No LLM anywhere in this file - pure arithmetic."""
from dataclasses import dataclass, field
from typing import List, Literal, Optional


@dataclass
class Assumption:
    """A single assumption with its provenance. Never a bare number."""
    name: str
    value: float
    source: Literal["filing", "market", "peer_group", "analyst_judgment"]
    rationale: str

    def __str__(self):
        return f"{self.name}={self.value:.4g} [{self.source}] {self.rationale}"


@dataclass
class DCFInputs:
    """All inputs required for a DCF. Every rate is a decimal (0.08 = 8%)."""
    cash_flow_type: Literal["FCFF", "FCFE"]
    base_cash_flow: float                  # most recent normalized FCF
    growth_rates: List[float]              # explicit forecast, one per year
    terminal_growth: float
    discount_rate: float                   # WACC for FCFF, cost of equity for FCFE
    net_debt: float                        # only used to bridge FCFF -> equity
    shares_outstanding: float              # diluted
    assumptions: List[Assumption] = field(default_factory=list)

class DCFConsistencyError(ValueError):
    """Raised when cash flow type, discount rate, and equity bridge don't match."""


def validate(inputs: DCFInputs) -> None:
    """Deterministic guards. These catch the classic double-counting errors."""
    # Guard 1: terminal growth must be below the discount rate (Gordon breaks otherwise)
    if inputs.terminal_growth >= inputs.discount_rate:
        raise DCFConsistencyError(
            f"terminal_growth ({inputs.terminal_growth:.2%}) must be below "
            f"discount_rate ({inputs.discount_rate:.2%}) - Gordon denominator would be <= 0"
        )
    # Guard 2: terminal growth above long-run economy growth is economically impossible
    if inputs.terminal_growth > 0.03:
        raise DCFConsistencyError(
            f"terminal_growth ({inputs.terminal_growth:.2%}) exceeds 3% - implies the "
            "company eventually exceeds the whole economy"
        )
    # Guard 3: net debt is only bridged when starting from firm-level cash flow
    if inputs.cash_flow_type == "FCFE" and inputs.net_debt != 0:
        raise DCFConsistencyError(
            "FCFE already yields equity value - subtracting net debt double counts it"
        )
    if inputs.shares_outstanding <= 0:
        raise DCFConsistencyError("shares_outstanding must be positive")

@dataclass
class DCFResult:
    enterprise_or_equity_value: float
    equity_value: float
    value_per_share: float
    pv_explicit: float                     # PV of the forecast period
    pv_terminal: float                     # PV of terminal value
    terminal_pct: float                    # how much of the value rests on TV
    yearly: List[dict]


def run_dcf(inputs: DCFInputs) -> DCFResult:
    """Core DCF. Deterministic: same inputs always produce the same output."""
    validate(inputs)

    r = inputs.discount_rate
    cf = inputs.base_cash_flow
    yearly, pv_explicit = [], 0.0

    # Explicit forecast period
    for year, g in enumerate(inputs.growth_rates, start=1):
        cf = cf * (1 + g)
        discount_factor = 1 / ((1 + r) ** year)
        pv = cf * discount_factor
        pv_explicit += pv
        yearly.append({"year": year, "growth": g, "cash_flow": cf,
                       "discount_factor": discount_factor, "pv": pv})

    # Terminal value via Gordon growth, discounted from the final forecast year
    n = len(inputs.growth_rates)
    terminal_value = cf * (1 + inputs.terminal_growth) / (r - inputs.terminal_growth)
    pv_terminal = terminal_value / ((1 + r) ** n)

    total = pv_explicit + pv_terminal
    equity = total - inputs.net_debt if inputs.cash_flow_type == "FCFF" else total

    return DCFResult(
        enterprise_or_equity_value=total,
        equity_value=equity,
        value_per_share=equity / inputs.shares_outstanding,
        pv_explicit=pv_explicit,
        pv_terminal=pv_terminal,
        terminal_pct=pv_terminal / total,
        yearly=yearly,
    )
from copy import deepcopy


def sensitivity_tornado(inputs: DCFInputs, ranges: dict) -> List[dict]:
    """
    Move one assumption at a time to its low and high bound, holding all else fixed.
    ranges: {"discount_rate": (0.07, 0.11), "terminal_growth": (0.01, 0.03), ...}
    Returns rows sorted by swing size, widest first.
    """
    base = run_dcf(inputs).value_per_share
    rows = []

    for param, (low, high) in ranges.items():
        values = {}
        for label, bound in (("low", low), ("high", high)):
            trial = deepcopy(inputs)
            if param == "growth_rates_shift":
                # Shift every forecast year growth rate by the same delta
                trial.growth_rates = [g + bound for g in inputs.growth_rates]
            else:
                setattr(trial, param, bound)
            try:
                values[label] = run_dcf(trial).value_per_share
            except DCFConsistencyError:
                values[label] = None            # bound violates a guard - report it

        if values["low"] is None or values["high"] is None:
            rows.append({"param": param, "low": values["low"], "high": values["high"],
                         "swing": None, "swing_pct": None})
            continue

        swing = abs(values["high"] - values["low"])
        rows.append({"param": param, "low": values["low"], "high": values["high"],
                     "swing": swing, "swing_pct": swing / base})

    # Widest swing first - that is the assumption worth arguing about
    return sorted(rows, key=lambda r: (r["swing"] is not None, r["swing"] or 0), reverse=True)

def reverse_dcf(inputs: DCFInputs, market_price_per_share: float,
                tolerance: float = 0.001, max_iter: int = 100) -> Optional[float]:
    """
    Solve for the uniform annual growth rate the market price implies.
    Binary search: deterministic, no optimizer library needed.
    """
    n_years = len(inputs.growth_rates)
    low, high = -0.50, 1.00                  # search between -50% and +100% annual growth

    def value_at(g):
        trial = deepcopy(inputs)
        trial.growth_rates = [g] * n_years
        try:
            return run_dcf(trial).value_per_share
        except DCFConsistencyError:
            return None

    for _ in range(max_iter):
        mid = (low + high) / 2
        v = value_at(mid)
        if v is None:
            high = mid                        # invalid region - search lower
            continue
        if abs(v - market_price_per_share) < tolerance * market_price_per_share:
            return mid
        if v < market_price_per_share:
            low = mid                         # need more growth to justify the price
        else:
            high = mid
    return None                               # did not converge in range