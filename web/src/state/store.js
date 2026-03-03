import { create } from "zustand";
export const useStore = create((set) => ({
    symbol: "BTC/USDT",
    timeframe: "5m",
    venue: "coinbase",
    rangeDays: 7,
    overlays: {
        bbands: true,
        ema20: true,
        ema50: false,
        ema200: false,
    },
    panels: {
        rsi: true,
        atr: false,
        bbWidth: false,
        volumeProfile: true,
    },
    setSymbol: (symbol) => set({ symbol }),
    setTimeframe: (timeframe) => set({ timeframe }),
    setRangeDays: (rangeDays) => set({ rangeDays }),
    toggleOverlay: (key) => set((state) => ({ overlays: { ...state.overlays, [key]: !state.overlays[key] } })),
    togglePanel: (key) => set((state) => ({ panels: { ...state.panels, [key]: !state.panels[key] } })),
}));
