"""Export the active analysed tracks to a new Mixxx-compatible library file (#133).

Each track's manual overrides win over its detected BPM and key; anything unknown is left empty. Tracks that
are not in the active library, have no available location or have no completed analysis are skipped, each with
its reason. The analysis database is only read.

With mood-quadrant colours (#134), each track whose valence and arousal come from the emomusic model, and
which has no manual energy or mood override, is coloured by its quadrant among those tracks; any other
track has no colour.
"""
from dataclasses import dataclass, replace
import math

from music_analyzer.application.dto.review import StoredTrack
from music_analyzer.application.ports.event_bus import EventBus
from music_analyzer.application.ports.mixxx_library import MixxxLibraryExport
from music_analyzer.application.ports.review import ReviewRepository
from music_analyzer.application.use_cases.active_library import active_exclusion_reason
from music_analyzer.domain.mixxx_library import (
    MixxxExportError, MixxxTrack, mixxx_bpm, mixxx_file_type, mixxx_key, mixxx_key_from_text, track_location)
from music_analyzer.domain.mood_colour import MOOD_QUADRANTS, mood_quadrant
from music_analyzer.domain.mood_evidence import AROUSAL_VALENCE_MODEL, has_provenance_model
from music_analyzer.domain.percentile_rank import percentile_ranks

NO_COLOURS = ''
MOOD_QUADRANT_COLOURS = 'mood-quadrant'
COLOURINGS = (NO_COLOURS, MOOD_QUADRANT_COLOURS)
NO_COLOUR = 'no colour'


@dataclass(frozen=True)
class ExportMixxxLibraryRequest:
    destination: str
    track_ids: tuple[str, ...] = ()
    colours: str = NO_COLOURS


@dataclass(frozen=True)
class MixxxLibraryExportPlan:
    destination: str
    tracks: tuple[MixxxTrack, ...]
    skipped: tuple[tuple[str, str], ...]
    colour_population: int = 0
    colour_counts: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class MixxxLibraryExportPlanned:
    destination: str
    track_count: int
    skipped_count: int


@dataclass(frozen=True)
class MixxxLibraryExported:
    destination: str
    track_count: int
    skipped_count: int


class ExportMixxxLibrary:
    def __init__(self, tracks: ReviewRepository, library_export: MixxxLibraryExport, events: EventBus):
        self._tracks = tracks
        self._library_export = library_export
        self._events = events

    def preview(self, request: ExportMixxxLibraryRequest) -> MixxxLibraryExportPlan:
        plan = self._plan(request)
        self._events.publish(MixxxLibraryExportPlanned(plan.destination, len(plan.tracks), len(plan.skipped)))
        return plan

    def export(self, request: ExportMixxxLibraryRequest) -> MixxxLibraryExportPlan:
        plan = self._plan(request)
        if not plan.tracks:
            raise MixxxExportError('No active analysed track to export: analyse tracks first, or choose others')
        self._library_export.create(plan.destination, plan.tracks)
        self._events.publish(MixxxLibraryExported(plan.destination, len(plan.tracks), len(plan.skipped)))
        return plan

    def _plan(self, request):
        if request.colours not in COLOURINGS:
            raise MixxxExportError(f'Unknown colouring "{request.colours}": the only one is {MOOD_QUADRANT_COLOURS}')
        if self._library_export.occupied(request.destination):
            raise MixxxExportError(f'{request.destination} already exists: the export only creates a new file')
        exported, skipped = [], []
        for track_id in self._chosen_track_ids(request):
            track = self._tracks.read_track(track_id)
            reason = _skip_reason(track)
            if reason:
                skipped.append((track_id, reason))
            else:
                exported.append(track)
        tracks = tuple(_mixxx_track(track) for track in exported)
        plan = MixxxLibraryExportPlan(request.destination, tracks, tuple(skipped))
        return _coloured_by_mood_quadrant(plan, exported) if request.colours == MOOD_QUADRANT_COLOURS else plan

    def _chosen_track_ids(self, request):
        return tuple(dict.fromkeys(request.track_ids or tuple(self._tracks.track_ids())))


def _coloured_by_mood_quadrant(plan, exported):
    moods = {index: mood for index, mood in enumerate(map(_valence_arousal, exported)) if mood}
    valence_levels = percentile_ranks({index: mood[0] for index, mood in moods.items()})
    arousal_levels = percentile_ranks({index: mood[1] for index, mood in moods.items()})
    quadrants = [mood_quadrant(valence_levels[index], arousal_levels[index]) if index in moods else None
                 for index in range(len(exported))]
    tracks = tuple(replace(track, color=quadrant.rgb if quadrant else None)
                   for track, quadrant in zip(plan.tracks, quadrants))
    counts = tuple((quadrant.name, quadrants.count(quadrant)) for quadrant in MOOD_QUADRANTS)
    return replace(plan, tracks=tracks, colour_population=len(moods),
                   colour_counts=counts + ((NO_COLOUR, quadrants.count(None)),))


def _valence_arousal(track):
    overrides = dict(track.overrides)
    if overrides.get('energy') is not None or overrides.get('mood') is not None:
        return None
    stage = next((stage for stage in track.run.stages if stage.stage == 'energy'), None)
    if stage is None or stage.summary is None or not has_provenance_model(stage.provenance, AROUSAL_VALENCE_MODEL):
        return None
    means = dict(zip(stage.summary.labels, stage.summary.mean))
    valence, arousal = means.get('valence'), means.get('arousal')
    return (float(valence), float(arousal)) if _finite(valence) and _finite(arousal) else None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _skip_reason(track: StoredTrack) -> str:
    exclusion = active_exclusion_reason(track.metadata)
    if exclusion:
        return 'Excluded from active library: ' + exclusion
    if not track.locations:
        return 'No available catalogue location'
    if track.run is None:
        return 'Not analysed yet'
    if track.run.status != 'completed':
        return 'Latest analysis run: ' + track.run.status
    return ''


def _mixxx_track(track: StoredTrack) -> MixxxTrack:
    location = track_location(track.locations[0])
    return MixxxTrack(
        location=location,
        filesize=track.size,
        title=_tag(track, 'title'),
        artist=_tag(track, 'artist'),
        album=_tag(track, 'album'),
        duration=float(track.metadata.duration_seconds),
        bpm=_bpm(track),
        key=_key(track),
        file_type=mixxx_file_type(location.filename),
    )


def _bpm(track):
    manual = dict(track.overrides).get('bpm')
    if manual is not None:
        return mixxx_bpm(manual)
    return mixxx_bpm(_detected(track, 'bpm').get('bpm'))


def _key(track):
    manual = dict(track.overrides).get('key')
    if manual is not None:
        return mixxx_key_from_text(manual)
    detected = _detected(track, 'key')
    return mixxx_key(detected.get('key'), detected.get('scale'))


def _detected(track, stage_name):
    for stage in track.run.stages:
        if stage.stage == stage_name:
            return dict(stage.values)
    return {}


def _tag(track, name):
    for key, value in track.metadata.common:
        if str(key).strip().lower() == name:
            values = value if isinstance(value, tuple) else (value,)
            return '; '.join(text for text in (str(v).strip() for v in values) if text)
    return ''
