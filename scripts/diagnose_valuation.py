"""Everything the valuation does NOT depend on, for one filing.

Same arguments as run_valuation.py: a doc_id and an optional market price.

WHY THIS IS A SEPARATE COMMAND. These layers - accounting quality, valuation
robustness, and five marked EXPERIMENTAL - are more than three quarters of
src/aleph/valuation/ by line count and change no valuation number. Printed
underneath the result they made run_valuation.py 522 lines long and made the
project look like something it is not. Measured, by import reachability and
line count:

    2,786 lines  a valuation number depends on it
    3,191 lines  diagnostic, computed inside value_filing, printed here
    4,962 lines  diagnostic, EXPERIMENTAL, computed here
    1,407 lines  wired to nothing, exercised only by tests

See README.md, "Diagnostic layers (not in the base DCF)", and docs/adr/0009
for why none of them was promoted into the base DCF.

EXCEPTIONS. Each layer used to sit behind a bare `except Exception` that
printed "not assessed" and carried on. Measured: no layer raises on any of the
four valued filings, and no diagnostic module contains a single `raise` - they
report status objects instead. So the bare handlers were catching nothing they
were written for, while being able to swallow any bug in the layer. One
already had: a `TypeError` from formatting `None` with `:.2f` surfaced as
"P6 not assessed", which read as an evidence failure (ISSUES.md #38).

They are replaced by DIAGNOSTIC_ERRORS below - the only exception types
anything under valuation/ raises. Anything else propagates and this script
exits non-zero with a traceback. That is affordable HERE and was not
affordable in run_valuation.py: a bug in a diagnostic must not take down a
valuation, and now it cannot, because the valuation is a different command.
"""
import sys

from aleph.valuation.bridge import BridgeError
from aleph.valuation.pipeline import (
    BlockedError,
    ContractBlockedError,
    DCFConsistencyError,
    value_filing,
)

# The complete set of exception types raised anywhere under
# src/aleph/valuation/, established by grepping every `raise` in the package:
# BridgeError (bridge.py, wacc.py) and DCFConsistencyError (dcf_engine.py).
# Both are ValueError subclasses. A layer that fails any other way has a bug,
# and a bug must not be reported as "not assessed".
DIAGNOSTIC_ERRORS = (DCFConsistencyError, BridgeError)

doc_id = sys.argv[1]
market_price = float(sys.argv[2]) if len(sys.argv) > 2 else None

try:
    run = value_filing(doc_id, market_price)
except ContractBlockedError as exc:
    print(f"DATA CONTRACT BLOCKED: {'; '.join(exc.result.reasons)}")
    print("Run scripts/run_valuation.py for the field-by-field table.")
    sys.exit(1)
except BlockedError as exc:
    print(f"BLOCKED: {[a.name for a in exc.blocked]}")
    sys.exit(1)
except (BridgeError, DCFConsistencyError) as exc:
    print(f"{type(exc).__name__}: {exc}")
    sys.exit(1)

bridged = run.bridged
result = run.result

# P4 - accounting quality. Diagnostic only: nothing here has touched a
# valuation number above. Every dimension is printed, including the ones that
# came back INSUFFICIENT_DATA - a missing diagnostic must not silently vanish.
aq = run.accounting_quality
if aq is not None and aq.not_assessed_reason:
    print("\n" + "=" * 74)
    print("ACCOUNTING QUALITY:  NOT ASSESSED")
    print("=" * 74)
    print(f"  reason: {aq.not_assessed_reason}")
    print("  The valuation above is complete and unaffected; the diagnostic "
          "layer did not run.")
elif aq is not None:
    header = "ASSESSED" if aq.assessed else "INSUFFICIENT DATA"
    print("\n" + "=" * 74)
    print("ACCOUNTING QUALITY:  " + header)
    print("=" * 74)
    print(f"  periods: {', '.join(aq.periods) or 'none'}   (diagnostic layer - "
          "does not modify FCFF, WACC, or value)")
    _DIM_TITLES = {
        "earnings_vs_cash": "Earnings / Cash",
        "accruals": "Accruals",
        "working_capital": "Working Capital",
        "revenue_quality": "Revenue Quality",
        "capital_intensity": "Capital Intensity",
        "sbc": "SBC",
        "sbc_dilution": "SBC Dilution",
        "one_off_items": "One-Off Items",
    }
    for dim, title in _DIM_TITLES.items():
        entries = aq.by_dimension(dim)
        if not entries:
            continue
        print(f"\n  {title}")
        for d in entries:
            print(f"    [{d.state.value}] {d.key}  "
                  f"impact={d.potential_valuation_impact.value}"
                  f"  confidence={d.confidence.value}"
                  + (f"  horizon={d.horizon.value}" if d.horizon else ""))
            print(f"      fact          : {d.fact}")
            print(f"      diagnostic    : {d.diagnostic}")
            print(f"      interpretation: {d.interpretation}")
            print(f"      valuation rel.: {d.valuation_relevance}")
            if d.limitation:
                print(f"      limitation    : {d.limitation}")
            if d.coverage is not None:
                print(f"      wc coverage   : {d.coverage.render()}")
            if d.evidence:
                shown = [e for e in d.evidence if e.quote][:2]
                for e in shown:
                    print(f"      evidence      : {e.label} = {e.value:,.0f} "
                          f"{e.unit} [{e.source_ref}]")
    print("\n  FCFF Quality")
    for note in aq.notes:
        print(f"    {note}")
    print("\n  Converging Risks")
    if aq.converging_risks:
        print(f"    {aq.converging_risks.summary}")
    else:
        print("    none: fewer than the threshold number of MEDIUM/HIGH flags "
              "point the same way. Not a statement that accounting quality is high.")

# P5 - valuation robustness. Diagnostic only: it re-ran the pure DCF engine on
# copies to measure how much of the answer is a choice. It changed nothing above.
rob = getattr(run, "robustness", None)
if rob is not None and rob.not_assessed_reason:
    print("\n" + "=" * 74)
    print("VALUATION ROBUSTNESS:  NOT ASSESSED")
    print("=" * 74)
    print(f"  reason: {rob.not_assessed_reason}")
elif rob is not None:
    print("\n" + "=" * 74)
    print(f"VALUATION APPLICABILITY:  {rob.applicability.value}"
          + (f"   (limitation families: {', '.join(rob.limitation_families)})"
             if rob.limitation_families else ""))
    print("=" * 74)
    if rob.headline_conclusion:
        print(f"  {rob.headline_conclusion}")
    for why in rob.applicability_reasons:
        print(f"    - {why}")
    print("\n" + "=" * 74)
    print("VALUATION ROBUSTNESS:  ASSESSED  (diagnostic only - valuation above "
          "is unchanged)")
    print("=" * 74)
    if rob.anchor_table:
        print("  FCFF anchor -> value per share:")
        for a in rob.anchor_table:
            v = "REJECTED" if a.value_per_share is None else f"{a.value_per_share:>10,.2f}"
            print(f"    {a.method:<18} FCFF {a.fcff:>13,.0f}  ->  {v}"
                  + (f"   ({a.rejected[:50]})" if a.rejected else ""))
    for f in rob.findings:
        cat = f"  [{f.category.value}]" if getattr(f, "category", None) else ""
        print(f"\n  [{f.severity.value}] {f.headline}{cat}")
        if f.detail:
            print(f"      {f.detail}")
        if f.interpretation:
            print(f"      -> {f.interpretation}")
    if getattr(rob, "model_conventions", ()):
        print("\n  MODEL CONVENTIONS  (choices between the filing and this "
              "valuation - all MODEL_CONVENTION grade):")
        for mc in rob.model_conventions:
            print(f"    {mc.name:<26} = {mc.value}")
            print(f"        {mc.rationale}")
            print(f"        location: {mc.location}  |  effect: {mc.effect}")
    for note in rob.notes:
        print(f"\n  {note}")

# P6 - sustainable / normalized FCFF. EXPERIMENTAL and NOT wired into the base
# DCF: the point value above is unchanged and still anchors on the latest
# reconstructed FCFF. This block runs assess_sustainable_fcff() directly here,
# not inside pipeline.value_filing, so the orchestrator carries no dependency
# on it (ISSUES.md #33, P6; promotion needs an ADR).
try:
    from aleph.valuation.sustainable_fcff import (
        assess_sustainable_fcff,
        sustainable_scenario_valuation,
    )
    _sust = assess_sustainable_fcff(run)
except DIAGNOSTIC_ERRORS as _exc:
    _sust = None
    print(f"\nSUSTAINABLE FCFF (EXPERIMENTAL): not assessed "
          f"({type(_exc).__name__}: {_exc})")

if _sust is not None:
    print("\n" + "=" * 74)
    print("SUSTAINABLE FCFF  (EXPERIMENTAL - NOT IN THE BASE DCF)")
    print("=" * 74)
    print(f"  status : {_sust.status.value}      regime : {_sust.regime.value}")
    print(f"  reconciliation_ok={_sust.reconciliation_ok}  "
          f"double_count_ok={_sust.double_count_ok}")
    print(f"  {'period':<8}{'CFO':>10}{'op cash exWC':>14}{'WC contrib':>12}"
          f"{'FCFF':>10}{'FCFF exWC':>11}{'recon':>7}")
    for p in _sust.periods:
        print(f"  {p.period:<8}{p.cfo:>10,.0f}{p.operating_cash_before_wc:>14,.0f}"
              f"{p.working_capital_total:>12,.0f}{p.reconstructed_fcff:>10,.0f}"
              f"{p.fcff_ex_working_capital:>11,.0f}{str(p.reconciles):>7}")
    print(f"\n  base DCF anchors on the latest reconstructed FCFF = "
          f"{_sust.latest_reconstructed_fcff:,.0f} ({_sust.latest_period})")
    if _sust.status.value == "SUPPORTED_RANGE":
        print(f"  evidence-based SUSTAINABLE FCFF   low {_sust.low:,.0f}   "
              f"central {_sust.central:,.0f}   high {_sust.high:,.0f}")
        for b in (_sust.low_basis, _sust.central_basis, _sust.high_basis):
            print(f"    - {b}")
        print("\n  sustainable-anchor scenario valuation (WACC, terminal "
              "growth, horizon, shares, net debt all held fixed):")
        for row in sustainable_scenario_valuation(bridged.inputs, _sust):
            v = ("REJECTED" if row.value_per_share is None
                 else f"{row.value_per_share:>9,.2f}")
            d = ("" if row.delta_vs_current is None
                 else f"   (delta vs current {row.delta_vs_current:+,.2f})")
            print(f"    {row.label:<20} FCFF {row.base_fcff:>10,.0f}  ->  {v}/share{d}")
    else:
        print("  SUSTAINABLE_FCFF: INSUFFICIENT_EVIDENCE - no range produced; "
              "the base DCF is unaffected.")
    for r in _sust.reasons:
        print(f"    - {r}")

# P7 - market-implied expectations (investor decision layer). EXPERIMENTAL and
# NOT wired into the base DCF. The market price flows in; analytical outputs
# flow out; nothing here changes a valuation number. Requires a market price.
if market_price:
    try:
        from aleph.valuation.market_expectations import assess_market_expectations
        _me = assess_market_expectations(run, market_price=market_price)
    except DIAGNOSTIC_ERRORS as _exc:
        _me = None
        print(f"\nMARKET EXPECTATIONS (EXPERIMENTAL): not assessed "
              f"({type(_exc).__name__}: {_exc})")

    if _me is not None:
        iug, ibf = _me.implied_uniform_growth, _me.implied_base_fcff
        print("\n" + "=" * 74)
        print("MARKET EXPECTATIONS  (EXPERIMENTAL - NOT IN THE BASE DCF)")
        print("=" * 74)
        print(f"  Market price          : {_me.price:>14,.2f}   (as of {_me.as_of})")
        print(f"  Forward DCF           : {_me.forward_dcf_value:>14,.2f}")
        g = "NOT_SOLVABLE" if iug.value is None else f"{iug.value:.2%}"
        print(f"  Market-implied uniform growth : {g:>14}"
              "   (uniform-growth equivalent, all other inputs fixed;")
        print(f"  {'':<32}not 'expected revenue growth')")
        f = "NOT_SOLVABLE" if ibf.value is None else f"{ibf.value:,.0f}"
        print(f"  Market-implied base FCFF      : {f:>14}   "
              f"(latest reconstructed {_me.base_fcff:,.0f})")
        print("\n  IMPLIED GROWTH BY FCFF ANCHOR (no anchor is chosen as correct):")
        for a in _me.anchor_scenarios:
            gg = "NOT_SOLVABLE" if a.implied_uniform_growth is None else f"{a.implied_uniform_growth:+.2%}"
            ff = "n/a" if a.anchor_fcff is None else f"{a.anchor_fcff:,.0f}"
            print(f"    {a.anchor_label:<20} FCFF {ff:>10}  ->  implied growth {gg}")
        print("\n  SENSITIVITY OF IMPLIED GROWTH (existing bands only):")
        for r in _me.wacc_sensitivity:
            gg = "NOT_SOLVABLE" if r.implied_uniform_growth is None else f"{r.implied_uniform_growth:+.2%}"
            print(f"    WACC {r.label:<5} {r.param_value:.2%}  ->  {gg}")
        for r in _me.terminal_growth_sensitivity:
            gg = "NOT_SOLVABLE" if r.implied_uniform_growth is None else f"{r.implied_uniform_growth:+.2%}"
            print(f"    g_T  {r.label:<5} {r.param_value:.2%}  ->  {gg}")
        print("\n  EXPECTATIONS vs EVIDENCE:")
        for gp in _me.gaps:
            print(f"    {gp.quantity:<24} implied={gp.market_implied}  [{gp.direction}]")
        print(f"\n  VS EVIDENCE : {_me.vs_evidence.value}")
        print(f"  LEVEL       : {_me.level.value}")
        print(f"\n  INTERPRETATION:\n    {_me.interpretation}")

# P8 - evidence depth. EXPERIMENTAL. Classifies the accounting evidence that is
# actually present and reports where it runs out. Changes no valuation number
# and promotes neither P6 nor P7.
try:
    from aleph.valuation.evidence_depth import assess_evidence_depth
    _ev = assess_evidence_depth(run)
except DIAGNOSTIC_ERRORS as _exc:
    _ev = None
    print(f"\nEVIDENCE DEPTH (EXPERIMENTAL): not assessed "
          f"({type(_exc).__name__}: {_exc})")

if _ev is not None:
    print("\n" + "=" * 74)
    print("EVIDENCE DEPTH  (EXPERIMENTAL - NOT IN THE BASE DCF)")
    print("=" * 74)
    print(f"  periods {_ev.oldest_period}..{_ev.newest_period}   "
          f"reduces_uncertainty = {_ev.reduces_uncertainty.value}")
    print(f"  {'period':<8}{'type':<10}{'score':<24}{'CFO rep':>11}"
          f"{'residual':>10}{'reconciliation':>24}")
    for pe in _ev.period_evidence:
        cr = "n/a" if pe.cfo_reported is None else f"{pe.cfo_reported:,.0f}"
        rs = "n/a" if pe.residual is None else f"{pe.residual:,.0f}"
        print(f"  {pe.period:<8}{pe.period_type:<10}{pe.score.value:<24}"
              f"{cr:>11}{rs:>10}{pe.reconciliation_status.value:>24}")
    print("\n  WORKING CAPITAL BY SUBCATEGORY (period scale):")
    subs = sorted({k for pe in _ev.period_evidence for k in pe.wc_by_subcategory})
    print("    " + f"{'subcategory':<26}"
          + "".join(f"{pe.period:>11}" for pe in _ev.period_evidence))
    for s in subs:
        print("    " + f"{s:<26}"
              + "".join(f"{pe.wc_by_subcategory.get(s, 0.0):>11,.0f}"
                        for pe in _ev.period_evidence))
    for pe in _ev.period_evidence:
        if pe.unclassified_wc:
            print(f"    [{pe.period}] UNCLASSIFIED cash-flow caption(s): "
                  f"{pe.unclassified_wc}")
    print(f"\n  P6 working-capital totals unchanged: agree = {_ev.p6_p8_wc_agree}")
    print(f"  CAPEX SPLIT : {_ev.capex_evidence.status.value}  "
          f"({_ev.capex_evidence.reason})")
    print(f"  ONE-OFF     : {_ev.one_off_evidence.tier.value}  "
          f"(explicit={list(_ev.one_off_evidence.explicit_items)[:3]}"
          f"{'...' if len(_ev.one_off_evidence.explicit_items) > 3 else ''}; "
          f"corroborating cash one-off={list(_ev.one_off_evidence.corroborating_items)})")
    print(f"\n  {_ev.reduces_uncertainty_reason}")

# P9 - driver-based operating model + DCF. EXPERIMENTAL. Revenue -> margin ->
# working capital -> capex -> FCFF, every value with a driver assumption and
# lineage, fed into the EXISTING DCF mathematics. Changes no live number and
# promotes nothing.
from aleph.valuation.driver_based_dcf import driver_based_dcf
from aleph.valuation.operating_model import (  # noqa: E402 - see module docstring
    Scenario, build_operating_forecast, historical_drivers,
)

# The old guard here wrapped the IMPORTS in `except Exception`, which cannot
# report a data problem - only a broken installation, and a broken
# installation should not be reported as "P9 not assessed". The real
# precondition is a bottom-up WACC: driver_based_dcf discounts at
# run.wacc.wacc, and run.wacc is None when build_wacc failed. That is a data
# condition, so it is CHECKED rather than caught as an AttributeError.
_p9_ok = run.wacc is not None
if not _p9_ok:
    print(f"\nDRIVER MODEL (EXPERIMENTAL): not run - no bottom-up WACC to "
          f"discount at ({run.wacc_error})")

if _p9_ok:
    print("\n" + "=" * 74)
    print("DRIVER-BASED OPERATING MODEL  (EXPERIMENTAL - NOT IN THE BASE DCF)")
    print("=" * 74)
    print("  HISTORICAL DRIVERS (observed series shape; describes, does not predict):")
    for d in historical_drivers(run):
        vv = ", ".join((f"{v:+.1%}" if d.unit == "decimal" else f"{v:,.0f}")
                       for v in d.values)
        print(f"    {d.name:<28} [{d.shape.value:<22}] = {vv}")
    for sc in (Scenario.BEAR, Scenario.BASE, Scenario.BULL):
        f = build_operating_forecast(run, sc)
        r = driver_based_dcf(
            f, discount_rate=run.wacc.wacc,
            terminal_growth=bridged.inputs.terminal_growth,
            net_debt=bridged.inputs.net_debt,
            shares_outstanding=bridged.inputs.shares_outstanding)
        v = "n/a" if r.value_per_share is None else f"{r.value_per_share:,.2f}"
        print(f"\n  {sc.value:<5} support={f.support.value}  "
              f"unsupported={list(f.unsupported_drivers)}  "
              f"scenario_driver={list(f.scenario_drivers)}")
        if f.years:
            y1, yn = f.years[0], f.years[-1]
            print(f"        yr1  revenue {y1.revenue:,.0f}  g {y1.revenue_growth:.1%}  "
                  f"op margin {(y1.operating_margin or 0):.1%}  FCFF {(y1.fcff or 0):,.0f}")
            print(f"        yr{yn.year} revenue {yn.revenue:,.0f}  g {yn.revenue_growth:.1%}  "
                  f"FCFF {(yn.fcff or 0):,.0f}")
        print(f"        DRIVER DCF: {r.status.value}   value/share = {v}")
        for n in f.notes:
            print(f"        - {n}")
    print("\n  VALUATION PATHS:")
    print(f"    A. LIVE (latest reconstructed FCFF)  : {result.value_per_share:,.2f}")
    _base = build_operating_forecast(run, Scenario.BASE)
    _rb = driver_based_dcf(_base, discount_rate=run.wacc.wacc,
                           terminal_growth=bridged.inputs.terminal_growth,
                           net_debt=bridged.inputs.net_debt,
                           shares_outstanding=bridged.inputs.shares_outstanding)
    _cv = ("n/a - " + _rb.status.value if _rb.value_per_share is None
           else f"{_rb.value_per_share:,.2f}")
    print(f"    C. P9 DRIVER (BASE scenario)         : {_cv}")

# P10 - model governance / arbitration. EXPERIMENTAL. Explains WHY the LIVE,
# P6 and P9 representations disagree, WHICH assumptions are responsible, and
# WHAT evidence would make one more defensible. Never picks a winner; its
# classification does not depend on the market price. Changes no live number.
try:
    from aleph.valuation.model_governance import assess_model_governance
    _gov = assess_model_governance(run)
except DIAGNOSTIC_ERRORS as _exc:
    _gov = None
    print(f"\nMODEL GOVERNANCE (EXPERIMENTAL): not assessed "
          f"({type(_exc).__name__}: {_exc})")

if _gov is not None:
    print("\n" + "=" * 74)
    print("MODEL GOVERNANCE  (EXPERIMENTAL - NOT IN THE BASE DCF)")
    print("=" * 74)
    print(f"  {_gov.headline}")
    print(f"\n  SBC audit  : {_gov.sbc_audit['double_count']}  "
          f"({_gov.sbc_audit['verdict'][:110]}...)")
    print(f"  TAX audit  : {_gov.tax_audit['classification']}  "
          f"(disclosed effective %: {_gov.tax_audit['disclosed_effective_rate_pct']})")
    print(f"\n  RECONCILIATION  LIVE -> P9  (order-dependent):")
    for s in _gov.reconciliation:
        fv = "n/a" if s.fcff_after is None else f"{s.fcff_after:,.0f}"
        vv = "n/a" if s.value_after is None else f"{s.value_after:,.2f}"
        dv = "" if s.delta_value is None else f"  d {s.delta_value:+,.2f}"
        print(f"    [{s.order}] {s.name:<42} FCFF {fv:>9}  value {vv:>9}{dv}")
    print(f"\n  BASE-CASE ASSUMPTION REGISTER (evidence x sensitivity, no score):")
    for e in _gov.register:
        v = "n/a" if e.value is None else f"{e.value:+.3f}"
        flag = "  !! CONTRADICTED" if e.contradiction.value.startswith("ASSUMPTION_CONTRA") else ""
        print(f"    {e.variable:<28} {v:>8}  [{e.evidence_band.value:<8} evidence x "
              f"{e.sensitivity_band.value:<6} sensitivity]  {e.evidence_level.value}{flag}")
    print(f"\n  DOMINANT ASSUMPTIONS:")
    for d in _gov.dominant_assumptions:
        print(f"    - {d}")
    print(f"\n  MODEL APPLICABILITY  (not 'correctness'):")
    for m in _gov.applicability:
        print(f"    {m.model:<40} value={m.value_per_share}  {m.applicability.value}")
        print(f"        dominant: {m.dominant_assumption}")
    print(f"\n  ARBITRATION: {_gov.arbitration.value}")
    for r in _gov.arbitration_reasons:
        print(f"    - {r}")
