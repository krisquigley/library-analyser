"""Conservative review policy: manual annotations never erase uncertainty."""
FIELDS = ('bpm', 'key', 'genres', 'mood', 'instruments', 'energy')


def validate_override(field, value):
    if field not in FIELDS:
        raise ValueError('Override field must be one of: ' + ', '.join(FIELDS))
    if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 4096):
        raise ValueError('Override must be nonblank text of at most 4096 characters')


def effective_value(automatic, manual):
    return manual if manual is not None else automatic
