"""Tests for the cross-statement gates.

The identity tests use REAL figures from UBER_FY2024 wherever the pipeline
extracts them, because a synthetic balance sheet that balances proves only
that addition works. The most valuable case here is the one that fails: see
TestIncomeIdentity.
"""
import pytest

from aleph.extraction.identities import (
    Figure,
    check_balance_sheet_identity,
    check_cash_rollforward,
    check_income_identity,
    check_period_alignment,
    check_unit_consistency,
    run_all,
)


def fig(name, value, period="FY2024", unit="USD millions", statement="operations"):
    return Figure(name=name, value=value, period=period, unit=unit, statement=statement)


class TestPeriodAlignment:
    def test_aligned_statements_report_nothing(self):
        """The negative control. Without it, every test below would pass
        against a function that flagged everything."""
        figures = [
            fig("Total revenue", 43978, statement="operations"),
            fig("Cash", 7003, statement="balance_sheet"),
            fig("CFO", 7137, statement="cash_flows"),
        ]
        assert check_period_alignment(figures) == []

    def test_a_statement_from_another_year_is_caught(self):
        """The LTM-over-stale-balance-sheet error, in its simplest form."""
        figures = [
            fig("CFO", 7137, period="FY2024", statement="cash_flows"),
            fig("Total assets", 51244, period="FY2023", statement="balance_sheet"),
        ]
        breaches = check_period_alignment(figures)
        assert len(breaches) == 1
        assert "no period is present on every statement" in breaches[0].detail
        assert "FY2023" in breaches[0].detail and "FY2024" in breaches[0].detail

    def test_an_undated_figure_is_reported_not_ignored(self):
        """Treating an undated number as compatible with everything is
        backwards: it can be aligned to nothing."""
        figures = [
            fig("CFO", 7137, statement="cash_flows"),
            fig("Mystery total", 1.0, period=None, statement="balance_sheet"),
        ]
        breaches = check_period_alignment(figures)
        assert any("carry no period" in b.detail for b in breaches)

    def test_overlapping_periods_are_fine(self):
        """Statements presenting several years must not be flagged merely for
        presenting several years - only for sharing none."""
        figures = [
            fig("CFO", 1, period="FY2023", statement="cash_flows"),
            fig("CFO", 2, period="FY2024", statement="cash_flows"),
            fig("Assets", 3, period="FY2024", statement="balance_sheet"),
        ]
        assert check_period_alignment(figures) == []


class TestUnitConsistency:
    def test_one_scale_reports_nothing(self):
        figures = [fig("a", 1), fig("b", 2, statement="balance_sheet")]
        assert check_unit_consistency(figures) == []

    def test_millions_against_thousands_is_caught(self):
        """ISSUES.md #15: this exact mismatch valued LYFT_FY2025 at 65,792
        against a 17.35 market price."""
        figures = [
            fig("CFO", 1168, unit="USD millions", statement="cash_flows"),
            fig("Shares", 421_000, unit="thousands", statement="operations"),
        ]
        breaches = check_unit_consistency(figures)
        assert len(breaches) == 1
        assert "2 different unit scales" in breaches[0].detail

    def test_percentages_are_excluded_rather_than_treated_as_a_mismatch(self):
        """Unresolved is unverifiable, not wrong - the same fail-safe rule
        check_unit_matches_source applies at the extraction gate."""
        figures = [
            fig("CFO", 7137, unit="USD millions"),
            fig("Effective tax rate", 21.0, unit="percent", statement="taxes"),
        ]
        assert check_unit_consistency(figures) == []


class TestBalanceSheetIdentity:
    def test_a_balancing_sheet_passes(self):
        assert check_balance_sheet_identity(51_244, 26_000, 25_244, "FY2024") == []

    def test_an_imbalance_is_caught_and_quantified(self):
        breaches = check_balance_sheet_identity(51_244, 26_000, 20_000, "FY2024")
        assert len(breaches) == 1
        assert "5,244" in breaches[0].detail
        assert breaches[0].figures == (
            "total_assets", "total_liabilities", "total_equity")

    @pytest.mark.parametrize(
        "period,assets,liabilities,parent_equity,nci,expected_breach",
        [
            ("FY2023", 38_699, 26_017, 11_249, 654 + 779, True),
            ("FY2024", 51_244, 28_768, 21_558, 93 + 825, True),
        ],
    )
    def test_the_parent_only_equity_subtotal_breaches_and_nci_closes_it(
        self, period, assets, liabilities, parent_equity, nci, expected_breach
    ):
        """MEASURED on UBER_FY2024, read from the filing itself.

        Uber's balance sheet is in balance. The extraction picks "Total Uber
        Technologies, Inc. stockholders' equity", which excludes both
        redeemable and non-redeemable non-controlling interests, so the check
        breaches by exactly the NCI - 1,433 in FY2023, 918 in FY2024.

        Adding the NCI back closes it to the cent, which is what proves the
        breach is a caption problem and not an arithmetic one. The same
        failure appears on the income statement; see check_income_identity.
        """
        assert bool(check_balance_sheet_identity(
            assets, liabilities, parent_equity, period)) is expected_breach
        assert check_balance_sheet_identity(
            assets, liabilities, parent_equity + nci, period) == []

    def test_rounding_inside_tolerance_is_not_a_breach(self):
        """Filers round components independently of totals. An exact test
        would fail on arithmetic the filer itself published."""
        assert check_balance_sheet_identity(10_000, 6_000, 3_980) == []

    def test_the_tolerance_has_an_edge_that_is_actually_tested(self):
        """A tolerance nothing ever exceeds is not a tolerance."""
        assert check_balance_sheet_identity(10_000, 6_000, 3_900) != []


class TestCashRollforward:
    def test_a_rolling_statement_passes(self):
        assert check_cash_rollforward(4_680, 2_323, 7_003, "FY2024") == []

    def test_a_break_is_caught(self):
        breaches = check_cash_rollforward(4_680, 2_323, 6_000, "FY2024")
        assert len(breaches) == 1
        assert "7,003" in breaches[0].detail

    def test_a_decrease_rolls_forward_too(self):
        """Net change is signed. Taking its magnitude would break every year
        a company burned cash."""
        assert check_cash_rollforward(7_003, -2_323, 4_680) == []


class TestIncomeIdentity:
    def test_a_tax_benefit_is_subtracted_not_absolutised(self):
        """UBER_FY2024: a benefit of -5,758 against pretax income of 4,125
        gives net income ABOVE pretax income. An implementation using abs()
        would report a breach on a filing that balances."""
        assert check_income_identity(4_125, -5_758, 9_883, "FY2024") == []

    def test_a_tax_expense_reduces_net_income(self):
        assert check_income_identity(2_321, 213, 2_108, "FY2023") == []

    @pytest.mark.parametrize(
        "period,pretax,tax,attributable,expected_breach",
        [
            ("FY2022", -9_426, -181, -9_141, True),    # gap 104, 1.1%
            ("FY2023", 2_321, 213, 1_887, True),       # gap 221, 10.5%
            ("FY2024", 4_125, -5_758, 9_856, False),   # gap  27, 0.3%
        ],
    )
    def test_the_attributable_figure_is_the_wrong_left_hand_side(
        self, period, pretax, tax, attributable, expected_breach
    ):
        """MEASURED, and the most useful thing in this file.

        The pipeline extracts "Net income (loss) attributable to Uber
        Technologies, Inc." - the figure AFTER non-controlling interests.
        This identity needs TOTAL net income. Run against the extracted
        caption, two of Uber's three disclosed years breach, and the check is
        right to breach: it is being handed the wrong quantity.

        This test exists so nobody wires the check to the current facts,
        sees red, and widens the tolerance until a wrong comparison passes.
        The fix is to extract total net income.
        """
        breaches = check_income_identity(pretax, tax, attributable, period)
        assert bool(breaches) is expected_breach


class TestRunAll:
    def test_an_identity_with_missing_inputs_is_not_run_and_not_reported_as_passing(self):
        """A check that never ran is not a check that succeeded. Conflating
        the two is how a documented guarantee ends up enforcing nothing -
        ISSUES.md #30, in one sentence."""
        figures = [fig("Total revenue", 43978)]
        breaches = run_all(figures, {"FY2024": {"total_assets": 51_244}})
        assert breaches == []

    def test_it_runs_every_identity_whose_inputs_are_present(self):
        figures = [fig("Total revenue", 43978)]
        breaches = run_all(figures, {"FY2024": {
            "total_assets": 51_244, "total_liabilities": 26_000, "total_equity": 20_000,
            "beginning_cash": 4_680, "net_change_in_cash": 2_323, "ending_cash": 6_000,
            "pretax_income": 4_125, "tax_provision": -5_758, "net_income": 1_000,
        }})
        assert {b.check for b in breaches} == {
            "balance_sheet_identity", "cash_rollforward", "income_identity"}

    def test_a_clean_set_produces_nothing(self):
        """The negative control for run_all itself."""
        figures = [
            fig("Total revenue", 43978, statement="operations"),
            fig("CFO", 7137, statement="cash_flows"),
        ]
        breaches = run_all(figures, {"FY2024": {
            "total_assets": 51_244, "total_liabilities": 26_000, "total_equity": 25_244,
            "beginning_cash": 4_680, "net_change_in_cash": 2_323, "ending_cash": 7_003,
            "pretax_income": 4_125, "tax_provision": -5_758, "net_income": 9_883,
        }})
        assert breaches == []
