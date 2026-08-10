"""Tests for the forensic engine, using synthetic companies with KNOWN profiles."""
from forensic_scores import (FinancialsYear, accrual_ratio, beneish_m_score,
                             altman_z_score, piotroski_f_score, interpret_combined)


def clean_company():
    """A healthy company: profit backed by cash, stable ratios, no dilution."""
    prev = FinancialsYear(
        year=2024, revenue=10000, net_income=1000, operating_cash_flow=1200,
        total_assets=8000, current_assets=3000, current_liabilities=1500,
        receivables=1200, ppe_net=3000, securities=500, depreciation=400,
        sga=2000, total_debt=2000, retained_earnings=3000, ebit=1400,
        market_cap=20000, shares_outstanding=1000,
    )
    curr = FinancialsYear(
        year=2025, revenue=11000, net_income=1150, operating_cash_flow=1400,
        total_assets=8500, current_assets=3300, current_liabilities=1550,
        receivables=1320, ppe_net=3100, securities=550, depreciation=430,
        sga=2150, total_debt=1900, retained_earnings=4150, ebit=1600,
        market_cap=23000, shares_outstanding=1000,
    )
    return prev, curr


def manipulator_company():
    """Same revenue growth, but: receivables exploding, cash flow collapsing,
    depreciation slowed, soft assets rising. The textbook manipulation profile."""
    prev = FinancialsYear(
        year=2024, revenue=10000, net_income=1000, operating_cash_flow=1100,
        total_assets=8000, current_assets=3000, current_liabilities=1500,
        receivables=1200, ppe_net=3000, securities=500, depreciation=400,
        sga=2000, total_debt=2000, retained_earnings=3000, ebit=1400,
        market_cap=20000, shares_outstanding=1000,
    )
    curr = FinancialsYear(
        year=2025, revenue=11000, net_income=1400,      # profit UP
        operating_cash_flow=300,                         # but cash COLLAPSED
        total_assets=9500, current_assets=3200,
        current_liabilities=1600,
        receivables=2400,                                # receivables DOUBLED on 10% sales growth
        ppe_net=3100,
        securities=300,
        depreciation=200,                                # depreciation HALVED - stretched asset lives
        sga=2100, total_debt=2600, retained_earnings=4400, ebit=1800,
        market_cap=22000, shares_outstanding=1050,       # slight dilution
    )
    return prev, curr


def report(name, prev, curr):
    print("=" * 70)
    print(name)
    print("=" * 70)

    ar = accrual_ratio(curr)
    m = beneish_m_score(curr, prev)
    z = altman_z_score(curr)
    f = piotroski_f_score(curr, prev)

    print(f"  Accrual ratio : {ar:+.3f}   ({'red flag' if ar > 0.05 else 'ok'})")
    print(f"  Beneish M     : {m['m_score']:+.2f}   "
          f"({'FLAGGED' if m['flagged'] else 'not flagged'}, threshold -1.78)")
    print(f"  Altman Z      : {z['z_score']:.2f}   ({z['zone']})")
    print(f"  Piotroski F   : {f['f_score']}/9   ({f['strength']})")

    print("\n  M-Score components (1.00 = no year-over-year change):")
    for k, v in m["components"].items():
        marker = "  <--" if abs(v - 1.0) > 0.25 and k != "TATA" else ""
        print(f"    {k:<6} {v:>7.3f}{marker}")

    notes = interpret_combined(m, z, f)
    if notes:
        print("\n  COMBINED INTERPRETATION:")
        for n in notes:
            print(f"    - {n}")
    print()


def test_clean_not_flagged():
    prev, curr = clean_company()
    m = beneish_m_score(curr, prev)
    assert not m["flagged"], f"clean company should not be flagged, got M={m['m_score']:.2f}"
    print("PASS test_clean_not_flagged")


def test_manipulator_is_flagged():
    prev, curr = manipulator_company()
    m = beneish_m_score(curr, prev)
    assert m["flagged"], f"manipulator should be flagged, got M={m['m_score']:.2f}"
    print("PASS test_manipulator_is_flagged")


def test_accrual_ratio_direction():
    prev, curr = manipulator_company()
    assert accrual_ratio(curr) > 0.05, "manipulator should show large positive accruals"
    prev_c, curr_c = clean_company()
    assert accrual_ratio(curr_c) < 0, "clean company should show negative accruals"
    print("PASS test_accrual_ratio_direction")


if __name__ == "__main__":
    test_clean_not_flagged()
    test_manipulator_is_flagged()
    test_accrual_ratio_direction()
    print("\nAll tests passed.\n")

    report("CLEAN COMPANY", *clean_company())
    report("MANIPULATOR", *manipulator_company())