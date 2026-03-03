import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
export default function VolumeProfile({ bins }) {
    const max = Math.max(1, ...bins.map((b) => b.volume));
    return (_jsxs("div", { style: { padding: 10, borderLeft: "1px solid #22262f", minWidth: 220 }, children: [_jsx("div", { style: { fontSize: 12, marginBottom: 8 }, children: "Visible Range Volume Profile" }), _jsx("div", { style: { display: "flex", flexDirection: "column", gap: 3 }, children: bins
                    .slice()
                    .reverse()
                    .map((bin) => (_jsxs("div", { style: { display: "flex", alignItems: "center", gap: 6 }, children: [_jsx("div", { style: { width: 68, fontSize: 10, color: "#9ca3af" }, children: bin.price.toFixed(2) }), _jsx("div", { style: { background: "#1d4ed8", height: 8, width: `${(bin.volume / max) * 120}px` } })] }, bin.price))) })] }));
}
