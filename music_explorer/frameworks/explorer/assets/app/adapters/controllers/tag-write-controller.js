// The Write tags panel's commands (#132). The selected track and the chosen policy are checked before the use case sees them.

const TAG_POLICIES = Object.freeze(['fill-empty', 'replace-existing']);

export function tagWriteController({tagWrite, currentTrackId, rejectInput}) {
  return Object.freeze({
    async previewRequested(policy) {
      const trackId = currentTrackId();
      if (typeof trackId !== 'string' || !trackId) {
        rejectInput('Select a track to tag first');
        return;
      }
      if (!TAG_POLICIES.includes(policy)) {
        rejectInput('Choose whether to fill empty tags only or also replace existing ones');
        return;
      }
      await tagWrite.preview({trackIds: [trackId], policy});
    },
    applyRequested: () => tagWrite.apply(),
  });
}
