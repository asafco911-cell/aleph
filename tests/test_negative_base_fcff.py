"""Guard 0d: a negative base FCFF is NOT_APPLICABLE, everywhere.

The engine used to grow a negative base_cash_flow at the forecast growth
rates for ten years, capitalise the deepening loss with Gordon, and report
the present value as a value per share. Guard 0c refused a ZERO base as
NOT_SOLVABLE and said nothing about the sign, so this passed straight
through. Two of the four valued filings hit it:

    LYFT_FY2025   FY2023 FCFF -712  ->  range low -$39.37
    UBER_FY2024   FY2022 FCFF -957  ->  range low -$14.13

Both numbers appeared in README.md, CLAUDE.md and the app as ends of a
valuation range. Neither was a valuation.

What this file tests is not only that the guard fires - a guard is easy - but
that every caller that re-runs the engine on a base it did not choose
DEGRADES instead of crashing, and that the refusal reaches the reader with
its reason attached. A guard that turns one bad number into a stack trace
in the middle of a valid valuation is not an improvement.
"""
import math

import pytest

import aleph.valuation.pipeline as pipeline
from aleph.valuation.dcf_engine import (
    DCFConsistencyError,
    DCFInputs,
    reverse_dcf,
    run_dcf,
    sensitivity_tornado,
)

UBER = ("UBER_FY2024", 76.95)
LYFT = ("LYFT_FY2025", 17.35)
DASH = ("DASH_FY2025", 231.89)


def mk(**kw):
    d = dict(cash_flow_type="FCFF", base_cash_flow=1000.0,
             growth_rates=[0.15, 0.13, 0.11, 0.09, 0.07,
                           0.05, 0.04, 0.035, 0.03, 0.025],
             terminal_growth=0.025, discount_rate=0.09, net_debt=200.0,
             shares_outstanding=500.0, assumptions=[])
    d.update(kw)
    return DCFInputs(**d)


class TestTheGuardItself:
    def test_a_negative_base_is_refused(self):
        with pytest.raises(DCFConsistencyError) as caught:
            run_dcf(mk(base_cash_flow=-712.0))
        message = str(caught.value)
        assert "NOT_APPLICABLE" in message, message
        # the number itself, so the reader does not have to go looking
        assert "-712" in message, message

    def test_a_positive_base_is_untouched(self):
        """The positive control. Without it, a guard that rejected every base
        would pass every other test in this class."""
        assert run_dcf(mk(base_cash_flow=1000.0)).value_per_share > 0

    def test_the_smallest_negative_is_still_negative(self):
        """No tolerance band, deliberately. -0.01 is a loss; there is no
        amount of loss small enough to grow into a valuation, and a threshold
        would be a number nobody could defend."""
        with pytest.raises(DCFConsistencyError):
            run_dcf(mk(base_cash_flow=-0.01))
        assert run_dcf(mk(base_cash_flow=0.01)).value_per_share is not None

    def test_zero_and_negative_are_different_refusals(self):
        """0c is NOT_SOLVABLE (there is nothing to grow); 0d is
        NOT_APPLICABLE (the thing to grow is a loss). A reader must be able to
        tell which one happened."""
        with pytest.raises(DCFConsistencyError, match="NOT_SOLVABLE"):
            run_dcf(mk(base_cash_flow=0.0))
        with pytest.raises(DCFConsistencyError, match="NOT_APPLICABLE"):
            run_dcf(mk(base_cash_flow=-1.0))


class TestReverseDCF:
    def test_a_negative_base_is_not_solvable(self):
        """The observable contract. reverse_dcf's own B < 0 direction branch
        is now unreachable - value_at() returns None at every g, so the window
        probe returns first - and this is what is testable instead."""
        assert reverse_dcf(mk(base_cash_flow=-500.0), 10.0) is None
        assert reverse_dcf(mk(base_cash_flow=-500.0), -10.0) is None

    def test_a_positive_base_still_solves(self):
        inp = mk()
        target = run_dcf(inp).value_per_share
        g = reverse_dcf(inp, target)
        assert g is not None


class TestTornado:
    def test_a_refused_bound_is_reported_not_raised(self):
        rows = sensitivity_tornado(
            mk(), {"base_cash_flow": (-712.0, 810.0),
                   "discount_rate": (0.07, 0.11)})
        row = next(r for r in rows if r["param"] == "base_cash_flow")
        assert row["low"] is None
        assert row["high"] is not None
        assert row["swing"] is None and row["swing_pct"] is None

    def test_a_refused_row_sorts_last_and_that_is_a_known_cost(self):
        """DOCUMENTED CONSEQUENCE, not an accident. sensitivity_tornado sorts
        on (swing is not None, swing or 0), so a row with no computable swing
        goes to the bottom - even when it is the driver that dominates the
        valuation. For LYFT_FY2025 that moves base_cash_flow from first
        (180%) to last, and the CLI prints the row with NOT_APPLICABLE and a
        note rather than letting the position speak. See ISSUES.md #38."""
        rows = sensitivity_tornado(
            mk(), {"base_cash_flow": (-712.0, 810.0),
                   "discount_rate": (0.07, 0.11)})
        assert rows[-1]["param"] == "base_cash_flow"


class TestEveryRerunCallerDegrades:
    """Each of these re-runs the engine on a base_cash_flow the caller did not
    choose. Under Guard 0d each must return None with the guard's message, not
    propagate the exception into an otherwise-valid valuation."""

    def test_robustness_rerun_at(self):
        from aleph.valuation.robustness import _rerun_at
        value, note = _rerun_at(mk(), -500.0)
        assert value is None
        assert "NOT_APPLICABLE" in note, note

    def test_model_governance_value_at_fcff(self):
        from aleph.valuation.model_governance import _value_at_fcff
        assert _value_at_fcff(mk(), -500.0) is None
        assert _value_at_fcff(mk(), 500.0) is not None

    def test_market_expectations_anchor_scenarios(self):
        from aleph.valuation.market_expectations import anchor_scenarios
        from aleph.valuation.market_expectations import Solvability
        inp = mk()
        price = run_dcf(inp).value_per_share
        rows = anchor_scenarios(inp, price,
                                [("FY2023", -712.0), ("latest", 1000.0)])
        by_label = {r.anchor_label: r for r in rows}
        assert by_label["FY2023"].solvability is Solvability.NOT_SOLVABLE
        assert by_label["FY2023"].implied_uniform_growth is None
        assert by_label["latest"].solvability is Solvability.SOLVED

    def test_no_unguarded_rerun_is_added_later(self):
        """The structural version, and the one that keeps paying.

        Guard 0d did not break pipeline.py because the guard was wrong - it
        broke it because ONE run_dcf call site out of fifteen re-ran the
        engine on a base_cash_flow the caller had not chosen and did not
        catch DCFConsistencyError. Every other site already did. Finding that
        took reading fifteen call sites by hand; this finds the sixteenth.

        Two call sites are allowed to propagate, and both are the BASE case -
        the valuation's own inputs, not a re-run. If the base is refused there
        is no valuation to protect, and the CLI turns it into exit 1 with the
        guard's message.
        """
        import ast
        from pathlib import Path
        import aleph.valuation as valuation_pkg

        allowed = {
            # the base case: if this is refused there is no valuation at all
            ("pipeline.py", "run_dcf(bridged.inputs)"),
            ("sensitivity.py", "run_dcf(inputs)"),
            # sensitivity_tornado's own centre. Reached only after the caller
            # already ran the same inputs successfully (pipeline.py runs the
            # base case first), so it cannot raise here; and if it could, a
            # tornado around a refused centre would be meaningless anyway.
            ("dcf_engine.py", "run_dcf(inputs)"),
        }
        offenders = []
        for path in sorted(Path(valuation_pkg.__file__).parent.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            guarded: list[tuple[int, int]] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Try) and any(
                    "DCFConsistencyError" in ast.dump(h) for h in node.handlers
                ):
                    guarded.append((node.body[0].lineno, node.end_lineno or 10**9))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call)
                        and getattr(node.func, "id", "") == "run_dcf"):
                    continue
                source = ast.unparse(node)
                if (path.name, source) in allowed:
                    continue
                if any(lo <= node.lineno <= hi for lo, hi in guarded):
                    continue
                offenders.append(f"{path.name}:{node.lineno} {source}")

        assert not offenders, (
            "run_dcf re-run(s) that do not catch DCFConsistencyError: "
            + "; ".join(offenders))


@pytest.mark.needs_filings
class TestTheLiveFilings:
    """The two filings that actually hit this, and the two that do not."""

    def test_lyft_low_becomes_not_applicable_and_nothing_else_moves(self):
        run = pipeline.value_filing(*LYFT)
        bound = run.bridged.base_cash_flow_bound
        assert bound["low_fcff"] < 0, bound["low_fcff"]
        assert run.low_vps is None
        assert "NOT_APPLICABLE" in run.low_vps_note
        # the parts that must NOT move
        assert run.high_vps == pytest.approx(49.06, abs=0.01)
        assert run.result.value_per_share == pytest.approx(49.06, abs=0.01)
        assert run.implied_growth == pytest.approx(-0.0851, abs=1e-3)

    def test_uber_fy2024_hits_it_too(self):
        """The task that introduced this guard named only Lyft. UBER_FY2024's
        FY2022 FCFF is -957 and its range low was -$14.13, quoted in
        CLAUDE.md's seventh settled principle and in README's "the decision
        that changed a conclusion". Measuring found it; reading did not."""
        run = pipeline.value_filing(*UBER)
        assert run.bridged.base_cash_flow_bound["low_fcff"] < 0
        assert run.low_vps is None
        assert "NOT_APPLICABLE" in run.low_vps_note
        assert run.high_vps == pytest.approx(77.08, abs=0.01)
        # the anchor CLAUDE.md requires
        assert run.result.value_per_share == pytest.approx(77.08, abs=0.01)

    @pytest.mark.parametrize("doc,price,low", [
        ("UBER_FY2025", 76.95, 26.86), ("DASH_FY2025", 231.89, 54.85)])
    def test_the_filings_with_a_positive_low_are_unchanged(self, doc, price, low):
        """The negative control across filings. If the guard had been written
        as `<= 0` on the wrong quantity, or applied to the bound instead of
        the base, these two would have moved as well."""
        run = pipeline.value_filing(doc, price)
        assert run.bridged.base_cash_flow_bound["low_fcff"] > 0
        assert run.low_vps == pytest.approx(low, abs=0.01)
        assert run.low_vps_note is None
        assert math.isfinite(run.result.value_per_share)
