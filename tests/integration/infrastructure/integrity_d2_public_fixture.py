"""Tiny public graph history on independent literal historical DDL.

The D1 helper owns true version-specific DDL/core rows; no writer, migrations,
private schema imports or PRAGMA downgrade. Every setup connection closes.
"""
from contextlib import closing
import sqlite3

from music_analyzer.application.dto.analysis import StageResult
from music_analyzer.application.use_cases.graph_feature_evidence import build_graph_feature_evidence
from music_analyzer.domain.analysis import ScoreSummary
from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database

OLD_BUILD = 'public-old-build'
CURRENT_BUILD = 'public-current-build'
DISTANCE_POLICY = 'symmetric-feature-distance-v1'
NEIGHBOUR_POLICY = 'endpoint-local-exact-top-k-neighbours-v2'
EDGE_COLUMNS = ('source_track_id,target_track_id,score,distance,supported_group_count,'
                'distance_policy_version,neighbour_policy_version,built_at')
STAMP = '2025-01-01 00:00:00'


def create_public_graph_database(path, version=10):
    identities = create_public_core_database(path, version)
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        if version >= 9:
            stages = (
                StageResult('bpm', (), '', (('bpm', 120.0),)),
                StageResult('key', (), '', (('key', '8A'),)),
                StageResult('genres', (), '', (('genre', 'house'),)),
                StageResult('mood', (), '', summary=ScoreSummary(('happy',), (0.8,), (0.7,), (0.9,), 1.0)),
                StageResult('energy', (), '', summary=ScoreSummary(('energy',), (0.6,), (0.5,), (0.7,), 1.0)),
            )
            for index, identity in enumerate(identities, 1):
                run = f'public-run-{index}'
                db.execute('INSERT INTO runs(id,location,status,detail,created_at) VALUES(?,?,?,?,?)',
                           (run, f'/public/d1-fixture/track-{index}.flac', 'completed', '', STAMP))
                db.execute('INSERT INTO run_tracks(run_id,track_id) VALUES(?,?)', (run, identity))
                evidence = build_graph_feature_evidence(identity, run, stages)
                if evidence is None:
                    raise AssertionError('Public completed evidence unavailable')
                db.execute('INSERT INTO graph_feature_evidence(track_id,run_id,fingerprint,evidence_json,is_current,created_at) VALUES(?,?,?,?,?,?)',
                           (identity, run, evidence.fingerprint, evidence.payload_json(), 1, STAMP))
        if version >= 7:
            edge = (*identities, 0.75, 0.25, 1, DISTANCE_POLICY, NEIGHBOUR_POLICY, STAMP)
            for build, current in ((OLD_BUILD, 0), (CURRENT_BUILD, 1)):
                columns = 'id,status,detail,edge_count,sparse_k,source_fingerprint,distance_policy_version,neighbour_policy_version,is_current,created_at,completed_at'
                values = (build, 'completed', '', 1, 1, 'public-source', DISTANCE_POLICY, NEIGHBOUR_POLICY, current, STAMP, STAMP)
                if version == 10:
                    columns += ',source_revision,attempt_revision'
                    values += ('public-source-revision', 'public-attempt-revision')
                db.execute(f'INSERT INTO graph_builds({columns}) VALUES({",".join("?" for _ in values)})', values)
                db.execute(f'INSERT INTO graph_build_edges(build_id,{EDGE_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?)', (build, *edge))
                if version >= 8:
                    db.execute('INSERT INTO graph_build_positioned_snapshots(build_id,edge_count,built_at) VALUES(?,?,?)', (build, 1, STAMP))
                    db.execute(f'INSERT INTO graph_build_positioned_edges(build_id,{EDGE_COLUMNS}) VALUES(?,?,?,?,?,?,?,?,?)', (build, *edge))
            db.execute(f'INSERT INTO graph_edges({EDGE_COLUMNS}) VALUES(?,?,?,?,?,?,?,?)', edge)
            if version >= 8:
                db.execute(f'INSERT INTO graph_positioned_edges({EDGE_COLUMNS}) VALUES(?,?,?,?,?,?,?,?)', edge)
        db.commit()
    return identities
