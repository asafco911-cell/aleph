"""Tests for the accounting normalisation module.

Every expected number here is computed by hand in the test body or taken
from a real filing, never copied from a previous run of the code under test.
A test whose expectation came from the implementation proves only that the
implementation is stable, not that it is right.
"""
import pytest

from aleph.valuation.normalization import (
    NON_RECURRING_MARKERS,
    adjusted_ebit,
    capitalise_rd,
    flag_non_recurring,
    invested_capital,
    roic,
    sbc_adjusted_fcff,
)


class TestCapitaliseRD:
    def test_schedule_matches_the_hand_calculation(self):
        """L=3, spend 100/200/300/400. Worked by hand, not read off a run.

        At the end of FY2024, each vintage carries (L - age)/L of its spend:
            FY2024 age 0  400 x 3/3 = 400,  no amortisation yet
            FY2023 age 1  300 x 2/3 = 200,  amortises 300/3 = 100
            FY2022 age 2  200 x 1/3 =  66.67, amortises 200/3 = 66.67
            FY2021 age 3  100 x 0/3 =   0,  amortises 100/3 = 33.33
        asset = 400 + 200 + 66.67 = 666.67; amortisation = 200.
        """
        history = {"FY2021": 100.0, "FY2022": 200.0, "FY2023": 300.0, "FY2024": 400.0}
        result = capitalise_rd(history, "FY2024", amortisation_years=3)

        assert result.unamortised_asset == pytest.approx(666.667, abs=0.01)
        assert result.amortisation == pytest.approx(200.0, abs=0.01)
        assert result.ebit_uplift == pytest.approx(200.0, abs=0.01)
        assert result.by_vintage["FY2021"] == pytest.approx(0.0)
        assert result.by_vintage["FY2023"] == pytest.approx(200.0)

    def test_flat_spending_produces_no_uplift(self):
        """The property that makes the adjustment meaningful.

        When R&D is flat, capitalising it changes the balance sheet but not
        the income statement: this year's spend exactly equals the
        amortisation of the previous years. An implementation that showed an
        uplift on flat spending would be double-counting.
        """
        history = {f"FY{y}": 500.0 for y in range(2020, 2025)}
        result = capitalise_rd(history, "FY2024", amortisation_years=3)
        assert result.ebit_uplift == pytest.approx(0.0, abs=1e-9)

    def test_shrinking_rd_produces_a_negative_uplift(self):
        """The negative control for the test above: the sign must follow the
        trend, not be positive by construction."""
        history = {"FY2021": 900.0, "FY2022": 600.0, "FY2023": 300.0, "FY2024": 100.0}
        result = capitalise_rd(history, "FY2024", amortisation_years=3)
        assert result.ebit_uplift < 0

    def test_a_short_history_is_reported_not_padded(self):
        """Padding missing years with zeros would understate the asset and
        overstate ROIC while looking complete."""
        result = capitalise_rd({"FY2023": 300.0, "FY2024": 400.0}, "FY2024", 3)
        assert result.note, "a truncated history must say so"
        assert "not padded with zeros" in result.note.lower()
        # Only FY2023 is available as a prior vintage: 300 x 2/3 = 200.
        assert result.unamortised_asset == pytest.approx(600.0)

    def test_one_year_amortisation_is_immediate_expensing(self):
        """L=1 must reduce to the unadjusted case: everything written off in
        a year means no asset beyond the current spend and no uplift."""
        history = {"FY2023": 300.0, "FY2024": 400.0}
        result = capitalise_rd(history, "FY2024", amortisation_years=1)
        assert result.unamortised_asset == pytest.approx(400.0)
        assert result.amortisation == pytest.approx(300.0)

    def test_rejects_a_period_it_has_no_data_for(self):
        with pytest.raises(KeyError):
            capitalise_rd({"FY2024": 100.0}, "FY2025", 3)

    def test_rejects_a_nonsensical_amortisation_period(self):
        with pytest.raises(ValueError):
            capitalise_rd({"FY2024": 100.0}, "FY2024", 0)


class TestAdjustedEbitAndROIC:
    def test_adjusted_ebit_adds_the_uplift(self):
        rd = capitalise_rd({"FY2023": 300.0, "FY2024": 400.0}, "FY2024", 3)
        assert adjusted_ebit(1000.0, rd) == pytest.approx(1000.0 + rd.ebit_uplift)

    def test_invested_capital_includes_the_rd_asset(self):
        assert invested_capital(1000.0, 4000.0, 600.0) == pytest.approx(5600.0)
        assert invested_capital(1000.0, 4000.0) == pytest.approx(5000.0)

    def test_roic_is_after_tax_over_capital(self):
        assert roic(1000.0, 0.21, 5000.0) == pytest.approx(790.0 / 5000.0)

    def test_flat_rd_lowers_roic_because_only_the_denominator_moves(self):
        """The one direction that is unconditional.

        Flat R&D produces no EBIT uplift, so the numerator is unchanged while
        the denominator gains the whole unamortised asset. ROIC must fall.
        This is the adjustment's real content for a steady-state R&D spender:
        an expensing company reports returns on capital it never recorded.
        """
        rd = capitalise_rd({f"FY{y}": 500.0 for y in range(2020, 2025)}, "FY2024", 3)
        assert rd.ebit_uplift == pytest.approx(0.0, abs=1e-9)
        before = roic(1000.0, 0.21, invested_capital(1000.0, 4000.0))
        after = roic(adjusted_ebit(1000.0, rd), 0.21,
                     invested_capital(1000.0, 4000.0, rd.unamortised_asset))
        assert after is not None and before is not None
        assert after < before

    def test_the_direction_is_not_universal_and_depends_on_the_ratios(self):
        """Guards against the plausible-sounding claim that capitalising R&D
        always lowers ROIC. It does not, and asserting that it does was this
        file's own first mistake.

        ROIC rises when the uplift is proportionally larger than the asset:
        with EBIT 1,000 and a growing R&D book, the numerator gains 20% while
        the denominator gains 13%, so the ratio goes UP. The condition is
        uplift/EBIT vs asset/capital, not a fixed direction.
        """
        history = {"FY2021": 100.0, "FY2022": 200.0, "FY2023": 300.0, "FY2024": 400.0}
        rd = capitalise_rd(history, "FY2024", 3)
        before = roic(1000.0, 0.21, invested_capital(1000.0, 4000.0))
        after = roic(adjusted_ebit(1000.0, rd), 0.21,
                     invested_capital(1000.0, 4000.0, rd.unamortised_asset))
        assert after is not None and before is not None
        assert after > before, "a fast-growing R&D book raises ROIC, it does not lower it"
        assert rd.ebit_uplift / 1000.0 > rd.unamortised_asset / 5000.0

    def test_roic_on_non_positive_capital_is_none_not_a_number(self):
        """A company financed by an accumulated deficit would otherwise post
        a spectacular return on the way to insolvency."""
        assert roic(1000.0, 0.21, 0.0) is None
        assert roic(1000.0, 0.21, -500.0) is None


class TestSBCAdjustedFCFF:
    def test_matches_the_bridge_formula_on_uber_fy2024(self):
        """The anchor's own components, read from the filing.

        UBER_FY2024: CFO 7,137, capex 242, SBC 1,796, interest 523, tax 21%.
            7,137 + 523 x 0.79 - 242 - 1,796 = 5,512.17

        5,512 is the FY2024 figure in the FCFF series ISSUES.md #29 records
        (-957, 1,927, 5,512, 8,285), which is what makes this a check against
        the pipeline rather than against itself. An earlier version of this
        docstring said capex was 805 - a number from nowhere. The assertion
        still passed, because both sides used it; only the claim about the
        filing was false. Every figure here is now traceable to an extracted
        fact: capex is "Purchases of property and equipment" = (242).
        """
        assert sbc_adjusted_fcff(7137.0, 242.0, 1796.0, 523.0, 0.21) == pytest.approx(
            5512.17, abs=0.01
        )

    def test_signs_are_normalised_so_a_negative_capex_cannot_be_added_back(self):
        """Filings print capex negative in the cash flow statement. Taking it
        at face value would ADD it to free cash flow."""
        positive = sbc_adjusted_fcff(7137.0, 242.0, 1796.0, 523.0, 0.21)
        negative = sbc_adjusted_fcff(7137.0, -242.0, -1796.0, -523.0, 0.21)
        assert positive == pytest.approx(negative)

    def test_omitting_interest_understates_fcff_by_the_after_tax_add_back(self):
        """The error the task specification's formula would have introduced.

        CFO is levered; WACC prices debt again. Dropping the add-back counts
        interest twice, and the gap is exactly I(1 - Tc).
        """
        with_interest = sbc_adjusted_fcff(7137.0, 242.0, 1796.0, 523.0, 0.21)
        without = sbc_adjusted_fcff(7137.0, 242.0, 1796.0)
        assert with_interest - without == pytest.approx(523.0 * 0.79)


class TestNonRecurringFilter:
    def test_flags_the_captions_it_knows(self):
        captions = {
            "Goodwill impairment": 1200.0,
            "Restructuring and related charges": 300.0,
            "Total revenue": 43978.0,
        }
        flagged, unmatched = flag_non_recurring(captions)
        assert set(flagged) == {"Goodwill impairment", "Restructuring and related charges"}
        assert unmatched == ["Total revenue"]

    def test_reports_what_it_did_not_match(self):
        """ISSUES.md #26: a filter that reports only its hits tells the reader
        nothing about what it missed. The unmatched list is the evidence."""
        captions = {"Provision for legal matters": 500.0, "Cost of revenue": 100.0}
        flagged, unmatched = flag_non_recurring(captions)
        assert flagged == {}
        assert unmatched == ["Cost of revenue", "Provision for legal matters"]

    def test_matching_is_case_insensitive(self):
        flagged, _ = flag_non_recurring({"IMPAIRMENT OF LONG-LIVED ASSETS": 42.0})
        assert len(flagged) == 1

    def test_nothing_is_removed_from_the_input(self):
        """It flags; the analyst decides. A filter that silently dropped rows
        would change a total nobody re-checked."""
        captions = {"Goodwill impairment": 1200.0, "Total revenue": 43978.0}
        before = dict(captions)
        flag_non_recurring(captions)
        assert captions == before

    def test_every_marker_is_lowercase(self):
        """Matching lowercases the caption, so an uppercase marker could
        never fire - a dead entry that looks live."""
        assert all(m == m.lower() for m in NON_RECURRING_MARKERS)
