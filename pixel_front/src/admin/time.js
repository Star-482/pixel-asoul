const SHANGHAI_OFFSET_MS = 8 * 60 * 60 * 1000;
const ISO_OFFSET_SUFFIX = /(?:Z|[+-]\d{2}:?\d{2})$/i;

export function parseApiInstant(value) {
  if (value instanceof Date) return new Date(value.getTime());
  if (typeof value !== 'string') return new Date(Number.NaN);
  if (ISO_OFFSET_SUFFIX.test(value)) return new Date(value);
  return new Date(shanghaiDatetimeLocalToIso(value));
}

export function toShanghaiDatetimeLocal(value) {
  if (!value) return '';
  const instant = parseApiInstant(value);
  if (!Number.isFinite(instant.getTime())) return '';
  return new Date(instant.getTime() + SHANGHAI_OFFSET_MS).toISOString().slice(0, 16);
}

export function shanghaiDatetimeLocalToIso(value) {
  if (!value) return '';
  const secondsValue = value.length === 16 ? `${value}:00` : value;
  const shanghaiWallClock = new Date(`${secondsValue}Z`);
  if (!Number.isFinite(shanghaiWallClock.getTime())) return '';
  return new Date(shanghaiWallClock.getTime() - SHANGHAI_OFFSET_MS).toISOString();
}
