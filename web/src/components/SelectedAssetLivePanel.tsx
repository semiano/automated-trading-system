import React from "react";
import type { AssetControl, OpenPosition } from "../api/types";
import { num } from "../utils/formatting";

type Props = {
  symbol: string;
  assetControl?: AssetControl;
  openPositions: OpenPosition[];
};

function parseApiTimestamp(value: string | null | undefined): Date | null {
  if (!value) return null;
  const normalized = /([zZ]|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export default function SelectedAssetLivePanel({ symbol, assetControl, openPositions }: Props) {
  return (
    <section style={{ borderBottom: "1px solid #22262f" }}>
      <div style={{ padding: "8px 10px", fontSize: 12, fontWeight: 600 }}>Selected Asset Live Data — {symbol}</div>
      <div style={{ overflowX: "auto", borderTop: "1px solid #1b1f29" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", padding: 8 }}>Run</th>
              <th style={{ textAlign: "left", padding: 8 }}>Mode</th>
              <th style={{ textAlign: "left", padding: 8 }}>Side</th>
              <th style={{ textAlign: "right", padding: 8 }}>Current Risk</th>
              <th style={{ textAlign: "left", padding: 8 }}>Last Run</th>
              <th style={{ textAlign: "left", padding: 8 }}>Next Run</th>
              <th style={{ textAlign: "left", padding: 8 }}>State</th>
            </tr>
          </thead>
          <tbody>
            <tr style={{ borderTop: "1px solid #1b1f29" }}>
              <td style={{ padding: 8 }}>{assetControl ? (assetControl.enabled ? "Run" : "Paused") : "-"}</td>
              <td style={{ padding: 8 }}>{assetControl ? (assetControl.execution_mode === "sim" ? "Sim" : "Real") : "-"}</td>
              <td style={{ padding: 8 }}>
                {assetControl
                  ? assetControl.trade_side === "long_short"
                    ? "Long+Short"
                    : assetControl.trade_side === "short_only"
                      ? "Short"
                      : "Long"
                  : "-"}
              </td>
              <td style={{ textAlign: "right", padding: 8 }}>{assetControl ? num(assetControl.current_risk_usd, 4) : "-"}</td>
              <td style={{ padding: 8 }}>{parseApiTimestamp(assetControl?.last_run_ts)?.toLocaleString() ?? "-"}</td>
              <td style={{ padding: 8 }}>{parseApiTimestamp(assetControl?.next_run_ts)?.toLocaleString() ?? "-"}</td>
              <td style={{ padding: 8 }}>{assetControl?.last_evaluated_state ?? "-"}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div style={{ overflowX: "auto", borderTop: "1px solid #1b1f29" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", padding: 8 }}>Open Positions (Asset)</th>
              <th style={{ textAlign: "left", padding: 8 }}>Side</th>
              <th style={{ textAlign: "right", padding: 8 }}>Entry</th>
              <th style={{ textAlign: "right", padding: 8 }}>Last</th>
              <th style={{ textAlign: "right", padding: 8 }}>Qty</th>
              <th style={{ textAlign: "right", padding: 8 }}>Unrealized P&L</th>
            </tr>
          </thead>
          <tbody>
            {openPositions.length === 0 ? (
              <tr style={{ borderTop: "1px solid #1b1f29" }}>
                <td style={{ padding: 8 }} colSpan={6}>No open positions for {symbol}.</td>
              </tr>
            ) : (
              openPositions.map((row) => (
                <tr key={row.id} style={{ borderTop: "1px solid #1b1f29" }}>
                  <td style={{ padding: 8 }}>{row.symbol}</td>
                  <td style={{ padding: 8 }}>{row.trade_side === "short" ? "Short" : "Long"}</td>
                  <td style={{ textAlign: "right", padding: 8 }}>{num(row.entry_price, 6)}</td>
                  <td style={{ textAlign: "right", padding: 8 }}>{num(row.last_price, 6)}</td>
                  <td style={{ textAlign: "right", padding: 8 }}>{num(row.qty, 6)}</td>
                  <td style={{ textAlign: "right", padding: 8 }}>{num(row.unrealized_pnl, 6)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
