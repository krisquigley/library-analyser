"""The track-labels request and response over HTTP (#243)."""
from music_explorer.application.use_cases.label_tracks.label_tracks import LabelTracksRequest


def label_request_from_query(values) -> LabelTracksRequest:
    """A parsed query string (name -> list of values), as the server's parser gives it."""
    return LabelTracksRequest(tuple(values.get('track', ())))


def track_labels_to_http(labels) -> dict:
    return {'labels': [{'track_id': label.track_id, 'title': label.title, 'artist': label.artist} for label in labels]}
