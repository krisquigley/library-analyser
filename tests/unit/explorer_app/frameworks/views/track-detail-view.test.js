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

test('a score is a compact bar with its label and raw value, named for assistive technology (#236)', () => {
  const row = trackDetailView().bar({label: 'calm', ariaLabel: 'calm: 0.3 out of 1', valueText: '0.3', fillPercent: 25});
  assert.equal(row.className, 'score-bar');
  const track = descendants(row).find(node => node.className === 'score-bar-track');
  assert.deepEqual([track.getAttribute('role'), track.getAttribute('aria-label')], ['img', 'calm: 0.3 out of 1']);
  assert.equal(descendants(row).find(node => node.className === 'score-bar-fill').style.width, '25%');
  assert.deepEqual(row.children.map(child => child.textContent).filter(Boolean), ['calm', '0.3']);
});

test('key facts are badges above the metadata, each saying where it comes from (#236)', () => {
  const detail = trackDetailView();
  detail.show({heading: 'Current Track', metadata: {lines: ['Title: Song'], keyFacts: [{text: '120.0 BPM', source: 'analysis (raw)'}]},
    fields: [], unavailable: null});
  const [, list] = roots.detail.children;
  const [metadata] = list.children;
  assert.equal(metadata.className, 'field track-metadata');
  const facts = metadata.children[0];
  assert.equal(facts.className, 'key-facts');
  assert.deepEqual(facts.children.map(fact => [fact.className, fact.textContent, fact.title, fact.getAttribute('aria-label')]),
    [['key-fact', '120.0 BPM', 'analysis (raw)', '120.0 BPM, from analysis (raw)']]);
  assert.equal(metadata.children[1].textContent, 'Title: Song');
});

test('fields without usable evidence share one section that expands to each reason (#236)', () => {
  const detail = trackDetailView();
  detail.show({heading: 'Current Track', metadata: {lines: []}, fields: [],
    unavailable: {summary: 'Not available: genres', reasons: [{name: 'genres', text: 'no usable evidence; not analysed'}]}});
  const [, list] = roots.detail.children;
  const section = list.children.at(-1);
  assert.equal(section.className, 'field unavailable-evidence');
  const [details] = section.children;
  assert.equal(details.tagName, 'DETAILS');
  assert.deepEqual(texts(details), ['Not available: genres', 'genres: no usable evidence; not analysed']);
});

test('the field list is drawn the same way whether shown or asked for by the diagnostics (#236)', () => {
  const detail = trackDetailView();
  const viewModel = {heading: 'Current Track', metadata: {lines: ['Title: Song'], keyFacts: [{text: 'Key 8A', source: 'analysis'}]},
    fields: [{name: 'bpm', items: [{text: '120.0 BPM (raw)'}]}], unavailable: {summary: 'Not available: mood', reasons: []}};
  const list = detail.fieldList(viewModel);
  detail.show(viewModel);
  assert.equal(list.tagName, 'DIV');
  assert.deepEqual(texts(list), texts(roots.detail.children[1]));
  assert.deepEqual(list.children.map(section => section.className), ['field track-metadata', 'field', 'field unavailable-evidence']);
});
