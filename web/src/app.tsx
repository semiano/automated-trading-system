import React, { useEffect, useMemo, useState } from "react";
import { fetchCandles, fetchGaps, fetchIndicators, fetchSymbols } from "./api/client";
import type { Gap, IndicatorRow } from "./api/types";
import ChartLayout from "./components/ChartLayout";
import HeaderBar from "./components/HeaderBar";
import SymbolTimeframePicker from "./components/SymbolTimeframePicker";
import { useStore } from "./state/store";
import { toIsoDate } from "./utils/formatting";
import { buildIndicatorsArg } from "./utils/indicators";

export default function App() {
  const {
    symbol,
    timeframe,
    venue,
    rangeDays,
    overlays,
    panels,
    setSymbol,
    setTimeframe,
    setRangeDays,
    toggleOverlay,
    togglePanel,
  } = useStore();

  const [symbols, setSymbols] = useState<string[]>(["BTC/USDT", "ETH/USDT"]);
  const [rows, setRows] = useState<IndicatorRow[]>([]);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [crosshair, setCrosshair] = useState<IndicatorRow | null>(null);

  const timeRange = useMemo(() => {
    const end = new Date();
    const start = new Date(end.getTime() - rangeDays * 24 * 60 * 60 * 1000);
    return { start: toIsoDate(start), end: toIsoDate(end) };
  }, [rangeDays]);

  const indicatorsArg = useMemo(
    () =>
      buildIndicatorsArg({
        bbands: overlays.bbands,
        ema20: overlays.ema20,
        ema50: overlays.ema50,
        ema200: overlays.ema200,
        rsi: panels.rsi,
        atr: panels.atr,
        bbWidth: panels.bbWidth,
      }),
    [overlays, panels]
  );

  useEffect(() => {
    fetchSymbols().then(setSymbols).catch(() => undefined);
  }, []);

  useEffect(() => {
    fetchCandles({
      symbol,
      timeframe,
      venue,
      start: timeRange.start,
      end: timeRange.end,
      limit: 20000,
    })
      .then((candles) => {
        fetchIndicators({ symbol, timeframe, venue, start: timeRange.start, end: timeRange.end, indicators: indicatorsArg })
          .then((indicatorRows) => {
            if (indicatorRows.length) {
              setRows(indicatorRows);
            } else {
              setRows(candles);
            }
          })
          .catch(() => setRows(candles));
      })
      .catch(() => setRows([]));

    fetchGaps({ symbol, timeframe, venue, start: timeRange.start, end: timeRange.end })
      .then(setGaps)
      .catch(() => setGaps([]));
  }, [symbol, timeframe, venue, timeRange.start, timeRange.end, indicatorsArg]);

  return (
    <div>
      <HeaderBar />
      <SymbolTimeframePicker
        symbols={symbols}
        symbol={symbol}
        timeframe={timeframe}
        rangeDays={rangeDays}
        onSymbol={setSymbol}
        onTimeframe={setTimeframe}
        onRangeDays={setRangeDays}
      />
      <div style={{ display: "flex", gap: 12, padding: "8px 12px", borderBottom: "1px solid #22262f", fontSize: 12 }}>
        <label><input type="checkbox" checked={overlays.bbands} onChange={() => toggleOverlay("bbands")} /> Bollinger</label>
        <label><input type="checkbox" checked={overlays.ema20} onChange={() => toggleOverlay("ema20")} /> EMA20</label>
        <label><input type="checkbox" checked={overlays.ema50} onChange={() => toggleOverlay("ema50")} /> EMA50</label>
        <label><input type="checkbox" checked={overlays.ema200} onChange={() => toggleOverlay("ema200")} /> EMA200</label>
        <label><input type="checkbox" checked={panels.rsi} onChange={() => togglePanel("rsi")} /> RSI</label>
        <label><input type="checkbox" checked={panels.atr} onChange={() => togglePanel("atr")} /> ATR</label>
        <label><input type="checkbox" checked={panels.bbWidth} onChange={() => togglePanel("bbWidth")} /> BB Width</label>
        <label><input type="checkbox" checked={panels.volumeProfile} onChange={() => togglePanel("volumeProfile")} /> Volume Profile</label>
      </div>

      <ChartLayout rows={rows} gaps={gaps} overlays={overlays} panels={panels} crosshair={crosshair} setCrosshair={setCrosshair} />
    </div>
  );
}
