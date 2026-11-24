// Previewing a BPM and key tag write for the selected track or the previewed playlist, then applying exactly that
// preview, once (#132).
// The server holds the approval behind a single-use token; the page keeps it only until it is used.

import {nextTagWriteState} from '../../domain/tag-write.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {TAG_WRITES} from '../ports/explorer-api.js';
import {requirePort} from '../ports/port.js';
import {tagWriteApplied, tagWriteApplying, tagWriteDiscarded, tagWriteFailed, tagWritePlaylistOffered, tagWritePlaylistWithdrawn,
  tagWritePreviewed, tagWritePreviewing} from './tag-write-events.js';

export function createTagWrite({explorerApi, eventBus}) {
  requirePort(TAG_WRITES, explorerApi);
  requirePort(EVENT_BUS, eventBus);
  let state = 'idle';
  let approval = null;
  let offeredPlaylist = null;
  let previewedTarget = null;

  function move(action, event) {
    state = nextTagWriteState(state, action);
    eventBus.publish(event);
  }

  async function settle(work) {
    try {
      move('succeed', await work());
    } catch (error) {
      move('fail', tagWriteFailed(error?.message || String(error)));
    }
  }

  function previewSelectedTrack({trackId, policy}) {
    return preview({trackIds: [trackId], policy, target: 'selected-track'});
  }

  async function previewOfferedPlaylist({policy}) {
    if (offeredPlaylist === null) {
      move('preview', tagWritePreviewing([]));
      move('fail', tagWriteFailed('Preview a playlist first'));
      return;
    }
    await preview({trackIds: offeredPlaylist, policy, target: 'previewed-playlist'});
  }

  async function preview({trackIds, policy, target}) {
    move('preview', tagWritePreviewing(trackIds));
    approval = null;
    previewedTarget = target;
    await settle(async () => {
      const previewed = await explorerApi.previewTagWrite({trackIds, policy});
      approval = previewed.token;
      return tagWritePreviewed({changes: previewed.changes, skipped: previewed.skipped, approvable: approval !== null});
    });
  }

  async function apply() {
    move('apply', tagWriteApplying());
    const token = approval;
    approval = null;
    await settle(async () => {
      if (token === null) throw new Error('There is nothing to write: preview again');
      return tagWriteApplied(await explorerApi.applyTagWrite(token));
    });
  }

  // Only an unapplied preview is discarded: its approval belongs to the tracks it was made for.
  function discard() {
    if (state !== 'previewed') return;
    approval = null;
    move('discard', tagWriteDiscarded());
  }

  function discardPlaylistPreview() {
    if (previewedTarget === 'previewed-playlist') discard();
  }

  function offerPlaylist(trackIds) {
    discardPlaylistPreview();
    offeredPlaylist = Object.freeze([...new Set(trackIds)]);
    eventBus.publish(tagWritePlaylistOffered(offeredPlaylist.length));
  }

  function withdrawPlaylist() {
    discardPlaylistPreview();
    offeredPlaylist = null;
    eventBus.publish(tagWritePlaylistWithdrawn());
  }

  return Object.freeze({state: () => state, previewSelectedTrack, previewOfferedPlaylist, apply, discard,
    offerPlaylist, withdrawPlaylist});
}
