#!/usr/bin/env python3
"""Synthetic Phase3 projection benchmark utility.

Writes results to stdout; callers should redirect outputs outside the repository.
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


def make_records(count):
    labels = ('house', 'techno', 'breaks', 'ambient')
    records = []
    for i in range(count):
        tid = 'sha256:' + format(i, '064x')[-64:]
        bpm = 80.0 + (i % 100)
        arousal = ((i % 200) / 100.0) - 1.0
        genre_values = tuple((label, ((i + j * 17) % 100) / 100.0) for j, label in enumerate(labels))
        stages = (
            StageResult('bpm', (), '', (('bpm', bpm),)),
            StageResult('energy', (), '', (), summary=ScoreSummary(('arousal',), (arousal,), (arousal,), (arousal,), 1.0, False, '')),
            StageResult('genres', (('model', 'synthetic'),), '', (), summary=ScoreSummary(labels, tuple(v for _, v in genre_values), tuple(v for _, v in genre_values), tuple(v for _, v in genre_values), 1.0, False, '')),
        )
        records.append(ExplorerStoredTrack(tid, tid.removeprefix('sha256:'), 1, 'Track ' + str(i), 1, AnalysisReport('run-' + str(i), 'completed', stages), ()))
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tracks', type=int, required=True)
    parser.add_argument('--queries', type=int, default=100)
    parser.add_argument('--k', type=int, default=10)
    parser.add_argument('--max-seconds', type=float, default=120.0)
    args = parser.parse_args()
    if args.tracks < 0 or args.queries != 100:
        parser.error('--queries must be exactly 100 for Phase3 acceptance')
    started = time.perf_counter()
    records = make_records(args.tracks)
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
        current = records[rng.randrange(len(records))].track_id
        q_start = time.perf_counter()
        selector.execute(CandidateQuery(current, controls, limit=25))
        query_times.append(time.perf_counter() - q_start)
    rss_kib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    query_sorted = sorted(query_times)
    result = {
        'tracks': args.tracks,
        'queries_requested': args.queries,
        'queries_completed': len(query_times),
        'preparation_seconds': prep_seconds,
        'artifact_tracks': len(artifact['tracks']),
        'artifact_edges': len(artifact['edges']),
        'query_p50_seconds': query_sorted[len(query_sorted)//2] if query_sorted else None,
        'query_p95_seconds': query_sorted[int(len(query_sorted)*0.95)-1] if query_sorted else None,
        'query_max_seconds': max(query_times) if query_times else None,
        'wall_seconds': time.perf_counter() - started,
        'max_rss_kib': rss_kib,
        'completed_within_cap': len(query_times) == args.queries and (time.perf_counter() - started) <= args.max_seconds,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result['completed_within_cap'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
