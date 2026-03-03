import React from "react";

type Props = {
  symbols: string[];
  symbol: string;
  timeframe: string;
  rangeDays: number;
  symbolStatus: Record<string, "stale" | "ok">;
  onSymbol: (symbol: string) => void;
  onTimeframe: (timeframe: string) => void;
  onRangeDays: (days: number) => void;
};

export default function SymbolTimeframePicker(props: Props) {
  return (
    <div style={{ display: "flex", gap: 12, padding: 12, alignItems: "center", borderBottom: "1px solid #22262f" }}>
      <label>
        Symbol
        <select value={props.symbol} onChange={(e) => props.onSymbol(e.target.value)} style={{ marginLeft: 6 }}>
          {props.symbols.map((sym) => (
            <option key={sym} value={sym}>
              {sym} {props.symbolStatus[sym] === "stale" ? "🔴 Stale" : "🟢 Up-to-date"}
            </option>
          ))}
        </select>
      </label>
      <label>
        Timeframe
        <select value={props.timeframe} onChange={(e) => props.onTimeframe(e.target.value)} style={{ marginLeft: 6 }}>
          {["1m", "5m", "1h"].map((tf) => (
            <option key={tf} value={tf}>
              {tf}
            </option>
          ))}
        </select>
      </label>
      <label>
        Range
        <select value={props.rangeDays} onChange={(e) => props.onRangeDays(Number(e.target.value))} style={{ marginLeft: 6 }}>
          <option value={1}>1d</option>
          <option value={7}>7d</option>
          <option value={30}>30d</option>
        </select>
      </label>
    </div>
  );
}
