import React, { useEffect, useMemo, useState } from "react";
import { API_BASE_URL, fetchAssetControls, fetchAssetTuningVersions, fetchCandles, fetchCatchupStatus, fetchClosedTrades, fetchGaps, fetchIndicators, fetchOpenPositions, fetchRiskPolicySettings, fetchSymbols, updateAssetControl, updateAssetTuning, updateRiskPolicySettings, valueBalanceAsset } from "./api/client";
import type { AssetControl, AssetTuningVersion, CatchupStatusRow, ClosedTrade, Gap, IndicatorRow, OpenPosition, RiskPolicySettings } from "./api/types";
import ChartLayout from "./components/ChartLayout";
import HeaderBar from "./components/HeaderBar";
import IngestionStatusPage from "./components/IngestionStatusPage";
import PortfolioPage from "./components/PortfolioPage";
import SelectedAssetLivePanel from "./components/SelectedAssetLivePanel";
import SymbolTimeframePicker from "./components/SymbolTimeframePicker";
import { useStore } from "./state/store";
import { toIsoDate } from "./utils/formatting";
import { buildIndicatorsArg } from "./utils/indicators";

const CHART_POINT_LIMITS: Record<string, number> = {
  "1m": 5000,
  "5m": 8000,
  "1h": 12000,
};

function chartPointLimitForTimeframe(tf: string): number {
  return CHART_POINT_LIMITS[tf] ?? 8000;
}

type ChartDataCapInfo = {
  capLimit: number;
  totalRows: number;
  shownRows: number;
  omittedRows: number;
  omittedStartTs: string;
  omittedEndTs: string;
  visibleStartTs: string;
  visibleEndTs: string;
};

function parseApiTsMillis(ts: string): number {
  const withZone = /Z$|[+-]\d{2}:\d{2}$/.test(ts) ? ts : `${ts}Z`;
  return new Date(withZone).getTime();
}

function normalizeIndicatorRows(rows: IndicatorRow[]): IndicatorRow[] {
  const sorted = [...rows]
    .filter((r) => Number.isFinite(parseApiTsMillis(r.ts)))
    .sort((a, b) => parseApiTsMillis(a.ts) - parseApiTsMillis(b.ts));

  const deduped: IndicatorRow[] = [];
  for (const row of sorted) {
    if (deduped.length === 0) {
      deduped.push(row);
      continue;
    }
    const prev = deduped[deduped.length - 1];
    if (parseApiTsMillis(prev.ts) === parseApiTsMillis(row.ts)) {
      deduped[deduped.length - 1] = row;
    } else {
      deduped.push(row);
    }
  }

  return deduped;
}

function mergeClosedTradesByTimeframe(parts: ClosedTrade[][]): ClosedTrade[] {
  const byId = new Map<number, ClosedTrade>();
  for (const group of parts) {
    for (const row of group) {
      byId.set(row.id, row);
    }
  }
  return Array.from(byId.values()).sort((a, b) => Date.parse(b.exit_ts) - Date.parse(a.exit_ts));
}

async function fetchAllAssetControls(): Promise<AssetControl[]> {
  // Let backend decide which control-plane timeframes are supported.
  // This avoids creating unsupported timeframe rows (e.g., 1h) on read paths.
  const rows = await fetchAssetControls();
  if (rows.length > 0) {
    return rows;
  }
  return fetchAssetControls();
}

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
  const [view, setView] = useState<"chart" | "portfolio" | "ingestion">("chart");
  const [openPositions, setOpenPositions] = useState<OpenPosition[]>([]);
  const [closedTrades, setClosedTrades] = useState<ClosedTrade[]>([]);
  const [totalNetPnl, setTotalNetPnl] = useState(0);
  const [assetControls, setAssetControls] = useState<AssetControl[]>([]);
  const [chartOpenPositions, setChartOpenPositions] = useState<OpenPosition[]>([]);
  const [chartClosedTrades, setChartClosedTrades] = useState<ClosedTrade[]>([]);
  const [pnlMode, setPnlMode] = useState<"sim" | "live">("sim");
  const [portfolioError, setPortfolioError] = useState<string | null>(null);
  const [portfolioInfo, setPortfolioInfo] = useState<string | null>(null);
  const [riskPolicy, setRiskPolicy] = useState<RiskPolicySettings>({
    risk_budget_policy: "per_symbol",
    portfolio_soft_risk_limit_usd: 0,
  });
  const [catchupRows, setCatchupRows] = useState<CatchupStatusRow[]>([]);
  const [catchupError, setCatchupError] = useState<string | null>(null);
  const [catchupUpdatedAt, setCatchupUpdatedAt] = useState<Date | null>(null);

  const { chartRows, chartDataCap } = useMemo((): { chartRows: IndicatorRow[]; chartDataCap: ChartDataCapInfo | null } => {
    const capLimit = chartPointLimitForTimeframe(timeframe);
    if (rows.length <= capLimit) {
      return { chartRows: rows, chartDataCap: null };
    }

    const startIndex = rows.length - capLimit;
    const visibleRows = rows.slice(startIndex);
    const omitted = rows.slice(0, startIndex);
    const omittedStartTs = omitted[0]?.ts;
    const omittedEndTs = omitted[omitted.length - 1]?.ts;
    const visibleStartTs = visibleRows[0]?.ts;
    const visibleEndTs = visibleRows[visibleRows.length - 1]?.ts;

    if (!omittedStartTs || !omittedEndTs || !visibleStartTs || !visibleEndTs) {
      return { chartRows: visibleRows, chartDataCap: null };
    }

    return {
      chartRows: visibleRows,
      chartDataCap: {
        capLimit,
        totalRows: rows.length,
        shownRows: visibleRows.length,
        omittedRows: omitted.length,
        omittedStartTs,
        omittedEndTs,
        visibleStartTs,
        visibleEndTs,
      },
    };
  }, [rows, timeframe]);

  const chartGaps = useMemo(() => {
    if (!chartDataCap) {
      return gaps;
    }
    const cutoff = Date.parse(chartDataCap.visibleStartTs);
    if (Number.isNaN(cutoff)) {
      return gaps;
    }
    return gaps.filter((gap) => {
      const gapEnd = Date.parse(gap.end_ts);
      return Number.isNaN(gapEnd) || gapEnd >= cutoff;
    });
  }, [gaps, chartDataCap]);

  const activeSymbols = useMemo(() => {
    if (assetControls.length > 0) {
      const byTf = assetControls.filter((row) => row.timeframe === timeframe);
      const source = byTf.length > 0 ? byTf : assetControls;
      return Array.from(new Set(source.map((row) => row.symbol)));
    }
    return Array.from(new Set(symbols));
  }, [assetControls, symbols, timeframe]);

  const isSelectedSymbolActive = useMemo(() => activeSymbols.includes(symbol), [activeSymbols, symbol]);

  const symbolStatus = useMemo<Record<string, "stale" | "ok">>(() => {
    const out: Record<string, "stale" | "ok"> = {};
    for (const row of assetControls.filter((r) => r.timeframe === timeframe)) {
      out[row.symbol] = row.last_evaluated_state === "stale_data" || row.last_evaluated_state === "runtime_tf_missing" ? "stale" : "ok";
    }
    return out;
  }, [assetControls, timeframe]);

  const selectedAssetControl = useMemo(
    () => assetControls.find((row) => row.symbol === symbol && row.timeframe === timeframe),
    [assetControls, symbol, timeframe]
  );

  const selectedAssetOpenPositions = useMemo(
    () => chartOpenPositions.filter((row) => row.symbol === symbol),
    [chartOpenPositions, symbol]
  );

  const timeRange = useMemo(() => {
    const end = new Date();
    const start = new Date(end.getTime() - rangeDays * 24 * 60 * 60 * 1000);
    return { start: toIsoDate(start), end: toIsoDate(end) };
  }, [rangeDays]);

  const indicatorsArg = useMemo(
    () => {
      const tuning = selectedAssetControl?.tuning_params ?? {};
      const emaFastLen = typeof tuning.ema_fast === "number" ? tuning.ema_fast : undefined;
      const emaSlowLen = typeof tuning.ema_slow === "number" ? tuning.ema_slow : undefined;
      const isSimpleEngineTf = timeframe === "1m" || timeframe === "5m";
      return (
      buildIndicatorsArg({
        bbands: overlays.bbands,
        ema20: overlays.ema20,
        ema50: overlays.ema50,
        ema200: overlays.ema200,
        rsi: panels.rsi,
        atr: panels.atr,
        bbWidth: panels.bbWidth,
        forceSimpleMechanics: isSimpleEngineTf,
        emaFastLen,
        emaSlowLen,
      })
      );
    },
    [overlays, panels, timeframe, selectedAssetControl]
  );

  useEffect(() => {
    fetchSymbols().then(setSymbols).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (activeSymbols.length === 0) return;
    if (!activeSymbols.includes(symbol)) {
      setSymbol(activeSymbols[0]);
    }
  }, [activeSymbols, symbol, setSymbol]);

  useEffect(() => {
    const loadPortfolio = async () => {
      const failed: string[] = [];

      await fetchOpenPositions({ venue })
        .then(setOpenPositions)
        .catch(() => {
          setOpenPositions([]);
          failed.push("open positions");
        });

      await Promise.all([
        fetchClosedTrades({ venue, timeframe: "1m", execution_mode: pnlMode, limit: 1000 }),
        fetchClosedTrades({ venue, timeframe: "5m", execution_mode: pnlMode, limit: 1000 }),
      ])
        .then(async ([pnl1m, pnl5m]) => {
          const merged = mergeClosedTradesByTimeframe([pnl1m.rows, pnl5m.rows]);
          setClosedTrades(merged);
          setTotalNetPnl(merged.reduce((sum, row) => sum + row.net_pnl, 0));

          if (pnlMode === "live" && merged.length === 0) {
            try {
              const [sim1m, sim5m] = await Promise.all([
                fetchClosedTrades({ venue, timeframe: "1m", execution_mode: "sim", limit: 1000 }),
                fetchClosedTrades({ venue, timeframe: "5m", execution_mode: "sim", limit: 1000 }),
              ]);
              const simMerged = mergeClosedTradesByTimeframe([sim1m.rows, sim5m.rows]);
              if (simMerged.length > 0) {
                setPortfolioInfo(
                  `No closed trades in live mode. ${simMerged.length} closed trade(s) exist in sim mode (1m + 5m).`
                );
              } else {
                setPortfolioInfo(null);
              }
            } catch {
              setPortfolioInfo(null);
            }
          } else {
            setPortfolioInfo(null);
          }
        })
        .catch(() => {
          setClosedTrades([]);
          setTotalNetPnl(0);
          failed.push("closed trades");
          setPortfolioInfo(null);
        });

      await fetchAllAssetControls()
        .then(setAssetControls)
        .catch(() => {
          setAssetControls([]);
          failed.push("asset controls");
        });

      await fetchRiskPolicySettings()
        .then(setRiskPolicy)
        .catch(() => {
          failed.push("risk policy");
        });

      if (failed.length > 0) {
        setPortfolioError(`Control plane fetch failed: ${failed.join(", ")}. API base: ${API_BASE_URL}`);
      } else {
        setPortfolioError(null);
      }
    };

    loadPortfolio();
    const timer = window.setInterval(loadPortfolio, 8000);
    return () => window.clearInterval(timer);
  }, [venue, pnlMode]);

  useEffect(() => {
    const loadCatchup = async () => {
      try {
        const rows = await fetchCatchupStatus({ venue });
        setCatchupRows(rows);
        setCatchupError(null);
        setCatchupUpdatedAt(new Date());
      } catch {
        setCatchupRows([]);
        setCatchupError(`Failed to fetch ingestion catchup status. API base: ${API_BASE_URL}`);
      }
    };

    loadCatchup();
    const timer = window.setInterval(loadCatchup, 5000);
    return () => window.clearInterval(timer);
  }, [venue]);

  const refreshAssetControls = async () => {
    const rows = await fetchAllAssetControls();
    setAssetControls(rows);
  };

  const saveRiskPolicy = async (payload: {
    risk_budget_policy?: "per_symbol" | "portfolio";
    portfolio_soft_risk_limit_usd?: number;
  }) => {
    const next = await updateRiskPolicySettings(payload);
    setRiskPolicy(next);
  };

  const saveAssetControl = async (payload: {
    symbol: string;
    timeframe: string;
    enabled?: boolean;
    execution_mode?: "sim" | "live";
    trade_side?: "long_only" | "long_short" | "short_only";
    soft_risk_limit_usd?: number;
  }) => {
    await updateAssetControl(payload);
    await refreshAssetControls();
  };

  const rebalanceAssetValue = async (payload: {
    symbol: string;
    target_base_ratio?: number;
    tolerance_bps?: number;
  }) => {
    await valueBalanceAsset(payload);
    await refreshAssetControls();
  };

  const saveAssetTuning = async (payload: {
    symbol: string;
    timeframe: string;
    bb_length?: number;
    bb_stdev?: number;
    atr_length?: number;
    ema_fast?: number;
    ema_slow?: number;
    bb_entry_deviation?: number;
    bb_exit_deviation?: number;
    slope_lookback_bars?: number;
    slope_flatten_factor?: number;
    stop_atr?: number;
    take_profit_atr?: number;
    max_hold_bars?: number;
    min_hold_bars?: number;
    max_take_profit_pct?: number;
    note?: string;
    source?: string;
    updated_by?: string;
  }) => {
    await updateAssetTuning(payload);
    await refreshAssetControls();
  };

  const loadAssetTuningVersions = async (payload: { symbol: string; timeframe: string; limit?: number }): Promise<AssetTuningVersion[]> => {
    return fetchAssetTuningVersions(payload);
  };


  useEffect(() => {
    if (!isSelectedSymbolActive) {
      return;
    }

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
              setRows(normalizeIndicatorRows(indicatorRows));
            } else {
              setRows(normalizeIndicatorRows(candles));
            }
          })
          .catch(() => setRows(normalizeIndicatorRows(candles)));
      })
      .catch(() => setRows([]));

    fetchGaps({ symbol, timeframe, venue, start: timeRange.start, end: timeRange.end })
      .then(setGaps)
      .catch(() => setGaps([]));

    fetchOpenPositions({ symbol, venue, timeframe })
      .then(setChartOpenPositions)
      .catch(() => setChartOpenPositions([]));

    fetchClosedTrades({ symbol, venue, timeframe, limit: 1500 })
      .then((payload) => setChartClosedTrades(payload.rows))
      .catch(() => setChartClosedTrades([]));
  }, [symbol, timeframe, venue, timeRange.start, timeRange.end, indicatorsArg, isSelectedSymbolActive]);


  return (
    <div>
      <HeaderBar view={view} onView={setView} />

      {portfolioError ? (
        <div style={{ margin: "10px 12px", padding: "8px 10px", borderRadius: 6, border: "1px solid #5b1f1f", background: "#2b1111", color: "#f2b8b5", fontSize: 12 }}>
          {portfolioError}
        </div>
      ) : null}

      {!portfolioError && portfolioInfo ? (
        <div style={{ margin: "10px 12px", padding: "8px 10px", borderRadius: 6, border: "1px solid #1f3f5b", background: "#0f2433", color: "#b8dfff", fontSize: 12 }}>
          {portfolioInfo}
        </div>
      ) : null}

      {view === "portfolio" && !portfolioError && assetControls.length === 0 ? (
        <div style={{ margin: "10px 12px", padding: "8px 10px", borderRadius: 6, border: "1px solid #4a3a18", background: "#2a2312", color: "#f0d28a", fontSize: 12 }}>
          Control plane returned no assets. Verify API is running and symbols are configured.
        </div>
      ) : null}

      {view === "chart" ? (
        <>
          <SymbolTimeframePicker
            symbols={activeSymbols}
            symbol={symbol}
            timeframe={timeframe}
            rangeDays={rangeDays}
            symbolStatus={symbolStatus}
            onSymbol={setSymbol}
            onTimeframe={setTimeframe}
            onRangeDays={setRangeDays}
          />
          <SelectedAssetLivePanel
            symbol={symbol}
            assetControl={selectedAssetControl}
            openPositions={selectedAssetOpenPositions}
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
          <ChartLayout
            timeframe={timeframe}
            rows={chartRows}
            gaps={chartGaps}
            overlays={overlays}
            panels={panels}
            openPositions={chartOpenPositions}
            closedTrades={chartClosedTrades}
            assetControl={selectedAssetControl}
            crosshair={crosshair}
            setCrosshair={setCrosshair}
            chartDataCap={chartDataCap}
          />
        </>
      ) : view === "portfolio" ? (
        <PortfolioPage
          openPositions={openPositions}
          closedTrades={closedTrades}
          totalNetPnl={totalNetPnl}
          assetControls={assetControls}
          riskPolicy={riskPolicy}
          pnlMode={pnlMode}
          onPnlMode={setPnlMode}
          onSaveAssetControl={saveAssetControl}
          onSaveAssetTuning={saveAssetTuning}
          onFetchAssetTuningVersions={loadAssetTuningVersions}
          onValueBalanceAsset={rebalanceAssetValue}
          onSaveRiskPolicy={saveRiskPolicy}
        />
      ) : (
        <IngestionStatusPage rows={catchupRows} error={catchupError} updatedAt={catchupUpdatedAt} />
      )}
    </div>
  );
}
