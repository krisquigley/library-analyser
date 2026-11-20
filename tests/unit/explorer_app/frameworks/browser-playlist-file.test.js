// Issue #146: the playlist is offered as a real browser download, and nothing is left behind.
import {test, beforeEach, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {browserPlaylistFile} from '../../../../music_explorer/frameworks/explorer/assets/app/frameworks/browser-playlist-file.js';

let page;
const realURL = globalThis.URL;
beforeEach(() => {
  page = {blobs: [], revoked: [], body: [], anchors: []};
  globalThis.URL = {createObjectURL: blob => { page.blobs.push(blob); return `blob:test/${page.blobs.length}`; },
    revokeObjectURL: url => page.revoked.push(url)};
  globalThis.document = {
    body: {append: node => page.body.push(node)},
    createElement: tag => {
      const anchor = {tag, href: '', download: '', clicks: 0, click() { this.clicks++; page.whenClicked?.(this); },
        remove() { page.body = page.body.filter(node => node !== this); }};
      page.anchors.push(anchor);
      return anchor;
    },
  };
});
afterEach(() => { globalThis.URL = realURL; });

test('saving downloads the contents under the filename from a blob URL, then cleans up', async () => {
  let atClick;
  page.whenClicked = anchor => { atClick = {href: anchor.href, download: anchor.download, inPage: page.body.includes(anchor)}; };
  browserPlaylistFile().save({filename: 'set.m3u', contents: '#EXTM3U\n/a.mp3\n', contentType: 'audio/x-mpegurl'});
  assert.deepEqual(atClick, {href: 'blob:test/1', download: 'set.m3u', inPage: true});
  assert.equal(page.anchors[0].clicks, 1);
  assert.deepEqual([page.blobs[0].type, await page.blobs[0].text()], ['audio/x-mpegurl', '#EXTM3U\n/a.mp3\n']);
  assert.deepEqual([page.body, page.revoked], [[], ['blob:test/1']]);
});

test('a download that fails still removes the link and revokes its URL, and the failure is reported', () => {
  page.whenClicked = () => { throw new Error('blocked'); };
  assert.throws(() => browserPlaylistFile().save({filename: 'set.m3u', contents: '', contentType: 'audio/x-mpegurl'}), /blocked/);
  assert.deepEqual([page.body, page.revoked], [[], ['blob:test/1']]);
});
