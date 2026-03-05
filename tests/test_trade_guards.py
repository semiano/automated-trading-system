from datetime import datetime, timedelta

from mdtas.trading.runtime import evaluate_entry_guards


def test_cooldown_blocks_entry_within_bars_after_normal_exit():
    decision_ts = datetime(2026, 3, 4, 12, 10, 0)
    last_exit_ts = decision_ts - timedelta(minutes=5)

    result = evaluate_entry_guards(
        decision_ts=decision_ts,
        timeframe="1m",
        last_exit_ts=last_exit_ts,
        last_exit_reason="signal",
        cooldown_bars_after_exit=10,
        cooldown_bars_after_stop=30,
        entries_last_hour=0,
        entries_last_day=0,
        max_entries_per_hour=6,
        max_entries_per_day=40,
    )

    assert result.blocked_reason == "cooldown_active"



def test_stop_cooldown_uses_longer_bar_window():
    decision_ts = datetime(2026, 3, 4, 12, 20, 0)
    last_exit_ts = decision_ts - timedelta(minutes=20)

    result = evaluate_entry_guards(
        decision_ts=decision_ts,
        timeframe="1m",
        last_exit_ts=last_exit_ts,
        last_exit_reason="stop",
        cooldown_bars_after_exit=10,
        cooldown_bars_after_stop=30,
        entries_last_hour=0,
        entries_last_day=0,
        max_entries_per_hour=6,
        max_entries_per_day=40,
    )

    assert result.blocked_reason == "cooldown_active"



def test_hourly_cap_blocks_after_threshold():
    decision_ts = datetime(2026, 3, 4, 12, 0, 0)

    result = evaluate_entry_guards(
        decision_ts=decision_ts,
        timeframe="1m",
        last_exit_ts=None,
        last_exit_reason=None,
        cooldown_bars_after_exit=10,
        cooldown_bars_after_stop=30,
        entries_last_hour=6,
        entries_last_day=6,
        max_entries_per_hour=6,
        max_entries_per_day=40,
    )

    assert result.blocked_reason == "max_entries_per_hour"
