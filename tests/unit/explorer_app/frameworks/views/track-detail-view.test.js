// Issue #146: the track detail panel's states on screen.
import {test, beforeEach} from 'node:test';
import assert from 'node:assert/strict';
import {trackDetailView} from '../../../../../music_explorer/frameworks/explorer/assets/app/frameworks/views/track-detail-view.js';
import {byTag, descendants, installFakeDocument} from '../fake-document.js';

let roots;
beforeEach(() => { roots = installFakeDocument(['detail']); });

const texts = node => descendants(node).map(each => each.textContent).filter(Boolean);

test('with no track selected the panel is empty and not busy', () => {
  const detail = trackDetailView();
  detail.showLoading({status: 'Loading current track detail…'});
  detail.showNone();
  assert.deepEqual(roots.detail.children, []);
  assert.equal(roots.detail.getAttribute('aria-busy'), 'false');
});

test('loading replaces the old detail at once with a polite status and no retry', () => {
  const detail = trackDetailView();
  detail.show({heading: 'Current Track', metadata: {lines: ['Title: Old']}, fields: []});
  detail.showLoading({status: 'Loading current track detail…'});
  const [status] = roots.detail.children;
  assert.equal(roots.detail.children.length, 1);
  assert.deepEqual([status.getAttribute('role'), status.getAttribute('aria-live'), status.textContent],
    ['status', 'polite', 'Loading current track detail…']);
  assert.equal(roots.detail.getAttribute('aria-busy'), 'true');
  assert.equal(byTag(roots.detail, 'button').length, 0);
});

test('the detail replaces the loading status and is no longer busy', () => {
  const detail = trackDetailView();
  detail.showLoading({status: 'Loading current track detail…'});
  detail.show({heading: 'Current Track', metadata: {lines: ['Title: Song']},
    fields: [{name: 'bpm', items: [{text: '120.0 BPM (raw)'}]}]});
  assert.deepEqual(texts(roots.detail), ['Current Track', 'Title: Song', 'bpm', '120.0 BPM (raw)']);
  assert.ok(!descendants(roots.detail).some(node => node.getAttribute?.('role') === 'status'));
  assert.equal(roots.detail.getAttribute('aria-busy'), 'false');
});

test('a failure is an alert, with Retry detail only when it can be retried', () => {
  const detail = trackDetailView();
  let retried = 0;
  detail.showFailure({alert: 'Unable to load current track detail: Gone'}, () => { retried++; });
  const [alert, retry] = roots.detail.children;
  assert.deepEqual([alert.getAttribute('role'), alert.textContent], ['alert', 'Unable to load current track detail: Gone']);
  assert.equal(retry.textContent, 'Retry detail');
  retry.onclick();
  assert.equal(retried, 1);
  detail.showFailure({alert: 'Unable to load current track detail: Refused'});
  assert.equal(byTag(roots.detail, 'button').length, 0);
});

test('a gauge names its score for assistive technology and turns its needle', () => {
  const gauge = trackDetailView().gauge({label: 'calm', ariaLabel: 'calm: 0.3 out of 1', needleDegrees: -60});
  const dial = descendants(gauge).find(node => node.className === 'score-gauge');
  assert.deepEqual([dial.getAttribute('role'), dial.getAttribute('aria-label')], ['img', 'calm: 0.3 out of 1']);
  assert.equal(descendants(gauge).find(node => node.className === 'score-needle').style.transform, 'rotate(-60deg)');
});
