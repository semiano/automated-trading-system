export function buildIndicatorsArg(args) {
    const out = ["volume_sma"];
    if (args.bbands || args.bbWidth)
        out.push("bbands");
    if (args.ema20)
        out.push("ema20");
    if (args.ema50)
        out.push("ema50");
    if (args.ema200)
        out.push("ema200");
    if (args.rsi)
        out.push("rsi");
    if (args.atr)
        out.push("atr");
    return out.join(",");
}
