// The M3U and preview endpoints' addresses for a playlist recipe (#146, #137, #138): the same parameters for both.

const ARC_LENGTH_PARAMETERS = Object.freeze({tracks: 'arc_tracks', minutes: 'arc_minutes'});

export function playlistDownloadQuery(recipe) {
  return '/api/playlists/m3u?' + playlistParameters(recipe);
}

export function playlistPreviewQuery(recipe) {
  return '/api/playlists/preview?' + playlistParameters(recipe);
}

function playlistParameters(recipe) {
  const params = new URLSearchParams();
  params.set('start', recipe.startTrackId);
  params.set('bpm_min', recipe.bpmMin);
  params.set('bpm_max', recipe.bpmMax);
  if (recipe.length.durationMinutes) params.set('duration_minutes', recipe.length.durationMinutes);
  else if (recipe.length.count) params.set('count', recipe.length.count);
  if (recipe.harmonicMixing) params.set('min_key_strength', recipe.minimumKeyStrength);
  else params.set('harmonic', 'off');
  appendEnergyPlan(params, recipe.energyPlan, recipe.length.arcs);
  if (recipe.moodHold) params.set('mood', recipe.moodHold);
  return params.toString();
}

// Arcs repeat in order; a list is sent only when some arc uses it, a blank keeping each unset value's place.
function appendEnergyPlan(params, energyPlan, arcUnit) {
  for (const arc of energyPlan) params.append('arc', arc.shape);
  appendPerArc(params, 'energy_low', energyPlan.map(arc => arc.low));
  appendPerArc(params, 'energy_high', energyPlan.map(arc => arc.high));
  if (arcUnit) appendPerArc(params, ARC_LENGTH_PARAMETERS[arcUnit], energyPlan.map(arc => arc.length));
}

function appendPerArc(params, name, values) {
  if (values.some(Boolean)) for (const value of values) params.append(name, value || '');
}
