"""Forensic accounting scores. Pure arithmetic - no LLM in this file."""
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class FinancialsYear:
    """One year of figures needed for the forensic scores. All in the same currency unit."""
    year: int
    revenue: float
    net_income: float
    operating_cash_flow: float
    total_assets: float
    current_assets: float
    current_liabilities: float
    receivables: float
    ppe_net: float                      # property, plant and equipment, net
    securities: float                   # short-term investments
    depreciation: float
    sga: float                          # selling, general and administrative
    total_debt: float
    retained_earnings: float
    ebit: float
    market_cap: Optional[float] = None
    shares_outstanding: Optional[float] = None


def accrual_ratio(f: FinancialsYear) -> float:
    """The core earnings-quality signal: profit not backed by cash.
    Positive and large = reported profit did not arrive as cash."""
    return (f.net_income - f.operating_cash_flow) / f.total_assets

def beneish_m_score(curr: FinancialsYear, prev: FinancialsYear) -> dict:
    """
    Beneish M-Score: 8 indices, each measuring CHANGE between two years.
    M > -1.78 flags elevated manipulation risk.
    """
    # DSRI - are receivables growing faster than sales?
    dsri = (curr.receivables / curr.revenue) / (prev.receivables / prev.revenue)

    # GMI - is the gross margin deteriorating? (deterioration creates pressure to manipulate)
    gm_curr = (curr.revenue - (curr.revenue - curr.ebit - curr.sga)) / curr.revenue
    gm_prev = (prev.revenue - (prev.revenue - prev.ebit - prev.sga)) / prev.revenue
    gmi = gm_prev / gm_curr if gm_curr else 1.0

    # AQI - is the share of "soft" assets rising? (a place to hide expenses)
    soft_curr = 1 - (curr.current_assets + curr.ppe_net + curr.securities) / curr.total_assets
    soft_prev = 1 - (prev.current_assets + prev.ppe_net + prev.securities) / prev.total_assets
    aqi = soft_curr / soft_prev if soft_prev else 1.0

    # SGI - sales growth (growth itself creates manipulation pressure)
    sgi = curr.revenue / prev.revenue

    # DEPI - is depreciation slowing down? (stretching asset life inflates profit)
    dep_rate_curr = curr.depreciation / (curr.depreciation + curr.ppe_net)
    dep_rate_prev = prev.depreciation / (prev.depreciation + prev.ppe_net)
    depi = dep_rate_prev / dep_rate_curr if dep_rate_curr else 1.0

    # SGAI - is SG&A growing faster than sales?
    sgai = (curr.sga / curr.revenue) / (prev.sga / prev.revenue)

    # LVGI - is leverage rising?
    lev_curr = (curr.total_debt + curr.current_liabilities) / curr.total_assets
    lev_prev = (prev.total_debt + prev.current_liabilities) / prev.total_assets
    lvgi = lev_curr / lev_prev if lev_prev else 1.0

    # TATA - total accruals to total assets (the accrual ratio, inside the model)
    tata = (curr.net_income - curr.operating_cash_flow) / curr.total_assets

    m = (-4.84 + 0.920 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi
         + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi)

    return {
        "m_score": m,
        "flagged": m > -1.78,
        "components": {"DSRI": dsri, "GMI": gmi, "AQI": aqi, "SGI": sgi,
                       "DEPI": depi, "SGAI": sgai, "LVGI": lvgi, "TATA": tata},
    }

def altman_z_score(f: FinancialsYear) -> dict:
    """Altman Z: bankruptcy risk within ~2 years. Z < 1.8 = distress zone."""
    if not f.market_cap:
        return {"z_score": None, "zone": "market_cap required"}
    wc = f.current_assets - f.current_liabilities
    total_liabilities = f.total_debt + f.current_liabilities

    z = (1.2 * (wc / f.total_assets)
         + 1.4 * (f.retained_earnings / f.total_assets)
         + 3.3 * (f.ebit / f.total_assets)
         + 0.6 * (f.market_cap / total_liabilities)
         + 1.0 * (f.revenue / f.total_assets))

    zone = "distress" if z < 1.8 else ("grey" if z < 3.0 else "safe")
    return {"z_score": z, "zone": zone}


def piotroski_f_score(curr: FinancialsYear, prev: FinancialsYear) -> dict:
    """Piotroski F: 9 binary tests of fundamental improvement. F >= 7 strong, F <= 3 weak."""
    tests = {}
    roa_curr = curr.net_income / curr.total_assets
    roa_prev = prev.net_income / prev.total_assets

    # Profitability
    tests["positive_net_income"] = curr.net_income > 0
    tests["positive_ocf"] = curr.operating_cash_flow > 0
    tests["improving_roa"] = roa_curr > roa_prev
    tests["ocf_exceeds_net_income"] = curr.operating_cash_flow > curr.net_income  # quality!

    # Leverage and liquidity
    tests["lower_leverage"] = (curr.total_debt / curr.total_assets) < (prev.total_debt / prev.total_assets)
    tests["higher_current_ratio"] = ((curr.current_assets / curr.current_liabilities)
                                     > (prev.current_assets / prev.current_liabilities))
    tests["no_dilution"] = (curr.shares_outstanding is not None
                            and prev.shares_outstanding is not None
                            and curr.shares_outstanding <= prev.shares_outstanding)

    # Operating efficiency
    gm_curr = curr.ebit / curr.revenue
    gm_prev = prev.ebit / prev.revenue
    tests["improving_margin"] = gm_curr > gm_prev
    tests["improving_asset_turnover"] = ((curr.revenue / curr.total_assets)
                                         > (prev.revenue / prev.total_assets))

    score = sum(1 for passed in tests.values() if passed)
    strength = "strong" if score >= 7 else ("weak" if score <= 3 else "moderate")
    return {"f_score": score, "strength": strength, "tests": tests}

def interpret_combined(m: dict, z: dict, f: dict) -> List[str]:
    """Scores are reported separately; this explains what their COMBINATION means."""
    notes = []
    if m["flagged"] and f["f_score"] >= 7:
        notes.append(
            "HIGH CONCERN: strong fundamental improvement (F>=7) alongside elevated "
            "manipulation risk (M flagged). The improvement may be accounting rather "
            "than operational - verify it against cash flow before trusting it."
        )
    if m["flagged"] and z.get("zone") == "distress":
        notes.append(
            "HIGH CONCERN: distress zone plus manipulation flags - the classic profile "
            "of a company under pressure to make the numbers look better."
        )
    if not m["flagged"] and z.get("zone") == "distress":
        notes.append(
            "Distress signals without manipulation flags: an honest company in "
            "difficulty. Different problem, different response."
        )
    if m["flagged"]:
        worst = max(m["components"].items(), key=lambda kv: abs(kv[1] - 1.0))
        notes.append(f"M-Score driven mainly by {worst[0]} = {worst[1]:.2f} "
                     f"(1.0 means no year-over-year change).")
    return notes