"""Aleph valuation UI.

Design principle: no number appears without its provenance grade, and a
composite number inherits the WEAKEST grade in its chain. The headline is the
RANGE, not the point. A point estimate with a disclaimer beside it still
anchors the reader on the point; a range labelled with the judgements that
produce its ends does not.

WHICH range is the headline is not a free choice. ISSUES.md #29 measured
base_cash_flow's swing as larger than discount_rate's in every run tested -
78% for Uber, 180% for Lyft - so leading with the beta/WACC band, as this
file did until the pipeline was unified, understated the dominant variable
instead of describing it. The FCFF range leads; the WACC band is reported
under Sensitivity alongside every other driver.

This file owns presentation only. The valuation sequence lives in
aleph.valuation.pipeline, shared with scripts/run_valuation.py, so the two
callers cannot disagree about what this project's own numbers are.
"""
import json
from pathlib import Path

import streamlit as st

from aleph.valuation.bridge import BridgeError
from aleph.valuation.dcf_engine import reverse_dcf
from aleph.valuation.pipeline import (
    BlockedError,
    DCFConsistencyError,
    load_market,
    range_position,
    value_filing,
)

# Ordered weakest-last. A composite inherits the weakest grade in its chain.
GRADES = {
    "filing": ("FILING", "#1a7f37", "Extracted from the document and gate-verified"),
    "derived": ("DERIVED", "#2da44e", "Computed from gate-verified facts (a statistic or a composite)"),
    "market": ("MARKET", "#0969da", "Observed market data, valid only at its as_of date"),
    "model_convention": ("CONVENTION", "#8250df", "A methodology choice (horizon, fade, terminal growth level)"),
    "peer_group": ("PEER", "#9a6700", "Chosen comparison set; the choice is a judgement"),
    "analyst_judgment": ("JUDGEMENT", "#cf222e", "Stated by the analyst, not derived"),
}
GRADE_ORDER = ["filing", "derived", "market", "model_convention", "peer_group", "analyst_judgment"]


def weakest(*grades: str) -> str:
    """A derived number is only as evidenced as its weakest input."""
    return max(grades, key=lambda g: GRADE_ORDER.index(g))


def badge(grade: str) -> str:
    label, colour, _ = GRADES[grade]
    return (f"<span style='background:{colour};color:white;padding:2px 7px;"
            f"border-radius:3px;font-size:11px;font-weight:600;'>{label}</span>")


@st.cache_data(show_spinner=False)
def load_manifest() -> list[dict]:
    return json.loads(Path("data/manifest.json").read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def load_share_price(doc_id: str) -> float | None:
    """The filing's own recorded share price.

    Defaulting the reverse-DCF input to one company's price for every filing
    invites comparing Lyft against Uber's price without noticing.

    Goes through pipeline.load_market rather than reading the JSON directly:
    that file has a shared/per_filing structure with a collision guard, and a
    second reader that flattened it its own way would be a second opinion
    about what a filing's market inputs are.
    """
    entry = load_market(doc_id).get("share_price")
    return float(entry.value) if entry else None


# cache_resource, not cache_data: a ValuationRun holds Pydantic models and
# engine result objects, memoised by doc_id rather than serialised.
@st.cache_resource(show_spinner="Extracting and validating facts...")
def run_pipeline(doc_id: str):
    """Return (run, error). Failures are values here, not exceptions.

    A library raises; this caller decides what the failure looks like on
    screen. Blocked inputs are not smoothed over - they end the page.
    """
    try:
        return value_filing(doc_id), None
    except (BlockedError, BridgeError, DCFConsistencyError) as exc:
        return None, exc


def show_evidence(facts, rejected, record) -> None:
    """Every accepted fact with its verbatim quote and page provenance."""
    st.caption(
        f"{len(facts)} facts passed every gate; "
        f"{len(rejected)} were rejected and are not used."
    )
    for fact in facts:
        with st.expander(
            f"{fact.name} = {fact.value:,.1f} {fact.unit}"
            f"  [{fact.period or 'no period'}]"
        ):
            st.markdown(badge("filing"), unsafe_allow_html=True)
            st.code(fact.quote, language=None)
            st.caption(
                f"{record.doc_id} - {fact.source.kind} {fact.source.ref} "
                f"(target {fact.source.target_key or 'n/a'}), "
                f"PDF pages {fact.source.pages} - "
                f"file {record.file_name} - sha256 {record.sha256[:16]}"
            )
    if rejected:
        st.subheader("Rejected")
        for failure in rejected:
            st.markdown(f"`{failure.gate}` **{failure.fact_name}** — {failure.detail}")


st.set_page_config(page_title="Aleph", layout="wide")
st.title("Aleph")

doc_ids = [r["doc_id"] for r in load_manifest()]
doc_id = st.sidebar.selectbox("Filing", doc_ids)
run, error = run_pipeline(doc_id)

st.sidebar.markdown("**Provenance grades**")
for key in GRADE_ORDER:
    _, _, meaning = GRADES[key]
    st.sidebar.markdown(f"{badge(key)} {meaning}", unsafe_allow_html=True)

if isinstance(error, BlockedError):
    st.error("Valuation blocked. Unverifiable inputs are not smoothed over.")
    for item in error.blocked:
        st.markdown(f"**{item.name}** — {item.rationale}")
    st.divider()
    st.caption(
        "The evidence extracted before the block is shown below. A block is "
        "not protection if the evidence it hands you is incomplete "
        "(ISSUES.md #26) - this is what an override would be written against."
    )
    record = next(r for r in load_manifest() if r["doc_id"] == doc_id)
    st.markdown(f"`{record['doc_id']}` — {record['company']} FY{record['fiscal_year']}")
    for fact in error.facts:
        st.markdown(
            f"{badge('filing')} &nbsp;**{fact.name}** = `{fact.value:,.1f}` "
            f"{fact.unit} [{fact.period or 'no period'}]",
            unsafe_allow_html=True,
        )
    st.stop()

if error is not None:
    st.error(f"{type(error).__name__}: {error}")
    st.stop()

record = run.record
st.sidebar.caption(
    f"{record.company}\nFY{record.fiscal_year} 10-K, {record.n_pages} pages\n"
    f"sha256 {record.sha256[:16]}"
)
skipped = [t.key for t in run.targets if t.skipped]
if skipped:
    st.sidebar.caption(f"Not disclosed by this filer: {', '.join(skipped)}")

if run.wacc_error:
    st.warning(f"WACC not built bottom-up: {run.wacc_error}")

bound = run.bridged.base_cash_flow_bound

# The range is the headline. The point estimate is deliberately secondary: it
# is one draw, anchored on whichever year happened to be the latest period.
st.subheader("Value per share")
left, right = st.columns([2, 1])
with left:
    if bound["available"]:
        low, high = min(run.low_vps, run.high_vps), max(run.low_vps, run.high_vps)
        st.markdown(f"### ${low:,.2f} &nbsp;to&nbsp; ${high:,.2f}",
                    unsafe_allow_html=True)
        st.caption(
            f"Range spans this filing's own disclosed FCFF, "
            f"{bound['low_period']} to {bound['high_period']}. Which year an "
            "analyst treats as representative moves the answer further than "
            "any other input in this model (ISSUES.md #29). Nothing in the "
            "pipeline normalises it."
        )
    else:
        low = high = None
        st.markdown(f"### ${run.result.value_per_share:,.2f}",
                    unsafe_allow_html=True)
        st.caption(f"Multi-year range unavailable: {bound['reason']}")
    st.markdown(
        f"{badge('analyst_judgment')} &nbsp;This figure inherits the weakest "
        "grade in its chain.",
        unsafe_allow_html=True,
    )
with right:
    st.metric(
        "Latest-period basis", f"${run.result.value_per_share:,.2f}",
        help=(f"{bound['high_period']} FCFF, the base case. One draw from the "
              "range on the left, not a consensus of it.")
        if bound["available"] else "The base case.",
    )
    st.metric("Terminal value share", f"{run.result.terminal_pct:.0%}",
              help="Fraction of value resting on the period beyond the forecast.")

default_price = load_share_price(doc_id)
price = st.number_input(
    "Market price for reverse DCF",
    value=default_price if default_price is not None else 0.0,
    step=0.01,
    help=f"Defaults to {doc_id}'s own recorded share price in data/market.json.",
)
if price > 0:
    if low is not None:
        st.caption(f"Against the range above: {range_position(price, low, high)}.")
    implied = reverse_dcf(run.bridged.inputs, price)
    if implied is None:
        st.warning(f"No growth rate in the searched range justifies ${price:,.2f}.")
    else:
        st.info(
            f"At \\${price:,.2f} the market implies **{implied:.1%}** annual growth "
            f"for {len(run.bridged.inputs.growth_rates)} years. This converts a "
            "valuation question into a business question. It is NOT an "
            "independent check: it holds base_cash_flow fixed at the "
            "latest-period value and solves only for growth, so it inherits "
            "the same dependency the range above measures."
        )

tab_assumptions, tab_evidence, tab_sensitivity = st.tabs(
    ["Assumptions", "Evidence", "Sensitivity"]
)

with tab_assumptions:
    for assumption in run.bridged.inputs.assumptions:
        grade = assumption.source
        if assumption.name == "discount_rate":
            # Built from a peer beta and a stated country premium.
            grade = weakest("market", "peer_group", "analyst_judgment")
        st.markdown(
            f"{badge(grade)} &nbsp;**{assumption.name}** = "
            f"`{assumption.value:,.4g}`", unsafe_allow_html=True,
        )
        st.caption(assumption.rationale)
        st.divider()

with tab_evidence:
    show_evidence(run.facts, run.rejected, record)

with tab_sensitivity:
    st.caption(
        "A tornado measures the ranges it is given, so bounds are stated here "
        "rather than left implicit."
    )
    for row in run.tornado_rows:
        if row["swing"] is None:
            st.markdown(f"**{row['param']}** — a bound violates a consistency guard")
            continue
        st.markdown(
            f"**{row['param']}** &nbsp; ${row['low']:,.2f} to ${row['high']:,.2f} "
            f"&nbsp; swing ${row['swing']:,.2f} ({row['swing_pct']:.0%})"
        )
        st.progress(min(row["swing_pct"], 1.0))

    if run.wacc:
        st.divider()
        st.markdown("**WACC components**")
        for note in run.wacc.notes:
            st.text(note)
        st.caption(
            f"The discount_rate row above is bounded by re-deriving WACC at an "
            f"unlevered industry beta of {run.beta_base * 0.75:.2f} and "
            f"{run.beta_base * 1.45:.2f} "
            f"(WACC {run.wacc_at_beta_bounds[0]:.2%} to "
            f"{run.wacc_at_beta_bounds[1]:.2%}), not by a hand-picked band "
            "around the derived rate. Both ends are defensible; the choice of "
            "industry classification is a judgement, not a derivation."
        )
