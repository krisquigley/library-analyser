// What the Download M3U controls show for the draft and each download event (#146).

import {energyRangeApplies, minimumKeyStrengthApplies} from '../../domain/playlist-draft.js';

const ENERGY_ARC_CHOICES = Object.freeze([
  ['none', 'No energy arc'], ['steady', 'Steady energy'], ['rise', 'Rising energy'], ['fall', 'Falling energy'],
  ['peak', 'Energy peak'], ['dip', 'Energy dip']]);

const PLAYLIST_EVENT_VIEWS = Object.freeze({
  'playlist-draft-edited': event => draftApplicability(event.draft),
  'playlist-download-started': () => ({downloadDisabled: true}),
  'playlist-downloaded': event => ({downloadDisabled: false, status: {
    text: event.warning ? `M3U downloaded. Warning: ${event.warning}` : 'M3U downloaded.', urgent: false}}),
  'playlist-download-failed': event => ({downloadDisabled: false, status: {
    text: `M3U download failed: ${event.message}`, urgent: true}}),
});

export function playlistControlsViewModel({draft, downloadState, moods}) {
  return {
    values: draft,
    ...draftApplicability(draft),
    downloadDisabled: downloadState === 'downloading',
    arcChoices: ENERGY_ARC_CHOICES.map(choice => [...choice]),
    moodChoices: [['', 'No mood hold'], ...moods.map(mood => [mood, `Hold mood: ${mood}`])],
  };
}

export function presentPlaylistDownloadEvent(event) {
  return PLAYLIST_EVENT_VIEWS[event.type](event);
}

export function presentRejectedPlaylistInput(message) {
  return {status: {text: message, urgent: true}};
}

function draftApplicability(draft) {
  return {minimumKeyStrengthDisabled: !minimumKeyStrengthApplies(draft), energyRangeDisabled: !energyRangeApplies(draft)};
}
