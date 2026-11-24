// Previewing a BPM and key tag write for chosen tracks, then applying exactly that preview, once (#132).
// The server holds the approval behind a single-use token; the page keeps it only until it is used.

import {nextTagWriteState} from '../../domain/tag-write.js';
import {EVENT_BUS} from '../ports/event-bus.js';
import {TAG_WRITES} from '../ports/explorer-api.js';
import {requirePort} from '../ports/port.js';
import {tagWriteApplied, tagWriteApplying, tagWriteFailed, tagWritePreviewed, tagWritePreviewing} from './tag-write-events.js';

export function createTagWrite({explorerApi, eventBus}) {
  requirePort(TAG_WRITES, explorerApi);
  requirePort(EVENT_BUS, eventBus);
  let state = 'idle';
  let approval = null;

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

  async function preview({trackIds, policy}) {
    move('preview', tagWritePreviewing(trackIds));
    approval = null;
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

  return Object.freeze({state: () => state, preview, apply});
}
