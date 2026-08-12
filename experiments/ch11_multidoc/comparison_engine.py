"""Cross-company and cross-year analysis. Pure arithmetic - no LLM here."""
from typing import List, Dict, Optional
from synthetic_data import CompanyYear, ALL_DATA


# ============================================================
# 1. NORMALIZATION - every comparable metric is a ratio
# ============================================================

def normalized_metrics(cy: CompanyYear) -> Dict[str, float]:
    """Convert raw figures into size-independent ratios so companies are comparable."""
    return {
        "gross_margin": cy.gross_profit / cy.revenue,
        "operating_margin": cy.operating_income / cy.revenue,
        "net_margin": cy.net_income / cy.revenue,
        "rnd_intensity": cy.rnd / cy.revenue,
        "sga_intensity": cy.sga / cy.revenue,
        "asset_turnover": cy.revenue / cy.total_assets,
        "debt_to_assets": cy.total_debt / cy.total_assets,
        "cash_conversion": cy.operating_cash_flow / cy.net_income if cy.net_income else 0.0,
        "adj_to_net_ratio": cy.adjusted_ebitda / cy.net_income if cy.net_income else 0.0,
    }


def series(data: List[CompanyYear], company: str, metric: str) -> List[tuple]:
    """Extract a (year, value) time series for one company and one normalized metric."""
    rows = sorted([cy for cy in data if cy.company == company], key=lambda c: c.year)
    return [(cy.year, normalized_metrics(cy)[metric]) for cy in rows]


# ============================================================
# 2. TREND DETECTION
# ============================================================

def linear_trend(points: List[tuple]) -> Dict[str, float]:
    """Least-squares slope over a time series. Deterministic, no library needed."""
    n = len(points)
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in points)
    den = sum((x - mean_x) ** 2 for x in xs)
    slope = num / den if den else 0.0

    # R-squared tells us how consistent the trend is, not just its direction
    pred = [mean_y + slope * (x - mean_x) for x in xs]
    ss_res = sum((y - p) ** 2 for y, p in zip(ys, pred))
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    r2 = 1 - (ss_res / ss_tot) if ss_tot else 1.0

    return {"slope_per_year": slope, "r_squared": r2,
            "start": ys[0], "end": ys[-1], "total_change": ys[-1] - ys[0]}


def detect_trend(data: List[CompanyYear], company: str, metric: str) -> Dict:
    """Classify a metric's trajectory: direction, consistency, magnitude."""
    t = linear_trend(series(data, company, metric))
    slope = t["slope_per_year"]

    # Direction is judged relative to the starting level, not in absolute points
    rel = abs(slope) / abs(t["start"]) if t["start"] else 0.0
    if rel < 0.02:
        direction = "flat"
    else:
        direction = "improving" if slope > 0 else "deteriorating"

    # A flat series has no variance to explain, so r-squared is meaningless there
    if direction == "flat":
        consistency = "stable"
    elif t["r_squared"] > 0.85:
        consistency = "consistent"
    elif t["r_squared"] > 0.5:
        consistency = "noisy"
    else:
        consistency = "erratic"

    return {"company": company, "metric": metric, "direction": direction,
            "consistency": consistency, **t}


# ============================================================
# 3. PEER BENCHMARKING
# ============================================================

def peer_benchmark(data: List[CompanyYear], year: int,
                   metrics: List[str]) -> Dict[str, List[tuple]]:
    """Rank every company on each normalized metric for a given year.
    Only ratios are compared - never absolute figures."""
    rows = [cy for cy in data if cy.year == year]
    out = {}
    for metric in metrics:
        scored = [(cy.company, normalized_metrics(cy)[metric]) for cy in rows]
        out[metric] = sorted(scored, key=lambda x: x[1], reverse=True)
    return out


def efficiency_improvement_ranking(data: List[CompanyYear]) -> List[dict]:
    """Who is improving efficiency most? Ranked by operating margin slope,
    with consistency reported alongside - a smooth trend differs from a lucky one."""
    companies = sorted({cy.company for cy in data})
    results = []
    for c in companies:
        t = detect_trend(data, c, "operating_margin")
        results.append({
            "company": c,
            "margin_start": t["start"],
            "margin_end": t["end"],
            "slope_per_year": t["slope_per_year"],
            "consistency": t["consistency"],
            "r_squared": t["r_squared"],
        })
    return sorted(results, key=lambda r: r["slope_per_year"], reverse=True)


# ============================================================
# 4. CONTRADICTION DETECTION - GAAP vs non-GAAP divergence
# ============================================================

def detect_nongaap_divergence(data: List[CompanyYear], company: str,
                              jump_threshold: float = 1.5) -> Optional[dict]:
    """Flag a year where the adjusted/GAAP ratio jumps abruptly.
    A sudden jump suggests a definition change, not an operating change."""
    s = series(data, company, "adj_to_net_ratio")
    for i in range(1, len(s)):
        prev_year, prev_val = s[i - 1]
        curr_year, curr_val = s[i]
        if prev_val > 0 and curr_val / prev_val >= jump_threshold:
            # Check whether GAAP moved in the same direction - if not, that is the tell
            gaap = series(data, company, "net_margin")
            gaap_change = gaap[i][1] - gaap[i - 1][1]
            return {
                "company": company,
                "year": curr_year,
                "ratio_before": prev_val,
                "ratio_after": curr_val,
                "multiple": curr_val / prev_val,
                "gaap_margin_change": gaap_change,
                "interpretation": (
                    "adjusted metric jumped while GAAP margin did NOT improve - "
                    "consistent with a definition change rather than an operating change"
                    if gaap_change <= 0 else
                    "adjusted metric jumped alongside GAAP improvement - "
                    "may reflect a genuine operating change"
                ),
            }
    return None


# ============================================================
# 5. RUN - everything below executes only when run directly
# ============================================================

if __name__ == "__main__":
    print("=" * 70)
    print("TREND DETECTION - operating margin")
    print("=" * 70)
    for company in ("ALPHA", "BETA", "GAMMA"):
        t = detect_trend(ALL_DATA, company, "operating_margin")
        print(f"  {company:<7} {t['start']:.1%} -> {t['end']:.1%}   "
              f"{t['direction']:<14} ({t['consistency']}, r2={t['r_squared']:.2f})")

    print("\n" + "=" * 70)
    print("NON-GAAP DIVERGENCE - adjusted EBITDA vs net income")
    print("=" * 70)
    for company in ("ALPHA", "BETA", "GAMMA"):
        s = series(ALL_DATA, company, "adj_to_net_ratio")
        path = " -> ".join(f"{v:.1f}x" for _, v in s)
        print(f"  {company:<7} {path}")

    print("\n" + "=" * 70)
    print("PEER BENCHMARK 2025 (normalized ratios only)")
    print("=" * 70)
    bench = peer_benchmark(ALL_DATA, 2025,
                           ["operating_margin", "rnd_intensity",
                            "asset_turnover", "debt_to_assets"])
    for metric, ranking in bench.items():
        line = "  ".join(f"{c}={v:.1%}" for c, v in ranking)
        print(f"  {metric:<18} {line}")

    print("\n" + "=" * 70)
    print("WHO IS IMPROVING EFFICIENCY MOST?")
    print("=" * 70)
    for i, r in enumerate(efficiency_improvement_ranking(ALL_DATA), 1):
        print(f"  {i}. {r['company']:<7} {r['margin_start']:.1%} -> {r['margin_end']:.1%}   "
              f"slope {r['slope_per_year']:+.2%}/yr   "
              f"({r['consistency']}, r2={r['r_squared']:.2f})")

    print("\n" + "=" * 70)
    print("CONTRADICTION SCAN - non-GAAP divergence")
    print("=" * 70)
    for company in ("ALPHA", "BETA", "GAMMA"):
        d = detect_nongaap_divergence(ALL_DATA, company)
        if d:
            print(f"  [FLAG] {d['company']} in {d['year']}: "
                  f"ratio {d['ratio_before']:.1f}x -> {d['ratio_after']:.1f}x "
                  f"({d['multiple']:.1f}x jump)")
            print(f"         GAAP net margin change: {d['gaap_margin_change']:+.2%}")
            print(f"         {d['interpretation']}")
        else:
            print(f"  [ok]   {company}: no abrupt non-GAAP divergence")