// Where the page asks for a track's audio (#258): the server streams the track's available file, read-only.

export function trackAudioUrl(trackId) {
  return `/api/track-audio?track=${encodeURIComponent(trackId)}`;
}
