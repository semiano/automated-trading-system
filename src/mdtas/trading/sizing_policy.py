from __future__ import annotations


def compute_discretionary_trade_notional(*, max_trade_usd: float, discretion_fraction: float | None = None) -> tuple[float, float]:
    max_trade = max(float(max_trade_usd), 0.0)
    if max_trade <= 0:
        return 0.0, 0.5
    raw_fraction = 0.75 if discretion_fraction is None else float(discretion_fraction)
    bounded_fraction = min(max(raw_fraction, 0.5), 1.0)
    return max_trade * bounded_fraction, bounded_fraction
