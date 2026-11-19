// The M3U endpoint's address for a playlist recipe (#146).

export function playlistDownloadQuery(recipe) {
  const params = new URLSearchParams();
  params.set('start', recipe.startTrackId);
  params.set('bpm_min', recipe.bpmMin);
  params.set('bpm_max', recipe.bpmMax);
  if (recipe.length.durationMinutes) params.set('duration_minutes', recipe.length.durationMinutes);
  else params.set('count', recipe.length.count);
  if (recipe.harmonicMixing) params.set('min_key_strength', recipe.minimumKeyStrength);
  else params.set('harmonic', 'off');
  if (recipe.energyArc) setEnergyArc(params, recipe.energyArc);
  if (recipe.moodHold) params.set('mood', recipe.moodHold);
  return '/api/playlists/m3u?' + params.toString();
}

function setEnergyArc(params, energyArc) {
  params.set('arc', energyArc.shape);
  if (energyArc.low) params.set('energy_low', energyArc.low);
  if (energyArc.high) params.set('energy_high', energyArc.high);
}
