"""Small public D1 schema/core controls, not an integrity certificate.

Reuse the established literal historical schema scaffold, never a writer or a
PRAGMA-only downgrade. Graph/evidence/stage tables intentionally stay empty;
these fixtures do not prove any populated deferred P7 phase.
"""
from contextlib import closing
import sqlite3

from tests.integration.infrastructure.analysis_historical_schema_fixture import (
    create_historical_schema,
)


PUBLIC_TRACK_IDS = tuple('sha256:' + digit * 64 for digit in ('1', '2'))


def create_public_core_database(path, version=10):
    """Create true v6-v10 with two eligible public tracks; return their IDs.

    All connections are sequential and closed before return. Callers own their
    temporary path. No private input, triggers, runtime DDL imports or migration.
    """
    if version not in range(6, 11):
        raise ValueError('Expected supported schema version 6 through 10')
    create_historical_schema(path, version)
    with closing(sqlite3.connect(path)) as db:
        db.execute('PRAGMA foreign_keys=ON')
        for index, track_id in enumerate(PUBLIC_TRACK_IDS, start=1):
            digest = str(index) * 64
            location = f'/public/d1-fixture/track-{index}.flac'
            db.execute('INSERT INTO tracks VALUES(?,?,?)',
                       (track_id, digest, 100 + index))
            db.execute('INSERT INTO locations VALUES(?,?,?,?,?)',
                       (location, track_id, index, 'flac', 1))
            db.execute('INSERT INTO scan_roots VALUES(?,?)',
                       ('/public/d1-fixture', location))
            db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)',
                       (track_id, 180.0 + index, 'mutagen', 'eligible', ''))
            db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)',
                       (track_id, '[["title","Public fixture"]]', '[]', '[]'))
        db.commit()
    return PUBLIC_TRACK_IDS
