"""Chained energy arc pilot (#137): how closely playlists follow their arcs, in aggregate only.

Runs the playlist preview from a seeded sample of eligible start tracks and
reports, for each arc, the mean distance between the target and the energy level
actually placed, with the mean relation score of the transitions and the run
timings. It can repeat the runs at other arc weights to re-check the weight; that
override is for measurement only and is put back afterwards. Nothing it prints
names a track, a title or a path, and it opens the database read-only.

    python -m tools.playlist_arc_pilot --database DB --chain rise:10,fall:10,peak:10 \
        --bpm-min 100 --bpm-max 140 --starts 30 --weights 0.6,0.8
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import random
from statistics import fmean
import time

from music_explorer.application.dto.playlists import EnergyArcRequest, PlaylistRecipe
from music_explorer.application.use_cases.preview_playlist.preview_playlist import GRAPH_SPARSE_K, PreviewPlaylist
from music_explorer.domain import energy_plan
from music_explorer.domain.playlist_eligibility import BpmRange, eligible
from tools.graph_read_benchmark import nearest_rank

UNITS = ('tracks', 'minutes')


def parse_chain(text: str, unit: str) -> tuple[EnergyArcRequest, ...]:
    """`shape:length,...` in order, every length in `unit`."""
    arcs = []
    for part in text.split(','):
        shape, _, length = part.strip().partition(':')
        if not shape or not length:
            raise ValueError(f'An arc is shape:length, not {part!r}')
        arcs.append(EnergyArcRequest(shape, tracks=int(length)) if unit == 'tracks'
                    else EnergyArcRequest(shape, minutes=float(length)))
    return tuple(arcs)


def arc_places(durations, arc_lengths, unit):
    """The arc each placed track belongs to: by its place, or by the time it starts."""
    spans = [length * 60.0 for length in arc_lengths] if unit == 'minutes' else list(arc_lengths)
    starts = list(range(len(durations)))
    if unit == 'minutes':
        starts, elapsed = [], 0.0
        for seconds in durations:
            starts.append(elapsed)
            elapsed += seconds
    arc_starts = [sum(spans[:index]) for index in range(len(spans))]
    return [max(index for index, start in enumerate(arc_starts) if start <= place) for place in starts]


def summarize(runs, *, arc_count):
    arcs = []
    for arc in range(arc_count):
        placed = [(level, target) for run in runs for index, level, target in run['placements'] if index == arc]
        misses = [abs(level - target) for level, target in placed if level is not None and target is not None]
        arcs.append({'arc': arc, 'placed': len(placed), 'known_energy': len(misses),
                     'mean_target_miss': fmean(misses) if misses else None})
    relations = [score for run in runs for score in run['relations']]
    seconds = [run['seconds'] for run in runs]
    return {
        'arcs': arcs, 'mean_relation_score': fmean(relations) if relations else None, 'runs': len(runs),
        'incomplete': sum(not run['complete'] for run in runs),
        'p50': nearest_rank(seconds, 50) if seconds else None, 'p95': nearest_rank(seconds, 95) if seconds else None,
        'max': max(seconds) if seconds else None,
    }


def run_pilot(repository, arcs, *, unit, starts, seed, bpm_range, weights):
    tracks = {track.track_id: track for track in repository.playlist_export_tracks()}
    bpm = BpmRange.of(*bpm_range)
    candidates = sorted(track_id for track_id, track in tracks.items() if eligible(track, bpm))
    sample = random.Random(seed).sample(candidates, min(starts, len(candidates)))
    relation = _relation_scores(repository)
    lengths = tuple(arc.tracks if unit == 'tracks' else arc.minutes for arc in arcs)
    results = []
    for weight in weights:
        with _arc_weight(weight):
            runs, failures = _runs(repository, arcs, sample, bpm_range, tracks, relation, lengths, unit)
        results.append({'arc_weight': weight, 'failures': failures, **summarize(runs, arc_count=len(arcs))})
    return {'chain': [{'shape': arc.shape, unit: length} for arc, length in zip(arcs, lengths)],
            'eligible_tracks': len(candidates), 'starts': len(sample), 'seed': seed, 'results': results}


def _runs(repository, arcs, sample, bpm_range, tracks, relation, lengths, unit):
    runs, failures = [], 0
    for start in sample:
        recipe = PlaylistRecipe(start_track_id=start, bpm_min=bpm_range[0], bpm_max=bpm_range[1], energy_plan=arcs)
        began = time.perf_counter()
        try:
            preview = PreviewPlaylist(repository).execute(recipe)
        except ValueError:
            failures += 1
            continue
        seconds = time.perf_counter() - began
        placed = preview.tracks
        places = arc_places([tracks[track.track_id].duration_seconds for track in placed], lengths, unit)
        runs.append({
            'placements': [(arc, track.energy_level, track.energy_target) for arc, track in zip(places, placed)],
            'relations': [relation[frozenset((step.from_track_id, step.to_track_id))] for step in preview.transitions],
            'seconds': seconds, 'complete': preview.complete})
    return runs, failures


def _relation_scores(repository):
    _status, edges = repository.related_track_edges(GRAPH_SPARSE_K)
    return {frozenset((edge.a, edge.b)): float(edge.score) for edge in edges}


@contextmanager
def _arc_weight(weight):
    original = energy_plan.ARC_WEIGHT
    energy_plan.ARC_WEIGHT = weight
    try:
        yield
    finally:
        energy_plan.ARC_WEIGHT = original


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--database', required=True)
    parser.add_argument('--chain', required=True, help='shape:length,... e.g. rise:10,fall:10')
    parser.add_argument('--unit', choices=UNITS, default='tracks')
    parser.add_argument('--bpm-min', type=float, required=True)
    parser.add_argument('--bpm-max', type=float, required=True)
    parser.add_argument('--starts', type=int, default=30)
    parser.add_argument('--seed', type=int, default=137)
    parser.add_argument('--weights', default=str(energy_plan.ARC_WEIGHT), help='comma-separated arc weights')
    options = parser.parse_args(argv)
    from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository
    report = run_pilot(ReadOnlyExplorerSQLiteRepository(options.database), parse_chain(options.chain, options.unit),
                       unit=options.unit, starts=options.starts, seed=options.seed,
                       bpm_range=(options.bpm_min, options.bpm_max),
                       weights=tuple(float(weight) for weight in options.weights.split(',')))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
