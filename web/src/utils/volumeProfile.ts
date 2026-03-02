import type { IndicatorRow } from "../api/types";

export type VolumeProfileBin = {
  price: number;
  volume: number;
};

export function buildVolumeProfile(candles: IndicatorRow[], bins = 24): VolumeProfileBin[] {
  if (!candles.length) return [];
  const low = Math.min(...candles.map((c) => c.low));
  const high = Math.max(...candles.map((c) => c.high));
  if (high <= low) return [];

  const width = (high - low) / bins;
  const bucket = Array.from({ length: bins }, (_, idx) => ({
    price: low + width * (idx + 0.5),
    volume: 0,
  }));

  candles.forEach((c) => {
    const typical = (c.high + c.low + c.close) / 3;
    const idx = Math.max(0, Math.min(bins - 1, Math.floor((typical - low) / width)));
    bucket[idx].volume += c.volume;
  });

  return bucket;
}

export function candleHeat(volume: number, volumeSma?: number | null): number {
  if (!volumeSma || volumeSma <= 0) return 0.35;
  const ratio = volume / volumeSma;
  return Math.min(0.95, Math.max(0.2, 0.2 + ratio * 0.35));
}
