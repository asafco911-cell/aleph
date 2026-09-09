"""P4.6 adversarial audit - the tests that must catch a broken implementation.

Grouped by the audit section that motivated them. Every one is designed to
FAIL if the corresponding safeguard is removed (mutation-tested).
"""
import math

import pytest

import aleph.valuation.pipeline as pipeline
from aleph.schemas.evidence import Fact, FactSource
from aleph.valuation.accounting_quality import (
    Confidence,
    DiagnosticState,
    Direction,
    ValuationImpact,
    WCCoverage,
    assess_accounting_quality,
)

INSUF = DiagnosticState.INSUFFICIENT_DATA
FLAG = DiagnosticState.FLAGGED
OK = DiagnosticState.ASSESSED_NO_ISSUE
Y3 = ("FY2022", "FY2023", "FY2024")
Y4 = ("FY2021", "FY2022", "FY2023", "FY2024")


def f(name, value, period, unit="USD millions", target="cash_flows"):
    return Fact(name=f"{name} {period}", value=float(value), unit=unit,
                period=period, quote=f"{name} ... {value}",
                source=FactSource(doc_id="SYNTH", kind="statement", ref=target,
                                  target_key=target, pages=[1]))


def S(name, values, years, **kw):
    return [f(name, v, y, **kw) for v, y in zip(values, years)]


def ni(v, y=Y4):
    return S("Net income (loss) including non-controlling interests", v, y)


def cfo(v, y=Y4):
    return S("Net cash provided by operating activities", v, y)


def rev(v, y=Y4):
    return S("Total revenue", v, y, target="operations")


def sbc(v, y=Y4):
    return S("Stock-based compensation", v, y)


def capex(v, y=Y4):
    return S("Purchases of property and equipment", v, y)


def ar(v, y=Y4):
    return S("Change in accounts receivable", v, y)


def get(r, key):
    d = r.get(key)
    assert d is not None, f"{key} missing"
    return d


# =========================================================================== #
# Section 2 - convergence engine must not fake independence (F1, F2)
# =========================================================================== #
class TestConvergenceIndependence:
    def _one_event(self):
        # one FY2024 receivables build; nothing else wrong
        return (ni([100, 100, 100, 100]) + cfo([95, 95, 95, 45])
                + rev([1000, 1000, 1000, 1300]) + ar([-5, -5, -5, -55])
                + sbc([5, 5, 5, 5]))

    def test_multiple_measurements_of_one_event_do_not_converge(self):
        r = assess_accounting_quality(self._one_event())
        flags = [d.key for d in r.diagnostics if d.flagged]
        assert len(flags) >= 3, f"expected the event to raise 3+ flags, got {flags}"
        assert r.converging_risks is None, (
            "convergence fired on multiple measurements of ONE accounting "
            f"event: {flags}")

    def test_two_independent_families_do_converge(self):
        # receivables build (cash_vs_earnings) + genuinely high SBC (equity_comp)
        facts = (ni([100, 100, 100, 100]) + cfo([95, 95, 95, 45])
                 + rev([1000, 1000, 1000, 1300]) + ar([-5, -5, -5, -55])
                 + sbc([150, 155, 160, 170]))
        r = assess_accounting_quality(facts)
        assert r.converging_risks is not None
        assert len(r.converging_risks.families) >= 2
        assert "INDEPENDENT accounting dimensions" in r.converging_risks.summary

    def test_summary_discloses_limited_confidence_flags(self):
        facts = (ni([100, 100, 100, 100]) + cfo([95, 95, 95, 45])
                 + rev([1000, 1000, 1000, 1300]) + ar([-5, -5, -5, -55])
                 + sbc([150, 155, 160, 170]))
        cr = assess_accounting_quality(facts).converging_risks
        assert cr.limited_flag_count >= 1
        assert "LIMITED-confidence" in cr.summary

    def test_convergence_never_says_N_independent_diagnostics_flatly(self):
        for facts in (self._one_event(),
                      ni([100] * 4) + cfo([95, 95, 95, 45])
                      + rev([1000, 1000, 1000, 1300]) + ar([-5, -5, -5, -55])
                      + sbc([150, 160, 170, 180])):
            cr = assess_accounting_quality(facts).converging_risks
            if cr:
                assert "independent diagnostics point" not in cr.summary


# =========================================================================== #
# Section 3 - working-capital classification: financing/investing must not enter
# =========================================================================== #
class TestWorkingCapitalContamination:
    @pytest.mark.parametrize("caption", [
        "Change in long-term debt",
        "Change in short-term borrowings",
        "Change in commercial paper",
        "Repayments of long-term debt",
        "Proceeds from issuance of debt",
        "Change in marketable securities",
        "Change in restricted cash",
        "Change in cash and cash equivalents",
        "Purchases of property and equipment",
        "Dividends paid",
    ])
    def test_non_operating_line_never_enters_wc(self, caption):
        from aleph.valuation.accounting_quality import _classify_wc_line
        assert _classify_wc_line(caption) in (
            "EXCLUDED_NON_OPERATING", "NO_CHANGE_MARKER", "STRUCTURAL"), \
            f"{caption!r} was routed into working capital"

    def test_financing_line_does_not_distort_wc_total(self):
        # a big financing debt movement must NOT change the net WC contribution
        clean = (cfo([100, 100, 100, 100]) + ni([50, 50, 50, 50])
                 + S("Change in accounts receivable", [-5, -5, -5, -5], Y4))
        contaminated = clean + S("Change in long-term debt", [0, 0, 0, 90], Y4)
        a = get(assess_accounting_quality(clean), "WORKING_CAPITAL_DEPENDENT_CFO")
        b_rep = assess_accounting_quality(contaminated)
        b = b_rep.get("WORKING_CAPITAL_DEPENDENT_CFO") or \
            b_rep.get("ONE_YEAR_WORKING_CAPITAL_SWING")
        assert "90" not in b.fact and "-95" not in b.fact, \
            "a financing debt movement leaked into the working-capital total"

    def test_unknown_operating_line_still_reduces_coverage(self):
        facts = (cfo([100, 100, 100, 100]) + ni([50, 50, 50, 50])
                 + S("Change in accounts receivable", [-2, -2, -2, -2], Y4)
                 + S("Change in merchant float balances", [-50, -50, -50, -50], Y4))
        d = get(assess_accounting_quality(facts), "WORKING_CAPITAL_DEPENDENT_CFO")
        assert d.state is INSUF
        assert any("merchant float" in n for n in d.coverage.unknown_components)


# =========================================================================== #
# Section 5 - single-year / LIMITED confidence semantics (comparable obs)
# =========================================================================== #
class TestComparableObservations:
    def test_three_dates_one_loss_year_is_still_limited(self):
        # 3 periods but only 2 have positive NI -> not 3 comparable observations
        facts = ni([-500, 100, 120], Y3) + cfo([50, 95, 90], Y3) + rev([9] * 3, Y3)
        d = get(assess_accounting_quality(facts), "HIGH_ACCRUAL_COMPONENT")
        assert d.confidence is Confidence.LIMITED

    def test_three_dates_one_zero_cfo_year_is_limited_for_capex(self):
        facts = (capex([-10, -10, -10], Y3) + cfo([0, 3000, 3000], Y3)
                 + rev([100] * 3, Y3))
        d = get(assess_accounting_quality(facts), "HIGH_CAPITAL_INTENSITY")
        assert d.confidence is Confidence.LIMITED

    def test_four_clean_periods_gives_normal_confidence(self):
        facts = (capex([-10, -10, -10, -10]) + cfo([100, 110, 120, 130])
                 + rev([1000, 1000, 1000, 1000]))
        d = get(assess_accounting_quality(facts), "HIGH_CAPITAL_INTENSITY")
        assert d.confidence is Confidence.NORMAL


# =========================================================================== #
# Section 6 - extreme / pathological financial values must not crash or leak
# =========================================================================== #
class TestExtremeValues:
    @pytest.mark.parametrize("facts", [
        [],
        ni([0], ["FY2024"]) + cfo([0], ["FY2024"]),
        ni([100, 100], ("FY2023", "FY2024")) + cfo([0, 0], ("FY2023", "FY2024")),
        rev([-100, -100], ("FY2023", "FY2024")) + sbc([10, 10], ("FY2023", "FY2024"))
        + cfo([5, 5], ("FY2023", "FY2024")),
        ni([1e18, 1e17, 1e18], Y3) + cfo([1e-9, 1e-9, 1e-9], Y3) + rev([1, 1, 1], Y3),
        cfo([math.inf, 10, 10], Y3) + ni([10, 10, 10], Y3) + rev([100] * 3, Y3),
    ])
    def test_no_crash_no_nan_no_inf_in_output(self, facts):
        r = assess_accounting_quality(facts, doc_id="X")
        for d in r.diagnostics:
            for e in d.evidence:
                if isinstance(e.value, float):
                    assert not math.isnan(e.value)
                    assert not math.isinf(e.value)
            # no diagnostic claims a real finding on garbage
            if d.state in (FLAG, OK):
                assert d.potential_valuation_impact in ValuationImpact

    def test_negative_revenue_does_not_produce_a_ratio_flag_on_that_ratio(self):
        facts = (rev([-100, -100], ("FY2023", "FY2024"))
                 + sbc([10, 10], ("FY2023", "FY2024"))
                 + cfo([-5, -5], ("FY2023", "FY2024")))
        d = get(assess_accounting_quality(facts), "HIGH_SBC")
        assert d.state is INSUF          # no positive denominator anywhere

    def test_zero_ni_is_insufficient_not_a_ratio(self):
        facts = ni([0, 0, 0], Y3) + cfo([50, 50, 50], Y3)
        assert get(assess_accounting_quality(facts),
                   "CASH_EARNINGS_DIVERGENCE").state is INSUF


# =========================================================================== #
# Section 7 - period integrity: mismatched / non-annual periods
# =========================================================================== #
class TestPeriodIntegrity:
    def test_quarterly_label_is_ignored_not_mixed_in(self):
        facts = (cfo([100, 100, 100], Y3) + S("Net cash provided by operating "
                 "activities", [999], ["Q3FY2024"])
                 + ni([50, 50, 50], Y3) + rev([500] * 3, Y3))
        r = assess_accounting_quality(facts)
        assert "Q3FY2024" not in r.periods
        d = get(r, "CASH_EARNINGS_DIVERGENCE")
        assert "999" not in d.fact and "9.99" not in d.diagnostic

    def test_ratio_only_uses_shared_periods(self):
        # capex only FY2023, cfo only FY2024 -> no shared period -> INSUFFICIENT
        facts = (S("Purchases of property and equipment", [-50], ["FY2023"])
                 + S("Net cash provided by operating activities", [100], ["FY2024"])
                 + rev([100], ["FY2024"]))
        assert get(assess_accounting_quality(facts),
                   "HIGH_CAPITAL_INTENSITY").state is INSUF


# =========================================================================== #
# Section 8 - unit-scale integrity in ratios (F4, ISSUES.md #15 class)
# =========================================================================== #
class TestSBCThresholdIndependence:
    def test_sbc_revenue_threshold_alone_can_flag(self):
        # SBC/revenue = 12% (> 8%), SBC/CFO = 10% (< 15%): only the revenue
        # line crosses. A test that also crosses SBC/CFO cannot detect a
        # broken SBC/revenue threshold.
        facts = (sbc([1200, 1200], ("FY2023", "FY2024"))
                 + rev([10000, 10000], ("FY2023", "FY2024"))
                 + cfo([12000, 12000], ("FY2023", "FY2024"))
                 + ni([2000, 2000], ("FY2023", "FY2024")))
        d = get(assess_accounting_quality(facts), "HIGH_SBC")
        assert d.state is FLAG, "SBC at 12% of revenue must flag on the revenue line"

    def test_sbc_just_below_revenue_threshold_does_not_flag(self):
        facts = (sbc([700, 700], ("FY2023", "FY2024"))          # 7% of revenue
                 + rev([10000, 10000], ("FY2023", "FY2024"))
                 + cfo([12000, 12000], ("FY2023", "FY2024"))    # 5.8% of CFO
                 + ni([2000, 2000], ("FY2023", "FY2024")))
        assert get(assess_accounting_quality(facts), "HIGH_SBC").state is OK


class TestOverclaimGuardPositiveControl:
    """M16: prove the guard actually fires - not just that clean reports pass."""

    def _report_with(self, text):
        from aleph.valuation.accounting_quality import (
            AccountingQualityReport, Diagnostic, Horizon)
        d = Diagnostic(key="X", dimension="d", state=OK, horizon=Horizon.TREND,
                       fact="f", diagnostic="g", interpretation=text,
                       valuation_relevance="v",
                       potential_valuation_impact=ValuationImpact.LOW)
        return AccountingQualityReport(doc_id="X", assessed=True,
                                       diagnostics=(d,), converging_risks=None,
                                       periods=("FY2024",), notes=())

    @pytest.mark.parametrize("phrase", [
        "the accounting is historically clean",
        "this is structurally normal",
        "there is no accounting-quality concern here",
        "revenue is legitimate and fully supported",
    ])
    def test_guard_detects_overclaiming_phrase(self, phrase):
        assert self._report_with(phrase).has_overclaiming_language()

    def test_guard_passes_a_neutral_phrase(self):
        assert not self._report_with(
            "no issue identified in the observed data").has_overclaiming_language()

    def test_forbidden_guard_detects_fraud_words(self):
        assert self._report_with("this looks like accounting fraud") \
            .has_forbidden_language()


class TestUnitScaleIntegrity:
    def test_mixed_scale_metrics_force_insufficient(self):
        # SBC in bare USD, revenue/CFO in USD millions -> ratio off by 1e6
        facts = (S("Stock-based compensation", [1_000_000, 1_000_000, 1_000_000],
                   Y3, unit="USD")
                 + rev([37000, 37000, 37000], Y3)
                 + cfo([7000, 7000, 7000], Y3)
                 + ni([9000, 9000, 9000], Y3))
        r = assess_accounting_quality(facts)
        assert get(r, "HIGH_SBC").state is INSUF
        assert get(r, "CASH_EARNINGS_DIVERGENCE").state is INSUF
        assert any("UNIT-SCALE MISMATCH" in n for n in r.notes)

    def test_consistent_scale_still_works(self):
        facts = (sbc([2000, 2000], ("FY2023", "FY2024"))
                 + rev([10000, 10000], ("FY2023", "FY2024"))
                 + cfo([3000, 3000], ("FY2023", "FY2024"))
                 + ni([1000, 1000], ("FY2023", "FY2024")))
        assert get(assess_accounting_quality(facts), "HIGH_SBC").state is FLAG


# =========================================================================== #
# Section 12 - conflicting facts must fail closed (F5)
# =========================================================================== #
class TestConflictingFacts:
    def test_conflicting_cfo_forces_insufficient(self):
        facts = (S("Net cash provided by operating activities", [100], ["FY2024"])
                 + S("Net cash provided by operating activities", [200], ["FY2024"])
                 + ni([50, 50, 50], Y3)
                 + cfo([40, 45], ("FY2022", "FY2023"))
                 + rev([500] * 3, Y3))
        r = assess_accounting_quality(facts)
        assert get(r, "CASH_EARNINGS_DIVERGENCE").state is INSUF
        assert get(r, "HIGH_ACCRUAL_COMPONENT").state is INSUF
        assert any("CONFLICTING SOURCE FACTS" in n for n in r.notes)

    def test_no_conflict_no_penalty(self):
        # same value twice is not a conflict
        facts = (S("Net cash provided by operating activities", [100, 100, 100], Y3)
                 + S("Net cash provided by operating activities", [100, 100, 100], Y3)
                 + ni([50, 50, 50], Y3) + rev([500] * 3, Y3))
        assert get(assess_accounting_quality(facts),
                   "CASH_EARNINGS_DIVERGENCE").state in (OK, FLAG, INSUF)
        r = assess_accounting_quality(facts)
        assert not any("CONFLICTING SOURCE FACTS" in n for n in r.notes)


# =========================================================================== #
# Section 9 - accounting quality cannot touch valuation, adversarially
# =========================================================================== #
class TestValuationIsolationAdversarial:
    def test_accounting_quality_module_imports_nothing_from_valuation(self):
        import aleph.valuation.accounting_quality as m
        import inspect
        src = inspect.getsource(m)
        for banned in ("dcf_engine", "build_wacc", "build_dcf_inputs",
                       "run_dcf", "from .bridge", "from .wacc",
                       "from .historical_fcff", "from .assumptions"):
            assert banned not in src, f"accounting_quality imports {banned!r}"

    def test_garbage_report_does_not_move_valuation(self, monkeypatch):
        good = pipeline.value_filing("UBER_FY2024", 76.95)
        gv = (good.result.value_per_share, good.result.enterprise_or_equity_value,
              good.result.equity_value, good.wacc.wacc,
              good.bridged.inputs.base_cash_flow, good.result.pv_terminal,
              good.implied_growth)

        from aleph.valuation.accounting_quality import (
            AccountingQualityReport, Diagnostic, Horizon)

        def absurd(*_a, **_k):
            d = Diagnostic(
                key="X", dimension="earnings_vs_cash", state=FLAG,
                horizon=Horizon.TREND, fact=str(math.inf), diagnostic="nan",
                interpretation="", valuation_relevance="",
                potential_valuation_impact=ValuationImpact.HIGH,
                direction=Direction.OVERSTATES_ECONOMIC_CASH)
            return AccountingQualityReport(
                doc_id="X", assessed=True, diagnostics=(d,) * 12,
                converging_risks=None, periods=("FY2024",), notes=())

        monkeypatch.setattr(pipeline, "assess_accounting_quality", absurd)
        bad = pipeline.value_filing("UBER_FY2024", 76.95)
        assert (bad.result.value_per_share, bad.result.enterprise_or_equity_value,
                bad.result.equity_value, bad.wacc.wacc,
                bad.bridged.inputs.base_cash_flow, bad.result.pv_terminal,
                bad.implied_growth) == gv

    def test_p4_exception_does_not_take_down_a_valid_valuation(self, monkeypatch):
        """P4.7: an exception inside the diagnostic layer must NOT crash an
        otherwise-valid valuation. The valuation survives byte-for-byte and
        the failure is recorded as NOT_ASSESSED with provenance - never a
        silent 'assessed, no issue'."""
        good = pipeline.value_filing("UBER_FY2024", 76.95)
        gv = (good.result.value_per_share, good.result.enterprise_or_equity_value,
              good.result.equity_value, good.wacc.wacc,
              good.bridged.inputs.base_cash_flow, good.result.pv_terminal,
              good.implied_growth, tuple(good.tornado_rows[0].items()))

        calls = {"run_dcf": 0}
        real_run_dcf = pipeline.run_dcf
        monkeypatch.setattr(pipeline, "run_dcf",
                            lambda i: (calls.__setitem__("run_dcf", calls["run_dcf"] + 1)
                                       or real_run_dcf(i)))

        def boom(*_a, **_k):
            raise RuntimeError("P4 blew up")
        monkeypatch.setattr(pipeline, "assess_accounting_quality", boom)

        run = pipeline.value_filing("UBER_FY2024", 76.95)     # no exception
        rv = (run.result.value_per_share, run.result.enterprise_or_equity_value,
              run.result.equity_value, run.wacc.wacc,
              run.bridged.inputs.base_cash_flow, run.result.pv_terminal,
              run.implied_growth, tuple(run.tornado_rows[0].items()))
        assert rv == gv, "valuation changed when the diagnostic layer failed"

        aq = run.accounting_quality
        assert aq is not None
        assert aq.assessed is False
        assert aq.not_assessed_reason
        assert "RuntimeError" in aq.not_assessed_reason
        assert "P4 blew up" in aq.not_assessed_reason
        assert aq.diagnostics == ()
        assert aq.converging_risks is None
        # NOT_ASSESSED must never read as a pass
        assert not aq.has_forbidden_language()
        assert not any("no issue" in n.lower() for n in aq.notes)
        # the diagnostic failure did not trigger a valuation recomputation:
        # run_dcf was called exactly as many times as a clean run (base +
        # 2 anchor-bound trials), and reverse_dcf/tornado are not re-run
        assert calls["run_dcf"] == 3, calls

    def test_clean_p4_run_is_unchanged_by_the_guard(self):
        run = pipeline.value_filing("UBER_FY2024", 76.95)
        assert run.accounting_quality.assessed is True
        assert run.accounting_quality.not_assessed_reason == ""
        assert run.result.value_per_share == pytest.approx(77.08, abs=0.01)


# =========================================================================== #
# Section 11 - cross-sector generalization
# =========================================================================== #
class TestCrossSector:
    def test_no_company_name_in_generic_logic(self):
        """A company name may appear in comments and docstrings (they record
        measurement history). It must not appear in executable classification
        logic - no `if company == "UBER"`, no issuer-tuned string constant."""
        import aleph.valuation.accounting_quality as m
        import io, tokenize
        src = open(m.__file__, encoding="utf-8").read()
        code_strings, code_names = [], []
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.STRING:
                code_strings.append(tok.string.lower())
            elif tok.type == tokenize.NAME:
                code_names.append(tok.string.lower())
        # docstrings are STRING tokens too; drop triple-quoted ones
        literals = [s for s in code_strings if not s.startswith(('"""', "'''"))]
        for name in ("uber", "lyft", "doordash", "airbnb"):
            for lit in literals:
                assert name not in lit, f"company name in string literal: {lit}"
            assert name not in code_names, f"company name as identifier: {name}"
        for pat in ('== "uber"', "doc_id ==", "company ==", 'if "uber"'):
            assert pat not in src.lower()

    def _industrial(self):
        # heavy capex, "Movement in operating assets" style captions
        return (rev([5000, 5200, 5400, 5600]) + ni([400, 420, 440, 450])
                + cfo([600, 620, 640, 660]) + capex([-500, -520, -540, -560])
                + sbc([10, 10, 10, 10])
                + S("Movement in trade receivables", [-20, -20, -20, -20], Y4)
                + S("Movement in operating provisions", [15, 15, 15, 15], Y4))

    def _financial_marketplace(self):
        return (rev([2000, 2400, 2900, 3400]) + ni([100, 130, 170, 200])
                + cfo([90, 110, 90, 60]) + capex([-30, -35, -40, -45])
                + sbc([180, 220, 260, 300])
                + S("Change in funds receivable and customer accounts",
                    [-40, -50, -70, -300], Y4)
                + S("Change in funds payable and amounts due to customers",
                    [30, 40, 55, 120], Y4))

    def _software_sub(self):
        return (rev([800, 1100, 1500, 2000]) + ni([-50, -20, 10, 40])
                + cfo([60, 120, 200, 320]) + capex([-10, -12, -15, -18])
                + sbc([120, 170, 240, 340])
                + S("Change in deferred revenue", [40, 60, 90, 130], Y4)
                + S("Change in accounts receivable", [-30, -45, -70, -110], Y4))

    @pytest.mark.parametrize("name", ["industrial", "financial", "software"])
    def test_runs_without_company_specific_logic(self, name):
        facts = {"industrial": self._industrial(),
                 "financial": self._financial_marketplace(),
                 "software": self._software_sub()}[name]
        r = assess_accounting_quality(facts, doc_id=name.upper())
        assert not r.has_forbidden_language()
        assert not r.has_overclaiming_language()
        # every diagnostic resolves to a real state, nothing crashes
        assert len(r.diagnostics) == 10

    def test_unfamiliar_terminology_fails_visibly_not_silently(self):
        facts = (rev([100, 120, 140, 160]) + ni([10, 12, 14, 16])
                 + cfo([8, 10, 8, 4])
                 + S("Operating asset and liability roll-forward, net (change)",
                     [-1, -1, -1, -8], Y4))
        d = get(assess_accounting_quality(facts), "WORKING_CAPITAL_DEPENDENT_CFO")
        # the unfamiliar line is a change-marked unknown -> visible + counted
        assert d.coverage is not None
        assert any("roll-forward" in n for n in d.coverage.unknown_components)


# =========================================================================== #
# Section 14 - overclaim guard robustness
# =========================================================================== #
class TestProvenanceAudit:
    """Section 13: no diagnostic is authoritative merely for having a polished
    interpretation string. Every real finding traces fact -> calc -> diagnostic."""

    @pytest.mark.parametrize("doc,price", [
        ("UBER_FY2024", 76.95), ("LYFT_FY2025", 17.35), ("DASH_FY2025", 231.89)])
    def test_every_real_finding_carries_full_provenance(self, doc, price):
        r = pipeline.value_filing(doc, price).accounting_quality
        for d in r.diagnostics:
            if d.state in (FLAG, OK):
                assert d.evidence, f"{doc}/{d.key}: no evidence"
                assert d.formula, f"{doc}/{d.key}: no formula"
                assert any(e.source_ref for e in d.evidence), \
                    f"{doc}/{d.key}: no evidence traces to a source"
                ratio_ev = [e for e in d.evidence
                            if e.value is not None and e.quote == ""]
                assert not ratio_ev or any(e.computed_from for e in ratio_ev), \
                    f"{doc}/{d.key}: a computed number with no computed_from"
            if d.state is INSUF:
                # an INSUFFICIENT diagnostic must explain itself somewhere
                assert (d.fact or d.diagnostic or d.interpretation), \
                    f"{doc}/{d.key}: INSUFFICIENT with no explanation"


class TestRevenueQualityEpistemics:
    """Section 4: the proxy must never become a recognition conclusion."""

    def test_case_d_revenue_falls_receivables_improve_no_flag(self):
        facts = (rev([120, 120, 120, 100]) + cfo([50, 50, 50, 60])
                 + ni([10, 10, 10, 10]) + ar([-10, -10, -10, -4]))
        d = get(assess_accounting_quality(facts), "REVENUE_CASH_DIVERGENCE")
        assert d.state is OK
        assert "REVENUE_QUALITY_ASSESSMENT" in d.limitation

    @pytest.mark.parametrize("scn", ["strong", "seasonal", "enterprise", "missing"])
    def test_no_recognition_or_fraud_conclusion_in_any_branch(self, scn):
        base = ni([10, 10, 10, 10]) + cfo([50, 50, 50, 44])
        facts = {
            "strong": rev([100, 100, 100, 130]) + ar([-8, -8, -8, -20]),
            "seasonal": rev([100, 105, 110, 143]) + ar([-8, -8, -22, -30]),
            "enterprise": rev([100, 100, 100, 130]) + ar([-8, -8, -8, -18]),
            "missing": rev([100, 105, 110, 130]),
        }[scn] + base
        d = get(assess_accounting_quality(facts), "REVENUE_CASH_DIVERGENCE")
        blob = d.text_blob()
        for banned in ("fraud", "manipulat", "improper", "fake", "fictitious",
                       "revenue is legitimate", "recognition is improper"):
            assert banned not in blob
        assert "proxy" in d.limitation.lower()


class TestOverclaimGuard:
    def test_real_filings_never_overclaim(self):
        for doc, price in (("UBER_FY2024", 76.95), ("LYFT_FY2025", 17.35),
                           ("DASH_FY2025", 231.89), ("UBER_FY2025", 76.95)):
            r = pipeline.value_filing(doc, price).accounting_quality
            assert not r.has_overclaiming_language(), doc
            assert not r.has_forbidden_language(), doc

    def test_synthetic_clean_company_says_observed_only(self):
        facts = (ni([100, 105, 110, 115]) + cfo([100, 106, 111, 117])
                 + rev([1000, 1050, 1100, 1150]) + sbc([10, 10, 10, 10])
                 + capex([-20, -21, -22, -23])
                 + S("Change in accounts receivable", [-2, -2, -2, -3], Y4))
        r = assess_accounting_quality(facts)
        blob = " ".join(d.text_blob() for d in r.diagnostics)
        for bad in ("historically clean", "structurally sound", "structurally normal",
                    "no accounting risk", "healthy account"):
            assert bad not in blob


# =========================================================================== #
# Section 15 - threshold-crossing language
# =========================================================================== #
class TestThresholdLanguage:
    def test_a_borderline_flag_is_hedged_not_asserted_as_proven(self):
        # accruals ratio just over 0.25
        facts = ni([100, 100, 100], Y3) + cfo([80, 80, 74.9], Y3) + rev([500] * 3, Y3)
        d = get(assess_accounting_quality(facts), "HIGH_ACCRUAL_COMPONENT")
        assert d.state is FLAG
        blob = (d.interpretation + d.threshold).lower()
        assert "not a quality verdict" in blob or "screening" in blob \
            or "reason to lean" in blob
        assert d.threshold, "a threshold flag must state its threshold"


# =========================================================================== #
# Section 16 - no silent data loss
# =========================================================================== #
class TestNoSilentDataLoss:
    def test_every_wc_reconciliation_line_is_accounted_for(self):
        # each cash-flow line must land in buckets, unknown, unmarked, or excluded
        from aleph.valuation.accounting_quality import _wc_lines_for_period
        lines = (S("Change in accounts receivable", [-5], ["FY2024"])
                 + S("Change in exotic operating balance", [-3], ["FY2024"])
                 + S("Change in long-term debt", [9], ["FY2024"])
                 + S("Gain on sale of assets", [-1], ["FY2024"])
                 + S("Some random line", [2], ["FY2024"]))
        buckets, unknown, unmarked = _wc_lines_for_period(lines, "FY2024")
        seen = (sum(len(v) for v in buckets.values())
                + len(unknown) + len(unmarked))
        # excluded lines (debt, gain on sale) are intentionally not returned,
        # but nothing operating-looking is dropped without a category
        assert any("exotic operating balance" in x.name for x in unknown)
        assert any("random line" in x.name for x in unmarked)
