"""Public literal supported schemas with retained rows, not a certificate.

No writer, migrations, private reader, evidence derivation or production DDL.
Every connection closes before return; each database has eight small stage rows.
"""
from contextlib import closing
import json
import sqlite3

from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database

STATUSES = ('completed', 'failed', 'interrupted', 'running')
STAGE_ROWS = tuple((f'public-{status}-{index}', f'custom-retained-{index}')
                   for status in STATUSES for index in range(2))


def stage_payload(stage='custom-retained-0'):
    return {'stage': stage, 'provenance': [['source', 'public']],
            'uncertainty': 'public retained control',
            'values': [['negative', -2], ['estimate', '-3']],
            'raw_predictions': [''], 'windows': {}, 'summary': None,
            'extra_public_field': {'ignored': True}}


def create_public_retained_database(path, version=10):
    ids = create_public_core_database(path, version)
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('UPDATE locations SET available=0 WHERE track_id=?', (ids[1],))
        for ordinal, (run_id, name) in enumerate(STAGE_ROWS):
            index = ordinal % 2
            location = f'/public/d1-fixture/track-{index + 1}.flac'
            db.execute('INSERT INTO runs(id,location,status) VALUES(?,?,?)',
                       (run_id, location, STATUSES[ordinal // 2]))
            db.execute('INSERT INTO run_tracks VALUES(?,?)', (run_id, ids[index]))
            db.execute('INSERT INTO stages VALUES(?,?,?)',
                       (run_id, name, json.dumps(stage_payload(name))))
        db.commit()
    return ids


def replace_stage(path, payload, row=0, raw=False):
    with closing(sqlite3.connect(path)) as db:
        db.execute('UPDATE stages SET result=? WHERE run_id=? AND stage=?',
                   (payload if raw else json.dumps(payload), *STAGE_ROWS[row]))
        db.commit()
