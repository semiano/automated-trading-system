import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
export default function DataHealthPanel({ lastTs, gapCount, gaps }) {
    return (_jsxs("div", { style: { borderTop: "1px solid #22262f", padding: 10, fontSize: 12 }, children: [_jsx("strong", { children: "Data Health" }), _jsxs("div", { children: ["Last update: ", lastTs ? new Date(lastTs).toLocaleString() : "-"] }), _jsxs("div", { children: ["Unresolved gaps: ", gapCount] }), gaps.slice(0, 3).map((g) => (_jsxs("div", { style: { color: "#fca5a5" }, children: [new Date(g.start_ts).toLocaleString(), " \u2192 ", new Date(g.end_ts).toLocaleString()] }, `${g.start_ts}-${g.end_ts}`)))] }));
}
