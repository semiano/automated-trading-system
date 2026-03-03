import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
export default function HeaderBar({ view, onView }) {
    return (_jsxs("div", { style: { padding: "10px 14px", borderBottom: "1px solid #22262f", background: "#131722", display: "flex", justifyContent: "space-between", alignItems: "center" }, children: [_jsx("strong", { children: "SEM Automated Trading System" }), _jsxs("div", { style: { display: "flex", gap: 8 }, children: [_jsx("button", { type: "button", onClick: () => onView("chart"), style: {
                            padding: "4px 10px",
                            borderRadius: 4,
                            border: "1px solid #2d3340",
                            background: view === "chart" ? "#2d3340" : "transparent",
                            color: "inherit",
                            cursor: "pointer",
                        }, children: "Chart" }), _jsx("button", { type: "button", onClick: () => onView("portfolio"), style: {
                            padding: "4px 10px",
                            borderRadius: 4,
                            border: "1px solid #2d3340",
                            background: view === "portfolio" ? "#2d3340" : "transparent",
                            color: "inherit",
                            cursor: "pointer",
                        }, children: "Portfolio" })] })] }));
}
