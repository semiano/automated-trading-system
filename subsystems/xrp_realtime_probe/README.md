# XRP Realtime Probe (Mature Async WS Pattern)

Standalone subsystem, independent from the trading app.

It implements the non-thrashy websocket structure:

- one websocket connection for product stream
- subscribe once per connection
- one bounded queue for backpressure
- one consumer loop (no per-message task spawning)
- reconnect with exponential backoff + jitter
- 1m candle aggregation from trade `match` events

## Endpoint

- URL: `wss://ws-feed.exchange.coinbase.com`
- Channel: `matches`
- Product: `XRP-USD`

## Run

```powershell
c:/Users/Steve/automated-trading-system/.venv/Scripts/python.exe subsystems/xrp_realtime_probe/monitor.py --minutes 10
```

Optional tuning:

```powershell
c:/Users/Steve/automated-trading-system/.venv/Scripts/python.exe subsystems/xrp_realtime_probe/monitor.py --minutes 10 --queue-size 5000 --ping-interval 20 --ping-timeout 20
```

## Summary metrics

- connection attempts / reconnects
- reader + parse errors
- queue overflow drops
- observed bars vs expected bars
- latency stats and inter-bar gap stats
- PASS/FAIL verdict
