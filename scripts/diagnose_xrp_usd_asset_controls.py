import os
from sqlalchemy.orm import Session
from mdtas.db.session import SessionLocal
from mdtas.db.models import AssetControl

# Diagnostic script: Print all asset controls for XRP/USD

def main():
    session = SessionLocal()
    try:
        controls = session.query(AssetControl).filter(AssetControl.symbol == "XRP/USD").all()
        for ac in controls:
            print(f"AssetControl: symbol={ac.symbol}, timeframe={ac.timeframe}, enabled={ac.enabled}, execution_mode={ac.execution_mode}, trade_side={ac.trade_side}, soft_risk_limit_usd={ac.soft_risk_limit_usd}")
        if not controls:
            print("No asset controls found for XRP/USD.")
    finally:
        session.close()

if __name__ == "__main__":
    main()
