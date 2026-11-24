// Lengths shown to the listener (#236, #257): m:ss, or h:mm:ss from an hour, to the nearest second.
// An unknown or impossible length is null, for the caller to say so its own way.

export function displayDuration(seconds) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds <= 0) return null;
  const whole = Math.round(seconds);
  const [hours, minutes, rest] = [Math.floor(whole / 3600), Math.floor(whole / 60) % 60, whole % 60];
  const pad = value => String(value).padStart(2, '0');
  return hours ? `${hours}:${pad(minutes)}:${pad(rest)}` : `${minutes}:${pad(rest)}`;
}
