from mdtas.trading.execution_adapter import PaperExecutionAdapter, SymbolExecutionConstraints, apply_slippage


def test_slippage_buy_sell_directional():
    assert apply_slippage(100.0, side="buy", slip=0.001) == 100.1
    assert apply_slippage(100.0, side="sell", slip=0.001) == 99.9


def test_entry_exit_direction_by_position_side():
    adapter = PaperExecutionAdapter(slippage_bps=10.0)
    constraints = SymbolExecutionConstraints(fee_bps=0.0)

    long_entry = adapter.submit_entry(raw_price=100.0, qty=1.0, trade_side="long", constraints=constraints)
    short_entry = adapter.submit_entry(raw_price=100.0, qty=1.0, trade_side="short", constraints=constraints)
    long_exit = adapter.submit_exit(raw_price=100.0, qty=1.0, trade_side="long", constraints=constraints)
    short_exit = adapter.submit_exit(raw_price=100.0, qty=1.0, trade_side="short", constraints=constraints)

    assert long_entry.price > 100.0
    assert short_entry.price < 100.0
    assert long_exit.price < 100.0
    assert short_exit.price > 100.0


def test_fees_reduce_round_trip_pnl():
    no_fee = SymbolExecutionConstraints(fee_bps=0.0)
    with_fee = SymbolExecutionConstraints(fee_bps=10.0)

    adapter = PaperExecutionAdapter(slippage_bps=0.0)

    entry_no_fee = adapter.submit_entry(raw_price=100.0, qty=1.0, trade_side="long", constraints=no_fee)
    exit_no_fee = adapter.submit_exit(raw_price=101.0, qty=1.0, trade_side="long", constraints=no_fee)
    pnl_no_fee = (exit_no_fee.price - entry_no_fee.price) * 1.0 - entry_no_fee.fee_usd - exit_no_fee.fee_usd

    entry_fee = adapter.submit_entry(raw_price=100.0, qty=1.0, trade_side="long", constraints=with_fee)
    exit_fee = adapter.submit_exit(raw_price=101.0, qty=1.0, trade_side="long", constraints=with_fee)
    pnl_with_fee = (exit_fee.price - entry_fee.price) * 1.0 - entry_fee.fee_usd - exit_fee.fee_usd

    assert pnl_with_fee < pnl_no_fee
