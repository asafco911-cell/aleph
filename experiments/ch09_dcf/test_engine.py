"""Tests for the DCF engine. A financial engine without tests is a guess."""
from dcf_engine import DCFInputs, run_dcf, validate, DCFConsistencyError


def test_known_value():
    """A flat, no-growth perpetuity must equal CF / r."""
    inputs = DCFInputs(cash_flow_type="FCFF", base_cash_flow=100,
                       growth_rates=[0.0], terminal_growth=0.0,
                       discount_rate=0.10, net_debt=0, shares_outstanding=1)
    result = run_dcf(inputs)
    # Year 1: 100/1.1 = 90.91 ; TV = 100/0.10 = 1000, discounted = 909.09 ; total = 1000
    assert abs(result.enterprise_or_equity_value - 1000) < 0.01, result.enterprise_or_equity_value
    print("PASS test_known_value")


def test_rejects_growth_above_discount():
    try:
        run_dcf(DCFInputs("FCFF", 100, [0.05], 0.12, 0.10, 0, 1))
        raise AssertionError("should have rejected g >= r")
    except DCFConsistencyError:
        print("PASS test_rejects_growth_above_discount")


def test_rejects_fcfe_with_net_debt():
    try:
        run_dcf(DCFInputs("FCFE", 100, [0.02], 0.02, 0.10, 5000, 1))
        raise AssertionError("should have rejected FCFE + net debt")
    except DCFConsistencyError:
        print("PASS test_rejects_fcfe_with_net_debt")


if __name__ == "__main__":
    test_known_value()
    test_rejects_growth_above_discount()
    test_rejects_fcfe_with_net_debt()
    print("\nAll tests passed.")