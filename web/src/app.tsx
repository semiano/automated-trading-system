import React, { useEffect, useMemo, useState } from "react";
import { API_BASE_URL, fetchAssetControls, fetchCandles, fetchClosedTrades, fetchGaps, fetchIndicators, fetchOpenPositions, fetchRiskPolicySettings, fetchSymbols, updateAssetControl, updateRiskPolicySettings } from "./api/client";
import type { AssetControl, ClosedTrade, Gap, IndicatorRow, OpenPosition, RiskPolicySettings } from "./api/types";
import ChartLayout from "./components/ChartLayout";
import HeaderBar from "./components/HeaderBar";
import PortfolioPage from "./components/PortfolioPage";
import SelectedAssetLivePanel from "./components/SelectedAssetLivePanel";
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
  const [view, setView] = useState<"chart" | "portfolio">("chart");
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

  const activeSymbols = useMemo(() => {
    if (assetControls.length > 0) {
      return assetControls.map((row) => row.symbol);
    }
    return symbols;
  }, [assetControls, symbols]);

  const symbolStatus = useMemo<Record<string, "stale" | "ok">>(() => {
    const out: Record<string, "stale" | "ok"> = {};
    for (const row of assetControls) {
      out[row.symbol] = row.last_evaluated_state === "stale_data" || row.last_evaluated_state === "runtime_tf_missing" ? "stale" : "ok";
    }
    return out;
  }, [assetControls]);

  const selectedAssetControl = useMemo(
    () => assetControls.find((row) => row.symbol === symbol),
    [assetControls, symbol]
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
    if (activeSymbols.length === 0) return;
    if (!activeSymbols.includes(symbol)) {
      setSymbol(activeSymbols[0]);
    }
  }, [activeSymbols, symbol, setSymbol]);

  useEffect(() => {
    const loadPortfolio = async () => {
      const failed: string[] = [];

      await fetchOpenPositions({ venue, timeframe: "1m" })
        .then(setOpenPositions)
        .catch(() => {
          setOpenPositions([]);
          failed.push("open positions");
        });

      await fetchClosedTrades({ venue, timeframe: "1m", execution_mode: pnlMode, limit: 1000 })
        .then(async (payload) => {
          setClosedTrades(payload.rows);
          setTotalNetPnl(payload.total_net_pnl);

          if (pnlMode === "live" && payload.rows.length === 0) {
            try {
              const simPayload = await fetchClosedTrades({
                venue,
                timeframe: "1m",
                execution_mode: "sim",
                limit: 1000,
              });
              if (simPayload.rows.length > 0) {
                setPortfolioInfo(
                  `No closed trades in live mode. ${simPayload.rows.length} closed trade(s) exist in sim mode.`
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

      await fetchAssetControls()
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

  const refreshAssetControls = async () => {
    const rows = await fetchAssetControls();
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
    enabled?: boolean;
    execution_mode?: "sim" | "live";
    trade_side?: "long_only" | "long_short" | "short_only";
    soft_risk_limit_usd?: number;
  }) => {
    await updateAssetControl(payload);
    await refreshAssetControls();
  };

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

    fetchOpenPositions({ symbol, venue, timeframe })
      .then(setChartOpenPositions)
      .catch(() => setChartOpenPositions([]));

    fetchClosedTrades({ symbol, venue, timeframe, limit: 1500 })
      .then((payload) => setChartClosedTrades(payload.rows))
      .catch(() => setChartClosedTrades([]));
  }, [symbol, timeframe, venue, timeRange.start, timeRange.end, indicatorsArg]);

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
            rows={rows}
            gaps={gaps}
            overlays={overlays}
            panels={panels}
            openPositions={chartOpenPositions}
            closedTrades={chartClosedTrades}
            crosshair={crosshair}
            setCrosshair={setCrosshair}
          />
        </>
      ) : (
        <PortfolioPage
          openPositions={openPositions}
          closedTrades={closedTrades}
          totalNetPnl={totalNetPnl}
          assetControls={assetControls}
          riskPolicy={riskPolicy}
          pnlMode={pnlMode}
          onPnlMode={setPnlMode}
          onSaveAssetControl={saveAssetControl}
          onSaveRiskPolicy={saveRiskPolicy}
        />
      )}
    </div>
  );
}
