"""Tests for the CFO decomposition and normalisation engine."""
import pytest

from aleph.valuation.cfo_normalization import (
    Classification,
    classify_caption,
    normalise_cfo,
)

# UBER_FY2024, FY2024 column, read from the filing's own reconciliation.
UBER_FY2024 = {
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


class TestDirection:
    def test_a_non_cash_reversal_is_kept_not_removed(self):
        """The regression this module was rewritten for.

        A first version removed every flagged adjustment and reported Uber's
        FY2024 normalised CFO as 14,688 against 7,137 reported - a 106%
        inflation from correct arithmetic. The reconciliation adjustment
        REVERSES a non-cash item out of net income; CFO is already clean of
        it, and subtracting the adjustment puts the non-cash amount back in.
        """
        result = normalise_cfo(7137, UBER_FY2024, "FY2024", doc_id="UBER_FY2024")
        assert result.sufficient
        assert result.normalised_cfo == pytest.approx(7137.0)
        assert result.normalised_cfo != pytest.approx(14688.0)

    def test_deferred_tax_and_unrealized_gains_are_classified_not_ignored(self):
        """The two lines ISSUES.md #29 named by hand must be identified -
        kept, but visible, because their swing is what moves CFO."""
        result = normalise_cfo(7137, UBER_FY2024, "FY2024")
        captions = {a.caption for a in
                    result.by_classification(Classification.NON_CASH_REVERSAL)}
        assert "Deferred income taxes" in captions
        assert "Unrealized (gain) loss on debt and equity securities, net" in captions

    def test_a_cash_non_recurring_cost_is_removed(self):
        """The negative control: something must actually be removable, or the
        engine is a no-op dressed as a normalisation."""
        recon = dict(UBER_FY2024)
        recon["Restructuring and severance charges"] = 400
        result = normalise_cfo(7137, recon, "FY2024")
        assert result.removed == pytest.approx(400.0)
        assert result.normalised_cfo == pytest.approx(7137.0 - 400.0)


class TestClassification:
    @pytest.mark.parametrize("caption,expected", [
        ("Depreciation and amortization", Classification.RECURRING),
        ("Stock-based compensation", Classification.RECURRING),
        ("Deferred income taxes", Classification.NON_CASH_REVERSAL),
        ("Unrealized gain on marketable securities", Classification.NON_CASH_REVERSAL),
        ("Goodwill impairment", Classification.NON_CASH_REVERSAL),
        ("Restructuring charges", Classification.POTENTIALLY_NON_RECURRING),
        ("Legal settlement paid", Classification.POTENTIALLY_NON_RECURRING),
        ("Accounts receivable", Classification.RECURRING),
        ("Something nobody has seen before", Classification.UNCERTAIN),
    ])
    def test_captions_land_in_the_right_class(self, caption, expected):
        assert classify_caption(caption)[0] is expected

    def test_cash_non_recurring_wins_over_non_cash_markers(self):
        """Restructuring-related asset write-offs is restructuring, not a
        write-off. Precedence is the whole content of this function."""
        assert classify_caption("Restructuring-related asset write-offs")[0] \
            is Classification.POTENTIALLY_NON_RECURRING

    def test_impairment_beats_amortisation(self):
        """Impairment of amortizable intangibles must not be read as routine
        amortisation."""
        assert classify_caption("Impairment of amortizable intangibles")[0] \
            is Classification.NON_CASH_REVERSAL

    def test_an_unknown_caption_is_never_assumed_recurring(self):
        cls, reason, _ = classify_caption("Zorble adjustment, net")
        assert cls is Classification.UNCERTAIN
        assert "never assumed recurring" in reason

    def test_working_capital_is_flagged_as_such(self):
        assert classify_caption("Accrued insurance reserves")[2] is True
        assert classify_caption("Depreciation and amortization")[2] is False


class TestInsufficiency:
    def test_too_much_unclassified_weight_refuses(self):
        """NORMALIZATION_INSUFFICIENT rather than a number with a caveat."""
        result = normalise_cfo(1000, {"Mystery item": 500}, "FY2024")
        assert result.sufficient is False
        assert result.normalised_cfo is None
        assert "NORMALIZATION_INSUFFICIENT" in result.reason
        assert "Mystery item" in result.unmatched_captions

    def test_the_reason_says_what_evidence_is_missing(self):
        result = normalise_cfo(1000, {"Mystery item": 500}, "FY2024")
        assert "do not estimate" in result.reason.lower()

    def test_uber_is_below_the_budget(self):
        """The negative control for the two tests above: a real filing must
        NOT trip the refusal, or the budget is set to block everything."""
        result = normalise_cfo(7137, UBER_FY2024, "FY2024")
        assert result.sufficient
        assert result.uncertain_weight < 0.20

    def test_an_immaterial_unknown_does_not_refuse(self):
        result = normalise_cfo(7137, {**UBER_FY2024, "Tiny unknown": 3}, "FY2024")
        assert result.sufficient


class TestProvenance:
    def test_every_adjustment_carries_amount_year_class_and_reason(self):
        result = normalise_cfo(
            7137, UBER_FY2024, "FY2024", doc_id="UBER_FY2024",
            quotes={"Deferred income taxes":
                    "Deferred income taxes (441) 26 (6,027)"},
        )
        for a in result.adjustments:
            assert a.fiscal_year == "FY2024"
            assert a.unit == "USD millions"
            assert a.reason
            assert a.doc_id == "UBER_FY2024"
        deferred = next(a for a in result.adjustments
                        if a.caption == "Deferred income taxes")
        assert "(6,027)" in deferred.quote

    def test_weights_are_relative_to_reported_cfo(self):
        result = normalise_cfo(7137, UBER_FY2024, "FY2024")
        deferred = next(a for a in result.adjustments
                        if a.caption == "Deferred income taxes")
        assert result.weight(deferred) == pytest.approx(6027 / 7137, abs=0.001)

    def test_zero_cfo_does_not_divide_by_zero(self):
        result = normalise_cfo(0.0, {"Depreciation": 100.0}, "FY2024")
        assert result.weight(result.adjustments[0]) == float("inf")
