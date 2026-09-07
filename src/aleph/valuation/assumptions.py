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
from dataclasses import dataclass
from itertools import combinations
from statistics import median

from ..infra.units import resolve_scale
from ..schemas.evidence import Fact
from ..schemas.valuation import AssumptionRange, Observation, Override


@dataclass(frozen=True)
class DispersionLimit:
    """How far a quantity's observations may spread before a summary is unsafe.

    In the QUANTITY'S OWN UNITS - percentage points for a rate - never as a
    ratio to the median. A relative limit divides by the median, so it tightens
    without limit as the median approaches zero and says nothing about
    economic materiality: under the old global MAX_RELATIVE_SPREAD = 1.0,
    tax rates of 1.9% and 9.2% (7.3 points apart) exceeded the limit at 1.3x
    while 45% and 52% would have passed comfortably (ISSUES.md #13).

    The span is a judgement, and is written here with its reasoning rather
    than left as a bare number, which is the whole difference from the
    constant it replaces - nobody ever recorded why that one was 1.0.
    """
    span: float
    unit: str
    rationale: str


# One limit per TREND quantity, declared beside the derivation that uses it.
DISPERSION_LIMITS = {
    "revenue_growth": DispersionLimit(
        span=12.0, unit="percentage points",
        rationale=(
            "Calibrated against every filing this project derives growth from, "
            "not chosen in the abstract. Observed spans: UBER_FY2025 0.3, "
            "UBER_FY2024 1.0, DASH_FY2025 3.8, DASH_FY2024 7.0, LYFT_FY2025 "
            "22.2, LYFT_FY2024 23.9 percentage points. Nothing lands between "
            "7.0 and 22.2 - a factor of three with no filing in it - so 12.0 "
            "sits in an empty gap with 5 points of margin below and 10 above, "
            "and is not knife-edge on anything measured. It reproduces the "
            "existing behaviour exactly: Uber and DoorDash derive, Lyft blocks "
            "in both years. Lyft's own override already records why that block "
            "is right - 31.4% and 9.2% are not draws from one distribution."
        ),
    ),
    "effective_tax_rate": DispersionLimit(
        span=21.0, unit="percentage points",
        rationale=(
            "Anchored on the US federal statutory rate: periods spanning more "
            "than the entire statutory rate are not describing one tax regime, "
            "and a median across them would be arithmetic, not a rate. "
            "NEVER REACHED on any filing measured - UBER_FY2024/FY2025, "
            "LYFT_FY2024/FY2025 and DASH_FY2025 all block on sign change "
            "first, which is checked before any span. #13's own motivating "
            "example (1.9% and 9.2% blocked at 1.3x) no longer reproduces for "
            "that reason. Declared anyway rather than omitted, so a future "
            "filer with same-signed rates meets a stated limit instead of none."
        ),
    ),
}

# Rounding slack when checking a set of components against a stated total.
# Measured on every geography breakdown extracted this session (Uber's two
# breakdowns, both fiscal years; Lyft's; DoorDash's): every one sums to its
# stated total exactly, to the unit the filing reports in. This tolerance
# exists for filings that round components independently of the total, not
# because slack was observed here.
TOTAL_REVENUE_TOLERANCE = 0.005


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
            period=fact.period, value=fact.value, fact_name=fact.name,
            unit=fact.unit,
        )

    return [found[period] for period in sorted(found)], collisions


def _dispersion_problem(name: str, values: list[float]) -> str | None:
    """Return why a set of observations cannot be summarised, or None.

    Sign change is checked first and needs no limit: a set spanning zero has
    no meaningful median regardless of how wide it is. The span check that
    follows is absolute, in the quantity's own units, so a median near zero
    no longer makes the test arbitrarily strict - the "median is zero" branch
    the relative test needed is gone with the division that required it.

    A quantity with no declared limit does not silently pass. Declaring the
    limit is part of declaring the derivation.
    """
    if len(values) < 2:
        return None
    if any(v > 0 for v in values) and any(v < 0 for v in values):
        return "values change sign across periods"

    limit = DISPERSION_LIMITS.get(name)
    if limit is None:
        return (f"no dispersion limit is declared for '{name}'. Add one to "
                "DISPERSION_LIMITS, in the quantity's own units, with the "
                "reasoning that sets it")

    span = max(values) - min(values)
    if span > limit.span:
        return (f"observations span {span:,.1f} {limit.unit} "
                f"(limit {limit.span:,.1f}). {limit.rationale}")
    return None


def _scale_mismatch(observations: list[Observation]) -> str | None:
    """Return why the observations do not share one unit scale, or None.

    Scale is compared, not the unit string: "thousands" and "thousands of
    shares" are the same scale and must not block each other. Comparison
    uses the same token logic bridge.to_millions uses (infra.units), so the
    two can never disagree about what a unit means. Percent/decimal
    quantities and any observation whose unit names no recognised scale
    token are excluded from the comparison rather than treated as a
    mismatch: an unresolved unit is unverifiable, not wrong - the same
    fail-safe rule check_unit_matches_source applies at the extraction gate.
    """
    scales: dict[float, list[Observation]] = {}
    for o in observations:
        scale = resolve_scale(o.unit)
        if scale is None:
            continue
        scales.setdefault(scale, []).append(o)
    if len(scales) <= 1:
        return None
    groups = [f"x{scale} ({', '.join(o.fact_name for o in group)})"
              for scale, group in sorted(scales.items())]
    return "observations do not share one unit scale: " + "; ".join(groups)


def _derive_unit(observations: list[Observation], fallback: str) -> str:
    """Use the unit the observations themselves carry, not a hardcoded label.

    _scale_mismatch has already guaranteed the kept observations agree on
    scale, so any one of their unit strings names the group correctly.
    Falls back to the caller's declared unit only when no observation
    carries one - true for Python-computed ratios like growth and tax rate,
    which have no scale of their own to report.
    """
    for o in observations:
        if o.unit:
            return o.unit
    return fallback


def _blocked(name, unit, observations, excluded, reason, doc_ids) -> AssumptionRange:
    return AssumptionRange(
        name=name, unit=unit, status="blocked",
        observations=observations, excluded=excluded,
        method="none", rationale=f"BLOCKED: {reason}", doc_ids=doc_ids,
    )


def _fixed(name, observations, excluded, override, doc_ids) -> AssumptionRange:
    """Build an overridden range. unit comes from the override itself, in
    the unit the filing states - the engine converts, the analyst does not."""
    return AssumptionRange(
        name=name, unit=override.unit, status="overridden",
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
        return _fixed(name, observations, excluded, override, doc_ids)
    if not kept:
        reason = (f"{len(excluded)} of {len(observations)} periods excluded by override"
                  if excluded else
                  "no facts extracted for this quantity; check extraction gates")
        return _blocked(name, unit, observations, excluded, reason, doc_ids)

    mismatch = _scale_mismatch(kept)
    if mismatch:
        return _blocked(name, unit, observations, excluded, mismatch, doc_ids)

    values = [o.value for o in kept]
    problem = _dispersion_problem(name, values)
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
        name=name, unit=_derive_unit(kept, unit),
        status="overridden" if override else "derived",
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
        return _fixed(name, observations, excluded, override, doc_ids)
    if not kept:
        return _blocked(name, unit, observations, excluded,
                        "no facts extracted for this quantity", doc_ids)

    mismatch = _scale_mismatch(kept)
    if mismatch:
        return _blocked(name, unit, observations, excluded, mismatch, doc_ids)

    latest = kept[-1]
    return AssumptionRange(
        name=name, unit=_derive_unit(kept, unit),
        status="overridden" if override else "derived",
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


def _unmatched_note(facts: list[Fact], target_key: str, matched: set[str],
                    where: str) -> str:
    """Name the facts a derivation's queries did not match, so a block prints
    the whole evidentiary basis rather than only the part it recognised.

    ISSUES.md #26: a block is not protection if the evidence it prints is
    incomplete. DoorDash's balance sheet says "Short-term marketable
    securities" where Uber and Lyft say "short-term investments", and its
    tax note says "Total provision for (benefit from) income taxes" where the
    query looks for "provision for income taxes". In both cases the fact was
    extracted and gate-verified and simply invisible to a substring written
    against two filers' wording.

    The queries are DELIBERATELY not widened to match those spellings. A
    longer substring list only relocates the bug to the next filer that
    phrases it a third way. Surfacing the miss is the fix; the query stays
    exactly as narrow, and exactly as fallible, as it was.
    """
    unmatched = [
        f for f in facts
        if f.source and f.source.target_key == target_key and f.name not in matched
    ]
    if not unmatched:
        return ""
    return (f" Extracted from {where} but matched by none of the queries "
            "above: " + "; ".join(f"{f.name}={f.value:,.0f}" for f in unmatched))


def _total_revenue_by_source(facts: list[Fact]) -> dict[str, dict[str, tuple]]:
    """Every 'total revenue' fact, grouped period -> target_key -> (value, unit).

    Deliberately excludes nothing. This is the one place that WANTS the
    restatements derive_growth filters out, because agreement between them
    is the thing being checked.
    """
    grouped: dict[str, dict[str, tuple]] = {}
    for fact in facts:
        if fact.period is None or not fact.source:
            continue
        if "total revenue" not in fact.name.lower():
            continue
        key = fact.source.target_key or f"{fact.source.kind}:{fact.source.ref}"
        grouped.setdefault(fact.period, {})[key] = (fact.value, fact.unit)
    return grouped


def _revenue_source_disagreements(facts: list[Fact]) -> list[str]:
    """Compare total revenue across the independent sources that state it.

    A filing states total revenue in at least two places: the income
    statement, and the Total row of the segment and geography notes. They
    agree on every filing measured (all six, every period) - which is the
    point. This check costs nothing while they agree and is the only thing
    that would see the day they do not; derive_growth excludes the note
    totals rather than reconciling them, so a disagreement there is
    currently invisible to every other step (ISSUES.md #20).

    The tolerance is the filing's OWN reported precision, not an invented
    constant (the failure #13 names): two values agree when they differ by
    less than one unit of the COARSER of the two declared scales. A figure
    printed in millions cannot distinguish anything finer than a million.
    """
    problems = []
    for period, sources in sorted(_total_revenue_by_source(facts).items()):
        if len(sources) < 2:
            continue
        scaled = {}
        for key, (value, unit) in sources.items():
            scale = resolve_scale(unit)
            if scale is None:            # unresolved unit: not comparable
                continue
            scaled[key] = (value * scale, scale, value, unit)
        if len(scaled) < 2:
            continue
        coarsest = max(entry[1] for entry in scaled.values())
        values = [entry[0] for entry in scaled.values()]
        if max(values) - min(values) < coarsest:
            continue
        listing = "; ".join(
            f"{key} states {value:,.0f} {unit}"
            for key, (_, _, value, unit) in sorted(scaled.items())
        )
        problems.append(f"{period}: {listing}")
    return problems


def derive_growth(facts, overrides) -> AssumptionRange:
    """Year-over-year revenue growth from the income statement total.

    Geographic and segment breakdowns restate the same total under different
    labels, so they are excluded here rather than allowed to collide with it.
    Excluding them means nothing else compares them, so they are cross-checked
    against the statement total first - see _revenue_source_disagreements.
    """
    disagreements = _revenue_source_disagreements(facts)
    if disagreements:
        return _blocked(
            "revenue_growth", "percent", [], [],
            "BLOCKED: the filing's independent statements of total revenue do "
            "not agree, so which one growth is measured on changes the answer. "
            + " | ".join(disagreements)
            + ". Resolve which source is authoritative before deriving growth.",
            _doc_ids(facts),
        )

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
    QUERIES = ("effective income tax rate", "provision for income taxes",
               "before income taxes")

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

    override = overrides.get("effective_tax_rate")
    if not computed and not override:
        # Without this, build_trend reports "no facts extracted for this
        # quantity; check extraction gates" - which sends the analyst to the
        # gates when the gates worked and a substring did not. Measured on
        # DASH_FY2024: three "Total provision for (benefit from) income taxes"
        # facts are extracted and gate-verified, and no query sees them.
        matched = {
            f.name for q in QUERIES for f in facts if q in f.name.lower()
        }
        return _blocked(
            "effective_tax_rate", "percent", [], [],
            "no tax rate could be stated or computed. Queries tried: "
            + "; ".join(repr(q) for q in QUERIES) + "."
            + _unmatched_note(facts, "taxes", matched, "the tax note")
            + ". Facts listed there were extracted and passed every gate - a "
            "query did not match their wording, so this is not an extraction "
            "failure. Set fixed_value in data/overrides.json with a rationale.",
            _doc_ids(facts),
        )

    return build_trend("effective_tax_rate", "percent", computed,
                       clash_a + clash_b, override, _doc_ids(facts))


def derive_operating_cash_flow(facts, overrides) -> AssumptionRange:
    observations, collisions = _observations(facts, "operating activities")
    # "USD millions" is a fallback label only, used if no observation
    # carries a unit. The declared unit comes from the facts themselves.
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


def derive_stock_based_compensation(facts, overrides) -> AssumptionRange:
    """SBC is a cash cost, subtracted from FCFF at full value (see bridge.py).

    "capitalized" excludes DoorDash's second line, "Stock-based compensation
    included in capitalized software and website development costs" - that
    portion was capitalised into an asset and already leaves through capex,
    so subtracting it here too would double count it. The same exclude=
    mechanism derive_net_debt uses for "restricted".
    """
    observations, collisions = _observations(
        facts, "stock-based compensation", exclude=("capitalized",)
    )
    return build_level("stock_based_compensation", "USD millions", observations,
                       collisions, overrides.get("stock_based_compensation"),
                       _doc_ids(facts))


def derive_diluted_shares(facts, overrides) -> AssumptionRange:
    observations, collisions = _observations(facts, "diluted")
    return build_level("diluted_shares", "thousands", observations, collisions,
                       overrides.get("diluted_shares"), _doc_ids(facts))


def _stated_total_revenue(facts: list[Fact], period: str) -> float | None:
    """Total revenue from the income statement, to check geography against.

    Selected by target (statement:operations), not by wording: the geography
    note's own restated "Total revenue by geography" line uses similar words
    and would collide with an exact-string match. Returns None, not a guess,
    if the operations target did not produce exactly one figure for the
    period - an unreconcilable geography breakdown is then reported as
    unverifiable rather than silently passed.
    """
    candidates = [
        f for f in facts
        if f.period == period and f.source
        and f.source.target_key == "operations"
        and "total revenue" in f.name.lower()
    ]
    return candidates[0].value if len(candidates) == 1 else None


def _split_geographic_partitions(
    rows: list[Observation], total: float | None
) -> tuple[list[Observation] | None, str | None]:
    """Reconcile one period's geography observations against stated revenue.

    A filing can disclose SEVERAL geographic breakdowns of the SAME revenue:
    Uber reports US&CAN/LatAm/EMEA/APAC and US/UK/all-other. Both are
    complete and not additive - merging them reports the United States at 12
    percent of revenue when it is 49. Previously this was avoided by picking
    the more granular EXTRACTION TARGET, which worked only as long as the two
    breakdowns arrived from two different notes. Measured on UBER_FY2025:
    Uber dropped its standalone Revenue note and merged both breakdowns into
    Note 13, so the two breakdowns now arrive from ONE target, and the
    target-based split has nothing left to distinguish them by.

    Reconciling against the filing's OWN stated total revenue does not
    depend on which note or target a component came from. If the full set
    already sums to the total, it is one clean breakdown. If it sums to
    roughly twice the total, exactly two breakdowns are mixed together; the
    two halves are found by search (only two-way splits are attempted - the
    only case measured) and the more granular one is kept. Anything else -
    no two-way split reconciles, or the search finds more than one distinct
    reconciling split - is not guessed at; the caller blocks.

    Only two-region-or-larger halves are searched (`range(2, ...)`): a
    single fact equal to the total is not a "breakdown" of anything, so a
    1-versus-n split is deliberately never tested. If a filer ever really
    does disclose revenue as one region plus a residual, this function finds
    no reconciling two-way split and the caller blocks, naming what it
    found - the correct behaviour for a shape genuinely unmeasured, not a
    silent gap.

    Returns (chosen_observations, note) on success, note is None if no split
    was needed. Returns (None, reason) when nothing could be reconciled.
    """
    if total is None:
        return None, "no single stated total revenue found to check against"
    if not rows:
        return None, "no geographic revenue observations for this period"

    tolerance = max(1.0, total * TOTAL_REVENUE_TOLERANCE)

    whole_sum = sum(o.value for o in rows)
    if abs(whole_sum - total) <= tolerance:
        return rows, None  # Already one coherent breakdown.

    seen_pairs: set[frozenset[frozenset[str]]] = set()
    splits_found = []
    for size in range(2, len(rows) - 1):
        for group in combinations(rows, size):
            if abs(sum(o.value for o in group) - total) > tolerance:
                continue
            complement = [o for o in rows if o not in group]
            if abs(sum(o.value for o in complement) - total) > tolerance:
                continue
            # Both halves independently reconcile to the stated total: two
            # partitions of the same revenue, not one. Identity is the
            # UNORDERED pair of half-names, not (group, complement) as
            # lists: when the two halves are the same size, both iteration
            # orders satisfy "len(group) >= len(complement)", so an
            # ordered-list key records the one real split twice and blocks
            # on a manufactured disagreement. A frozenset of frozensets
            # cannot be fooled by which half the loop happened to call
            # "group".
            key = frozenset((
                frozenset(o.fact_name for o in group),
                frozenset(o.fact_name for o in complement),
            ))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            # More regions wins on a real size difference. A genuine tie is
            # broken by sorted names - not "more correct" than the other
            # order, just deterministic, so the same input never resolves
            # differently between runs.
            if len(group) != len(complement):
                chosen, other = (list(group), complement) if len(group) > len(complement) \
                    else (complement, list(group))
            else:
                names_a = tuple(sorted(o.fact_name for o in group))
                names_b = tuple(sorted(o.fact_name for o in complement))
                chosen, other = (list(group), complement) if names_a < names_b \
                    else (complement, list(group))
            splits_found.append((chosen, other))

    if len(splits_found) == 1:
        chosen, other = splits_found[0]
        return chosen, (
            f"two geographic breakdowns of the same revenue were found in "
            f"the source (each reconciles to the stated total {total:,.0f}); "
            f"selected the more granular one, {len(chosen)} regions "
            f"({', '.join(o.fact_name for o in chosen)}), over "
            f"{len(other)} regions ({', '.join(o.fact_name for o in other)})"
        )

    if not splits_found:
        return None, (
            f"observations sum to {whole_sum:,.0f}, neither the stated total "
            f"revenue {total:,.0f} nor a two-way split of it; cannot "
            f"determine which facts form one coherent breakdown"
        )

    return None, (
        f"{len(splits_found)} different two-way splits each reconcile to the "
        f"stated total {total:,.0f}; cannot determine which is the real "
        "breakdown without guessing"
    )


def derive_geographic_revenue(facts, overrides) -> AssumptionRange:
    """Revenue by geography, for the CRP judgement. Not itself a WACC input.

    Region names are filer-specific, so components are gathered from every
    extraction target whose key starts with "geography" rather than by
    matching region wording. Selecting ONE coherent breakdown among possibly
    several is done by reconciling against the filing's own stated total
    revenue - see _split_geographic_partitions - not by which target or note
    a component happened to come from.
    """
    all_rows: list[Observation] = []
    for fact in facts:
        if not (fact.source and fact.period):
            continue
        if not fact.source.target_key.startswith("geography"):
            continue
        if "total" in fact.name.lower():
            continue  # A stated total is the denominator, not a component.
        all_rows.append(Observation(period=fact.period, value=fact.value,
                                    fact_name=fact.name, unit=fact.unit))

    if not all_rows:
        return _blocked("geographic_revenue", "USD millions", [], [],
                        "no geographic revenue disclosed in any candidate note; "
                        "a country risk premium cannot be weighted against the mix",
                        _doc_ids(facts))

    latest = max(o.period for o in all_rows)
    latest_rows = [o for o in all_rows if o.period == latest]
    total = _stated_total_revenue(facts, latest)
    chosen, note = _split_geographic_partitions(latest_rows, total)

    if chosen is None:
        listing = "; ".join(f"{o.fact_name}={o.value:,.0f}" for o in latest_rows)
        return _blocked(
            "geographic_revenue", "USD millions", latest_rows, [],
            f"geographic breakdown does not reconcile to stated total "
            f"revenue: {note}. Observations: {listing}.",
            _doc_ids(facts),
        )

    result = build_level("geographic_revenue", "USD millions", chosen, [],
                         overrides.get("geographic_revenue"), _doc_ids(facts))
    if note:
        return result.model_copy(update={"rationale": f"{result.rationale} {note}."})
    return result

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

    Scoped to the BALANCE SHEET target, and not by preference. Net debt is a
    balance, and the cash flow statement names the same words in captions
    that are not balances at all: "Net increase (decrease) in cash, cash
    equivalents, and restricted cash" and the beginning and end of period
    lines all contain "restricted cash". Measured on DASH_FY2024 the moment
    those captions began being extracted: eight collisions, and net_debt
    blocked as ambiguous instead of on its policy. Reading a stock from a
    flow statement was always wrong; until those captions existed, nothing
    made it visible.
    """
    override = overrides.get("net_debt")
    doc_ids = _doc_ids(facts)

    balance_sheet_only = [
        f for f in facts
        if f.source and f.source.target_key == "balance_sheet"
    ]

    queries = (
        (("cash and cash equivalents",), ("restricted",)),
        (("short-term investments",), ()),
        (("long-term debt",), ()),
        (("restricted cash",), ()),
    )
    components, collisions = [], []
    for name_contains, exclude in queries:
        found, clashes = _observations(
            balance_sheet_only, *name_contains, exclude=exclude)
        components.extend(found)
        collisions.extend(clashes)

    if override and override.fixed_value is not None:
        return _fixed("net_debt", components, [], override, doc_ids)

    if collisions:
        return _blocked("net_debt", "USD millions", components, [],
                        "ambiguous fact selection: " + "; ".join(collisions), doc_ids)

    listing = [f"{o.fact_name}={o.value:,.0f}" for o in components] or ["none extracted"]

    # The block above is correct; the danger is a component list an analyst
    # reads as complete when it is not. Measured on DASH_FY2024: the balance
    # sheet target extracted "Short-term marketable securities" - gate-
    # verified, sitting in `facts` the whole time - and none of the four
    # queries above matched it, because DoorDash's own wording differs from
    # the one every query was written against. The queries are deliberately
    # NOT widened to catch this one phrasing: a wider substring list only
    # relocates the same bug to the next filer that renames something. This
    # line is the fix - it surfaces whatever the queries miss, whatever the
    # wording turns out to be, without needing to have seen that wording first.
    matched_names = {
        fact.name
        for name_contains, exclude in queries
        for fact in facts
        if all(token.lower() in fact.name.lower() for token in name_contains)
        and not any(token.lower() in fact.name.lower() for token in exclude)
    }
    unmatched_note = _unmatched_note(
        facts, "balance_sheet", matched_names, "the balance sheet"
    )

    return _blocked(
        "net_debt", "USD millions", components, [],
        "net debt requires a stated cash and debt policy, not a derivation. "
        "Restricted cash is unavailable by definition; cash equivalents are "
        "available; short-term investments and operating lease liabilities are "
        "analyst judgements. Components found: " + "; ".join(listing) +
        "." + unmatched_note +
        " Set fixed_value in data/overrides.json with the policy as rationale.",
        doc_ids,
    )


DERIVATIONS = (
    derive_growth, derive_tax_rate, derive_operating_cash_flow, derive_capex,
    derive_interest_expense, derive_stock_based_compensation, derive_diluted_shares,
    derive_geographic_revenue, derive_net_debt,
)


def derive_all(facts: list[Fact], overrides: dict[str, Override]) -> list[AssumptionRange]:
    return [derive(facts, overrides) for derive in DERIVATIONS]
