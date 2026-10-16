"""Pure catalogue metadata shape policy, independent of serialization and storage."""
from music_analyzer.application.dto.catalogue import TrackMetadata


def validate_metadata(metadata: TrackMetadata) -> None:
    """Require text common/tag pairs and text warnings without coercing values.

    Lists and tuples represent the same ordered metadata contract. Boolean
    durations are not measurements; other duration normalization and eligibility
    remain separate policies. No text-size policy is imposed.
    """
    if not metadata_common_valid(metadata.common):
        raise ValueError('Invalid metadata common pairs')
    if not metadata_tags_valid(metadata.tags):
        raise ValueError('Invalid metadata tag pairs')
    if not metadata_warnings_valid(metadata.warnings):
        raise ValueError('Invalid metadata warnings')
    if isinstance(metadata.duration_seconds, bool):
        raise ValueError('Invalid duration: boolean is not a numeric measurement')


def metadata_common_valid(values) -> bool:
    """Validate one independently decoded common document without coercion.

    Empty text/keys, duplicate keys and ordered list/tuple pairs are retained.
    No size or audio-duration policy belongs to this component predicate.
    """
    return _pairs(values, common=True)


def metadata_tags_valid(values) -> bool:
    """Validate one decoded tag document; values must be text sequences."""
    return _pairs(values, common=False)


def metadata_warnings_valid(values) -> bool:
    """Validate one decoded warnings document, not legacy reader coercions."""
    return _texts(values)


def _texts(values) -> bool:
    return isinstance(values, (tuple, list)) and all(isinstance(value, str) for value in values)


def _pairs(values, *, common: bool) -> bool:
    if not isinstance(values, (tuple, list)):
        return False
    for pair in values:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            return False
        key, value = pair
        if not isinstance(key, str):
            return False
        if not (_texts(value) or (common and isinstance(value, str))):
            return False
    return True
