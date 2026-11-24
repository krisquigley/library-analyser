// Issue #132: previewing a tag write for chosen tracks, then applying exactly that preview once.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createTagWrite} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/write-tags/write-tags.js';
import {TAG_WRITE_EVENT_TYPES} from '../../../../../music_explorer/frameworks/explorer/assets/app/application/write-tags/tag-write-events.js';

const CHANGES = [{file: 'one.mp3', field: 'bpm', current: null, proposed: '124', replaces: false}];
const REPORT = {outcomes: [{file: 'one.mp3', status: 'written', detail: 'BPM 124'}], notice: 'Rescan them.'};

function harness(api = {}) {
  const published = [], applied = [], previewed = [];
  const explorerApi = {
    previewTagWrite: async request => { previewed.push(request); return {token: 'tok', changes: CHANGES, skipped: []}; },
    applyTagWrite: async token => { applied.push(token); return REPORT; },
    ...api,
  };
  const tagWrite = createTagWrite({explorerApi, eventBus: {publish: event => published.push(event), subscribe() {}}});
  return {tagWrite, published, applied, previewed};
}

test('the event types are the ones the use case publishes', () => {
  assert.deepEqual(TAG_WRITE_EVENT_TYPES, ['tag-write-previewing', 'tag-write-previewed', 'tag-write-applying',
    'tag-write-applied', 'tag-write-failed', 'tag-write-discarded', 'tag-write-playlist-offered', 'tag-write-playlist-withdrawn']);
});

test('a preview lists the changes and an apply sends its token once', async () => {
  const {tagWrite, published, applied, previewed} = harness();
  await tagWrite.previewSelectedTrack({trackId: 't1', policy: 'fill-empty'});
  assert.deepEqual(previewed, [{trackIds: ['t1'], policy: 'fill-empty'}]);
  assert.deepEqual(published, [{type: 'tag-write-previewing', trackIds: ['t1']},
    {type: 'tag-write-previewed', changes: CHANGES, skipped: [], approvable: true}]);
  await tagWrite.apply();
  assert.deepEqual(applied, ['tok']);
  assert.deepEqual(published.slice(2), [{type: 'tag-write-applying'},
    {type: 'tag-write-applied', outcomes: REPORT.outcomes, notice: REPORT.notice}]);
  assert.equal(tagWrite.state(), 'applied');
  await assert.rejects(tagWrite.apply(), /cannot apply while applied/);
  assert.deepEqual(applied, ['tok']);
});

test('a preview with nothing to change cannot be applied', async () => {
  const {tagWrite, published, applied} = harness({previewTagWrite: async () => ({token: null, changes: [],
    skipped: [{trackId: 't1', reason: 'Nothing to change'}]})});
  await tagWrite.previewSelectedTrack({trackId: 't1', policy: 'fill-empty'});
  assert.equal(published.at(-1).approvable, false);
  await tagWrite.apply();
  assert.deepEqual(applied, []);
  assert.deepEqual(published.at(-1), {type: 'tag-write-failed', message: 'There is nothing to write: preview again'});
});

test('a refused preview or apply is told, and an apply that failed needs a new preview', async () => {
  const refused = harness({previewTagWrite: async () => { throw new Error('Choose at least one track to tag'); }});
  await refused.tagWrite.previewSelectedTrack({trackId: 't1', policy: 'fill-empty'});
  assert.deepEqual(refused.published.at(-1), {type: 'tag-write-failed', message: 'Choose at least one track to tag'});
  const stale = harness({applyTagWrite: async () => { throw new Error('The tags changed since the preview: preview again'); }});
  await stale.tagWrite.previewSelectedTrack({trackId: 't1', policy: 'fill-empty'});
  await stale.tagWrite.apply();
  assert.deepEqual(stale.published.at(-1), {type: 'tag-write-failed',
    message: 'The tags changed since the preview: preview again'});
  await assert.rejects(stale.tagWrite.apply(), /cannot apply while failed/);
});

test('choosing another track discards an unapplied preview, so its approval cannot be used for the wrong track', async () => {
  const {tagWrite, published, applied} = harness();
  tagWrite.discard();
  assert.deepEqual([published, tagWrite.state()], [[], 'idle'], 'nothing to discard before a preview');
  await tagWrite.previewSelectedTrack({trackId: 't1', policy: 'fill-empty'});
  tagWrite.discard();
  assert.deepEqual([published.at(-1), tagWrite.state()], [{type: 'tag-write-discarded'}, 'idle']);
  await assert.rejects(tagWrite.apply(), /cannot apply while idle/);
  assert.deepEqual(applied, []);
  await tagWrite.previewSelectedTrack({trackId: 't1', policy: 'fill-empty'});
  await tagWrite.apply();
  tagWrite.discard();
  assert.equal(tagWrite.state(), 'applied', 'a finished write keeps its report on screen');
});

test('a previewed playlist can be tagged as one action, once it is offered', async () => {
  const {tagWrite, published, previewed} = harness();
  await tagWrite.previewOfferedPlaylist({policy: 'fill-empty'});
  assert.deepEqual(published.at(-1), {type: 'tag-write-failed', message: 'Preview a playlist first'});
  assert.deepEqual(previewed, []);
  tagWrite.offerPlaylist(['t1', 't2', 't1']);
  assert.deepEqual(published.at(-1), {type: 'tag-write-playlist-offered', count: 2});
  await tagWrite.previewOfferedPlaylist({policy: 'replace-existing'});
  assert.deepEqual(previewed, [{trackIds: ['t1', 't2'], policy: 'replace-existing'}]);
  assert.equal(tagWrite.state(), 'previewed');
});

test('a new or withdrawn playlist discards a preview made for the old one, but not one for the selected track', async () => {
  const {tagWrite, published} = harness();
  tagWrite.offerPlaylist(['t1', 't2']);
  await tagWrite.previewOfferedPlaylist({policy: 'fill-empty'});
  tagWrite.withdrawPlaylist();
  assert.deepEqual(published.slice(-2), [{type: 'tag-write-discarded'}, {type: 'tag-write-playlist-withdrawn'}]);
  assert.equal(tagWrite.state(), 'idle');
  await tagWrite.previewOfferedPlaylist({policy: 'fill-empty'});
  assert.deepEqual(published.at(-1), {type: 'tag-write-failed', message: 'Preview a playlist first'});
  await tagWrite.previewSelectedTrack({trackId: 't9', policy: 'fill-empty'});
  tagWrite.offerPlaylist(['t3']);
  assert.equal(tagWrite.state(), 'previewed', 'a selected-track preview survives a playlist change');
});
