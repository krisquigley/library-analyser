"""Read-only inspection details for disposable public synthetic SQLite fixtures.

These APIs neither generate fixtures nor certify the Explorer's full schema or
payload trust rules. Never use them to publish observations of private data.
"""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3


_APPLICATION_ID = 0x4D414E41
_INVALID_FIXTURE = 'Invalid synthetic SQLite fixture'


def _existing_path(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError('Synthetic SQLite fixture does not exist')
    return path


def _file_sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_sqlite_files(path):
    """Hash main and optional WAL bytes without opening SQLite or writing files.

    Hashes are sequential, not an atomic snapshot. Only a caller-owned,
    quiescent lifecycle permits meaningful before/after comparison; checkpoint
    races may appear as changes. An absent WAL is explicitly represented by
    None. SHM is coordination state, not committed data, and is not fingerprinted.
    """
    path = _existing_path(path)
    main_hash = _file_sha256(path)
    wal = Path(str(path) + '-wal')
    try:
        wal_hash = _file_sha256(wal)
    except FileNotFoundError:
        wal_hash = None
    return {'main_sha256': main_hash, 'wal_sha256': wal_hash}


def inspect_fixture(path):
    """Inspect a writer-owned current-schema v10 synthetic fixture read-only.

    Returns only schema identifiers, integrity results and aggregate counts, not
    paths, handles, metadata or evidence bodies. Invalid/unrecognized inputs
    raise a sanitized ValueError; missing files raise FileNotFoundError. This
    checks identifiers and SQLite integrity, not full repository validation.
    mode=ro keeps committed WAL visible; immutable=1 is deliberately not used.
    SQLite may maintain SHM coordination state when reading a live WAL; this
    API must therefore be used only with caller-owned disposable fixtures.
    """
    path = _existing_path(path)
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            application_id = db.execute('PRAGMA application_id').fetchone()[0]
            schema_version = db.execute('PRAGMA user_version').fetchone()[0]
            if application_id != _APPLICATION_ID or schema_version != 10:
                raise ValueError(_INVALID_FIXTURE)
            integrity_rows = db.execute('PRAGMA integrity_check').fetchall()
            foreign_keys = db.execute('PRAGMA foreign_key_check').fetchall()
            if integrity_rows != [('ok',)] or foreign_keys:
                raise ValueError(_INVALID_FIXTURE)
            tracks = db.execute('SELECT count(*) FROM tracks').fetchone()[0]
            evidence = db.execute(
                'SELECT count(*) FROM graph_feature_evidence WHERE is_current=1'
            ).fetchone()[0]
            return {
                'application_id': application_id,
                'schema_version': schema_version,
                'integrity_check': 'ok',
                'foreign_key_check': [],
                'counts': {'tracks': tracks, 'current_graph_feature_evidence': evidence},
            }
    except sqlite3.Error:
        raise ValueError(_INVALID_FIXTURE) from None
