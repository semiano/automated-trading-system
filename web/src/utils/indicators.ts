export function buildIndicatorsArg(args: {
  bbands: boolean;
  ema20: boolean;
  ema50: boolean;
  ema200: boolean;
  rsi: boolean;
  atr: boolean;
  bbWidth: boolean;
  forceSimpleMechanics?: boolean;
  emaFastLen?: number;
  emaSlowLen?: number;
}): string {
  const out = new Set<string>(["volume_sma"]);
  const forceCore = Boolean(args.forceSimpleMechanics);
  if (args.bbands || args.bbWidth || forceCore) out.add("bbands");
  if (args.ema20 || forceCore) out.add("ema20");
  if (args.ema50 || forceCore) out.add("ema50");
  if (args.ema200) out.add("ema200");
  if (args.rsi) out.add("rsi");
  if (args.atr) out.add("atr");

  if (typeof args.emaFastLen === "number" && Number.isFinite(args.emaFastLen) && args.emaFastLen > 0) {
    out.add(`ema${Math.trunc(args.emaFastLen)}`);
  }
  if (typeof args.emaSlowLen === "number" && Number.isFinite(args.emaSlowLen) && args.emaSlowLen > 0) {
    out.add(`ema${Math.trunc(args.emaSlowLen)}`);
  }

  return Array.from(out).join(",");
}
