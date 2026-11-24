// The tag-write responses (#132), checked against their schemas at the boundary. A wrong shape is refused whole.

const TAG_FIELDS = Object.freeze(['bpm', 'key']);
const OUTCOME_STATUSES = Object.freeze(['written', 'skipped', 'failed']);

export function tagWritePreviewFrom(body) {
  if (body?.token !== null && typeof body?.token !== 'string') refuseTagPreview('token must be text or null');
  if (!Array.isArray(body.changes)) refuseTagPreview('changes must be a list');
  if (!Array.isArray(body.skipped)) refuseTagPreview('skipped must be a list');
  return {token: body.token, changes: body.changes.map(tagChangeFrom), skipped: body.skipped.map(skippedTrackFrom)};
}

export function tagWriteReportFrom(body) {
  if (!Array.isArray(body?.outcomes)) refuseTagReport('outcomes must be a list');
  if (typeof body.notice !== 'string') refuseTagReport('notice must be text');
  return {outcomes: body.outcomes.map(tagOutcomeFrom), notice: body.notice};
}

function tagChangeFrom(change, index) {
  const label = `change ${index + 1}`;
  if (typeof change?.file !== 'string') refuseTagPreview(`${label} file must be text`);
  if (!TAG_FIELDS.includes(change.field)) refuseTagPreview(`${label} field must be bpm or key`);
  if (change.current !== null && typeof change.current !== 'string') refuseTagPreview(`${label} current must be text or null`);
  if (typeof change.proposed !== 'string') refuseTagPreview(`${label} proposed must be text`);
  if (typeof change.replaces !== 'boolean') refuseTagPreview(`${label} replaces must be true or false`);
  return {file: change.file, field: change.field, current: change.current, proposed: change.proposed, replaces: change.replaces};
}

function skippedTrackFrom(skipped, index) {
  const label = `skipped track ${index + 1}`;
  if (typeof skipped?.track_id !== 'string') refuseTagPreview(`${label} track_id must be text`);
  if (typeof skipped.reason !== 'string') refuseTagPreview(`${label} reason must be text`);
  return {trackId: skipped.track_id, reason: skipped.reason};
}

function tagOutcomeFrom(outcome, index) {
  const label = `outcome ${index + 1}`;
  if (typeof outcome?.file !== 'string') refuseTagReport(`${label} file must be text`);
  if (!OUTCOME_STATUSES.includes(outcome.status)) refuseTagReport(`${label} status must be written, skipped or failed`);
  if (typeof outcome.detail !== 'string') refuseTagReport(`${label} detail must be text`);
  return {file: outcome.file, status: outcome.status, detail: outcome.detail};
}

function refuseTagPreview(problem) {
  throw new Error(`Invalid tag preview: ${problem}`);
}

function refuseTagReport(problem) {
  throw new Error(`Invalid tag write report: ${problem}`);
}
