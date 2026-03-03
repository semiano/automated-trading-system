import { create } from "zustand";

type OverlayState = {
  bbands: boolean;
  ema20: boolean;
  ema50: boolean;
  ema200: boolean;
};

type PanelState = {
  rsi: boolean;
  atr: boolean;
  bbWidth: boolean;
  volumeProfile: boolean;
};

type AppState = {
  symbol: string;
  timeframe: string;
  venue: string;
  rangeDays: number;
  overlays: OverlayState;
  panels: PanelState;
  setSymbol: (symbol: string) => void;
  setTimeframe: (timeframe: string) => void;
  setRangeDays: (days: number) => void;
  toggleOverlay: (key: keyof OverlayState) => void;
  togglePanel: (key: keyof PanelState) => void;
};

export const useStore = create<AppState>((set) => ({
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
    atr: true,
    bbWidth: true,
    volumeProfile: true,
  },
  setSymbol: (symbol) => set({ symbol }),
  setTimeframe: (timeframe) => set({ timeframe }),
  setRangeDays: (rangeDays) => set({ rangeDays }),
  toggleOverlay: (key) =>
    set((state) => ({ overlays: { ...state.overlays, [key]: !state.overlays[key] } })),
  togglePanel: (key) =>
    set((state) => ({ panels: { ...state.panels, [key]: !state.panels[key] } })),
}));
