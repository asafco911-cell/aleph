"""Tests for the reconciliations in assumptions.py.

_split_geographic_partitions decides whether a filing has disclosed one
geographic breakdown of revenue or several overlapping ones, by reconciling
against the stated total rather than trusting note or target boundaries.

_revenue_source_disagreements compares the independent places a filing
states total revenue against each other (ISSUES.md #20).

A financial derivation without tests is a guess.
"""
from aleph.schemas.evidence import Fact, FactSource
from aleph.schemas.valuation import Observation
from aleph.valuation.assumptions import (
    _revenue_source_disagreements,
    _split_geographic_partitions,
)


def obs(name, value):
    return Observation(period="FY2025", value=value, fact_name=name)


def revenue_fact(target_key, period, value, unit="USD millions"):
    """A gate-passed 'Total revenue' fact, as one target would produce it."""
    return Fact(
        name="Total revenue", value=value, unit=unit, period=period,
        quote=f"Total revenue $ {value:,.0f}",
        source=FactSource(doc_id="TEST_FY2025", kind="statement",
                          ref="operations", target_key=target_key, pages=[1]),
    )


def test_single_breakdown_needs_no_split():
    """Already reconciles to the total: returned as-is, no note."""
    rows = [obs("US", 6000), obs("International", 4000)]
    chosen, note = _split_geographic_partitions(rows, 10000.0)
    assert chosen is not None and {o.fact_name for o in chosen} == {"US", "International"}
    assert note is None
    print("PASS test_single_breakdown_needs_no_split")


def test_unequal_split_resolves_to_the_larger_half():
    """Measured shape: UBER_FY2025, a 4-region breakdown and a 3-region
    breakdown of the same revenue merged into one target. Found at both
    size 3 and size 4 during the search - must be recorded once, not
    reported as two competing splits."""
    # Values spaced apart deliberately, at a realistic total, so no OTHER
    # subset of the seven accidentally reconciles within the real 0.5%
    # tolerance - verified: exactly two subsets of {2..5} elements land
    # within 50 of 10,000, and they are these two.
    rows = [
        obs("US&CAN", 4100), obs("LatAm", 2700), obs("EMEA", 1900), obs("APAC", 1300),
        obs("United States", 5300), obs("United Kingdom", 3100), obs("All other", 1600),
    ]
    chosen, note = _split_geographic_partitions(rows, 10000.0)
    assert chosen is not None, "should have resolved, not blocked"
    assert {o.fact_name for o in chosen} == {"US&CAN", "LatAm", "EMEA", "APAC"}, \
        "should keep the more granular (4-region) half"
    assert note is not None and "two geographic breakdowns" in note
    print("PASS test_unequal_split_resolves_to_the_larger_half")


def test_equal_size_split_resolves_not_blocks():
    """Regression case for the tie-ordering bug: two THREE-region
    breakdowns of the same revenue. len(group) >= len(complement) is true
    in both iteration directions when the halves are the same size, so an
    ordered-list pair key recorded the one real split twice and the
    function blocked on a manufactured "2 different splits" disagreement.
    A same-size split must resolve, deterministically, not block."""
    # Same spacing discipline as the unequal-split test above: no other
    # subset accidentally reconciles within tolerance.
    rows = [
        obs("a1", 5000), obs("a2", 3000), obs("a3", 2000),
        obs("b1", 6000), obs("b2", 2500), obs("b3", 1500),
    ]
    chosen, note = _split_geographic_partitions(rows, 10000.0)
    assert chosen is not None, "an equal-sized split must resolve, not block"
    assert len(chosen) == 3
    # The tie-break (sorted names) is deterministic, not "correct" over the
    # other half - assert it picks consistently, not that "a" beats "b" for
    # any principled reason.
    again, _ = _split_geographic_partitions(rows, 10000.0)
    assert {o.fact_name for o in chosen} == {o.fact_name for o in again}, \
        "must resolve the same way on every run"
    print("PASS test_equal_size_split_resolves_not_blocks")


def test_unreconcilable_blocks():
    """Nothing sums to the total or a two-way split of it: block, don't guess."""
    rows = [obs("US", 6100), obs("International", 4000)]  # sums to 10,100, not 10,000
    chosen, note = _split_geographic_partitions(rows, 10000.0)
    assert chosen is None
    assert note is not None and "cannot determine" in note
    print("PASS test_unreconcilable_blocks")


def test_no_stated_total_blocks():
    """A missing or ambiguous stated total is reported as unverifiable, not
    guessed past."""
    rows = [obs("US", 6000), obs("International", 4000)]
    chosen, note = _split_geographic_partitions(rows, None)
    assert chosen is None
    assert note == "no single stated total revenue found to check against"
    print("PASS test_no_stated_total_blocks")


def test_agreeing_sources_report_nothing():
    """The measured case: all six filings agree on every period.

    This is the negative control for the three tests below. Without it they
    would pass just as well against a function that flagged everything.
    """
    facts = [
        revenue_fact("operations", "FY2024", 43978),
        revenue_fact("segments", "FY2024", 43978),
        revenue_fact("geography_n13", "FY2024", 43978),
        revenue_fact("operations", "FY2025", 52017),
        revenue_fact("segments", "FY2025", 52017),
    ]
    assert _revenue_source_disagreements(facts) == []
    print("PASS test_agreeing_sources_report_nothing")


def test_disagreeing_sources_are_reported():
    """A segment note whose Total differs from the income statement."""
    facts = [
        revenue_fact("operations", "FY2025", 52017),
        revenue_fact("segments", "FY2025", 51900),
    ]
    problems = _revenue_source_disagreements(facts)
    assert len(problems) == 1, problems
    assert "FY2025" in problems[0]
    assert "52,017" in problems[0] and "51,900" in problems[0], problems[0]
    print("PASS test_disagreeing_sources_are_reported")


def test_a_single_source_cannot_disagree():
    """LYFT_FY2024's real shape: no geography or segment note resolved, so
    total revenue has exactly one source. That is not a disagreement."""
    facts = [revenue_fact("operations", "FY2024", 5786016, "USD thousands")]
    assert _revenue_source_disagreements(facts) == []
    print("PASS test_a_single_source_cannot_disagree")


def test_tolerance_is_the_coarser_declared_scale():
    """Two sources in different scales, agreeing to the coarser one's own
    precision, are not a disagreement - a figure printed in millions cannot
    resolve anything finer than a million. A difference of a full million
    is, and must be caught.
    """
    within = [
        revenue_fact("operations", "FY2025", 52017, "USD millions"),
        revenue_fact("segments", "FY2025", 52_017_400, "USD thousands"),
    ]
    assert _revenue_source_disagreements(within) == [], _revenue_source_disagreements(within)

    beyond = [
        revenue_fact("operations", "FY2025", 52017, "USD millions"),
        revenue_fact("segments", "FY2025", 52_019_000, "USD thousands"),
    ]
    assert len(_revenue_source_disagreements(beyond)) == 1
    print("PASS test_tolerance_is_the_coarser_declared_scale")


if __name__ == "__main__":
    test_single_breakdown_needs_no_split()
    test_unequal_split_resolves_to_the_larger_half()
    test_equal_size_split_resolves_not_blocks()
    test_unreconcilable_blocks()
    test_no_stated_total_blocks()
    test_agreeing_sources_report_nothing()
    test_disagreeing_sources_are_reported()
    test_a_single_source_cannot_disagree()
    test_tolerance_is_the_coarser_declared_scale()
    print("\nAll tests passed.")
