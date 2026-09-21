#!/usr/bin/env python3
"""Synthetic Phase3 projection benchmark utility.

Writes capped, honest results to stdout; callers should redirect outputs outside
the repository. Defaults use representative Phase3 feature vocabularies (400
genre labels and 56 mood labels) across the requested track workloads.
"""
import argparse
import json
from pathlib import Path
import random
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.application.dto.analysis import AnalysisReport, StageResult
from music_analyzer.application.dto.explorer import ExplorerStoredTrack
from music_analyzer.application.use_cases.candidates import SelectExplorerCandidates
from music_analyzer.application.dto.candidates import CandidateQuery, SelectionControlDto
from music_analyzer.application.use_cases.projection_artifacts import PrepareProjectionArtifact


class Repo:
    def __init__(self, records):
        self.records = tuple(records)
    def metadata(self):
        return {'application_id': 0x4D414E41, 'schema_version': 4, 'read_policy': 'synthetic_benchmark'}
    def candidate_snapshot(self):
        return self.metadata(), self.records


class Store:
    def __init__(self):
        self.artifact = None
    def load(self):
        if self.artifact is None:
            raise RuntimeError('missing')
        return self.artifact
    def replace(self, artifact):
        self.artifact = artifact


def _vector(labels, seed, *, pathological):
    if pathological == 'identical':
        return tuple((label, 1.0) for label in labels)
    if pathological == 'orthogonal':
        active = seed % len(labels)
        return tuple((label, 1.0 if i == active else 0.0) for i, label in enumerate(labels))
    # Deterministic sparse-ish but full-dimensional summary vector: every label is
    # present so cosine dimensionality matches the representative vocabulary.
    return tuple((label, ((seed * 131 + i * 17) % 1000) / 1000.0) for i, label in enumerate(labels))


def make_records(count, genre_dimensions, mood_dimensions, pathological):
    genre_labels = tuple(f'genre_{i:03d}' for i in range(genre_dimensions))
    mood_labels = tuple(f'mood_{i:02d}' for i in range(mood_dimensions))
    records = []
    for i in range(count):
        tid = 'sha256:' + format(i, '064x')[-64:]
        bpm = 80.0 + (i % 100)
        arousal = ((i % 200) / 100.0) - 1.0
        genre_values = _vector(genre_labels, i, pathological=pathological)
        mood_values = _vector(mood_labels, i * 7 + 3, pathological=pathological)
        stages = (
            StageResult('bpm', (), '', (('bpm', bpm),)),
            StageResult('energy', (), '', (), summary=ScoreSummary(('arousal',), (arousal,), (arousal,), (arousal,), 1.0, False, '')),
            StageResult('genres', (('model', 'synthetic-400-genre'),), '', (), summary=ScoreSummary(genre_labels, tuple(v for _, v in genre_values), tuple(v for _, v in genre_values), tuple(v for _, v in genre_values), 1.0, False, '')),
            StageResult('mood', (('model', 'synthetic-56-mood'),), '', (), summary=ScoreSummary(mood_labels, tuple(v for _, v in mood_values), tuple(v for _, v in mood_values), tuple(v for _, v in mood_values), 1.0, False, '')),
        )
        records.append(ExplorerStoredTrack(tid, tid.removeprefix('sha256:'), 1, 'Track ' + str(i), 1, AnalysisReport('run-' + str(i), 'completed', stages), ()))
    return records


def _percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    index = min(len(sorted_values) - 1, max(0, int(len(sorted_values) * fraction) - 1))
    return sorted_values[index]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tracks', type=int, required=True)
    parser.add_argument('--queries', type=int, default=100)
    parser.add_argument('--k', type=int, default=10)
    parser.add_argument('--max-seconds', type=float, default=120.0)
    parser.add_argument('--genre-dimensions', type=int, default=400)
    parser.add_argument('--mood-dimensions', type=int, default=56)
    parser.add_argument('--pathological', choices=('none', 'identical', 'orthogonal'), default='none')
    parser.add_argument('--allow-smoke', action='store_true', help='permit non-acceptance reduced workloads')
    args = parser.parse_args()
    representative = args.tracks in {3000, 10000} and args.genre_dimensions == 400 and args.mood_dimensions == 56 and args.queries == 100
    if not representative and not args.allow_smoke:
        parser.error('reduced smoke workloads require --allow-smoke and are not Phase3 acceptance evidence')
    if args.tracks < 0 or args.queries < 0 or args.genre_dimensions <= 0 or args.mood_dimensions <= 0:
        parser.error('tracks/queries must be non-negative and dimensions must be positive')
    started = time.perf_counter()
    records = make_records(args.tracks, args.genre_dimensions, args.mood_dimensions, args.pathological)
    repo = Repo(records)
    store = Store()
    prep_start = time.perf_counter()
    artifact = PrepareProjectionArtifact(repo, store, args.k).execute().artifact
    prep_seconds = time.perf_counter() - prep_start
    selector = SelectExplorerCandidates(repo)
    query_times = []
    rng = random.Random(3)
    controls = (SelectionControlDto('tempo', 'soft', 1.0, {'tolerance': 0.08}), SelectionControlDto('energy', 'soft', 1.0, {'energy_mode': 'hold'}))
    for _ in range(args.queries):
        if time.perf_counter() - started > args.max_seconds:
            break
        current = records[rng.randrange(len(records))].track_id if records else ''
        q_start = time.perf_counter()
        selector.execute(CandidateQuery(current, controls, limit=25))
        query_times.append(time.perf_counter() - q_start)
    wall_seconds = time.perf_counter() - started
    rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    query_sorted = sorted(query_times)
    result = {
        'tracks': args.tracks,
        'genre_dimensions': args.genre_dimensions,
        'mood_dimensions': args.mood_dimensions,
        'pathological': args.pathological,
        'representative_phase3_acceptance_workload': representative,
        'queries_requested': args.queries,
        'queries_completed': len(query_times),
        'preparation_seconds_exact_projection_and_edges': prep_seconds,
        'artifact_tracks': len(artifact['tracks']),
        'artifact_edges': len(artifact['edges']),
        'query_p50_seconds': _percentile(query_sorted, 0.50),
        'query_p95_seconds': _percentile(query_sorted, 0.95),
        'query_max_seconds': max(query_times) if query_times else None,
        'wall_seconds': wall_seconds,
        'max_rss_kib': rss_kib,
        'completed_within_cap': len(query_times) == args.queries and wall_seconds <= args.max_seconds,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result['completed_within_cap'] and representative else 2


if __name__ == '__main__':
    raise SystemExit(main())
