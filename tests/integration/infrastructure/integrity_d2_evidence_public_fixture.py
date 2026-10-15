"""Independent compact evidence on genuine public v9/v10 DDL.

Separate from the graph fixture: historical rowids precede current rowids.
No writer/reader private helper or production payload builder supplies the oracle.
"""
from contextlib import closing
import hashlib
import json
import sqlite3

from tests.integration.infrastructure.integrity_d2_public_fixture import (
    create_public_graph_database, STAMP,
)

OLD_RUNS = ('evidence-old-1', 'evidence-old-2')
CURRENT_RUNS = ('evidence-current-1', 'evidence-current-2')


def stage(values=(), summary=None):
    return {'values': list(values), 'summary_values': [] if summary is None else
            [list(pair) for pair in zip(summary['labels'], summary['mean'])],
            'summary': summary, 'provenance': [], 'uncertainty': ''}


def summary():
    return {'labels': ['public'], 'mean': [0.5], 'minimum': [0.2],
            'maximum': [0.8], 'coverage': 1.0, 'provisional': False,
            'uncertainty': ''}


def payload(track, run):
    return {'feature_contract_version': 'graph-feature-evidence-v1',
            'track_id': track, 'run_id': run,
            'features': {'bpm': stage([['bpm', 120.0]]),
                         'key': stage([['key', '8A']]),
                         'genres': stage([['genre', 'house']]),
                         'mood': stage(summary=summary()),
                         'energy': stage(summary=summary())}}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def create_public_evidence_database(path, version=10):
    identities = create_public_graph_database(path, version)
    if version < 9:
        return identities
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        # Existing graph publication does not depend on runs/evidence. Rebuild
        # only these public fixture rows; no schema or previous helper changes.
        db.execute('DELETE FROM graph_feature_evidence')
        db.execute('DELETE FROM run_tracks')
        db.execute('DELETE FROM runs')
        for runs, current in ((OLD_RUNS, 0), (CURRENT_RUNS, 1)):
            for index, (track, run) in enumerate(zip(identities, runs), 1):
                db.execute('INSERT INTO runs(id,location,status,detail,created_at) VALUES(?,?,?,?,?)',
                           (run, f'/public/d1-fixture/track-{index}.flac', 'completed', '', STAMP))
                db.execute('INSERT INTO run_tracks(run_id,track_id) VALUES(?,?)', (run, track))
                value = payload(track, run)
                db.execute('INSERT INTO graph_feature_evidence(track_id,run_id,fingerprint,evidence_json,is_current,created_at) VALUES(?,?,?,?,?,?)',
                           (track, run, fingerprint(value), canonical(value), current, STAMP))
        db.commit()
    return identities


def change(path, sql, args=(), *, corrupt=False):
    """Confined legal-row mutation; CHECK/FK bypass only when explicit."""
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA foreign_keys=' + ('OFF' if corrupt else 'ON'))
        if corrupt:
            db.execute('PRAGMA ignore_check_constraints=ON')
        cursor = db.execute(sql, args)
        if cursor.rowcount != 1:
            raise AssertionError('Expected exactly one public row mutation')
        db.commit()


def store_payload(path, run, value, *, text=None, digest=None):
    change(path, 'UPDATE graph_feature_evidence SET evidence_json=?,fingerprint=? WHERE run_id=?',
           (canonical(value) if text is None else text,
            fingerprint(value) if digest is None else digest, run))
