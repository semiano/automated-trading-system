import React from "react";
import type { VolumeProfileBin } from "../utils/volumeProfile";

type Props = { bins: VolumeProfileBin[] };

export default function VolumeProfile({ bins }: Props) {
  const max = Math.max(1, ...bins.map((b) => b.volume));
  return (
    <div style={{ padding: 10, borderLeft: "1px solid #22262f", minWidth: 220 }}>
      <div style={{ fontSize: 12, marginBottom: 8 }}>Visible Range Volume Profile</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        {bins
          .slice()
          .reverse()
          .map((bin) => (
            <div key={bin.price} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 68, fontSize: 10, color: "#9ca3af" }}>{bin.price.toFixed(2)}</div>
              <div style={{ background: "#1d4ed8", height: 8, width: `${(bin.volume / max) * 120}px` }} />
            </div>
          ))}
      </div>
    </div>
  );
}
