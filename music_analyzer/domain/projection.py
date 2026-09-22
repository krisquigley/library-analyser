"""Phase3 deterministic anchor-distance projection contract.

This module keeps the visualization baseline pure and stdlib-only. It is not PCA
and its coordinates are never ranking inputs.
"""
from dataclasses import dataclass
from math import isfinite, log, sqrt

from music_analyzer.domain.candidate_selection import CandidateFeatures, FeatureEvidence

PROJECTION_POLICY_VERSION = 'anchor-distance-projection-v1'
NEIGHBOUR_POLICY_VERSION = 'endpoint-local-exact-top-k-neighbours-v2'
DISTANCE_POLICY_VERSION = 'symmetric-feature-distance-v1'


@dataclass(frozen=True)
class ProjectionParameters:
    k: int = 10
    explicit_relayout: bool = False

    def __post_init__(self):
        if not isinstance(self.k, int) or self.k < 0 or self.k > 100:
            raise ValueError('k must be an integer in [0, 100]')


@dataclass(frozen=True)
class ProjectionAnchor:
    low_track_id: str
    high_track_id: str
    low_value: float
    high_value: float
    metadata: tuple[tuple[str, str], ...] = ()
    low_feature: tuple[tuple[str, object], ...] = ()
    high_feature: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class ProjectionTransform:
    policy_version: str
    parameters: ProjectionParameters
    anchors: dict[str, ProjectionAnchor]
    center_x: float
    center_y: float
    range_x: float
    range_y: float
    degenerate_axes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectionPoint:
    track_id: str
    x: float | None
    y: float | None
    layout_state: str
    missing_groups: tuple[str, ...]
    missing_reasons: tuple[str, ...]


@dataclass(frozen=True)
class ProjectionEdge:
    a: str
    b: str
    distance: float
    supported_group_count: int


@dataclass(frozen=True)
class ProjectionResult:
    points: tuple[ProjectionPoint, ...]
    edges: tuple[ProjectionEdge, ...]
    transform: ProjectionTransform


@dataclass(frozen=True)
class FeatureDistance:
    distance: float | None
    group_distances: dict[str, float]
    missing_reasons: tuple[str, ...]

    @property
    def supported_group_count(self):
        return len(self.group_distances)


def fit_projection_transform(tracks, parameters: ProjectionParameters | None = None) -> ProjectionTransform:
    parameters = parameters or ProjectionParameters()
    tracks = tuple(sorted(tracks, key=lambda t: t.track_id))
    anchors = {}
    for group in ('tempo', 'energy', 'mood', 'genre', 'harmony'):
        values = [(track.track_id, scalar) for track in tracks for scalar in [_scalar(track, group)] if scalar is not None]
        if len({value for _, value in values}) >= 2:
            low = min(values, key=lambda item: (item[1], item[0]))
            high = max(values, key=lambda item: (item[1], item[0]))
            anchors[group] = ProjectionAnchor(
                low[0], high[0], low[1], high[1], _metadata(_by_id(tracks, low[0]), group),
                _anchor_feature(_by_id(tracks, low[0]), group), _anchor_feature(_by_id(tracks, high[0]), group)
            )
    raw = [_raw_point(track, tracks, anchors) for track in tracks]
    xs = [x for x, _ in raw if x is not None]
    ys = [y for _, y in raw if y is not None]
    center_x, range_x, dx = _center_range(xs)
    center_y, range_y, dy = _center_range(ys)
    deg = tuple(name for name, flag in (('x', dx), ('y', dy)) if flag)
    return ProjectionTransform(PROJECTION_POLICY_VERSION, parameters, anchors, center_x, center_y, range_x, range_y, deg)


def project_tracks(tracks, transform: ProjectionTransform) -> ProjectionResult:
    tracks = tuple(sorted(tracks, key=lambda t: t.track_id))
    points = []
    for track in tracks:
        raw_x, raw_y = _raw_point_from_transform(track, transform)
        missing = _missing_groups(track, transform)
        if raw_x is None and raw_y is None and not transform.anchors:
            if _has_projection_evidence(track):
                raw_x = transform.center_x
                raw_y = transform.center_y
                missing = ()
            else:
                missing = _missing_projection_evidence(track)
        if raw_x is None and raw_y is None:
            state = 'missing'; x = y = None
        else:
            state = 'partial' if missing else 'projected'
            if raw_x is None:
                x = None
            elif 'x' in transform.degenerate_axes or transform.range_x == 0:
                x = 0.0; state = 'degenerate' if state == 'projected' else state
            else:
                x = _clamp((raw_x - transform.center_x) / transform.range_x, -1, 1)
            if raw_y is None:
                y = None
            elif 'y' in transform.degenerate_axes or transform.range_y == 0:
                y = 0.0; state = 'degenerate' if state == 'projected' else state
            else:
                y = _clamp((raw_y - transform.center_y) / transform.range_y, -1, 1)
        points.append(ProjectionPoint(track.track_id, x, y, state, tuple(g.split(':', 1)[0] for g in missing), tuple(missing)))
    return ProjectionResult(tuple(points), _bounded_edges(tracks, transform.parameters.k), transform)


def symmetric_feature_distance(a: CandidateFeatures, b: CandidateFeatures) -> FeatureDistance:
    groups = {}
    missing = []
    ta = _tempo(a); tb = _tempo(b)
    if ta is not None and tb is not None:
        groups['tempo'] = min(1.0, abs(log(tb / ta)) / log(2))
    else:
        missing.append('tempo: missing usable evidence')
    ea = _summary(a, 'energy'); eb = _summary(b, 'energy')
    if ea and eb and 'arousal' in ea and 'arousal' in eb:
        groups['energy'] = min(1.0, abs(ea['arousal'] - eb['arousal']) / 2.0)
    else:
        missing.append('energy: missing usable evidence')
    for field, label in (('mood', 'mood'), ('genres', 'genre')):
        va = _summary(a, field); vb = _summary(b, field)
        if not va or not vb:
            missing.append(label + ': missing usable evidence')
        elif set(va) != set(vb) or _model(_field(a, field)) != _model(_field(b, field)):
            missing.append(label + ': incompatible label/model alignment')
        else:
            sim = _cosine(va, vb)
            if sim is None:
                missing.append(label + ': zero vector is missing usable evidence')
            else:
                groups[label] = 1.0 - _clamp(sim, 0, 1)
    ka = _key(a); kb = _key(b)
    if ka is not None and kb is not None:
        groups['harmony'] = _harmony_distance(ka, kb)
    else:
        missing.append('harmony: missing usable evidence')
    if not groups:
        return FeatureDistance(None, {}, tuple(_uniq(missing)))
    return FeatureDistance(sum(groups.values()) / len(groups), dict(sorted(groups.items())), tuple(_uniq(missing)))


def _bounded_edges(tracks, k):
    if k <= 0 or not tracks:
        return ()
    # Exact feature-neighbour selection: every unordered pair in the prepared
    # representative set is measured with the canonical symmetric feature
    # distance. Retained storage is bounded to each endpoint's best sparse
    # candidates; no dense distance matrix or unbounded pair array is kept.
    ordered = tuple(sorted(tracks, key=lambda t: t.track_id))
    profiles = tuple(_NeighbourFeatureProfile.from_track(track) for track in ordered)
    selector = _SparseNeighbourSelector(ordered, k)
    for i, a in enumerate(profiles):
        for b in profiles[i + 1:]:
            distance = a.distance_to(b)
            if distance.distance is not None:
                selector.consider(a.track_id, b.track_id, distance.distance, distance.supported_group_count)
    return selector.edges()



@dataclass(frozen=True)
class _NeighbourDistance:
    distance: float | None
    supported_group_count: int


@dataclass(frozen=True)
class _VectorProfile:
    model: str
    labels: tuple[str, ...]
    values: tuple[float, ...]
    norm: float

    @classmethod
    def from_track(cls, track, field):
        values = _summary(track, field)
        if not values:
            return None
        ev = _field(track, field)
        labels = tuple(sorted(values))
        ordered = tuple(values[label] for label in labels)
        norm = sqrt(sum(value * value for value in ordered))
        if norm == 0:
            return None
        return cls(_model(ev), labels, ordered, norm)

    def distance_to(self, other):
        if other is None or self.labels != other.labels or self.model != other.model:
            return None
        dot = sum(a * b for a, b in zip(self.values, other.values))
        return 1.0 - _clamp(dot / (self.norm * other.norm), 0, 1)


@dataclass(frozen=True)
class _NeighbourFeatureProfile:
    track_id: str
    tempo: float | None
    energy: float | None
    mood: _VectorProfile | None
    genre: _VectorProfile | None
    harmony: tuple[int, str] | None

    @classmethod
    def from_track(cls, track):
        energy = _summary(track, 'energy')
        return cls(
            track.track_id,
            _tempo(track),
            (energy.get('arousal') if energy and 'arousal' in energy else None),
            _VectorProfile.from_track(track, 'mood'),
            _VectorProfile.from_track(track, 'genres'),
            _key(track),
        )

    def distance_to(self, other):
        groups = []
        if self.tempo is not None and other.tempo is not None:
            groups.append(min(1.0, abs(log(other.tempo / self.tempo)) / log(2)))
        if self.energy is not None and other.energy is not None:
            groups.append(min(1.0, abs(self.energy - other.energy) / 2.0))
        mood = self.mood.distance_to(other.mood) if self.mood is not None else None
        if mood is not None:
            groups.append(mood)
        genre = self.genre.distance_to(other.genre) if self.genre is not None else None
        if genre is not None:
            groups.append(genre)
        if self.harmony is not None and other.harmony is not None:
            groups.append(_harmony_distance(self.harmony, other.harmony))
        if not groups:
            return _NeighbourDistance(None, 0)
        return _NeighbourDistance(sum(groups) / len(groups), len(groups))


class _SparseNeighbourSelector:
    def __init__(self, tracks, k):
        self._k = k
        self._candidates = {track.track_id: [] for track in tracks}
        self._track_ids = tuple(track.track_id for track in tracks)

    def consider(self, a, b, distance, supported_group_count):
        first = min(a, b)
        second = max(a, b)
        item = (distance, first, second, supported_group_count)
        self._retain(a, item)
        self._retain(b, item)

    def edges(self):
        proposals = sorted(set(item for values in self._candidates.values() for item in values))
        degree = {track_id: 0 for track_id in self._track_ids}
        edges = []
        for distance, a, b, count in proposals:
            if degree[a] < self._k and degree[b] < self._k:
                degree[a] += 1
                degree[b] += 1
                edges.append(ProjectionEdge(a, b, distance, count))
        return tuple(edges)

    def _retain(self, endpoint, item):
        values = self._candidates[endpoint]
        if len(values) < self._k:
            values.append(item)
        else:
            worst_index, worst = max(enumerate(values), key=lambda value: value[1])
            if item < worst:
                values[worst_index] = item
        self._candidates[endpoint] = values


def _raw_point(track, tracks, anchors):
    return _raw_point_from_transform(track, ProjectionTransform(PROJECTION_POLICY_VERSION, ProjectionParameters(), anchors, 0, 0, 1, 1))


def _raw_point_from_transform(track, transform):
    horizontal = []
    vertical = []
    for group, anchor in transform.anchors.items():
        scalar = _scalar(track, group)
        if scalar is None:
            continue
        if group in {'mood', 'genre'}:
            meta = _metadata(track, 'genres' if group == 'genre' else group)
            if meta != anchor.metadata:
                continue
        contribution = _anchor_contribution(track, group, anchor)
        if contribution is None:
            continue
        if group in {'tempo', 'energy', 'harmony'}:
            horizontal.append(contribution)
        else:
            vertical.append(contribution)
    return (_mean(horizontal), _mean(vertical))


def _missing_groups(track, transform):
    missing = []
    for group, anchor in transform.anchors.items():
        scalar = _scalar(track, group)
        if scalar is None:
            missing.append(group + ': missing usable evidence')
        elif group in {'mood', 'genre'}:
            field = 'genres' if group == 'genre' else group
            if _metadata(track, field) != anchor.metadata:
                missing.append(group + ': incompatible label/model alignment')
    return tuple(_uniq(missing))


def _has_projection_evidence(track):
    return any(_scalar(track, group) is not None for group in ('tempo', 'energy', 'mood', 'genre', 'harmony'))


def _missing_projection_evidence(track):
    return tuple(group + ': missing usable evidence' for group in ('tempo', 'energy', 'mood', 'genre', 'harmony') if _scalar(track, group) is None)


def _anchor_contribution(track, group, anchor):
    feature = _anchor_feature(track, group)
    if not feature:
        return None
    feature = dict(feature)
    low = dict(anchor.low_feature)
    high = dict(anchor.high_feature)
    d_low = _feature_distance(group, feature, low)
    d_high = _feature_distance(group, feature, high)
    if d_low is None or d_high is None:
        return None
    return d_low - d_high


def _anchor_feature(track, group):
    if group == 'tempo':
        value = _scalar(track, group)
        return (('value', value),) if value is not None else ()
    if group == 'energy':
        value = _scalar(track, group)
        return (('value', value),) if value is not None else ()
    if group == 'harmony':
        key = _key(track)
        return (('pitch', key[0]), ('scale', key[1])) if key else ()
    if group == 'mood':
        values = _summary(track, 'mood')
        return tuple(sorted(values.items())) if values else ()
    if group == 'genre':
        values = _summary(track, 'genres')
        return tuple(sorted(values.items())) if values else ()
    return ()


def _feature_distance(group, a, b):
    if group in {'tempo', 'energy'}:
        if 'value' not in a or 'value' not in b:
            return None
        if group == 'tempo':
            return min(1.0, abs(a['value'] - b['value']) / log(2))
        return min(1.0, abs(a['value'] - b['value']) / 2.0)
    if group in {'mood', 'genre'}:
        if set(a) != set(b):
            return None
        sim = _cosine(a, b)
        return None if sim is None else 1.0 - _clamp(sim, 0, 1)
    if group == 'harmony':
        if 'pitch' not in a or 'scale' not in a or 'pitch' not in b or 'scale' not in b:
            return None
        return _harmony_distance((a['pitch'], a['scale']), (b['pitch'], b['scale']))
    return None


def _scalar(track, group):
    if group == 'tempo':
        bpm = _tempo(track)
        return log(bpm) if bpm else None
    if group == 'energy':
        values = _summary(track, 'energy')
        return values.get('arousal') if values and 'arousal' in values else None
    if group == 'mood':
        values = _summary(track, 'mood')
        return values[sorted(values)[0]] if values else None
    if group == 'genre':
        values = _summary(track, 'genres')
        if values and any(v != 0 for v in values.values()):
            return values[sorted(values)[0]]
        return None
    if group == 'harmony':
        key = _key(track)
        return float(key[0]) if key else None
    return None


def _tempo(track):
    ev = _field(track, 'bpm')
    if ev.manual_text is not None or ev.effective_source == 'manual_text':
        return None
    for k, v in ev.values:
        if k == 'bpm' and isinstance(v, (int, float)) and isfinite(v) and v > 0:
            return float(v)
    return None


def _summary(track, field):
    ev = _field(track, field)
    if ev.manual_text is not None or ev.effective_source == 'manual_text':
        return None
    out = {k: float(v) for k, v in ev.summary_values if isinstance(v, (int, float)) and isfinite(v)}
    return out or None


def _key(track):
    ev = _field(track, 'key')
    if ev.uncertainty and 'ambiguous' in ev.uncertainty.lower():
        return None
    values = dict(ev.values)
    key = values.get('key'); scale = values.get('scale')
    pcs = {'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3, 'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8, 'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11}
    if key in pcs and scale in {'major', 'minor'}:
        return pcs[key], scale
    return None


def _harmony_distance(a, b):
    if a == b:
        return 0.0
    if (a[1] == 'minor' and b[1] == 'major' and (a[0] + 3) % 12 == b[0]) or (a[1] == 'major' and b[1] == 'minor' and (a[0] - 3) % 12 == b[0]):
        return 0.25
    if a[0] == b[0]:
        return 0.5
    diff = abs(a[0] - b[0]) % 12
    fifth_steps = min(diff, 12 - diff)
    return min(1.0, fifth_steps / 6.0)


def _field(track, field):
    return track.fields.get(field, FeatureEvidence())


def _metadata(track, field):
    ev = _field(track, field)
    labels = tuple(k for k, _ in ev.summary_values)
    return (('model', _model(ev)), ('labels', ','.join(labels)))


def _model(ev):
    for k, v in ev.provenance:
        if k == 'model':
            return str(v)
    return ''


def _by_id(tracks, track_id):
    for track in tracks:
        if track.track_id == track_id:
            return track
    raise KeyError(track_id)


def _center_range(values):
    if not values:
        return 0.0, 0.0, True
    ordered = sorted(values)
    mid = len(ordered) // 2
    center = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    rng = max(abs(v - center) for v in values)
    return center, rng, rng == 0


def _mean(values):
    return sum(values) / len(values) if values else None


def _cosine(a, b):
    dot = sum(a[k] * b[k] for k in a)
    na = sqrt(sum(v * v for v in a.values())); nb = sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return None
    return dot / (na * nb)


def _clamp(value, low, high):
    return max(low, min(high, value))


def _uniq(items):
    out = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
