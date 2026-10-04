from __future__ import annotations

from contextlib import closing
import sqlite3
from pathlib import Path

from music_analyzer.application.dto.analysis import AudioSource, StageResult
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository


def register_track(repository: SQLiteAnalysisRepository, suffix: str, *, location: str | None = None,
                   available: bool = True, eligible: bool = True) -> FileIdentity:
    identity = FileIdentity(suffix * 64, 100 + ord(suffix[0]))
    path = location or f'/music/{suffix}.flac'
    metadata = TrackMetadata(duration_seconds=180.0, duration_source='mutagen')
    repository.register(Inventory('/music', (
        ScannedFile(path, identity, 1, 'flac', metadata),
    ), (), available))
    return identity


def graph_relevant_stages(seed: float = 1.0) -> tuple[StageResult, ...]:
    bpm = 120.0 + seed
    return (
        StageResult('bpm', (('algorithm', 'fixture-bpm'),), 'fixture bpm', (('bpm', bpm),)),
        StageResult('key', (('algorithm', 'fixture-key'),), 'fixture key', (('key', '8A'),)),
        StageResult('genres', (('algorithm', 'fixture-genre'),), 'fixture genres', (('genre', 'house'), ('genre', 'deep house'))),
        StageResult(
            'mood',
            (('algorithm', 'fixture-mood'),),
            'fixture mood',
            summary=ScoreSummary(('happy', 'dark'), (0.75, 0.20), (0.70, 0.10), (0.80, 0.30), 1.0),
        ),
        StageResult(
            'energy',
            (('algorithm', 'fixture-energy'),),
            'fixture energy',
            summary=ScoreSummary(('energy',), (0.66,), (0.60,), (0.70,), 1.0),
        ),
    )


def complete_graph_relevant_run(repository: SQLiteAnalysisRepository, identity: FileIdentity,
                                *, location: str | None = None, seed: float = 1.0) -> str:
    run_id = repository.start(AudioSource(location or f'/music/{identity.sha256[0]}.flac', identity.track_id))
    for stage in graph_relevant_stages(seed):
        repository.save_stage(run_id, stage)
    repository.finish(run_id, 'completed', '')
    return run_id


def fail_latest_run(repository: SQLiteAnalysisRepository, identity: FileIdentity, *, location: str | None = None) -> str:
    run_id = repository.start(AudioSource(location or f'/music/{identity.sha256[0]}.flac', identity.track_id))
    repository.save_stage(run_id, StageResult('bpm', (('algorithm', 'fixture-bpm'),), 'partial', (('bpm', 90.0),)))
    repository.finish(run_id, 'failed', 'key unavailable')
    return run_id


def create_historical_v10_database(path: Path, *, track_count: int = 1, include_graph: bool = False) -> tuple[str, ...]:
    repository = SQLiteAnalysisRepository(str(path))
    track_ids = []
    identities = []
    for index in range(track_count):
        suffix = chr(ord('a') + index)
        identity = register_track(repository, suffix)
        identities.append(identity)
        track_ids.append(identity.track_id)
        complete_graph_relevant_run(repository, identity, seed=float(index))
    if include_graph and len(identities) >= 2:
        repository.replace_graph_snapshot(
            (ProjectionEdge(identities[0].track_id, identities[1].track_id, 0.25, 2),),
            10,
            'source-fingerprint-before-backfill',
            positioned_edges=(ProjectionEdge(identities[0].track_id, identities[1].track_id, 0.50, 2),),
        )
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('DELETE FROM graph_feature_evidence')
    return tuple(track_ids)


def current_graph_feature_rows(path: Path) -> tuple[tuple[str, str, str, int], ...]:
    with closing(sqlite3.connect(path)) as db:
        return tuple(db.execute('''
            SELECT track_id, run_id, fingerprint, is_current
            FROM graph_feature_evidence
            WHERE is_current=1
            ORDER BY track_id, run_id
        '''))


def current_graph_state(path: Path) -> tuple[tuple, tuple]:
    with closing(sqlite3.connect(path)) as db:
        builds = tuple(db.execute('''
            SELECT id,status,edge_count,sparse_k,source_fingerprint,source_revision,is_current
            FROM graph_builds ORDER BY id
        '''))
        edges = tuple(db.execute('''
            SELECT source_track_id,target_track_id,score,distance,supported_group_count
            FROM graph_edges ORDER BY source_track_id,target_track_id
        '''))
    return builds, edges
