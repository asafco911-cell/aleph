"""Derive valuation assumption ranges from extracted facts.

The division of labour is fixed: the model extracts facts, Python derives
ranges. The model never chooses a range, and Python never chooses a point
estimate where the evidence does not support one.

Two kinds of quantity are derived differently:

  TREND quantities (growth, tax rate) summarise several periods, so dispersion
  across periods is meaningful and a wide spread means the summary is unsafe.

  LEVEL quantities (cash flow, share count, net debt) take the most recent
  period. Min/max across years is a time series, not an uncertainty band:
  treating Uber's 2022 operating cash flow as the low bound on its 2024 figure
  would report a 91 percent downside that reflects growth, not risk.
"""
from statistics import median

from ..schemas.evidence import Fact
from ..schemas.valuation import AssumptionRange, Observation, Override

MAX_RELATIVE_SPREAD = 1.0  # see ISSUES.md #13: scale-dependent, per-quantity limits pending


def _observations(facts: list[Fact], *name_contains: str) -> list[Observation]:
    """Collect one observation per period for facts matching all labels."""
    found: dict[str, Observation] = {}
    for fact in facts:
        name = fact.name.lower()
        if fact.period is None or not all(t.lower() in name for t in name_contains):
            continue
        found[fact.period] = Observation(
            period=fact.period, value=fact.value, fact_name=fact.name
        )
    return [found[period] for period in sorted(found)]


def _dispersion_problem(values: list[float]) -> str | None:
    """Return why a set of observations cannot be summarised, or None."""
    if len(values) < 2:
        return None
    if any(v > 0 for v in values) and any(v < 0 for v in values):
        return "values change sign across periods"
    centre = median(values)
    if centre == 0:
        return "median is zero; relative spread is undefined"
    spread = (max(values) - min(values)) / abs(centre)
    if spread > MAX_RELATIVE_SPREAD:
        return (f"relative spread is {spread:.1f}x the median "
                f"(limit {MAX_RELATIVE_SPREAD:.1f}x)")
    return None


def _blocked(name, unit, observations, excluded, reason, doc_ids) -> AssumptionRange:
    return AssumptionRange(
        name=name, unit=unit, status="blocked",
        observations=observations, excluded=excluded,
        method="none", rationale=f"BLOCKED: {reason}", doc_ids=doc_ids,
    )


def _apply_override(observations, override):
    if not override or not override.excluded_periods:
        return observations, []
    kept = [o for o in observations if o.period not in override.excluded_periods]
    dropped = [o for o in observations if o.period in override.excluded_periods]
    return kept, dropped


def _fixed(name, unit, observations, excluded, override, doc_ids) -> AssumptionRange:
    return AssumptionRange(
        name=name, unit=unit, status="overridden",
        low=override.fixed_value, base=override.fixed_value, high=override.fixed_value,
        observations=observations, excluded=excluded,
        method="fixed by analyst override",
        rationale=f"{override.rationale} [{override.decided_by}, {override.decided_at}]",
        doc_ids=doc_ids,
    )


def build_trend(name, unit, observations, override, doc_ids) -> AssumptionRange:
    """Summarise several periods. Blocks when dispersion makes a summary unsafe."""
    kept, excluded = _apply_override(observations, override)
    if override and override.fixed_value is not None:
        return _fixed(name, unit, observations, excluded, override, doc_ids)
    if not kept:
        reason = (f"{len(excluded)} of {len(observations)} periods excluded by override"
                  if excluded else
                  "no facts extracted for this quantity; check extraction gates")
        return _blocked(name, unit, observations, excluded, reason, doc_ids)

    values = [o.value for o in kept]
    problem = _dispersion_problem(values)
    if problem:
        return _blocked(
            name, unit, observations, excluded,
            f"{problem}. Observed {[f'{o.period}={o.value:,.1f}' for o in kept]}. "
            "A summary statistic over these would be arithmetically valid and "
            "economically meaningless. Record an override in data/overrides.json "
            "with a written rationale to proceed.",
            doc_ids,
        )

    note = (f" Analyst excluded {override.excluded_periods}: {override.rationale} "
            f"[{override.decided_by}, {override.decided_at}]") if override else ""
    return AssumptionRange(
        name=name, unit=unit, status="overridden" if override else "derived",
        low=min(values), base=median(values), high=max(values),
        observations=observations, excluded=excluded,
        method="low/high are the observed min and max; base is the median",
        rationale=(f"Derived from {len(kept)} periods "
                   f"({', '.join(o.period for o in kept)}); "
                   f"dispersion within limits.{note}"),
        doc_ids=doc_ids,
    )


def build_level(name, unit, observations, override, doc_ids) -> AssumptionRange:
    """Take the most recent period. Prior periods are context, not a range."""
    kept, excluded = _apply_override(observations, override)
    if override and override.fixed_value is not None:
        return _fixed(name, unit, observations, excluded, override, doc_ids)
    if not kept:
        return _blocked(name, unit, observations, excluded,
                        "no facts extracted for this quantity", doc_ids)

    latest = kept[-1]
    note = (f" Analyst excluded {override.excluded_periods}: {override.rationale} "
            f"[{override.decided_by}, {override.decided_at}]") if override else ""
    return AssumptionRange(
        name=name, unit=unit, status="overridden" if override else "derived",
        low=latest.value, base=latest.value, high=latest.value,
        observations=observations, excluded=excluded,
        method=f"most recent period ({latest.period}); no band derived from history",
        rationale=(f"Level quantity taken from {latest.period}. Prior periods "
                   f"{[f'{o.period}={o.value:,.0f}' for o in kept[:-1]]} are "
                   f"context, not an uncertainty band.{note}"),
        doc_ids=doc_ids,
    )


def _doc_ids(facts: list[Fact]) -> list[str]:
    return sorted({f.source.doc_id for f in facts if f.source})


def derive_growth(facts, overrides) -> AssumptionRange:
    """Year-over-year revenue growth, one observation per consecutive pair."""
    totals = _observations(facts, "total revenue")
    pairs = [
        Observation(period=current.period,
                    value=(current.value / previous.value - 1.0) * 100.0,
                    fact_name=f"{current.fact_name} over {previous.fact_name}")
        for previous, current in zip(totals, totals[1:]) if previous.value
    ]
    return build_trend("revenue_growth", "percent", pairs,
                       overrides.get("revenue_growth"), _doc_ids(facts))


def derive_tax_rate(facts, overrides) -> AssumptionRange:
    return build_trend("effective_tax_rate", "percent",
                       _observations(facts, "effective income tax rate"),
                       overrides.get("effective_tax_rate"), _doc_ids(facts))


def derive_operating_cash_flow(facts, overrides) -> AssumptionRange:
    return build_level("operating_cash_flow", "USD millions",
                       _observations(facts, "operating activities"),
                       overrides.get("operating_cash_flow"), _doc_ids(facts))


def derive_capex(facts, overrides) -> AssumptionRange:
    return build_level("capex", "USD millions",
                       _observations(facts, "property and equipment"),
                       overrides.get("capex"), _doc_ids(facts))


def derive_interest_expense(facts, overrides) -> AssumptionRange:
    return build_level("interest_expense", "USD millions",
                       _observations(facts, "interest expense"),
                       overrides.get("interest_expense"), _doc_ids(facts))


def derive_diluted_shares(facts, overrides) -> AssumptionRange:
    return build_level("diluted_shares", "thousands",
                       _observations(facts, "diluted"),
                       overrides.get("diluted_shares"), _doc_ids(facts))


def derive_net_debt(facts, overrides) -> AssumptionRange:
    """Net debt is NOT derived. It is blocked until the analyst states a policy.

    The balance sheet reports balances, not availability. Whether short-term
    investments can service debt is a judgement about liquidity and intent,
    neither of which is a disclosed fact. Operating lease liabilities are a
    second judgement with the same shape: including them in net debt while
    leaving lease costs inside operating cash flow charges for leases twice -
    the same numerator/denominator inconsistency the engine guards against.

    Components are surfaced so the decision is made against the numbers.
    """
    override = overrides.get("net_debt")
    components = (
        _observations(facts, "cash and cash equivalents")
        + _observations(facts, "short-term investments")
        + _observations(facts, "long-term debt")
        + _observations(facts, "restricted cash")
    )
    doc_ids = _doc_ids(facts)

    if override and override.fixed_value is not None:
        return _fixed("net_debt", "USD millions", components, [], override, doc_ids)

    listing = [f"{o.fact_name}={o.value:,.0f}" for o in components] or ["none extracted"]
    return _blocked(
        "net_debt", "USD millions", components, [],
        "net debt requires a stated cash and debt policy, not a derivation. "
        "Restricted cash is unavailable by definition; cash equivalents are "
        "available; short-term investments and operating lease liabilities are "
        "analyst judgements. Components found: " + "; ".join(listing) +
        ". Set fixed_value in data/overrides.json with the policy as rationale.",
        doc_ids,
    )


DERIVATIONS = (
    derive_growth, derive_tax_rate, derive_operating_cash_flow, derive_capex,
    derive_interest_expense, derive_diluted_shares, derive_net_debt,
)


def derive_all(facts: list[Fact], overrides: dict[str, Override]) -> list[AssumptionRange]:
    return [derive(facts, overrides) for derive in DERIVATIONS]