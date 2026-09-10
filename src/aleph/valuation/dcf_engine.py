"""Deterministic DCF engine. No LLM anywhere in this file - pure arithmetic."""
import math
from copy import deepcopy
from dataclasses import dataclass, field
from typing import List, Literal, Optional


@dataclass
class Assumption:
    """A single assumption with its provenance. Never a bare number.

    P5.1 widened the vocabulary. The machine-readable ``source`` must reflect
    the ACTUAL origin, not a convenient label:

      filing            a single gate-verified extracted fact, taken as-is
      derived           computed from gate-verified facts (a statistic, or a
                        composite like FCFF built from several line items)
      market            observed external market data, valid at its as_of date
      analyst_judgment  stated by the analyst - an override or a policy choice
      model_convention  a methodology choice (horizon, fade shape, terminal
                        growth level) - see robustness.MODEL_CONVENTIONS
      peer_group        a chosen comparison set; the choice is a judgement

    Before P5.1, ``growth_year_1`` and ``net_debt`` were hard-coded "filing"
    even when they were analyst overrides (net_debt ALWAYS is). That mislabel
    is the V3 vulnerability from the Phase 2 audit.
    """
    name: str
    value: float
    source: Literal["filing", "derived", "market", "analyst_judgment",
                    "model_convention", "peer_group"]
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
    """Deterministic guards. These catch the classic double-counting errors
    and, per P5, refuse mathematically ill-posed inputs rather than emit a
    NaN / inf / division-by-zero result that looks like a valuation."""
    # Guard 0 (P5): every numeric input must be finite. A NaN or inf anywhere
    # upstream (a bad market rate, a mis-scaled fact) would otherwise flow
    # straight through to value_per_share.
    _numeric = {
        "base_cash_flow": inputs.base_cash_flow,
        "terminal_growth": inputs.terminal_growth,
        "discount_rate": inputs.discount_rate,
        "net_debt": inputs.net_debt,
        "shares_outstanding": inputs.shares_outstanding,
        **{f"growth_rates[{i}]": g for i, g in enumerate(inputs.growth_rates)},
    }
    nonfinite = [k for k, v in _numeric.items()
                 if not isinstance(v, (int, float)) or not math.isfinite(v)]
    if nonfinite:
        raise DCFConsistencyError(
            f"non-finite DCF input(s): {', '.join(nonfinite)} - refusing to "
            "produce a NaN/inf valuation")
    # Guard 0b (P5): the discount factor (1 + r) ** year must be well-defined
    # and non-zero. r <= -1 makes it zero or complex.
    if inputs.discount_rate <= -1.0:
        raise DCFConsistencyError(
            f"discount_rate ({inputs.discount_rate:.2%}) <= -100% - the "
            "discount factor is undefined")
    # Guard 0c (P5): a DCF has nothing to grow from a zero base. This is
    # NOT_SOLVABLE, not a $0.00 valuation.
    if inputs.base_cash_flow == 0:
        raise DCFConsistencyError(
            "base_cash_flow is zero - a DCF has no cash flow to discount; "
            "NOT_SOLVABLE")
    # Guard 0d: a negative base is not a small valuation, it is a category
    # error, and 0c refused the sign's only other special case while leaving
    # this one through. run_dcf multiplies base_cash_flow by (1 + g) each
    # forecast year and capitalises the last year with Gordon. Applied to a
    # LOSS that compounds the loss for the whole horizon and then reports the
    # present value of a deepening loss as a value per share - a number with
    # a currency sign in front of it and no meaning behind it.
    #
    # Measured, and the reason this guard exists: LYFT_FY2025's reported
    # range low was -$39.37, produced by growing FY2023 FCFF of -712 at the
    # forecast rates for ten years. Nothing was wrong with the arithmetic.
    #
    # What this is NOT saying: that Lyft was worth nothing in FY2023, or that
    # the anchor should be excluded from the analyst's attention. The opposite
    # - "one of the three disclosed years cannot be valued by this model at
    # all" is a stronger statement about anchor sensitivity than any number
    # this branch could return, and every caller reports it as such.
    if inputs.base_cash_flow < 0:
        raise DCFConsistencyError(
            f"base_cash_flow is negative ({inputs.base_cash_flow:,.0f}) - "
            "growing a loss is not a valuation; NOT_APPLICABLE")
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
    if total == 0 or not math.isfinite(total):
        raise DCFConsistencyError(
            "enterprise value collapsed to zero or non-finite - the growth "
            "path drove cash flow to zero; NOT_SOLVABLE")
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

REVERSE_DCF_LOW, REVERSE_DCF_HIGH = -0.50, 1.00   # uniform-growth search window


def reverse_dcf(inputs: DCFInputs, market_price_per_share: float,
                tolerance: float = 0.001, max_iter: int = 100) -> Optional[float]:
    r"""The UNIFORM-GROWTH EQUIVALENT implied by the market price, holding every
    other input (anchor FCFF, WACC, terminal growth, net debt, shares) fixed.

    NOT the mathematical inverse of the forward DCF: the forward model uses a
    FADED growth vector; this solves for a single flat rate applied to every
    forecast year. It answers "what constant growth would justify the price
    under the current non-growth assumptions?", nothing more.

    P5.1 CLOSURE - the well-posedness is now PROVEN, not sampled.

    With base FCFF B, discount rate r, terminal growth g_T, forecast horizon
    n, net debt D, shares S, and x = (1 + g) / (1 + r):

        EV(g) = B * [ sum_{k=1..n} x^k  +  K * x^n ]      K = (1 + g_T)/(r - g_T)
        vps(g) = (B / S) * Phi(x(g)) - D / S              Phi(x) = sum x^k + K x^n

    Whenever run_dcf succeeds it has already enforced r > g_T (Guard 1) and
    S > 0, so K > 0. Over the search window g in [-0.5, +1.0] with a valid
    r, x(g) > 0 and dx/dg = 1/(1+r) > 0. Every term of Phi'(x) is then
    strictly positive, so Phi is strictly increasing in x, hence in g.
    Therefore:

        B > 0  =>  vps(g) strictly INCREASING in g
        B <= 0 =>  run_dcf raises for every g (Guards 0c and 0d)

    The B < 0 half of that statement changed. It used to read "vps(g)
    strictly DECREASING in g", and the decreasing branch was live: the
    engine would value a negative anchor and this solver would invert it in
    the correct direction. Guard 0d now refuses a negative base outright, so
    value_at() returns None at every g and the window probe below returns
    NOT_SOLVABLE before the direction is ever read.

    The consequence for the code: `increasing` is True whenever the direction
    logic is reached, and its else-branch is unreachable while Guard 0d
    stands. It is kept, not deleted - it is one expression, it is correct,
    and it is the single place that would have to change if the guard is ever
    revisited. What is TESTED is the observable contract (a negative base
    yields None), not the dead branch; see ISSUES.md #38.

    There is no non-monotonic case and no partial-validity pocket: for a
    given input, value(g) is valid at every g in the window or at none of
    them (run_dcf's remaining guards depend only on the fixed inputs, and
    total = B * Phi(x) != 0 for B > 0, x > 0). So the direction is read
    directly from sign(B) and the only runtime checks are (a) the window is
    well-posed at all, and (b) the target is bracketed - both preconditions
    of bisection, each isolated by a mutation-killing test.

    Returns the implied uniform growth rate, or None (NOT_SOLVABLE) when the
    window is ill-posed or the price is unattainable.
    """
    n_years = len(inputs.growth_rates)
    if n_years == 0 or not math.isfinite(market_price_per_share):
        return None

    def value_at(g: float) -> Optional[float]:
        trial = deepcopy(inputs)
        trial.growth_rates = [g] * n_years
        try:
            return run_dcf(trial).value_per_share
        except DCFConsistencyError:
            return None

    # (a) is the window well-posed? value(g) is all-or-nothing valid, so the
    # two bracket ends settle it. If either is invalid the problem is not
    # solvable by a uniform growth rate.
    v_lo, v_hi = value_at(REVERSE_DCF_LOW), value_at(REVERSE_DCF_HIGH)
    if v_lo is None or v_hi is None:
        return None                           # NOT_SOLVABLE - window ill-posed

    # direction from the proof above - not from sampling. Always True once
    # Guard 0d is in place; see the docstring for why the expression stays.
    increasing = inputs.base_cash_flow > 0
    lo_bound, hi_bound = (v_lo, v_hi) if increasing else (v_hi, v_lo)

    # (b) bisection needs the root bracketed. An unattainable target - one
    # the uniform-growth model cannot reach anywhere in the window - is
    # NOT_SOLVABLE, not a boundary answer dressed up as a solution.
    if not (lo_bound <= market_price_per_share <= hi_bound):
        return None                           # unattainable target price

    lo, hi = REVERSE_DCF_LOW, REVERSE_DCF_HIGH
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        v = value_at(mid)                      # valid: window proven all-valid
        if abs(v - market_price_per_share) < tolerance * abs(market_price_per_share):
            return mid
        if (v < market_price_per_share) == increasing:
            lo = mid                           # move toward higher g
        else:
            hi = mid
    return None                               # did not converge