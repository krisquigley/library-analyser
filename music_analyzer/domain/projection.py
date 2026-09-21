"""Phase3 deterministic anchor-distance projection contract.

This module keeps the visualization baseline pure and stdlib-only. It is not PCA
and its coordinates are never ranking inputs.
"""
from dataclasses import dataclass
from math import isfinite, log, sqrt

from music_analyzer.domain.candidate_selection import CandidateFeatures, FeatureEvidence

PROJECTION_POLICY_VERSION = 'anchor-distance-projection-v1'
NEIGHBOUR_POLICY_VERSION = 'bounded-symmetric-neighbours-v1'
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
            anchors[group] = ProjectionAnchor(low[0], high[0], low[1], high[1], _metadata(_by_id(tracks, low[0]), group))
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
    # Bound preparation work: compare each track only with a deterministic window
    # in cheap scalar order. Stored distances remain true symmetric feature
    # distances for accepted edges; no dense pair matrix/list is retained.
    window = max(k * 20, 20)
    ordered = sorted(tracks, key=lambda t: (_ordering_scalar(t), t.track_id))
    pairs = []
    seen = set()
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:i + 1 + window]:
            key = (a.track_id, b.track_id) if a.track_id < b.track_id else (b.track_id, a.track_id)
            if key in seen:
                continue
            seen.add(key)
            d = symmetric_feature_distance(a, b)
            if d.distance is not None:
                pairs.append((d.distance, key[0], key[1], d.supported_group_count))
    degree = {t.track_id: 0 for t in tracks}
    edges = []
    for distance, a, b, count in sorted(pairs):
        if degree[a] < k and degree[b] < k:
            degree[a] += 1; degree[b] += 1
            edges.append(ProjectionEdge(a, b, distance, count))
    return tuple(edges)


def _ordering_scalar(track):
    for group in ('tempo', 'energy', 'genre', 'mood', 'harmony'):
        value = _scalar(track, group)
        if value is not None:
            return value
    return 0.0


def _raw_point(track, tracks, anchors):
    return _raw_point_from_transform(track, ProjectionTransform(PROJECTION_POLICY_VERSION, ProjectionParameters(), anchors, 0, 0, 1, 1))


def _raw_point_from_transform(track, transform):
    horizontal = []
    vertical = []
    for group, anchor in transform.anchors.items():
        scalar = _scalar(track, group)
        if scalar is None:
            continue
        denom = anchor.high_value - anchor.low_value
        if denom == 0:
            continue
        contribution = ((scalar - anchor.low_value) / denom) * 2 - 1
        if group in {'tempo', 'energy', 'harmony'}:
            horizontal.append(contribution)
        else:
            meta = _metadata(track, 'genres' if group == 'genre' else group)
            if group in {'mood', 'genre'} and meta != anchor.metadata:
                continue
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
