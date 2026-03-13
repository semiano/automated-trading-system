const FALLBACK_TIMEZONE = "UTC";

function getResolvedTimeZone(): string {
  try {
    const resolved = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (resolved && resolved.trim()) return resolved;
  } catch {
    // Ignore and fall back to UTC.
  }
  return FALLBACK_TIMEZONE;
}

function normalizeToDate(value: string | Date): Date {
  if (value instanceof Date) return value;
  if (/([zZ]|[+-]\d{2}:\d{2})$/.test(value)) return new Date(value);
  return new Date(`${value}Z`);
}

function getTzShortLabel(date: Date, timeZone: string): string {
  try {
    const parts = new Intl.DateTimeFormat(undefined, {
      timeZone,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      timeZoneName: "short",
    }).formatToParts(date);
    const label = parts.find((p) => p.type === "timeZoneName")?.value?.trim();
    if (label) return label;
  } catch {
    // Ignore and use fallback.
  }
  return "UTC";
}

export function getClientTimeZone(): string {
  return getResolvedTimeZone();
}

export function getClientTimeZoneLabel(date: Date = new Date()): string {
  return getTzShortLabel(date, getResolvedTimeZone());
}

export function parseApiTimestamp(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = normalizeToDate(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatDateTimeWithZone(value: string | Date | null | undefined): string {
  if (!value) return "-";
  const date = typeof value === "string" || value instanceof Date ? normalizeToDate(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "-";

  const timeZone = getResolvedTimeZone();
  const body = new Intl.DateTimeFormat(undefined, {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
  const label = getTzShortLabel(date, timeZone);
  return `${body} ${label}`;
}

export function formatTimeWithZone(value: Date | null | undefined): string {
  if (!value || Number.isNaN(value.getTime())) return "-";
  const timeZone = getResolvedTimeZone();
  const body = new Intl.DateTimeFormat(undefined, {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(value);
  const label = getTzShortLabel(value, timeZone);
  return `${body} ${label}`;
}

export function formatDateWithZone(value: string | Date | null | undefined): string {
  if (!value) return "-";
  const date = typeof value === "string" || value instanceof Date ? normalizeToDate(value) : null;
  if (!date || Number.isNaN(date.getTime())) return "-";
  const timeZone = getResolvedTimeZone();
  const body = new Intl.DateTimeFormat(undefined, {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
  const label = getTzShortLabel(date, timeZone);
  return `${body} ${label}`;
}
