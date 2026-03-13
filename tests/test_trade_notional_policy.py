from mdtas.trading.sizing_policy import compute_discretionary_trade_notional


def test_discretionary_trade_notional_bounds_and_default():
    target, fraction = compute_discretionary_trade_notional(max_trade_usd=200.0)
    assert fraction == 0.75
    assert target == 150.0

    target_low, fraction_low = compute_discretionary_trade_notional(max_trade_usd=200.0, discretion_fraction=0.1)
    assert fraction_low == 0.5
    assert target_low == 100.0

    target_high, fraction_high = compute_discretionary_trade_notional(max_trade_usd=200.0, discretion_fraction=3.0)
    assert fraction_high == 1.0
    assert target_high == 200.0


def test_discretionary_trade_notional_zero_max_returns_zero_target():
    target, fraction = compute_discretionary_trade_notional(max_trade_usd=0.0, discretion_fraction=0.9)
    assert target == 0.0
    assert fraction == 0.5
