// The Write tags panel's commands (#132). The target, the selected track and the policy are checked before the use
// case sees them; a playlist preview offers its tracks as a target.

const TAG_POLICIES = Object.freeze(['fill-empty', 'replace-existing']);
const TAG_TARGETS = Object.freeze(['selected-track', 'previewed-playlist']);

export function tagWriteController({tagWrite, currentTrackId, rejectInput}) {
  async function previewRequested(policy, target) {
    if (!TAG_POLICIES.includes(policy)) return rejectInput('Choose whether to fill empty tags only or also replace existing ones');
    if (!TAG_TARGETS.includes(target)) return rejectInput('Choose the selected track or the previewed playlist');
    if (target === 'previewed-playlist') return tagWrite.previewOfferedPlaylist({policy});
    const trackId = currentTrackId();
    if (typeof trackId !== 'string' || !trackId) return rejectInput('Select a track to tag first');
    return tagWrite.previewSelectedTrack({trackId, policy});
  }

  return Object.freeze({
    previewRequested,
    applyRequested: () => tagWrite.apply(),
    trackChanged: () => tagWrite.discard(),
    playlistPreviewed: tracks => tagWrite.offerPlaylist(tracks.map(track => track.trackId)),
    playlistPreviewCleared: () => tagWrite.withdrawPlaylist(),
  });
}
