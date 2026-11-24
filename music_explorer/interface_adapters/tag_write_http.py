"""The tag-write action over HTTP (#132): query -> preview request, and results -> JSON for the page.

Files are named by their file name only; the page never needs a full path.
"""
from music_explorer.application.use_cases.preview_tag_write.preview_tag_write import (
    PreviewTagWriteRequest, TagWriteRequestError)
from music_explorer.domain.harmonic_mixing import DEFAULT_MINIMUM_KEY_STRENGTH
from music_explorer.domain.tag_change_set import FILL_EMPTY


def preview_request_from_query(values) -> PreviewTagWriteRequest:
    """A parsed query string (name -> list of values), as the server's parser gives it."""
    return PreviewTagWriteRequest(tuple(values.get('track', ())), values.get('policy', [FILL_EMPTY])[0],
                                  _strength(values.get('minimum_key_strength', [None])[0]))


def tag_write_preview_to_http(preview) -> dict:
    return {
        'token': preview.token,
        'changes': [{'file': _file_name(change.location), 'field': change.field, 'current': change.current,
                     'proposed': change.proposed, 'replaces': change.replaces} for change in preview.changes],
        'skipped': [{'track_id': track_id, 'reason': reason} for track_id, reason in preview.skipped],
    }


def tag_write_report_to_http(report) -> dict:
    return {
        'outcomes': [{'file': _file_name(outcome.location), 'status': outcome.status, 'detail': outcome.detail}
                     for outcome in report.outcomes],
        'notice': report.notice,
    }


def _strength(text):
    if text is None:
        return DEFAULT_MINIMUM_KEY_STRENGTH
    try:
        return float(text)
    except ValueError:
        raise TagWriteRequestError('The minimum key strength must be between 0 and 1') from None


def _file_name(location):
    return location.rsplit('/', 1)[-1]
