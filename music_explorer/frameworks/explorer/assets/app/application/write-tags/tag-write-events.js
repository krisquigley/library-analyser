// What happens while a listener previews a tag write and approves it (#132).

export const TAG_WRITE_EVENT_TYPES = Object.freeze(['tag-write-previewing', 'tag-write-previewed', 'tag-write-applying',
  'tag-write-applied', 'tag-write-failed', 'tag-write-discarded', 'tag-write-playlist-offered', 'tag-write-playlist-withdrawn']);

export function tagWritePreviewing(trackIds) {
  return Object.freeze({type: 'tag-write-previewing', trackIds});
}

export function tagWritePreviewed({changes, skipped, approvable}) {
  return Object.freeze({type: 'tag-write-previewed', changes, skipped, approvable});
}

export function tagWriteApplying() {
  return Object.freeze({type: 'tag-write-applying'});
}

export function tagWriteApplied({outcomes, notice}) {
  return Object.freeze({type: 'tag-write-applied', outcomes, notice});
}

export function tagWriteFailed(message) {
  return Object.freeze({type: 'tag-write-failed', message});
}

export function tagWriteDiscarded() {
  return Object.freeze({type: 'tag-write-discarded'});
}

export function tagWritePlaylistOffered(count) {
  return Object.freeze({type: 'tag-write-playlist-offered', count});
}

export function tagWritePlaylistWithdrawn() {
  return Object.freeze({type: 'tag-write-playlist-withdrawn'});
}
