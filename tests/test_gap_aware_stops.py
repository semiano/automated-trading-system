from mdtas.trading.execution_adapter import gap_aware_raw_exit_price


def test_long_stop_gap_down_fills_at_open():
    raw_exit = gap_aware_raw_exit_price(
        trade_side="long",
        reason="stop",
        bar_open=95.0,
        stop_price=98.0,
        take_profit_price=110.0,
    )
    assert raw_exit == 95.0


def test_short_stop_gap_up_fills_at_open():
    raw_exit = gap_aware_raw_exit_price(
        trade_side="short",
        reason="stop",
        bar_open=105.0,
        stop_price=102.0,
        take_profit_price=90.0,
    )
    assert raw_exit == 105.0
