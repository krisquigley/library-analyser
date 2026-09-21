"""Pure Phase2 candidate-selection policies for the track journey explorer."""
from dataclasses import dataclass
from math import isfinite, log, sqrt
from typing import Mapping

SELECTION_POLICY_VERSION = 'candidate-selection-v1'
DISTANCE_POLICY_VERSION = 'summary-distance-v1'
RANKING_POLICY_VERSION = 'additive-ranking-v1'
HARMONIC_POLICY_VERSION = 'conservative-key-v1'


@dataclass(frozen=True)
class FeatureEvidence:
    values: tuple[tuple[str, str | float], ...] = ()
    summary_values: tuple[tuple[str, float], ...] = ()
    manual_text: str | None = None
    effective_source: str = 'missing'
    provenance: tuple[tuple[str, str], ...] = ()
    uncertainty: str = ''


@dataclass(frozen=True)
class CandidateFeatures:
    track_id: str
    fields: Mapping[str, FeatureEvidence]
    projection: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class SelectionControl:
    name: str
    mode: str = 'off'
    weight: float = 0.0
    parameters: Mapping[str, object] | None = None
    within: str = 'any'

    def __post_init__(self):
        if self.mode not in {'off', 'soft', 'hard'}:
            raise ValueError('control mode must be off, soft, or hard')
        if not isinstance(self.weight, (int, float)) or not isfinite(self.weight) or self.weight < 0 or self.weight > 10:
            raise ValueError('control weight must be finite in [0, 10]')
        if self.within not in {'any', 'all'}:
            raise ValueError('within semantics must be any or all')
        object.__setattr__(self, 'weight', float(self.weight))
        object.__setattr__(self, 'parameters', dict(self.parameters or {}))


@dataclass(frozen=True)
class SelectionRequest:
    controls: tuple[SelectionControl, ...] = ()
    limit: int = 50
    exclude_track_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Contribution:
    control: str
    weight: float
    supported: bool
    value: float | None
    formula_label: str
    direction_or_relation: str
    distance: float | None
    reason: str = ''


@dataclass(frozen=True)
class CandidateExplanation:
    satisfied_rules: tuple[str, ...] = ()
    failed_rules: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    contributions: tuple[Contribution, ...] = ()
    raw_values: tuple[tuple[str, tuple[tuple[str, str | float], ...]], ...] = ()
    manual_values: tuple[tuple[str, str], ...] = ()
    provenance: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    uncertainty: tuple[tuple[str, str], ...] = ()
    relation_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateRank:
    track_id: str
    tier: str
    score: float | None
    supported_weight_mass: float
    missing_weight_mass: float
    requested_weight_mass: float
    explanation: CandidateExplanation


@dataclass(frozen=True)
class SelectionResult:
    policy_versions: Mapping[str, str]
    candidates: tuple[CandidateRank, ...]
    excluded_summary: Mapping[str, int]
    no_match_suggestions: tuple[str, ...]


def rank_candidates(current: CandidateFeatures, candidates: list[CandidateFeatures] | tuple[CandidateFeatures, ...], request: SelectionRequest) -> SelectionResult:
    controls = tuple(c for c in request.controls if c.mode != 'off')
    ranked = []
    excluded: dict[str, int] = {}
    for candidate in candidates:
        if candidate.track_id in request.exclude_track_ids or candidate.track_id == current.track_id:
            excluded['explicitly_excluded'] = excluded.get('explicitly_excluded', 0) + 1
            continue
        failed: list[str] = []
        missing: list[str] = []
        satisfied: list[str] = []
        contribs: list[Contribution] = []
        relations: list[str] = []
        requested_weight = sum(c.weight for c in controls if c.mode == 'soft')
        for control in controls:
            evaluations = _evaluate_control(control, current, candidate)
            hard_ok = all(e[0] for e in evaluations)
            if control.mode == 'hard':
                for ok, contribution, miss, relation in evaluations:
                    if miss:
                        missing.append(miss)
                    if relation:
                        relations.append(relation)
                if hard_ok:
                    satisfied.append(control.name + ': hard passed')
                else:
                    failed.append(control.name + ': hard failed')
                    excluded[control.name + '_hard_failed'] = excluded.get(control.name + '_hard_failed', 0) + 1
            elif control.weight > 0:
                for ok, contribution, miss, relation in evaluations:
                    if miss:
                        missing.append(miss)
                    if contribution is not None:
                        contribs.append(contribution)
                    if relation:
                        relations.append(relation)
            else:
                satisfied.append(control.name + ': zero-weight soft ignored for score')
        if failed:
            continue
        supported_weight = sum(c.weight for c in contribs if c.supported and c.value is not None)
        missing_weight = max(0.0, requested_weight - supported_weight)
        if supported_weight > 0:
            score = sum(c.weight * (c.value or 0.0) for c in contribs if c.supported and c.value is not None) / supported_weight
            tier = 'eligible_scored'
        else:
            score = None
            tier = 'eligible_insufficient_evidence' if requested_weight > 0 else 'eligible_unscored'
        explanation = CandidateExplanation(tuple(satisfied), tuple(failed), _uniq(missing), tuple(contribs), _raw(candidate), _manual(candidate), _prov(candidate), _unc(candidate), tuple(relations))
        ranked.append(CandidateRank(candidate.track_id, tier, score, supported_weight, missing_weight, requested_weight, explanation))
    ranked.sort(key=lambda r: (0 if r.tier == 'eligible_scored' else 1, -(r.score or 0.0), -r.supported_weight_mass, r.track_id))
    limited = tuple(ranked[:request.limit])
    suggestions = () if limited else ('No automatic relaxation was applied; explicitly widen a hard control or make it soft to change results.',)
    return SelectionResult(_versions(), limited, dict(sorted(excluded.items())), suggestions)


def _versions():
    return {'selection_policy_version': SELECTION_POLICY_VERSION, 'distance_policy_version': DISTANCE_POLICY_VERSION, 'ranking_policy_version': RANKING_POLICY_VERSION, 'harmonic_policy_version': HARMONIC_POLICY_VERSION}


def _evaluate_control(control, current, candidate):
    name = control.name
    if name == 'tempo':
        return [_tempo(control, current, candidate)]
    if name == 'energy':
        return [_energy(control, current, candidate)]
    if name == 'mood':
        return _labels(control, candidate, 'mood')
    if name == 'genre':
        return _genre(control, current, candidate)
    if name == 'harmony':
        return [_harmony(control, current, candidate)]
    return [(True, None, '', '')]


def _field(track, field):
    return track.fields.get(field, FeatureEvidence())


def _manual_missing(field, ev, subject):
    if ev.manual_text is not None or ev.effective_source == 'manual_text':
        return f'{field}: {subject} {field} has unresolved manual text'
    return f'{field}: {subject} {field} missing usable evidence'


def _value(ev, key):
    if ev.manual_text is not None or ev.effective_source == 'manual_text':
        return None
    for k, v in ev.values:
        if k == key and isinstance(v, (int, float)) and isfinite(v):
            return float(v)
    return None


def _string(ev, key):
    if ev.manual_text is not None or ev.effective_source == 'manual_text':
        return None
    for k, v in ev.values:
        if k == key and isinstance(v, str) and v and '/' not in v:
            return v
    return None


def _summary(ev):
    if ev.manual_text is not None or ev.effective_source == 'manual_text':
        return None
    out = {}
    for k, v in ev.summary_values:
        if isinstance(v, (int, float)) and isfinite(v):
            out[k] = float(v)
    return out if out else None


def _clamp01(x):
    if x < 0:
        return 0.0
    if x > 1:
        return 1.0
    return x


def _tempo(control, current, candidate):
    cur = _value(_field(current, 'bpm'), 'bpm')
    cand_ev = _field(candidate, 'bpm')
    cand = _value(cand_ev, 'bpm')
    if cur is None or cur <= 0:
        return (False, None, _manual_missing('bpm', _field(current, 'bpm'), 'current').replace('bpm:', 'tempo:'), '')
    if cand is None or cand <= 0:
        return (False, None, _manual_missing('bpm', cand_ev, 'candidate').replace('bpm:', 'tempo:'), '')
    tol = float(control.parameters.get('tolerance', 0.06))
    multipliers = (0.5, 1.0, 2.0) if control.parameters.get('allow_octaves') else (1.0,)
    pairs = [(abs(log((cand * m) / cur)), m) for m in multipliers]
    distance, mult = min(pairs, key=lambda x: (x[0], x[1]))
    threshold = log(1 + tol)
    contribution = 1.0 - _clamp01(distance / threshold) if threshold > 0 else 0.0
    relation = f'tempo:{mult}x' if mult != 1.0 else 'tempo:1.0x'
    ok = distance <= threshold
    return (ok, Contribution('tempo', control.weight, True, contribution, 'log-symmetric-tempo-v1', relation, distance), '', relation)


def _energy(control, current, candidate):
    cur_s = _summary(_field(current, 'energy'))
    cand_ev = _field(candidate, 'energy')
    cand_s = _summary(cand_ev)
    if not cur_s or 'arousal' not in cur_s:
        return (False, None, _manual_missing('energy', _field(current, 'energy'), 'current'), '')
    if not cand_s or 'arousal' not in cand_s:
        return (False, None, _manual_missing('energy', cand_ev, 'candidate'), '')
    cur = cur_s['arousal']; cand = cand_s['arousal']
    mode = str(control.parameters.get('energy_mode', 'hold'))
    if mode == 'rise':
        delta = cand - cur; value = _clamp01(delta / float(control.parameters.get('delta_target', 1.0))); ok = cand > cur
    elif mode == 'fall':
        delta = cur - cand; value = _clamp01(delta / float(control.parameters.get('delta_target', 1.0))); ok = cand < cur
    elif mode == 'target_band':
        low = float(control.parameters.get('low', cur - 1.0)); high = float(control.parameters.get('high', cur + 1.0)); outside = max(low - cand, cand - high, 0.0); tol = float(control.parameters.get('band_tolerance', 1.0)); value = 1 - _clamp01(outside / tol); ok = low <= cand <= high
    else:
        tol = float(control.parameters.get('hold_tolerance', 1.0)); dist = abs(cand - cur); value = 1 - _clamp01(dist / tol); ok = dist <= tol
    return (ok, Contribution('energy', control.weight, True, value, 'raw-arousal-relative-v1', mode, abs(cand - cur)), '', 'energy:' + mode)


def _labels(control, candidate, field, control_label=None):
    control_label = control_label or field
    labels = _summary(_field(candidate, field))
    if labels is None:
        return [(False, None, _manual_missing(control_label, _field(candidate, field), 'candidate'), '')]
    params = control.parameters
    threshold = float(params.get('threshold', 0.5))
    out = []
    include = tuple(params.get('include', ()))
    exclude = tuple(params.get('exclude', ()))
    if include:
        present = [labels.get(x) for x in include]
        known = [x for x in present if x is not None]
        if control.within == 'all':
            ok = len(known) == len(include) and all(x >= threshold for x in known)
        else:
            ok = any(x >= threshold for x in known)
        value = sum(known) / len(known) if known else None
        miss = '' if (known and (control.within == 'any' or len(known) == len(include))) else f'{control_label}: candidate missing selected labels'
        out.append((ok, Contribution(control_label + '_include', control.weight, value is not None, _clamp01(value) if value is not None else None, 'label-mean-include-v1', control.within, None, miss), miss, ''))
    if exclude:
        known = [labels.get(x) for x in exclude if labels.get(x) is not None]
        # Exclusion means no known excluded label may meet the visible threshold. Missing excluded labels are not failures.
        ok = not any(x >= threshold for x in known)
        value = 1 - max(known) if known else None
        miss = '' if len(known) == len(exclude) else f'{control_label}: candidate missing selected labels'
        out.append((ok, Contribution(control_label + '_exclude', control.weight, value is not None, _clamp01(value) if value is not None else None, 'one-minus-max-exclude-v1', control.within, None, miss), miss, ''))
    return out or [(True, None, '', '')]


def _genre(control, current, candidate):
    mode = str(control.parameters.get('genre_mode', 'stay_near'))
    if mode == 'move_toward_labels' or control.parameters.get('include'):
        return _labels(control, candidate, 'genres', 'genre')
    cur = _summary(_field(current, 'genres'))
    cand_ev = _field(candidate, 'genres')
    cand = _summary(cand_ev)
    if not cur or not cand:
        return [(False, None, _manual_missing('genre', cand_ev, 'candidate'), '')]
    if set(cur) != set(cand) or _model(_field(current, 'genres')) != _model(cand_ev):
        return [(False, None, 'genre: incompatible label/model alignment', '')]
    sim = _cosine(cur, cand)
    if sim is None:
        return [(False, None, 'genre: zero vector is missing usable evidence', '')]
    dist = 1 - _clamp01(sim)
    if mode == 'prefer_novelty':
        mn = float(control.parameters.get('novelty_min_distance', 0.20)); target = float(control.parameters.get('novelty_target_distance', 0.60)); value = _clamp01((dist - mn) / (target - mn)); ok = dist >= mn
    else:
        near = float(control.parameters.get('near_distance', 0.35)); value = 1 - _clamp01(dist / near); ok = dist <= near
    return [(ok, Contribution('genre', control.weight, True, value, 'cosine-genre-distance-v1', mode, dist), '', 'genre:' + mode)]


def _model(ev):
    for k, v in ev.values:
        if k == 'model':
            return v
    return ''


def _cosine(a, b):
    dot = sum(a[k] * b[k] for k in a)
    na = sqrt(sum(v * v for v in a.values())); nb = sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return None
    return dot / (na * nb)


def _harmony(control, current, candidate):
    ck = _parse_key(_field(current, 'key'))
    dk = _parse_key(_field(candidate, 'key'))
    if ck is None:
        return (False, None, _manual_missing('harmony', _field(current, 'key'), 'current'), '')
    if dk is None:
        return (False, None, _manual_missing('harmony', _field(candidate, 'key'), 'candidate'), '')
    relation = _relation(ck, dk)
    allowed = set(control.parameters.get('relations', ('same_key', 'relative_major_minor')))
    ok = relation in allowed
    value = 1.0 if ok else 0.0
    label = 'harmony:' + (relation or 'unsupported')
    return (ok, Contribution('harmony', control.weight, True, value, 'conservative-key-v1', relation or 'unsupported', None), '', label)


def _parse_key(ev):
    if ev.uncertainty and 'ambiguous' in ev.uncertainty.lower():
        return None
    key = _string(ev, 'key'); scale = _string(ev, 'scale')
    if key is None or scale is None:
        return None
    pcs = {'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3, 'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8, 'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11}
    scale = scale.lower()
    if key not in pcs or scale not in {'major', 'minor'}:
        return None
    return pcs[key], scale


def _relation(a, b):
    if a == b:
        return 'same_key'
    if a[1] == 'minor' and b[1] == 'major' and (a[0] + 3) % 12 == b[0]:
        return 'relative_major_minor'
    if a[1] == 'major' and b[1] == 'minor' and (a[0] - 3) % 12 == b[0]:
        return 'relative_major_minor'
    return ''


def _raw(candidate):
    return tuple((k, tuple(v.values) + tuple(v.summary_values)) for k, v in sorted(candidate.fields.items()) if hasattr(v, 'values') and (v.values or v.summary_values))


def _manual(candidate):
    return tuple((k, v.manual_text) for k, v in sorted(candidate.fields.items()) if hasattr(v, 'manual_text') and v.manual_text is not None)


def _prov(candidate):
    return tuple((k, v.provenance) for k, v in sorted(candidate.fields.items()) if hasattr(v, 'provenance') and v.provenance)


def _unc(candidate):
    return tuple((k, v.uncertainty) for k, v in sorted(candidate.fields.items()) if hasattr(v, 'uncertainty') and v.uncertainty)


def _uniq(items):
    seen = []
    for item in items:
        if item and item not in seen:
            seen.append(item)
    return tuple(seen)
