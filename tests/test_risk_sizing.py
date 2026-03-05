from mdtas.trading.runtime import compute_entry_sizing


def test_risk_sizing_qty_decreases_as_atr_increases():
    low_atr = compute_entry_sizing(
        sizing_mode="risk_per_trade",
        position_size_usd=100.0,
        risk_per_trade_usd=5.0,
        max_position_notional_usd=None,
        raw_entry_price=100.0,
        atr=1.0,
        stop_atr=2.0,
        qty_step=0.0001,
    )
    high_atr = compute_entry_sizing(
        sizing_mode="risk_per_trade",
        position_size_usd=100.0,
        risk_per_trade_usd=5.0,
        max_position_notional_usd=None,
        raw_entry_price=100.0,
        atr=4.0,
        stop_atr=2.0,
        qty_step=0.0001,
    )

    assert low_atr.qty_final > high_atr.qty_final



def test_risk_sizing_respects_qty_step_round_down():
    result = compute_entry_sizing(
        sizing_mode="risk_per_trade",
        position_size_usd=100.0,
        risk_per_trade_usd=5.0,
        max_position_notional_usd=None,
        raw_entry_price=100.0,
        atr=1.0,
        stop_atr=3.0,
        qty_step=0.1,
    )

    assert result.qty_raw > result.qty_final
    assert result.qty_final == 1.6



def test_min_and_max_notional_enforcement_inputs_supported():
    capped = compute_entry_sizing(
        sizing_mode="risk_per_trade",
        position_size_usd=100.0,
        risk_per_trade_usd=50.0,
        max_position_notional_usd=30.0,
        raw_entry_price=100.0,
        atr=1.0,
        stop_atr=1.0,
        qty_step=0.0001,
    )
    uncapped = compute_entry_sizing(
        sizing_mode="risk_per_trade",
        position_size_usd=100.0,
        risk_per_trade_usd=50.0,
        max_position_notional_usd=None,
        raw_entry_price=100.0,
        atr=1.0,
        stop_atr=1.0,
        qty_step=0.0001,
    )

    assert capped.qty_final < uncapped.qty_final
    assert capped.qty_final * 100.0 <= 30.0

    min_notional = 10.0
    notional = capped.qty_final * 100.0
    assert notional >= min_notional
