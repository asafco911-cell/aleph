"""Tests for the DCF engine. A financial engine without tests is a guess."""
from aleph.valuation.dcf_engine import DCFInputs, run_dcf, validate, DCFConsistencyError


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


def test_rejects_negative_base_cash_flow():
    """Guard 0d. The engine used to grow a loss for ten years and report the
    present value of a deepening loss as a value per share - that is what
    LYFT_FY2025's -$39.37 range low was."""
    try:
        run_dcf(DCFInputs("FCFF", -712, [0.10] * 10, 0.025, 0.081, 0, 417.7))
        raise AssertionError("should have rejected a negative base_cash_flow")
    except DCFConsistencyError as exc:
        assert "NOT_APPLICABLE" in str(exc), exc
        assert "-712" in str(exc), exc
        print("PASS test_rejects_negative_base_cash_flow")


def test_still_values_a_positive_base():
    """The positive control. A guard that rejected everything would pass the
    test above."""
    result = run_dcf(DCFInputs("FCFF", 810, [0.10] * 10, 0.025, 0.081, 0, 417.7))
    assert result.value_per_share > 0, result.value_per_share
    print("PASS test_still_values_a_positive_base")


def test_zero_and_negative_are_the_same_refusal_for_different_reasons():
    """0c says NOT_SOLVABLE (nothing to grow); 0d says NOT_APPLICABLE (the
    thing to grow is a loss). Both refuse; the words are not interchangeable
    and a reader has to be able to tell which happened."""
    for base, token in ((0, "NOT_SOLVABLE"), (-1, "NOT_APPLICABLE")):
        try:
            run_dcf(DCFInputs("FCFF", base, [0.0], 0.0, 0.10, 0, 1))
            raise AssertionError(f"should have rejected base={base}")
        except DCFConsistencyError as exc:
            assert token in str(exc), (base, str(exc))
    print("PASS test_zero_and_negative_are_the_same_refusal_for_different_reasons")


if __name__ == "__main__":
    test_known_value()
    test_rejects_growth_above_discount()
    test_rejects_fcfe_with_net_debt()
    test_rejects_negative_base_cash_flow()
    test_still_values_a_positive_base()
    test_zero_and_negative_are_the_same_refusal_for_different_reasons()
    print("\nAll tests passed.")