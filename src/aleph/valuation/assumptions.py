"""Derive valuation assumption ranges from extracted facts.

The division of labour is fixed: the model extracts facts, Python derives
ranges. The model never chooses a range, and Python never chooses a point
estimate where the evidence does not support one.

Dispersion tests are STRUCTURAL, not domain-specific. A hardcoded plausible
band ("tax rates lie between 0 and 35 percent") encodes what happens to be
known about one metric and fails silently on the next one. Sign inconsistency
and relative spread apply to any quantity.
"""
from statistics import median

from ..schemas.evidence import Fact
from ..schemas.valuation import AssumptionRange, Observation, Override

MAX_RELATIVE_SPREAD = 1.0  # (max - min) / |median|


def _observations(facts: list[Fact], name_contains: str) -> list[Observation]:
    """Collect one observation per period for facts matching a label."""
    found: dict[str, Observation] = {}
    for fact in facts:
        if name_contains.lower() not in fact.name.lower() or fact.period is None:
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


def _build(
    name: str,
    unit: str,
    observations: list[Observation],
    override: Override | None,
    doc_ids: list[str],
) -> AssumptionRange:
    excluded: list[Observation] = []
    kept = observations

    if override and override.excluded_periods:
        excluded = [o for o in observations if o.period in override.excluded_periods]
        kept = [o for o in observations if o.period not in override.excluded_periods]

    if override and override.fixed_value is not None:
        return AssumptionRange(
            name=name, unit=unit, status="overridden",
            low=override.fixed_value, base=override.fixed_value,
            high=override.fixed_value,
            observations=observations, excluded=excluded,
            method="fixed by analyst override",
            rationale=f"{override.rationale} [{override.decided_by}, {override.decided_at}]",
            doc_ids=doc_ids,
        )

    if not kept:
        reason = (
            f"{len(excluded)} of {len(observations)} periods excluded by override"
            if excluded else
            "no facts were extracted for this quantity; check extraction gates"
        )
        return AssumptionRange(
            name=name, unit=unit, status="blocked",
            observations=observations, excluded=excluded,
            method="none",
            rationale=f"BLOCKED: {reason}",
            doc_ids=doc_ids,
        )

    values = [o.value for o in kept]
    problem = _dispersion_problem(values)
    if problem:
        return AssumptionRange(
            name=name, unit=unit, status="blocked",
            observations=observations, excluded=excluded,
            method="none",
            rationale=(
                f"BLOCKED: {problem}. Observed "
                f"{[f'{o.period}={o.value:,.1f}' for o in kept]}. "
                "A summary statistic over these would be arithmetically valid "
                "and economically meaningless. Record an override in "
                "data/overrides.json with a written rationale to proceed."
            ),
            doc_ids=doc_ids,
        )

    status = "overridden" if override else "derived"
    note = (f" Analyst excluded {override.excluded_periods}: {override.rationale} "
            f"[{override.decided_by}, {override.decided_at}]") if override else ""

    return AssumptionRange(
        name=name, unit=unit, status=status,
        low=min(values), base=median(values), high=max(values),
        observations=observations, excluded=excluded,
        method="low/high are the observed min and max; base is the median",
        rationale=(
            f"Derived from {len(kept)} observed periods "
            f"({', '.join(o.period for o in kept)}); dispersion within limits.{note}"
        ),
        doc_ids=doc_ids,
    )


def derive_growth(facts: list[Fact], overrides: dict[str, Override]) -> AssumptionRange:
    """Year-over-year revenue growth, one observation per consecutive pair."""
    totals = _observations(facts, "total revenue")
    pairs: list[Observation] = []
    for previous, current in zip(totals, totals[1:]):
        if previous.value:
            pairs.append(Observation(
                period=current.period,
                value=(current.value / previous.value - 1.0) * 100.0,
                fact_name=f"{current.fact_name} over {previous.fact_name}",
            ))
    doc_ids = sorted({f.source.doc_id for f in facts if f.source})
    return _build("revenue_growth", "percent", pairs,
                  overrides.get("revenue_growth"), doc_ids)


def derive_tax_rate(facts: list[Fact], overrides: dict[str, Override]) -> AssumptionRange:
    """Effective tax rate as reported, per period."""
    observations = _observations(facts, "effective income tax rate")
    doc_ids = sorted({f.source.doc_id for f in facts if f.source})
    return _build("effective_tax_rate", "percent", observations,
                  overrides.get("effective_tax_rate"), doc_ids)


DERIVATIONS = (derive_growth, derive_tax_rate)


def derive_all(
    facts: list[Fact], overrides: dict[str, Override]
) -> list[AssumptionRange]:
    return [derive(facts, overrides) for derive in DERIVATIONS]