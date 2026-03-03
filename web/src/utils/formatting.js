export function toIsoDate(date) {
    return date.toISOString();
}
export function num(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(value))
        return "-";
    return value.toFixed(digits);
}
