from mdtas.db.session import get_session, init_db
from mdtas.db.trading_repo import TradingRepository


def test_sim_wallet_augment_and_list():
    init_db()
    session = get_session()
    repo = TradingRepository(session)

    symbol = "XRP/USD"
    repo.augment_sim_wallet_balance(symbol=symbol, bucket="cash", amount_usd=25.0)
    row = repo.augment_sim_wallet_balance(symbol=symbol, bucket="asset", amount_usd=40.0)

    assert float(row.cash_adjustment_usd) >= 25.0
    assert float(row.asset_adjustment_usd) >= 40.0

    rows = repo.list_sim_wallet_balances()
    assert any(r.symbol == symbol for r in rows)
    session.close()
