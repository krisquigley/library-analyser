"""What the listener reads after `music-analyzer export-mixxx` (#133)."""
_TARGET = 'Mixxx 2.5, schema 39'


def present_mixxx_export_planned(event) -> str:
    return (f'Dry run: would export {_tracks(event.track_count)} to {event.destination} ({_TARGET}); '
            f'{event.skipped_count} skipped. Nothing was written.')


def present_mixxx_exported(event) -> str:
    return f'Exported {_tracks(event.track_count)} to {event.destination} ({_TARGET}); {event.skipped_count} skipped.'


def present_skipped_tracks(skipped) -> str:
    return '\n'.join(f'Skipped {track_id}: {reason}' for track_id, reason in skipped)


def _tracks(count):
    return f'{count} track' if count == 1 else f'{count} tracks'
