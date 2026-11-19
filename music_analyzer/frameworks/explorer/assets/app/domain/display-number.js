// Numbers shown to the listener (#146): one decimal place, half away from zero.

export function displayNumber(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return String(value);
  return (Math.sign(value) * Math.round((Math.abs(value) + Number.EPSILON) * 10) / 10).toFixed(1);
}
