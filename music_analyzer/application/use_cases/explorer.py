from math import isfinite

from music_analyzer.application.dto.explorer import (
    AutomaticEvidence,
    AxisValue,
    ExplorerFieldEvidence,
    ExplorerMetadata,
    ExplorerSnapshot,
    ExplorerTrackDetail,
    MoodAxisEdge,
    MoodAxisGraph,
    MoodAxisNode,
    UnpositionedTrack,
)
from music_analyzer.application.ports.explorer import ExplorerRepository
from music_analyzer.application.use_cases.candidates import _features
from music_analyzer.domain.projection import DISTANCE_POLICY_VERSION, NEIGHBOUR_POLICY_VERSION, _bounded_edges, symmetric_feature_distance
from music_analyzer.domain.review import FIELDS


class ListExplorerTracks:
    def __init__(self, repository: ExplorerRepository):
        self.repository = repository

    def execute(self, limit=100, after=None):
        if limit == 'all':
            metadata, tracks = self.repository.candidate_snapshot()
            return ExplorerSnapshot(self._metadata(metadata, len(tracks)), tuple(_map_track(track) for track in tracks))
        if not isinstance(limit, int) or limit < 1 or limit > 500:
            raise ValueError('Explorer list limit must be between 1 and 500 or all')
        metadata, track_count, tracks = self.repository.list_tracks(limit, after)
        return ExplorerSnapshot(self._metadata(metadata, track_count), tuple(_map_track(track) for track in tracks))

    def _metadata(self, raw, track_count):
        return ExplorerMetadata(
            application_id=int(raw.get('application_id', 0)),
            schema_version=int(raw.get('schema_version', 0)),
            read_policy=str(raw.get('read_policy', 'bounded_read_transaction')),
            track_count=track_count,
        )


class GetExplorerTrackDetail:
    def __init__(self, repository: ExplorerRepository):
        self.repository = repository

    def execute(self, handle):
        if handle not in self.repository.track_ids():
            raise ValueError('Unknown explorer track')
        return _map_track(self.repository.read_track(handle))


class ExploreCatalogue:
    def __init__(self, repository: ExplorerRepository):
        self.repository = repository

    def list_tracks(self):
        return ListExplorerTracks(self.repository).execute(limit='all')

    def track_detail(self, handle):
        return GetExplorerTrackDetail(self.repository).execute(handle)


class BuildMoodAxisGraph:
    def __init__(self, repository: ExplorerRepository, sparse_k: int = 10):
        self.repository = repository
        self.sparse_k = sparse_k

    def execute(self, mood: str | None = None):
        raw_meta, records = self.repository.candidate_snapshot()
        records = tuple(records)
        available = _available_moods(records)
        selected = _resolve_mood(mood, available)
        positioned = []
        unpositioned = []
        for record in records:
            detail = _map_track(record)
            node, reasons = _axis_node(record, detail, selected)
            if node is None:
                unpositioned.append(UnpositionedTrack(record.track_id, record.display_label, tuple(reasons)))
            else:
                positioned.append(node)
        edges = _axis_edges(records, {node.track_id for node in positioned}, self.sparse_k)
        return MoodAxisGraph(
            metadata={
                'application_id': int(raw_meta.get('application_id', 0)),
                'schema_version': int(raw_meta.get('schema_version', 0)),
                'read_policy': str(raw_meta.get('read_policy', 'coherent_in_memory_snapshot')),
                'track_count': len(records),
                'coordinate_policy': 'fixed-mood-axis-v1',
                'normalization_policy': 'documented-model-scale-linear-v1',
                'energy_scale': 'Emomusic native valence/arousal regression coordinates retained when model provenance is compatible; no arbitrary clipping or DJ-energy interpretation',
                'mood_scale': 'Jamendo mood/theme sigmoid labelled mean score, display normalized from [0,1] to [-1,1] when finite and in range',
                'genre_filter_policy': 'ANY selected genre with retained mean score >= finite threshold from stage provenance or 0.5 default',
                'edge_policy': NEIGHBOUR_POLICY_VERSION,
                'distance_policy': DISTANCE_POLICY_VERSION,
                'sparse_k': self.sparse_k,
            },
            selected_mood=selected,
            available_moods=available,
            positioned=tuple(positioned),
            unpositioned=tuple(unpositioned),
            edges=edges,
        )


class FilterMoodAxisGraph:
    def execute(self, graph: MoodAxisGraph, bpm_min=None, bpm_max=None, genres=()):
        selected_genres = tuple(g for g in (genres or ()) if g)
        nodes = tuple(node for node in graph.positioned if _passes_filters(node, bpm_min, bpm_max, selected_genres))
        ids = {node.track_id for node in nodes}
        edges = tuple(edge for edge in graph.edges if edge.a in ids and edge.b in ids)
        return MoodAxisGraph(graph.metadata, graph.selected_mood, graph.available_moods, nodes, graph.unpositioned, edges)


def _map_track(track):
    stages = {stage.stage: stage for stage in track.run.stages} if track.run else {}
    manual = dict(track.overrides)
    reasons = []
    if not track.available_locations:
        reasons.append('No available catalogue location')
    if not track.run:
        reasons.append('No identity-linked analysis; legacy/path-only runs are not attributed')
    elif track.run.status != 'completed':
        reasons.append('Latest run: ' + track.run.status)
    fields = {}
    for field in FIELDS:
        stage = stages.get(field)
        missing_reason = ''
        automatic = AutomaticEvidence()
        if stage is None:
            missing_reason = field + ': missing result'
            reasons.append(missing_reason)
        else:
            summary_values = ()
            coverage = None
            if stage.summary is not None:
                summary_values = tuple(zip(stage.summary.labels, stage.summary.mean))
                coverage = stage.summary.coverage
            automatic = AutomaticEvidence(stage.values, summary_values, coverage, stage.provenance, stage.uncertainty)
            if stage.uncertainty:
                reasons.append(field + ': ' + stage.uncertainty)
            if stage.summary and stage.summary.provisional:
                reasons.append(field + ': provisional, uncalibrated scores')
        manual_text = manual.get(field)
        if manual_text is not None:
            effective = 'manual_text'
            typed_status = 'unresolved'
        elif automatic.values or automatic.summary_values:
            effective = 'automatic'
            typed_status = 'absent'
        else:
            effective = 'missing'
            typed_status = 'absent'
        fields[field] = ExplorerFieldEvidence(field, automatic, manual_text, effective, typed_status, missing_reason)
    return ExplorerTrackDetail(
        handle=track.track_id,
        track_id=track.track_id,
        sha256=track.sha256,
        size=track.size,
        display_label=track.display_label,
        available_locations=track.available_locations,
        latest_run_id=track.run.run_id if track.run else None,
        latest_run_status=track.run.status if track.run else None,
        latest_run_detail='',
        fields=fields,
        reasons=tuple(reasons),
    )


def _available_moods(records):
    labels = []
    for record in records:
        if dict(record.overrides).get('mood') is not None:
            continue
        stage = _stage(record, 'mood')
        if stage and stage.summary:
            for label, value in zip(stage.summary.labels, stage.summary.mean):
                if _finite_number(value) and label not in labels:
                    labels.append(label)
    return tuple(sorted(labels))


def _resolve_mood(requested, available):
    if not available:
        if requested is None or requested == '':
            return ''
        raise ValueError('Unsupported mood label ' + str(requested) + '; available: none')
    if requested is None or requested == '':
        return available[0]
    folded = str(requested).strip().lower().replace('_', ' ').replace('-', ' ')
    aliases = {label.lower().replace('_', ' ').replace('-', ' '): label for label in available}
    if folded not in aliases:
        raise ValueError('Unsupported mood label ' + str(requested) + '; available: ' + ', '.join(available))
    return aliases[folded]


def _axis_node(record, detail, selected_mood):
    reasons = []
    energy = _summary_map(record, 'energy', reasons)
    mood = _summary_map(record, 'mood', reasons)
    if dict(record.overrides).get('energy') is not None:
        reasons.append('energy: unresolved manual text override')
    if dict(record.overrides).get('mood') is not None:
        reasons.append('mood: unresolved manual text override')
    energy_stage = _stage(record, 'energy')
    mood_stage = _stage(record, 'mood')
    if selected_mood == '':
        reasons.append('mood: no supported labels available')
    if energy_stage is None or not _has_provenance_model(energy_stage.provenance, 'emomusic-msd-musicnn-2'):
        reasons.append('energy: incompatible model/scale for fixed valence/arousal axis')
    if mood_stage is not None and not _has_provenance_model(mood_stage.provenance, 'mtg_jamendo_moodtheme-discogs-effnet-1'):
        reasons.append('mood: incompatible model/scale for fixed mood axis')
    valence = energy.get('valence') if energy else None
    arousal = energy.get('arousal') if energy else None
    z = mood.get(selected_mood) if mood and selected_mood else None
    if not _finite_number(valence): reasons.append('energy: missing valence')
    if not _finite_number(arousal): reasons.append('energy: missing arousal')
    if mood is not None and not any(value != 0 for value in mood.values()): reasons.append('mood: zero vector is missing usable evidence')
    if selected_mood and not _finite_number(z): reasons.append('mood: missing selected label ' + selected_mood)
    if _finite_number(z) and not _score01(float(z)):
        reasons.append('mood: selected label ' + selected_mood + ' outside supported [0,1] score scale')
    if reasons:
        return None, _uniq(reasons)
    energy_prov = energy_stage.provenance
    mood_prov = mood_stage.provenance
    return MoodAxisNode(
        record.track_id,
        record.display_label,
        AxisValue('valence', float(valence), float(valence), 'native-emomusic-valence-regression', energy_prov),
        AxisValue('arousal', float(arousal), float(arousal), 'native-emomusic-arousal-regression', energy_prov),
        AxisValue(selected_mood, float(z), _norm01(float(z)), 'sigmoid-score-[0,1]->[-1,1]', mood_prov),
        _bpm(record),
        tuple(sorted((_summary_map(record, 'genres', []) or {}).items())),
        detail.reasons,
        _genre_threshold(record),
    ), ()


def _axis_edges(records, positioned_ids, k):
    features_by_id = {feature.track_id: feature for feature in (_features(record) for record in records if record.track_id in positioned_ids)}
    selected_records = tuple(_features(record) for record in records if record.track_id in positioned_ids)
    edges = []
    for edge in _bounded_edges(selected_records, k):
        a = features_by_id[edge.a]
        b = features_by_id[edge.b]
        distance = symmetric_feature_distance(a, b)
        groups = tuple(distance.group_distances) if distance.distance is not None else ()
        edges.append(MoodAxisEdge(edge.a, edge.b, round(1.0 - edge.distance, 6), 'axis-independent relatedness from existing stored summaries; groups=' + ','.join(groups), {'policy': DISTANCE_POLICY_VERSION, 'neighbour_policy': NEIGHBOUR_POLICY_VERSION}, edge.supported_group_count))
    return tuple(edges)


def _passes_filters(node, bpm_min, bpm_max, genres):
    if bpm_min is not None and (node.bpm is None or node.bpm < float(bpm_min)):
        return False
    if bpm_max is not None and (node.bpm is None or node.bpm > float(bpm_max)):
        return False
    if genres:
        scores = dict(node.genres)
        return any(scores.get(genre, -1.0) >= node.genre_threshold for genre in genres)
    return True


def _stage(record, field):
    if not record.run:
        return None
    for stage in record.run.stages:
        if stage.stage == field:
            return stage
    return None


def _summary_map(record, field, reasons):
    if dict(record.overrides).get(field) is not None:
        return None
    stage = _stage(record, field)
    if stage is None or stage.summary is None:
        return None
    values = {}
    for label, value in zip(stage.summary.labels, stage.summary.mean):
        if _finite_number(value):
            values[str(label)] = float(value)
    return values or None


def _bpm(record):
    if dict(record.overrides).get('bpm') is not None:
        return None
    stage = _stage(record, 'bpm')
    if stage is None:
        return None
    for key, value in stage.values:
        if key == 'bpm' and _finite_number(value) and float(value) > 0:
            return float(value)
    return None


def _finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value)


def _norm01(value):
    return round(value * 2.0 - 1.0, 12)


def _score01(value):
    return isfinite(value) and 0.0 <= value <= 1.0


def _has_provenance_model(provenance, model_id):
    return any(key == model_id for key, _value in provenance)


def _genre_threshold(record):
    stage = _stage(record, 'genres')
    if stage is None:
        return 0.5
    for key, value in stage.provenance:
        if key == 'threshold':
            try:
                threshold = float(value)
            except (TypeError, ValueError):
                return 0.5
            return threshold if _score01(threshold) else 0.5
    return 0.5


def _uniq(items):
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return tuple(out)
