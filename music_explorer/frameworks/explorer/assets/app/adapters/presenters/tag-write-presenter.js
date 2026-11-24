// What the Write tags panel shows for each step of a previewed and approved tag write (#132).

const FIELD_NAMES = Object.freeze({bpm: 'BPM', key: 'Key'});

const TAG_WRITE_EVENT_VIEWS = Object.freeze({
  'tag-write-previewing': () => ({busy: true, rows: [], skipped: [], report: [], canApply: false,
    status: {text: 'Reading the file’s tags…', urgent: false}}),
  'tag-write-previewed': event => ({busy: false, rows: event.changes.map(tagChangeRow), report: [],
    skipped: event.skipped.map(skipped => skipped.reason), canApply: event.approvable,
    status: {text: previewText(event), urgent: false}}),
  'tag-write-applying': () => ({busy: true, canApply: false, status: {text: 'Writing tags…', urgent: false}}),
  'tag-write-applied': event => ({busy: false, canApply: false, rows: [], report: event.outcomes.map(outcomeLine),
    status: {text: appliedText(event), urgent: event.outcomes.some(outcome => outcome.status !== 'written')}}),
  'tag-write-failed': event => ({busy: false, canApply: false, status: {text: `Tags not written: ${event.message}`, urgent: true}}),
});

export function tagWriteViewModel() {
  return {busy: false, rows: [], skipped: [], report: [], canApply: false,
    status: {text: 'Preview the BPM and key tags of the selected track before writing them.', urgent: false}};
}

export function presentTagWriteEvent(event) {
  return TAG_WRITE_EVENT_VIEWS[event.type](event);
}

export function presentRejectedTagWriteInput(message) {
  return {status: {text: message, urgent: true}};
}

function tagChangeRow({file, field, current, proposed, replaces}) {
  const change = `${current ?? '(empty)'} → ${proposed}${replaces ? ' (replaces)' : ''}`;
  return {file, field: FIELD_NAMES[field], change, replaces};
}

function previewText({changes, approvable}) {
  if (!approvable) return 'Nothing to write.';
  const count = changes.length === 1 ? '1 tag change' : `${changes.length} tag changes`;
  return `${count} to write. Check them, then choose Write these tags.`;
}

function outcomeLine({file, status, detail}) {
  return detail ? `${file}: ${status} (${detail})` : `${file}: ${status}`;
}

function appliedText({outcomes, notice}) {
  const count = status => outcomes.filter(outcome => outcome.status === status).length;
  const summary = `${count('written')} written, ${count('skipped')} skipped, ${count('failed')} failed.`;
  return notice ? `${summary} ${notice}` : summary;
}
