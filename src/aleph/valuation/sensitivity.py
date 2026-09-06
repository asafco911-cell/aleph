"""Two-dimensional sensitivity, and a warning about terminal-value dependence.

The tornado in dcf_engine moves one assumption at a time. That is the right
instrument for ranking drivers and the wrong one for the pair that interact:
WACC and terminal growth enter the Gordon denominator together as (r - g), so
their joint effect is not the sum of their separate effects. A grid shows the
interaction; a tornado cannot.

dcf_engine.py is untouched. Its four guards - terminal growth below the
discount rate, terminal growth at or under 3%, FCFE never carrying net debt,
a positive share count - still decide what is valuable and what raises. This
module calls run_dcf and reports what it returns, including the cells the
guards reject rather than quietly dropping them.
"""
from dataclasses import dataclass, field

from .dcf_engine import DCFConsistencyError, DCFInputs, run_dcf

__all__ = [
    "TERMINAL_DEPENDENCE_LIMIT",
    "WACC_OFFSETS",
    "TERMINAL_GROWTH_OFFSETS",
    "GridCell",
    "SensitivityGrid",
    "terminal_dependence_warning",
    "sensitivity_grid",
    "grid_as_markdown",
]

# Above this share of total value resting on the terminal value, the answer is
# mostly an opinion about the far future rather than a reading of the forecast.
# 85% is the threshold this project reports at; it is a convention, not a
# derived constant, which is why the warning names the figure and does not
# block. MEASURED on every filing valued here, and none of them trips it:
# UBER_FY2024 60.3%, UBER_FY2025 60.5%, LYFT_FY2025 61.0%, DASH_FY2025 64.8%.
# So the warning is currently dead code on this corpus, and is written to
# stay silent rather than to decorate an ordinary run.
TERMINAL_DEPENDENCE_LIMIT = 0.85

# Absolute offsets in decimal, applied to the base case.
WACC_OFFSETS: tuple[float, ...] = (-0.010, -0.005, 0.0, 0.005, 0.010)
TERMINAL_GROWTH_OFFSETS: tuple[float, ...] = (-0.005, 0.0, 0.005)


@dataclass(frozen=True)
class GridCell:
    """One (discount rate, terminal growth) pair and what it produced.

    ``value_per_share`` is None when a consistency guard rejected the pair.
    ``rejected`` then carries the guard's own message. A rejected cell is
    reported, never silently blanked: "no value here" and "the model refuses
    this combination, and here is why" are different statements, and the
    second is the informative one.
    """
    discount_rate: float
    terminal_growth: float
    value_per_share: float | None
    is_base: bool = False
    rejected: str = ""


@dataclass(frozen=True)
class SensitivityGrid:
    base_discount_rate: float
    base_terminal_growth: float
    base_value_per_share: float
    cells: list[GridCell] = field(default_factory=list)
    notes: tuple[str, ...] = ()

    def cell(self, discount_rate: float, terminal_growth: float) -> GridCell | None:
        for c in self.cells:
            if (abs(c.discount_rate - discount_rate) < 1e-12
                    and abs(c.terminal_growth - terminal_growth) < 1e-12):
                return c
        return None

    @property
    def rejected_count(self) -> int:
        return sum(1 for c in self.cells if c.value_per_share is None)


def terminal_dependence_warning(
    terminal_pct: float, limit: float = TERMINAL_DEPENDENCE_LIMIT
) -> str:
    """Return a warning when too much of the value rests beyond the forecast.

    Empty string when under the limit, so a caller can print it
    unconditionally and stay silent in the ordinary case.

    This does not block, and deliberately so. A high terminal share is a
    property of a long-duration business discounted at a low rate, not an
    error. Measured on this corpus it never fires: the four valued filings
    sit at 60.3%, 60.5%, 61.0% and 64.8%, all comfortably under the limit.
    It is here for the filing that is not like these four, and it says so
    rather than blocking, because what it costs to be wrong about the far
    future is exactly what the number reports.
    """
    if terminal_pct <= limit:
        return ""
    return (
        f"{terminal_pct:.0%} of the value rests on the terminal value, above "
        f"the {limit:.0%} mark. Beyond the explicit forecast the model is a "
        "single growth rate held forever, so most of this answer is a view "
        "about perpetuity rather than a reading of the forecast period. The "
        "WACC x terminal-growth grid shows how far that view moves it."
    )


def sensitivity_grid(
    inputs: DCFInputs,
    wacc_offsets: tuple[float, ...] = WACC_OFFSETS,
    terminal_growth_offsets: tuple[float, ...] = TERMINAL_GROWTH_OFFSETS,
) -> SensitivityGrid:
    """Value the filing at every (WACC, terminal growth) pair in the grid.

    Offsets are ABSOLUTE and in decimal: -0.005 is half a percentage point
    below the base rate, not half a percent of it. A relative offset would
    mean something different at 8% than at 14% and would make two filings'
    grids incomparable, which is the whole point of running one.

    Every cell is computed independently from the base inputs. Nothing is
    carried between cells, so a rejected pair cannot contaminate its
    neighbours.
    """
    base_result = run_dcf(inputs)
    base_r = inputs.discount_rate
    base_g = inputs.terminal_growth

    cells: list[GridCell] = []
    for dr in wacc_offsets:
        for dg in terminal_growth_offsets:
            # Rounded because binary floating point manufactures refusals
            # that the guard does not intend: 0.025 + 0.005 is
            # 0.030000000000000002, which trips `terminal_growth > 0.03`
            # even though the engine allows exactly 3.0%. Measured, not
            # assumed - the whole g = 3% column came back rejected before
            # this line existed. Ten places is far below any offset this
            # grid uses and far above the dust it removes.
            r = round(base_r + dr, 10)
            g = round(base_g + dg, 10)
            trial = DCFInputs(
                cash_flow_type=inputs.cash_flow_type,
                base_cash_flow=inputs.base_cash_flow,
                growth_rates=list(inputs.growth_rates),
                terminal_growth=g,
                discount_rate=r,
                net_debt=inputs.net_debt,
                shares_outstanding=inputs.shares_outstanding,
                assumptions=[],
            )
            is_base = dr == 0.0 and dg == 0.0
            try:
                cells.append(GridCell(r, g, run_dcf(trial).value_per_share, is_base))
            except DCFConsistencyError as exc:
                cells.append(GridCell(r, g, None, is_base, str(exc)))

    notes: list[str] = []
    warning = terminal_dependence_warning(base_result.terminal_pct)
    if warning:
        notes.append(warning)
    rejected = sum(1 for c in cells if c.value_per_share is None)
    if rejected:
        notes.append(
            f"{rejected} of {len(cells)} cells violate a consistency guard and "
            "carry no value. They are shown, not dropped: the shape of the "
            "region the model refuses is part of the answer."
        )

    return SensitivityGrid(
        base_discount_rate=base_r,
        base_terminal_growth=base_g,
        base_value_per_share=base_result.value_per_share,
        cells=cells,
        notes=tuple(notes),
    )


def grid_as_markdown(grid: SensitivityGrid) -> str:
    """Render the grid as a Markdown table, rows WACC, columns terminal growth.

    The base cell is marked. A rejected cell prints as "-" with the count of
    such cells stated in the grid's notes, so the table never implies a
    number where the engine refused to produce one.
    """
    rates = sorted({c.discount_rate for c in grid.cells})
    growths = sorted({c.terminal_growth for c in grid.cells})

    header = "| WACC \\ g | " + " | ".join(f"{g:.2%}" for g in growths) + " |"
    divider = "|---" * (len(growths) + 1) + "|"
    lines = [header, divider]
    for r in rates:
        row = [f"| {r:.2%} "]
        for g in growths:
            cell = grid.cell(r, g)
            if cell is None or cell.value_per_share is None:
                row.append("| - ")
            elif cell.is_base:
                row.append(f"| **{cell.value_per_share:,.2f}** ")
            else:
                row.append(f"| {cell.value_per_share:,.2f} ")
        lines.append("".join(row) + "|")
    return "\n".join(lines)
