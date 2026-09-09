"""P5.1-P5.12 controls: provenance integrity, model conventions, historical
comparability, WACC input quality, reverse-DCF well-posedness, share-unit
gating. Every test is designed to FAIL if its safeguard is removed
(mutation-tested in test_p5_mutations / the P5 harness).
"""
import math

import pytest

import aleph.valuation.pipeline as pipeline
from aleph.schemas.evidence import Fact, FactSource
from aleph.schemas.valuation import Override
from aleph.valuation.assumptions import derive_diluted_shares
from aleph.valuation.dcf_engine import (
    DCFConsistencyError,
    DCFInputs,
    reverse_dcf,
    run_dcf,
)
from aleph.valuation.robustness import (
    FailureCategory,
    Severity,
    assess_robustness,
    model_conventions,
)

UBER, LYFT = ("UBER_FY2024", 76.95), ("LYFT_FY2025", 17.35)


def mk(**kw):
    d = dict(cash_flow_type="FCFF", base_cash_flow=1000.0, growth_rates=[0.05] * 10,
             terminal_growth=0.025, discount_rate=0.09, net_debt=100.0,
             shares_outstanding=1000.0, assumptions=[])
    d.update(kw)
    return DCFInputs(**d)


def sfact(name, value, period, unit):
    return Fact(name=f"{name} {period}", value=value, unit=unit, period=period,
                quote="q", source=FactSource(doc_id="X", kind="statement",
                ref="operations", target_key="operations", pages=[1]))


# =========================================================================== #
# P5.1 - machine-readable provenance
# =========================================================================== #
class TestProvenanceIntegrity:
    @pytest.mark.needs_filings
    def test_net_debt_is_never_labelled_filing(self):
        for doc, price in (UBER, LYFT):
            run = pipeline.value_filing(doc, price)
            nd = next(a for a in run.bridged.inputs.assumptions
                      if a.name == "net_debt")
            assert nd.source == "analyst_judgment", (doc, nd.source)

    @pytest.mark.needs_filings
    def test_lyft_override_growth_is_analyst_judgment_not_filing(self):
        run = pipeline.value_filing(*LYFT)          # LYFT growth is a 9.2% override
        g = next(a for a in run.bridged.inputs.assumptions
                 if a.name == "growth_year_1")
        assert g.source == "analyst_judgment"

    @pytest.mark.needs_filings
    def test_uber_derived_growth_is_derived_not_filing(self):
        run = pipeline.value_filing(*UBER)          # UBER growth is a median
        g = next(a for a in run.bridged.inputs.assumptions
                 if a.name == "growth_year_1")
        assert g.source == "derived"

    @pytest.mark.needs_filings
    def test_base_cash_flow_is_derived_composite_not_filing(self):
        run = pipeline.value_filing(*UBER)
        b = next(a for a in run.bridged.inputs.assumptions
                 if a.name == "base_cash_flow")
        assert b.source == "derived"
        assert "LINEAGE" in b.rationale and "effective_tax_rate" in b.rationale

    @pytest.mark.needs_filings
    def test_terminal_growth_and_discount_rate_tags_are_unchanged(self):
        run = pipeline.value_filing(*UBER)
        tags = {a.name: a.source for a in run.bridged.inputs.assumptions}
        assert tags["terminal_growth"] == "analyst_judgment"
        assert tags["discount_rate"] == "market"
        assert tags["effective_tax_rate"] == "analyst_judgment"

    @pytest.mark.needs_filings
    def test_provenance_correction_does_not_move_the_point_value(self):
        assert pipeline.value_filing(*UBER).result.value_per_share == \
            pytest.approx(77.08, abs=0.01)
        assert pipeline.value_filing(*LYFT).result.value_per_share == \
            pytest.approx(49.06, abs=0.01)


# =========================================================================== #
# P5.2 - model conventions are first-class
# =========================================================================== #
class TestModelConventions:
    @pytest.mark.needs_filings
    def test_every_run_carries_the_convention_registry(self):
        run = pipeline.value_filing(*UBER)
        mcs = run.robustness.model_conventions
        names = {m.name for m in mcs}
        assert {"forecast_horizon", "growth_summary_statistic", "growth_fade_shape",
                "terminal_growth", "terminal_growth_cap",
                "reverse_dcf_search_window", "sbc_treatment",
                "net_cash_wacc_clamp"} <= names
        for m in mcs:
            assert m.classification == "MODEL_CONVENTION"
            assert m.rationale and m.location and m.effect

    @pytest.mark.needs_filings
    def test_conventions_report_live_values(self):
        run = pipeline.value_filing(*UBER)
        by = {m.name: m.value for m in run.robustness.model_conventions}
        assert by["forecast_horizon"] == "10"
        assert by["growth_summary_statistic"] == "median"
        assert "17.46%" in by["growth_fade_shape"] and "2.50%" in by["growth_fade_shape"]

    @pytest.mark.needs_filings
    def test_can_answer_which_conventions_generated_this_valuation(self):
        # the whole point: enumerable from the ValuationRun, not from prose
        run = pipeline.value_filing(*LYFT)
        assert len(run.robustness.model_conventions) >= 8


# =========================================================================== #
# P5.4 - historical comparability taxonomy
# =========================================================================== #
class TestHistoryComparability:
    def _run(self, fcff_by_period, growth_band=None, note=""):
        from aleph.valuation.robustness import _history_comparability
        pair = (0.0, growth_band) if growth_band is not None else None
        return _history_comparability(fcff_by_period, pair, note)

    def test_sign_change_is_high_concern(self):
        f = self._run({"FY2022": -900.0, "FY2023": 1900.0, "FY2024": 5000.0})
        assert f.headline.endswith("HIGH_CONCERN")
        assert f.severity is Severity.HIGH
        assert f.category is FailureCategory.ECONOMIC_MODEL_FAILURE

    def test_reconstructed_with_assumption_is_flagged(self):
        f = self._run({"FY2022": 100.0, "FY2023": 110.0, "FY2024": 120.0},
                      note="interest_expense has no per-period disclosure; flat override applied")
        assert "reconstructed using an assumption" in f.detail

    def test_one_period_is_no_determinable_conclusion(self):
        f = self._run({"FY2024": 1000.0})
        assert "NO_DETERMINABLE_CONCLUSION" in f.headline

    def test_stable_comparable_series_triggers_nothing(self):
        f = self._run({"FY2022": 1000.0, "FY2023": 1030.0, "FY2024": 1055.0})
        assert "NO_DETERMINABLE_CONCERN" in f.headline
        assert "not a statement that the anchor level is right" in f.interpretation

    def test_never_claims_a_new_regime(self):
        f = self._run({"FY2022": -900.0, "FY2023": 1900.0, "FY2024": 5000.0})
        assert "NOT a claim that the business entered a new regime" in f.interpretation
        blob = (f.headline + f.detail + f.interpretation).lower()
        for asserted in ("the business has entered", "regime change confirmed",
                         "is a regime change", "new regime detected"):
            assert asserted not in blob

    @pytest.mark.needs_filings
    def test_real_filings_are_high_concern(self):
        for doc, price in (UBER, LYFT):
            f = pipeline.value_filing(doc, price).robustness.get("HISTORY_COMPARABILITY")
            assert f.headline.endswith("HIGH_CONCERN")


# =========================================================================== #
# P5.6 - WACC input quality (integrity separate from math validity)
# =========================================================================== #
class TestWACCInputQuality:
    @pytest.mark.needs_filings
    def test_uber_is_limited_stale_erp_and_undisclosed_crp(self):
        f = pipeline.value_filing(*UBER).robustness.get("WACC_INPUT_QUALITY")
        assert f.headline == "WACC INPUT QUALITY: LIMITED"
        assert "different market states" in f.detail
        assert "undisclosed analyst judgement" in f.detail

    @pytest.mark.needs_filings
    def test_lyft_is_insufficient_evidence_unverified_spread(self):
        f = pipeline.value_filing(*LYFT).robustness.get("WACC_INPUT_QUALITY")
        assert f.headline == "WACC INPUT QUALITY: INSUFFICIENT_EVIDENCE"
        assert "UNVERIFIED" in f.detail
        assert f.category is FailureCategory.INSUFFICIENT_EVIDENCE

    def test_extreme_beta_is_limited_not_blocked(self):
        from aleph.valuation.robustness import _wacc_input_quality
        market = {"unlevered_industry_beta": type("M", (), {
                    "value": 9.0, "source": "x", "rationale": "x", "as_of": "2026-01"})(),
                  "risk_free_rate": type("M", (), {
                    "value": 0.045, "source": "x", "rationale": "x", "as_of": "2026-01"})(),
                  "equity_risk_premium": type("M", (), {
                    "value": 0.045, "source": "x", "rationale": "x", "as_of": "2026-01"})()}
        f = _wacc_input_quality(market, mk(discount_rate=0.5))
        assert "LIMITED" in f.headline
        assert "beta 9.00" in f.detail

    def test_missing_input_is_blocked(self):
        from aleph.valuation.robustness import _wacc_input_quality
        f = _wacc_input_quality({"risk_free_rate": None}, mk())
        assert f.headline == "WACC INPUT QUALITY: BLOCKED"
        assert f.severity is Severity.HIGH

    def test_missing_input_is_reported_as_missing_by_the_is_none_branch(self):
        # pins the `val is None` branch specifically - a mutation that removes
        # it must not be silently covered by the non-finite branch
        from aleph.valuation.robustness import _wacc_input_quality
        f = _wacc_input_quality({"risk_free_rate": None,
                                 "equity_risk_premium": None,
                                 "unlevered_industry_beta": None}, mk())
        assert "risk_free_rate is missing" in f.detail
        assert "equity_risk_premium is missing" in f.detail

    def test_wacc_le_terminal_growth_is_blocked_here_too(self):
        from aleph.valuation.robustness import _wacc_input_quality
        good = {n: type("M", (), {"value": v, "source": "s", "rationale": "r",
                                  "as_of": "2026-01"})()
                for n, v in (("risk_free_rate", 0.04),
                             ("equity_risk_premium", 0.045),
                             ("unlevered_industry_beta", 0.9))}
        f = _wacc_input_quality(good, mk(discount_rate=0.02, terminal_growth=0.025))
        assert f.headline == "WACC INPUT QUALITY: BLOCKED"


# =========================================================================== #
# P5.7 - reverse DCF well-posedness
# =========================================================================== #
class TestReverseDCFWellPosed:
    @pytest.mark.needs_filings
    def test_positive_fcff_still_solves_the_live_cases(self):
        assert pipeline.value_filing(*UBER).implied_growth == pytest.approx(0.1048, abs=1e-3)
        assert pipeline.value_filing(*LYFT).implied_growth == pytest.approx(-0.0851, abs=1e-3)

    def test_negative_fcff_is_not_solvable(self):
        """REWRITTEN when Guard 0d landed. This used to assert the opposite -
        that value(g) is DECREASING for a negative anchor and that a lower
        target round-trips through reverse_dcf. That was true, and it was the
        machinery that produced LYFT_FY2025's -$39.37 range low.

        The engine no longer values a negative base at all, so value_at()
        returns None at every g and the window probe returns NOT_SOLVABLE
        before the direction is read. The old assertion is preserved as
        history in the docstring rather than deleted, because the arithmetic
        it described was never wrong - the decision about what to do with it
        changed."""
        neg = mk(base_cash_flow=-500.0)
        with pytest.raises(DCFConsistencyError, match="NOT_APPLICABLE"):
            run_dcf(neg)
        assert reverse_dcf(neg, 10.0) is None
        assert reverse_dcf(neg, -10.0) is None

    def test_zero_fcff_is_not_solvable(self):
        assert reverse_dcf(mk(base_cash_flow=0.0), 10.0) is None

    def test_reverse_dcf_does_not_mutate_its_input(self):
        # the solver re-runs the engine on COPIES; the caller's growth vector
        # (the faded forecast) must be intact afterwards, so a later reader of
        # bridged.inputs sees the forecast, not the last bisection midpoint.
        inp = mk()
        before = list(inp.growth_rates)
        reverse_dcf(inp, 60.0)
        assert list(inp.growth_rates) == before

    def test_unattainable_high_target_is_not_solvable(self):
        inp = mk()
        v_hi = run_dcf(mk(growth_rates=[1.0] * 10)).value_per_share
        assert reverse_dcf(inp, v_hi + 10_000.0) is None

    def test_target_just_above_the_attainable_max_is_not_solvable(self):
        # isolates the BRACKETING check: 0.05% above the true maximum is
        # within the convergence tolerance, so without the bracket check the
        # solver would converge to the boundary and return a wrong "solution".
        inp = mk()
        v_hi = run_dcf(mk(growth_rates=[1.0] * 10)).value_per_share
        assert reverse_dcf(inp, v_hi * 1.0005) is None

    def test_ill_posed_window_returns_none_not_a_type_error(self):
        # isolates the WINDOW-WELL-POSED probe: g_T >= r makes value(g)
        # invalid at every g; removing the probe would reach the bracket
        # comparison with None operands and raise, not return None.
        assert reverse_dcf(mk(discount_rate=0.02, terminal_growth=0.025), 5.0) is None
        assert reverse_dcf(mk(base_cash_flow=0.0), 5.0) is None

    def test_unattainable_low_target_is_not_solvable(self):
        inp = mk()
        v_lo = run_dcf(mk(growth_rates=[-0.5] * 10)).value_per_share
        assert reverse_dcf(inp, v_lo - 50.0) is None

    def test_near_flat_value_function_is_not_solvable(self):
        # a near-zero anchor makes the attainable value range collapse to
        # ~ -D/S; a target above it is unattainable -> None (bracket check)
        assert reverse_dcf(mk(base_cash_flow=1e-6), 0.01) is None

    def test_monotonicity_direction_is_read_from_the_base_fcff_sign(self):
        """The proof: value(g) increases with g iff base FCFF > 0. Guard 0d
        left only the positive half of that reachable, so this now tests the
        surviving half as a round trip and the refused half as a refusal -
        NOT by dropping the negative case, which would leave the engine's sign
        behaviour untested in either direction."""
        inp = mk(base_cash_flow=1000.0)
        v0 = run_dcf(inp).value_per_share
        target = v0 * 1.2
        g = reverse_dcf(inp, target)
        assert g is not None
        rt = run_dcf(mk(base_cash_flow=1000.0,
                        growth_rates=[g] * 10)).value_per_share
        assert abs(rt - target) / abs(target) < 0.01

        # the other sign is a refusal, not a direction
        with pytest.raises(DCFConsistencyError):
            run_dcf(mk(base_cash_flow=-500.0))

    def test_near_boundary_target_still_solves(self):
        # a target 1% inside the attainable max must still solve (not be
        # rejected by an over-tight bracket check)
        inp = mk()
        v_hi = run_dcf(mk(growth_rates=[1.0] * 10)).value_per_share
        g = reverse_dcf(inp, v_hi * 0.98)
        assert g is not None and 0.9 < g <= 1.0


# =========================================================================== #
# P5.8 - share-unit / net-debt-unit integrity
# =========================================================================== #
class TestValueBridgeInputIntegrity:
    def test_shares_with_no_unit_blocks_not_assumes_thousands(self):
        r = derive_diluted_shares(
            [sfact("Diluted weighted-average shares outstanding", 1_000_000.0, "FY2023", ""),
             sfact("Diluted weighted-average shares outstanding", 1_010_000.0, "FY2024", "")],
            {})
        assert r.status == "blocked"
        assert "INVALID_UNIT" in r.rationale

    def test_shares_with_a_unit_derive_normally(self):
        r = derive_diluted_shares(
            [sfact("Diluted weighted-average shares outstanding", 1_000_000.0, "FY2023", "thousands"),
             sfact("Diluted weighted-average shares outstanding", 1_010_000.0, "FY2024", "thousands")],
            {})
        assert r.status == "derived" and r.unit == "thousands"

    @pytest.mark.needs_filings
    def test_live_filings_share_facts_carry_a_unit(self):
        for doc, price in (UBER, LYFT):
            r = pipeline.value_filing(doc, price)
            assert r.ranges["diluted_shares"].status in ("derived", "overridden")
            assert (r.ranges["diluted_shares"].unit or "").strip()

    def test_net_debt_override_with_unrecognised_unit_fails_closed_at_bridge(self):
        # a net_debt override unit that names no scale token must not slip
        # through - to_millions raises BridgeError
        from aleph.valuation.bridge import to_millions, BridgeError
        from aleph.schemas.valuation import AssumptionRange
        bad = AssumptionRange(name="net_debt", unit="USD", status="overridden",
                              low=1370.0, base=1370.0, high=1370.0,
                              observations=[], method="fixed", rationale="x")
        with pytest.raises(BridgeError):
            to_millions(bad)


# =========================================================================== #
# P5.10 - scenario / base-case isolation (re-assert with the new fields)
# =========================================================================== #
class TestScenarioIsolation:
    @pytest.mark.needs_filings
    def test_assess_robustness_does_not_mutate_the_run(self):
        run = pipeline.value_filing(*UBER)
        before = (run.result.value_per_share, run.bridged.inputs.base_cash_flow,
                  list(run.bridged.inputs.growth_rates), run.implied_growth,
                  run.wacc.wacc)
        assess_robustness(run)
        assess_robustness(run)
        after = (run.result.value_per_share, run.bridged.inputs.base_cash_flow,
                 list(run.bridged.inputs.growth_rates), run.implied_growth,
                 run.wacc.wacc)
        assert before == after


# =========================================================================== #
# P5.12 - failure taxonomy on the new findings
# =========================================================================== #
class TestFailureTaxonomyOnFindings:
    @pytest.mark.needs_filings
    def test_high_concern_and_market_findings_carry_a_category(self):
        rob = pipeline.value_filing(*LYFT).robustness
        assert rob.get("HISTORY_COMPARABILITY").category is FailureCategory.ECONOMIC_MODEL_FAILURE
        assert rob.get("WACC_INPUT_QUALITY").category is FailureCategory.INSUFFICIENT_EVIDENCE

    @pytest.mark.needs_filings
    def test_ok_findings_have_no_category(self):
        rob = pipeline.value_filing(*UBER).robustness
        assert rob.get("VALUE_BRIDGE_INTEGRITY").category is None


# =========================================================================== #
# P5.1-closure Part 2 - negative / zero equity is a first-class limitation
# =========================================================================== #
class TestNegativeEquity:
    def _finding(self, net_debt):
        from aleph.valuation.robustness import _negative_equity
        inp = mk(net_debt=net_debt)
        return _negative_equity(inp, run_dcf(inp))

    def test_positive_equity_has_no_finding(self):
        assert self._finding(net_debt=100.0) is None

    def test_large_negative_equity_is_flagged(self):
        f = self._finding(net_debt=1_000_000.0)
        assert f.key == "NEGATIVE_EQUITY_VALUE"
        assert f.severity is Severity.HIGH
        assert "NEGATIVE EQUITY VALUE" in f.headline
        assert "MATHEMATICALLY VALID, ECONOMICALLY LIMITED" in f.interpretation
        assert "NOT an ordinary bear-case" in f.interpretation

    def test_small_negative_equity_is_still_flagged(self):
        v0 = run_dcf(mk(net_debt=0.0)).enterprise_or_equity_value
        f = self._finding(net_debt=v0 + 1.0)     # EV - net_debt = -1
        assert f is not None and f.severity is Severity.HIGH
        assert f.headline.startswith("NEGATIVE EQUITY VALUE")

    def test_zero_equity_is_flagged_as_breakeven(self):
        from aleph.valuation.robustness import _negative_equity
        ev = run_dcf(mk(net_debt=0.0)).enterprise_or_equity_value
        f = _negative_equity(mk(net_debt=ev), run_dcf(mk(net_debt=ev)))
        assert f is not None and "ZERO" in f.headline

    def test_arithmetic_is_unchanged_and_number_not_hidden(self):
        inp = mk(net_debt=1_000_000.0)
        res = run_dcf(inp)
        assert res.equity_value == pytest.approx(
            res.enterprise_or_equity_value - 1_000_000.0, rel=1e-12)
        assert res.value_per_share == pytest.approx(
            res.equity_value / inp.shares_outstanding, rel=1e-12)
        # negative per-share is still returned, not clamped or hidden
        assert res.value_per_share < 0


# =========================================================================== #
# P5.1-closure Parts 5-10 - valuation applicability + evidence families
# =========================================================================== #
class TestValuationApplicability:
    @pytest.mark.needs_filings
    def test_the_rule_is_a_model_convention(self):
        run = pipeline.value_filing(*UBER)
        names = {m.name for m in run.robustness.model_conventions}
        assert "valuation_applicability_rules" in names

    @pytest.mark.needs_filings
    def test_uber_and_lyft_are_limited_applicability(self):
        from aleph.valuation.robustness import Applicability
        for doc, price in (UBER, LYFT):
            rob = pipeline.value_filing(doc, price).robustness
            assert rob.applicability is Applicability.LIMITED_APPLICABILITY
            assert "cash_flow_representativeness" in rob.limitation_families

    @pytest.mark.needs_filings
    def test_anchor_high_plus_history_high_concern_gives_limited(self):
        # the explicit Part 7 rule
        from aleph.valuation.robustness import _applicability, Applicability
        rob = pipeline.value_filing(*UBER).robustness
        state, reasons, fams, _ = _applicability(list(rob.findings))
        assert state is Applicability.LIMITED_APPLICABILITY
        assert any("ANCHOR_SENSITIVITY HIGH" in r and "HIGH_CONCERN" in r
                   for r in reasons)

    @pytest.mark.needs_filings
    def test_correlated_findings_collapse_to_one_family(self):
        # anchor + historical regime + history comparability all describe the
        # SAME cash-flow instability -> ONE family, not three concerns
        rob = pipeline.value_filing(*UBER).robustness
        cf_findings = [f.key for f in rob.findings
                       if f.key in ("ANCHOR_SENSITIVITY", "HISTORICAL_REGIME",
                                    "HISTORY_COMPARABILITY")]
        assert len(cf_findings) >= 2                      # multiple manifestations
        assert rob.limitation_families.count("cash_flow_representativeness") == 1
        # the cluster contributes EXACTLY one family name; UBER's only other
        # family is the (distinct) market-input-evidence one. If the family
        # map sent any cluster member to its own name this tuple would grow.
        assert rob.limitation_families == (
            "cash_flow_representativeness", "market_input_evidence")

    @pytest.mark.needs_filings
    def test_five_wacc_diagnostics_from_one_stale_erp_are_one_family(self):
        rob = pipeline.value_filing(*UBER).robustness
        w = rob.get("WACC_INPUT_QUALITY")
        assert w.detail.count(";") >= 1                   # multiple sub-reasons
        assert rob.limitation_families.count("market_input_evidence") == 1

    def test_clean_synthetic_company_is_usable(self):
        from aleph.valuation.robustness import assess_robustness, Applicability
        from aleph.valuation.dcf_engine import run_dcf as _rd
        inp = mk(base_cash_flow=1000.0, net_debt=200.0)

        class _R:
            doc_id = "S"
            bridged = type("B", (), {"inputs": inp, "base_cash_flow_bound": {
                "available": True,
                "fcff_by_period": {"FY2022": 1000.0, "FY2023": 990.0,
                                   "FY2024": 1010.0}, "note": ""},
                "tornado_ranges": {}})()
            result = _rd(inp)
            market_price = _rd(inp).value_per_share
            implied_growth = 0.05           # matches the forward growth -> round trip closes
            tornado_rows = []
            market = {}
            forecast_years = 10
        rob = assess_robustness(_R())
        assert rob.applicability in (Applicability.USABLE,
                                     Applicability.USABLE_WITH_LIMITATIONS)

    def test_wacc_insufficient_evidence_propagates_to_applicability(self):
        # isolates the WACC -> applicability propagation, independent of the
        # cash-flow family: a synthetic run with a clean anchor but an
        # INSUFFICIENT_EVIDENCE WACC finding must be LIMITED_APPLICABILITY.
        from aleph.valuation.robustness import (
            _applicability, Applicability, RobustnessFinding, Severity,
            Sensitivity)
        clean_anchor = RobustnessFinding(
            key="ANCHOR_SENSITIVITY", severity=Severity.LOW,
            sensitivity=Sensitivity.LOW, headline="ANCHOR SENSITIVITY: LOW",
            detail="", interpretation="")
        wacc_unverified = RobustnessFinding(
            key="WACC_INPUT_QUALITY", severity=Severity.MEDIUM,
            sensitivity=Sensitivity.MEDIUM,
            headline="WACC INPUT QUALITY: INSUFFICIENT_EVIDENCE",
            detail="", interpretation="")
        state, reasons, families, _ = _applicability(
            [clean_anchor, wacc_unverified])
        assert state is Applicability.LIMITED_APPLICABILITY
        assert families == ("market_input_evidence",)

    def test_one_family_is_never_counted_twice(self):
        # two findings in the SAME family (negative base FCFF -> method
        # limitation, AND an anchor-only concern) must yield ONE
        # cash_flow_representativeness entry, not two.
        from aleph.valuation.robustness import (
            _applicability, RobustnessFinding, Severity, Sensitivity)
        anchor_only = RobustnessFinding(
            key="ANCHOR_SENSITIVITY", severity=Severity.HIGH,
            sensitivity=Sensitivity.HIGH, headline="ANCHOR SENSITIVITY: HIGH",
            detail="", interpretation="")
        method_lim = RobustnessFinding(
            key="VALUATION_METHOD_LIMITATION", severity=Severity.HIGH,
            sensitivity=Sensitivity.HIGH,
            headline="VALUATION METHOD LIMITATION: negative base FCFF",
            detail="", interpretation="")
        _, _, families, _ = _applicability([anchor_only, method_lim])
        assert list(families).count("cash_flow_representativeness") == 1

    def test_negative_fcff_forces_limited_applicability(self):
        """robustness._method_limitation still fires on a negative base, and
        this still proves it - but the DCFResult is now CONSTRUCTED rather
        than obtained from run_dcf, because Guard 0d refuses to produce one.

        That is the point worth recording, not a test-plumbing detail: the
        finding has become unreachable through the pipeline. A filing whose
        LATEST FCFF is negative no longer reaches robustness at all - it stops
        at pipeline's own run_dcf and the CLI exits 1 with the guard's
        message. The branch is kept and kept tested because it is the correct
        report for any caller that hands robustness such a run, and because
        deleting live logic on the strength of "nothing calls it today" is how
        a guard becomes untested the day something does. See ISSUES.md #38."""
        from aleph.valuation.robustness import assess_robustness, Applicability
        from aleph.valuation.dcf_engine import DCFResult
        inp = mk(base_cash_flow=-400.0, growth_rates=[0.30] * 10)
        # the arithmetic run_dcf USED to return for this input, by hand
        constructed = DCFResult(
            enterprise_or_equity_value=-8_000.0, equity_value=-13_000.0,
            value_per_share=-13.0, pv_explicit=-3_000.0, pv_terminal=-5_000.0,
            terminal_pct=0.625, yearly=[])

        class _R:
            doc_id = "S"
            bridged = type("B", (), {"inputs": inp, "base_cash_flow_bound": {
                "available": True, "fcff_by_period": {
                    "FY2022": -800.0, "FY2023": -600.0, "FY2024": -400.0},
                "note": ""}, "tornado_ranges": {}})()
            result = constructed
            market_price = None
            implied_growth = None
            tornado_rows = []
            market = {}
            forecast_years = 10
        rob = assess_robustness(_R())
        assert rob.applicability is Applicability.LIMITED_APPLICABILITY


# =========================================================================== #
# P5.1-closure Part 16 - the central economic truth, machine-readable
# =========================================================================== #
class TestCentralConclusion:
    @pytest.mark.needs_filings
    def test_uber_conclusion_names_the_actual_reason_not_a_score(self):
        c = pipeline.value_filing(*UBER).robustness.headline_conclusion
        assert "latest FCFF year is a dominant economic assumption" in c
        assert "comparability is limited" in c
        for banned in ("confidence", "score", "/10", "%"):
            assert banned not in c.lower()

    @pytest.mark.needs_filings
    def test_conclusion_is_in_cli_output(self):
        import subprocess, sys
        out = subprocess.run([sys.executable, "scripts/run_valuation.py",
                              "UBER_FY2024", "76.95"], capture_output=True,
                             text=True).stdout
        assert "VALUATION APPLICABILITY:  LIMITED_APPLICABILITY" in out
        assert "latest FCFF year is a dominant economic assumption" in out


# =========================================================================== #
# P5.1-closure Part 4 - share-unit adversarial sweep (no hidden fallback)
# =========================================================================== #
class TestShareUnitSweep:
    def _derive(self, unit):
        return derive_diluted_shares(
            [sfact("Diluted weighted-average shares outstanding", 1_000_000.0, "FY2023", unit),
             sfact("Diluted weighted-average shares outstanding", 1_010_000.0, "FY2024", unit)],
            {})

    @pytest.mark.parametrize("unit", ["thousands", "millions", "billions",
                                      "USD thousands", "shares in thousands"])
    def test_valid_scale_units_derive(self, unit):
        assert self._derive(unit).status == "derived"

    @pytest.mark.parametrize("unit", ["", "each", "count", "widgets",
                                      "thousands millions", "USD"])
    def test_blank_ambiguous_or_unsupported_units_block(self, unit):
        r = self._derive(unit)
        assert r.status == "blocked"
        assert "INVALID_UNIT" in r.rationale

    def test_conflicting_duplicate_share_facts_block(self):
        r = derive_diluted_shares(
            [sfact("Diluted weighted-average shares A", 1_000_000.0, "FY2024", "thousands"),
             sfact("Diluted weighted-average shares B", 2_000_000.0, "FY2024", "thousands")],
            {})
        assert r.status == "blocked"

    def test_no_magnitude_rescue_no_diagnostic_rescue(self):
        # a blank unit blocks the DERIVATION; the value never reaches the DCF,
        # so no P5 diagnostic and no magnitude check can "rescue" it
        r = self._derive("")
        assert r.base is None and r.status == "blocked"


# =========================================================================== #
# P5.1-closure Part 3 - net-debt unit gate
# =========================================================================== #
class TestNetDebtUnitGate:
    def _nd(self, unit):
        from aleph.valuation.assumptions import derive_net_debt
        facts = [sfact("Long-term debt, net of current portion", 8347.0, "FY2024", "USD millions")]
        ov = Override(fixed_value=1370.0, unit=unit,
                      rationale="stated net debt policy for the test",
                      decided_by="t", decided_at="2026-01-01")
        return derive_net_debt(facts, {"net_debt": ov})

    @pytest.mark.parametrize("unit", ["USD", "thousands millions", "percent",
                                      "each"])
    def test_unrecognised_monetary_unit_blocks_at_derivation(self, unit):
        r = self._nd(unit)
        assert r.status == "blocked" and "INVALID_UNIT" in r.rationale

    @pytest.mark.needs_filings
    def test_plausible_magnitude_wrong_scale_blocks_at_the_bridge(self):
        # override says "thousands", the filing (CFO) is "USD millions".
        # 1370 thousands is a magnitude-plausible number and passes to_millions
        # (a single valid scale token); the bridge cross-scale check catches it.
        from aleph.valuation.bridge import build_dcf_inputs, BridgeError
        from aleph.valuation.assumptions import derive_all
        from aleph.schemas.valuation import MarketAssumption
        rec = pipeline.load_record("UBER_FY2024")
        facts, _ = pipeline.extract_facts(rec)
        ov = pipeline.load_overrides("UBER_FY2024")
        ov["net_debt"] = Override(
            fixed_value=1370.0, unit="thousands",
            rationale="deliberate thousands/millions typo for the unit-gate test",
            decided_by="t", decided_at="2026-01-01")
        ranges = {a.name: a for a in derive_all(facts, ov)}
        assert ranges["net_debt"].status == "overridden"   # passed the derive gate
        market = pipeline.load_market("UBER_FY2024")
        market["discount_rate"] = MarketAssumption(
            name="discount_rate", value=0.09, unit="decimal", as_of="2026-08-28",
            source="derived", rationale="fixed rate for this bridge-level test")
        with pytest.raises(BridgeError, match="different monetary scale"):
            build_dcf_inputs(ranges, market)

    @pytest.mark.needs_filings
    def test_live_filings_pass_the_net_debt_unit_gate(self):
        for doc, price in (UBER, LYFT):
            r = pipeline.value_filing(doc, price)
            assert r.ranges["net_debt"].status == "overridden"


# =========================================================================== #
# P5.1-closure Part 14 - regression invariants (diagnostic/provenance only)
# =========================================================================== #
class TestRegressionInvariants:
    @pytest.mark.needs_filings
    def test_uber_and_lyft_point_values_and_bridge_unchanged(self):
        for doc, price, want in (("UBER_FY2024", 76.95, 77.08),
                                 ("LYFT_FY2025", 17.35, 49.06)):
            r = pipeline.value_filing(doc, price)
            res, i = r.result, r.bridged.inputs
            assert res.value_per_share == pytest.approx(want, abs=0.01)
            # EV / equity / per-share identities
            assert res.equity_value == pytest.approx(
                res.enterprise_or_equity_value - i.net_debt, rel=1e-9)
            assert res.value_per_share == pytest.approx(
                res.equity_value / i.shares_outstanding, rel=1e-9)
            # WACC, base FCFF, terminal value, shares, reverse DCF unchanged
            assert 0.07 < r.wacc.wacc < 0.10
            assert res.pv_terminal > 0 and math.isfinite(res.pv_terminal)
            assert r.implied_growth is not None and math.isfinite(r.implied_growth)
            assert r.tornado_rows[0]["swing"] is not None
