"""Derive valuation assumption ranges from extracted facts.

The division of labour is fixed: the model extracts facts, Python derives
ranges. The model never chooses a range, and Python never chooses a point
estimate where the evidence does not support one.

Two kinds of quantity are derived differently:

  TREND quantities (growth, tax rate) summarise several periods, so dispersion
  across periods is meaningful and a wide spread means the summary is unsafe.

  LEVEL quantities (cash flow, share count, net debt) take the most recent
  period. Min/max across years is a time series, not an uncertainty band.

Fact selection is by substring, which collides: "cash and cash equivalents" is
contained in "restricted cash and cash equivalents". Two different facts
matching one query in one period is an ambiguous query, and silently keeping
the last one drops the figure that matters. Collisions therefore block.
"""
from statistics import median

from ..schemas.evidence import Fact
from ..schemas.valuation import AssumptionRange, Observation, Override

MAX_RELATIVE_SPREAD = 1.0  # see ISSUES.md #13: scale-dependent, per-quantity limits pending


def _observations(
    facts: list[Fact],
    *name_contains: str,
    exclude: tuple[str, ...] = (),
    exclude_targets: tuple[str, ...] = (),
) -> tuple[list[Observation], list[str]]:
    """Return (one observation per period, collision descriptions).

    exclude_targets removes facts by their extraction target rather than by
    name. A geographic breakdown restates the same total under a different
    label, so it collides with the income statement total while adding nothing;
    excluding the target is precise, while excluding a name fragment would be a
    guess about wording.
    """
    found: dict[str, Observation] = {}
    collisions: list[str] = []

    for fact in facts:
        name = fact.name.lower()
        if fact.period is None:
            continue
        if fact.source and any(
            fact.source.target_key.startswith(prefix) for prefix in exclude_targets
        ):
            continue
        if not all(token.lower() in name for token in name_contains):
            continue
        if any(token.lower() in name for token in exclude):
            continue

        prior = found.get(fact.period)
        if prior is not None and prior.fact_name != fact.name:
            collisions.append(
                f"{fact.period}: '{prior.fact_name}' and '{fact.name}' both match "
                f"{list(name_contains)}"
            )
            continue
        found[fact.period] = Observation(
            period=fact.period, value=fact.value, fact_name=fact.name
        )

    return [found[period] for period in sorted(found)], collisions


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


def _fixed(name, unit, observations, excluded, override, doc_ids) -> AssumptionRange:
    return AssumptionRange(
        name=name, unit=unit, status="overridden",
        low=override.fixed_value, base=override.fixed_value, high=override.fixed_value,
        observations=observations, excluded=excluded,
        method="fixed by analyst override",
        rationale=f"{override.rationale} [{override.decided_by}, {override.decided_at}]",
        doc_ids=doc_ids,
    )


def _apply_override(observations, override):
    if not override or not override.excluded_periods:
        return observations, []
    kept = [o for o in observations if o.period not in override.excluded_periods]
    dropped = [o for o in observations if o.period in override.excluded_periods]
    return kept, dropped


def _override_note(override) -> str:
    if not override or not override.excluded_periods:
        return ""
    return (f" Analyst excluded {override.excluded_periods}: {override.rationale} "
            f"[{override.decided_by}, {override.decided_at}]")


def build_trend(name, unit, observations, collisions, override, doc_ids) -> AssumptionRange:
    """Summarise several periods. Blocks when dispersion makes a summary unsafe."""
    if collisions:
        return _blocked(name, unit, observations, [],
                        "ambiguous fact selection: " + "; ".join(collisions), doc_ids)

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

    return AssumptionRange(
        name=name, unit=unit, status="overridden" if override else "derived",
        low=min(values), base=median(values), high=max(values),
        observations=observations, excluded=excluded,
        method="low/high are the observed min and max; base is the median",
        rationale=(f"Derived from {len(kept)} periods "
                   f"({', '.join(o.period for o in kept)}); "
                   f"dispersion within limits.{_override_note(override)}"),
        doc_ids=doc_ids,
    )


def build_level(name, unit, observations, collisions, override, doc_ids) -> AssumptionRange:
    """Take the most recent period. Prior periods are context, not a range."""
    if collisions:
        return _blocked(name, unit, observations, [],
                        "ambiguous fact selection: " + "; ".join(collisions), doc_ids)

    kept, excluded = _apply_override(observations, override)
    if override and override.fixed_value is not None:
        return _fixed(name, unit, observations, excluded, override, doc_ids)
    if not kept:
        return _blocked(name, unit, observations, excluded,
                        "no facts extracted for this quantity", doc_ids)

    latest = kept[-1]
    return AssumptionRange(
        name=name, unit=unit, status="overridden" if override else "derived",
        low=latest.value, base=latest.value, high=latest.value,
        observations=observations, excluded=excluded,
        method=f"most recent period ({latest.period}); no band derived from history",
        rationale=(f"Level quantity taken from {latest.period}. Prior periods "
                   f"{[f'{o.period}={o.value:,.0f}' for o in kept[:-1]]} are "
                   f"context, not an uncertainty band.{_override_note(override)}"),
        doc_ids=doc_ids,
    )


def _doc_ids(facts: list[Fact]) -> list[str]:
    return sorted({f.source.doc_id for f in facts if f.source})


def derive_growth(facts, overrides) -> AssumptionRange:
    """Year-over-year revenue growth from the income statement total.

    Geographic and segment breakdowns restate the same total under different
    labels, so they are excluded here rather than allowed to collide with it.
    """
    totals, collisions = _observations(
        facts, "total revenue", exclude_targets=("geography",)
    )
    pairs = [
        Observation(period=current.period,
                    value=(current.value / previous.value - 1.0) * 100.0,
                    fact_name=f"{current.fact_name} over {previous.fact_name}")
        for previous, current in zip(totals, totals[1:]) if previous.value
    ]
    return build_trend("revenue_growth", "percent", pairs, collisions,
                       overrides.get("revenue_growth"), _doc_ids(facts))


def derive_tax_rate(facts, overrides) -> AssumptionRange:
    """Effective tax rate, stated if disclosed as a percentage, else computed.

    Presentation varies: some filers state the rate, others reconcile only in
    dollars. Computing provision over pretax income is the definition of the
    rate, so it is filer-independent and is used whenever the components are
    available.
    """
    stated, collisions = _observations(facts, "effective income tax rate")
    if stated:
        return build_trend("effective_tax_rate", "percent", stated, collisions,
                           overrides.get("effective_tax_rate"), _doc_ids(facts))

    provision, clash_a = _observations(facts, "provision for income taxes")
    pretax, clash_b = _observations(facts, "before income taxes")
    by_period = {o.period: o for o in pretax}

    computed = [
        Observation(period=p.period,
                    value=(p.value / by_period[p.period].value) * 100.0,
                    fact_name=f"{p.fact_name} over {by_period[p.period].fact_name}")
        for p in provision
        if p.period in by_period and by_period[p.period].value
    ]
    return build_trend("effective_tax_rate", "percent", computed,
                       clash_a + clash_b, overrides.get("effective_tax_rate"),
                       _doc_ids(facts))


def derive_operating_cash_flow(facts, overrides) -> AssumptionRange:
    observations, collisions = _observations(facts, "operating activities")
    return build_level("operating_cash_flow", "USD millions", observations, collisions,
                       overrides.get("operating_cash_flow"), _doc_ids(facts))


def derive_capex(facts, overrides) -> AssumptionRange:
    observations, collisions = _observations(facts, "property and equipment")
    return build_level("capex", "USD millions", observations, collisions,
                       overrides.get("capex"), _doc_ids(facts))


def derive_interest_expense(facts, overrides) -> AssumptionRange:
    observations, collisions = _observations(facts, "interest expense")
    return build_level("interest_expense", "USD millions", observations, collisions,
                       overrides.get("interest_expense"), _doc_ids(facts))


def derive_diluted_shares(facts, overrides) -> AssumptionRange:
    observations, collisions = _observations(facts, "diluted")
    return build_level("diluted_shares", "thousands", observations, collisions,
                       overrides.get("diluted_shares"), _doc_ids(facts))


def derive_geographic_revenue(facts, overrides) -> AssumptionRange:
    """Revenue by geography, for the CRP judgement. Not itself a WACC input.

    Region names are filer-specific, so facts are selected by the extraction
    target that produced them rather than by matching region wording.

    A filing can disclose SEVERAL geographic breakdowns on different axes: Uber
    reports US&CAN/LatAm/EMEA/APAC in its revenue note and US/UK/all-other in
    its segment note. Both are complete and they are not additive, so merging
    them quadruples the denominator and reports the United States at 12 percent
    of revenue when it is 49. One breakdown is chosen - the most granular - and
    stated totals are excluded so the parts sum to the whole.
    """
    by_target: dict[str, list[Observation]] = {}
    for fact in facts:
        if not (fact.source and fact.period):
            continue
        if not fact.source.target_key.startswith("geography"):
            continue
        if "total" in fact.name.lower():
            continue  # A stated total is the denominator, not a component.
        by_target.setdefault(fact.source.target_key, []).append(
            Observation(period=fact.period, value=fact.value, fact_name=fact.name)
        )

    if not by_target:
        return _blocked("geographic_revenue", "USD millions", [], [],
                        "no geographic revenue disclosed in any candidate note; "
                        "a country risk premium cannot be weighted against the mix",
                        _doc_ids(facts))

    # Most granular breakdown wins: more regions means a tighter CRP judgement.
    chosen = max(
        by_target.values(),
        key=lambda rows: len({r.fact_name.rsplit(" ", 1)[0] for r in rows}),
    )
    latest = max(o.period for o in chosen)
    return build_level("geographic_revenue", "USD millions",
                       [o for o in chosen if o.period == latest], [],
                       overrides.get("geographic_revenue"), _doc_ids(facts))

def derive_net_debt(facts, overrides) -> AssumptionRange:
    """Net debt is NOT derived. It is blocked until the analyst states a policy.

    The balance sheet reports balances, not availability. Whether short-term
    investments can service debt is a judgement about liquidity and intent,
    neither of which is a disclosed fact. Operating lease liabilities are a
    second judgement with the same shape: including them in net debt while
    leaving lease costs inside operating cash flow charges for leases twice.

    Components are surfaced so the decision is made against the numbers. The
    unrestricted cash query excludes "restricted" explicitly, because substring
    matching would otherwise return restricted balances as available cash.
    """
    override = overrides.get("net_debt")
    doc_ids = _doc_ids(facts)

    queries = (
        (("cash and cash equivalents",), ("restricted",)),
        (("short-term investments",), ()),
        (("long-term debt",), ()),
        (("restricted cash",), ()),
    )
    components, collisions = [], []
    for name_contains, exclude in queries:
        found, clashes = _observations(facts, *name_contains, exclude=exclude)
        components.extend(found)
        collisions.extend(clashes)

    if override and override.fixed_value is not None:
        return _fixed("net_debt", "USD millions", components, [], override, doc_ids)

    if collisions:
        return _blocked("net_debt", "USD millions", components, [],
                        "ambiguous fact selection: " + "; ".join(collisions), doc_ids)

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
    derive_interest_expense, derive_diluted_shares, derive_geographic_revenue,
    derive_net_debt,
)


def derive_all(facts: list[Fact], overrides: dict[str, Override]) -> list[AssumptionRange]:
    return [derive(facts, overrides) for derive in DERIVATIONS]