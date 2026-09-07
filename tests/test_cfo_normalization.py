"""P1.5 validation of the CFO normalisation engine.

The eight lettered cases are the adversarial accounting fixtures: each has a
known correct answer, and several of them assert that the engine REFUSES to
act rather than acting plausibly.
"""
import pytest

from aleph.valuation.cfo_normalization import (
    AnalystAdjustment,
    Classification,
    Coverage,
    LineRole,
    abnormality_diagnostics,
    classify_caption,
    classify_role,
    normalise_cfo,
)

# UBER_FY2024, FY2024 column, read from the filing's own reconciliation.
UBER = {
    "Depreciation and amortization": 737,
    "Bad debt expense": 61,
    "Stock-based compensation": 1796,
    "Deferred income taxes": -6027,
    "Accretion of discounts on marketable debt securities, net": -251,
    "Loss (income) from equity method investments, net": 38,
    "Unrealized (gain) loss on debt and equity securities, net": -1832,
    "Unrealized foreign currency transactions": 308,
    "Other": 88,
    "Accounts receivable": -142,
    "Prepaid expenses and other assets": -694,
    "Operating lease right-of-use assets": 196,
    "Accounts payable": 86,
    "Accrued insurance reserves": 2819,
    "Accrued expenses and other liabilities": 330,
    "Operating lease liabilities": -221,
}


class TestDirectionalRegressions:
    """Both instances of the bug, permanently pinned."""

    def test_bug_1_non_cash_reversals_are_never_removed(self):
        """First version removed every flagged line and reported Uber's FY2024
        normalised CFO as 14,688 against 7,137 - a 106% inflation."""
        r = normalise_cfo(7137, UBER, "FY2024")
        assert r.normalised_cfo == pytest.approx(7137.0)
        assert r.normalised_cfo != pytest.approx(14688.0)

    def test_bug_2_a_restructuring_add_back_is_not_removed_either(self):
        """Second version kept restructuring in the removable set, so a
        non-cash accrual being reversed was subtracted, understating CFO by
        400. An add-back is never removed, whatever it is called."""
        r = normalise_cfo(7137, {**UBER, "Restructuring charges": 400}, "FY2024")
        assert r.normalised_cfo == pytest.approx(7137.0)
        assert r.normalised_cfo != pytest.approx(6737.0)
        assert classify_caption("Restructuring charges")[0] \
            is Classification.NON_CASH_REVERSAL


class TestLineRoles:
    """Subtotals and balances are not adjustments."""

    @pytest.mark.parametrize("caption,role", [
        ("Net cash provided by operating activities", LineRole.SUBTOTAL),
        ("Net increase in cash and cash equivalents", LineRole.SUBTOTAL),
        ("Net income (loss)", LineRole.STARTING_POINT),
        ("Cash, cash equivalents, and restricted cash, beginning of period",
         LineRole.BALANCE),
        ("Depreciation and amortization", LineRole.ADJUSTMENT),
    ])
    def test_roles(self, caption, role):
        assert classify_role(caption) is role

    def test_subtotals_do_not_pollute_the_uncertain_weight(self):
        """They previously did, inflating the measure used to decide whether
        the normalisation could be trusted."""
        noisy = {**UBER,
                 "Net cash provided by operating activities": 7137,
                 "Cash, cash equivalents, and restricted cash, end of period": 8610}
        clean = normalise_cfo(7137, UBER, "FY2024")
        with_noise = normalise_cfo(7137, noisy, "FY2024")
        assert with_noise.uncertain_weight == pytest.approx(clean.uncertain_weight)


class TestAdversarialCases:
    """The eight lettered cases."""

    def test_case_a_clean_cfo_needs_no_adjustment(self):
        r = normalise_cfo(1000, {"Depreciation and amortization": 100}, "FY2024")
        assert r.removed == 0.0
        assert r.normalised_cfo == pytest.approx(1000.0)

    def test_case_b_a_one_time_cash_settlement_needs_an_analyst(self):
        """The engine cannot find this in the statement - measured: zero of 71
        captions across six filings name a one-time cash cost. It enters as an
        override, and then it moves the number."""
        paid = AnalystAdjustment(
            caption="Litigation settlement paid", amount=-500.0,
            fiscal_year="FY2024", reason="one-time, disclosed in Note 14",
            source="10-K Note 14")
        r = normalise_cfo(1000, {"Depreciation and amortization": 100}, "FY2024",
                          analyst_adjustments=(paid,))
        assert r.normalised_cfo == pytest.approx(1500.0)

    def test_case_b_negative_control_without_the_override_nothing_moves(self):
        """A caption naming a settlement is still an add-back, so it changes
        nothing on its own. This is what makes case B a real capability and
        not caption-matching in disguise."""
        r = normalise_cfo(1000, {"Litigation settlement charge": 500}, "FY2024")
        assert r.normalised_cfo == pytest.approx(1000.0)

    def test_case_c_restructuring_cash_payment_via_override(self):
        cash = AnalystAdjustment("Restructuring cash paid", -300.0, "FY2024",
                                 "exit of one market, not expected to repeat")
        r = normalise_cfo(1000, {"Depreciation and amortization": 100}, "FY2024",
                          analyst_adjustments=(cash,))
        assert r.normalised_cfo == pytest.approx(1300.0)

    def test_case_d_a_working_capital_release_is_not_silently_normalised(self):
        """It is real cash. It is reported by weight and left in CFO."""
        r = normalise_cfo(1000, {"Accounts receivable": 600}, "FY2024")
        assert r.normalised_cfo == pytest.approx(1000.0)
        assert r.by_classification(Classification.WORKING_CAPITAL)
        assert any("working capital contributes" in n for n in r.notes)

    def test_case_e_a_deferred_tax_benefit_is_not_adjusted_either_way(self):
        r = normalise_cfo(7137, UBER, "FY2024")
        deferred = next(a for a in r.adjustments
                        if a.caption == "Deferred income taxes")
        assert deferred.classification is Classification.NON_CASH_REVERSAL
        assert r.normalised_cfo == pytest.approx(7137.0)

    def test_case_f_an_unrealized_gain_is_not_double_adjusted(self):
        r = normalise_cfo(7137, UBER, "FY2024")
        gain = next(a for a in r.adjustments if "Unrealized (gain)" in a.caption)
        assert gain.classification is Classification.NON_CASH_REVERSAL
        assert r.normalised_cfo == pytest.approx(r.reported_cfo)

    def test_case_g_sbc_stays_separately_identifiable(self):
        r = normalise_cfo(7137, UBER, "FY2024")
        sbc = next(a for a in r.adjustments
                   if a.caption == "Stock-based compensation")
        assert sbc.classification is Classification.RECURRING
        assert "stock-based compensation" in sbc.reason

    def test_case_h_investing_captions_are_not_treated_as_operating(self):
        """Acquisition cash flow belongs to investing. Handed in here, it must
        not silently become an operating adjustment that moves CFO.

        The engine refuses outright, which is better than the pass this test
        first asserted: an unrecognised line twice the size of CFO means the
        composition is not understood, and returning a tidy 1,000 would have
        been a number produced over evidence nobody could account for. What
        matters is that the 2,000 never reached the arithmetic.
        """
        r = normalise_cfo(1000, {"Acquisitions, net of cash acquired": -2000},
                          "FY2024")
        assert r.sufficient is False
        assert r.normalised_cfo is None
        assert r.coverage is Coverage.INSUFFICIENT
        assert r.removed == 0.0
        assert "Acquisitions, net of cash acquired" in r.unmatched_captions

    def test_case_h_an_immaterial_investing_line_still_does_not_move_cfo(self):
        """The same caption, small enough to stay inside the budget: coverage
        holds, and CFO is still untouched."""
        r = normalise_cfo(10_000, {"Depreciation and amortization": 500,
                                   "Acquisitions, net of cash acquired": -100},
                          "FY2024")
        assert r.sufficient
        assert r.normalised_cfo == pytest.approx(10_000.0)
        assert r.removed == 0.0


class TestCoverage:
    def test_uber_has_high_coverage_and_that_is_not_a_clean_bill(self):
        r = normalise_cfo(7137, UBER, "FY2024")
        assert r.coverage is Coverage.HIGH
        assert any("says nothing about whether this year is economically"
                   in n for n in r.notes)

    def test_no_adjustment_identified_is_distinguished_from_none_required(self):
        r = normalise_cfo(7137, UBER, "FY2024")
        assert any("NO_ADJUSTMENT_IDENTIFIED" in n for n in r.notes)
        assert any("not evidence of a clean year" in n for n in r.notes)

    def test_coverage_degrades_as_unclassified_weight_rises(self):
        high = normalise_cfo(1000, {"Depreciation": 500}, "FY2024")
        medium = normalise_cfo(1000, {"Depreciation": 500, "Zorble": 60}, "FY2024")
        low = normalise_cfo(1000, {"Depreciation": 500, "Zorble": 150}, "FY2024")
        assert (high.coverage, medium.coverage, low.coverage) == (
            Coverage.HIGH, Coverage.MEDIUM, Coverage.LOW)

    def test_above_the_budget_it_refuses(self):
        r = normalise_cfo(1000, {"Mystery item": 500}, "FY2024")
        assert r.coverage is Coverage.INSUFFICIENT
        assert r.sufficient is False
        assert r.normalised_cfo is None
        assert "NORMALIZATION_INSUFFICIENT" in r.reason
        assert "do not estimate" in r.reason.lower()


class TestAbnormalityDiagnostics:
    def test_uber_cfo_is_flagged_as_outside_its_own_prior_range(self):
        """FY2025 CFO of 10,099 against 642 / 3,585 / 7,137."""
        d = abnormality_diagnostics(
            {"FY2022": 642, "FY2023": 3585, "FY2024": 7137, "FY2025": 10099})
        assert d.is_outside_prior_range
        assert d.historical_median == pytest.approx(3585)
        assert "Diagnostic only" in d.verdict

    def test_a_normal_year_is_not_flagged(self):
        d = abnormality_diagnostics(
            {"FY2022": 1000, "FY2023": 1100, "FY2024": 1050})
        assert not d.is_outside_prior_range

    def test_a_short_history_says_so_rather_than_reporting_a_deviation(self):
        d = abnormality_diagnostics({"FY2023": 100, "FY2024": 900})
        assert d.historical_median is None
        assert "history too short" in d.verdict

    def test_nothing_is_adjusted_on_this_basis(self):
        """The diagnostic must not be wired to the number. Uber's CFO is
        abnormal AND its normalised CFO equals reported."""
        d = abnormality_diagnostics(
            {"FY2022": 642, "FY2023": 3585, "FY2024": 7137, "FY2025": 10099})
        r = normalise_cfo(7137, UBER, "FY2024")
        assert d.is_outside_prior_range
        assert r.normalised_cfo == pytest.approx(r.reported_cfo)


class TestProvenance:
    def test_every_line_carries_year_unit_role_and_reason(self):
        r = normalise_cfo(7137, UBER, "FY2024", doc_id="UBER_FY2024",
                          quotes={"Deferred income taxes":
                                  "Deferred income taxes (441) 26 (6,027)"})
        for line in r.lines:
            assert line.fiscal_year == "FY2024"
            assert line.unit == "USD millions"
            assert line.reason and line.doc_id == "UBER_FY2024"
        deferred = next(a for a in r.lines if a.caption == "Deferred income taxes")
        assert "(6,027)" in deferred.quote

    def test_analyst_adjustments_require_a_reason(self):
        adj = AnalystAdjustment("Settlement", -500.0, "FY2024", "one-time")
        assert adj.reason

    def test_zero_cfo_does_not_divide_by_zero(self):
        r = normalise_cfo(0.0, {"Depreciation": 100.0}, "FY2024")
        assert r.weight(r.lines[0]) == float("inf")
