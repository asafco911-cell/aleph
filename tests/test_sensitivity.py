"""Tests for the two-dimensional WACC x terminal-growth grid.

Uses DCFInputs directly rather than a real filing, so these run with no PDFs
and no API key alongside the rest of the fixture suite.
"""
import pytest

from aleph.valuation.dcf_engine import DCFInputs, run_dcf
from aleph.valuation.sensitivity import (
    TERMINAL_DEPENDENCE_LIMIT,
    grid_as_markdown,
    sensitivity_grid,
    terminal_dependence_warning,
)


def inputs(discount_rate=0.0872, terminal_growth=0.025):
    return DCFInputs(
        cash_flow_type="FCFF",
        base_cash_flow=4_949.0,
        growth_rates=[0.175, 0.158, 0.142, 0.125, 0.108, 0.092, 0.075, 0.058, 0.042, 0.025],
        terminal_growth=terminal_growth,
        discount_rate=discount_rate,
        net_debt=3_000.0,
        shares_outstanding=2_100.0,
    )


class TestTerminalDependenceWarning:
    def test_silent_below_the_limit(self):
        """Measured: the four valued filings sit at 60.3%, 60.5%, 61.0% and
        64.8%, so this is the ordinary case and must produce nothing."""
        assert terminal_dependence_warning(0.603) == ""
        assert terminal_dependence_warning(0.648) == ""

    def test_fires_above_the_limit(self):
        warning = terminal_dependence_warning(0.91)
        assert "91%" in warning and "85%" in warning

    def test_the_boundary_is_inclusive(self):
        """At exactly the limit there is nothing to warn about; one basis
        point above, there is. A limit nothing can sit exactly on is untested."""
        assert terminal_dependence_warning(TERMINAL_DEPENDENCE_LIMIT) == ""
        assert terminal_dependence_warning(TERMINAL_DEPENDENCE_LIMIT + 1e-6) != ""


class TestSensitivityGrid:
    def test_the_base_cell_reproduces_run_dcf_exactly(self):
        """The grid must not be a second implementation of the DCF. If the
        centre cell disagrees with run_dcf, everything around it is fiction."""
        base = inputs()
        grid = sensitivity_grid(base)
        centre = grid.cell(base.discount_rate, base.terminal_growth)
        assert centre is not None and centre.is_base
        assert centre.value_per_share == pytest.approx(run_dcf(base).value_per_share)

    def test_the_grid_is_the_full_cross_product(self):
        grid = sensitivity_grid(inputs())
        assert len(grid.cells) == 15
        assert len({c.discount_rate for c in grid.cells}) == 5
        assert len({c.terminal_growth for c in grid.cells}) == 3

    def test_value_falls_as_the_discount_rate_rises(self):
        """Monotonicity along one axis. A grid that got this backwards would
        still look plausible in a table."""
        grid = sensitivity_grid(inputs())
        g = inputs().terminal_growth
        rates = sorted({c.discount_rate for c in grid.cells})
        values = [grid.cell(r, g).value_per_share for r in rates]
        assert all(a > b for a, b in zip(values, values[1:])), values

    def test_value_rises_as_terminal_growth_rises(self):
        grid = sensitivity_grid(inputs())
        r = inputs().discount_rate
        growths = sorted({c.terminal_growth for c in grid.cells})
        values = [grid.cell(r, g).value_per_share for g in growths]
        assert all(a < b for a, b in zip(values, values[1:])), values

    def test_floating_point_dust_does_not_manufacture_a_refusal(self):
        """0.025 + 0.005 is 0.030000000000000002, which trips the engine's
        `terminal_growth > 0.03` guard even though 3.0% is allowed. Before
        the offsets were rounded, the whole g = 3% column came back rejected.
        """
        grid = sensitivity_grid(inputs())
        assert grid.rejected_count == 0
        top = max(c.terminal_growth for c in grid.cells)
        assert top == pytest.approx(0.03)
        assert grid.cell(inputs().discount_rate, top).value_per_share is not None

    def test_a_genuinely_invalid_pair_is_reported_not_dropped(self):
        """The negative control for the test above: real refusals must still
        appear, carrying the guard's own message."""
        grid = sensitivity_grid(inputs(discount_rate=0.028, terminal_growth=0.025))
        rejected = [c for c in grid.cells if c.value_per_share is None]
        assert rejected, "a discount rate at the growth rate must refuse"
        assert all(c.rejected for c in rejected)
        assert any("cells violate a consistency guard" in n for n in grid.notes)

    def test_offsets_are_absolute_not_relative(self):
        """A relative offset would mean something different at 8% than at 14%
        and make two filings' grids incomparable."""
        grid = sensitivity_grid(inputs(discount_rate=0.10))
        rates = sorted({c.discount_rate for c in grid.cells})
        assert rates == pytest.approx([0.09, 0.095, 0.10, 0.105, 0.11])


class TestMarkdownRendering:
    def test_the_base_cell_is_marked(self):
        table = grid_as_markdown(sensitivity_grid(inputs()))
        assert table.count("**") == 2, "exactly one bolded base cell"

    def test_shape_matches_the_grid(self):
        table = grid_as_markdown(sensitivity_grid(inputs()))
        lines = table.splitlines()
        assert len(lines) == 2 + 5           # header, divider, five WACC rows
        assert lines[0].count("|") == 5      # label + three growth columns

    def test_a_rejected_cell_prints_a_dash_not_a_number(self):
        """The table must never imply a value where the engine refused."""
        table = grid_as_markdown(
            sensitivity_grid(inputs(discount_rate=0.028, terminal_growth=0.025)))
        assert "| - " in table
