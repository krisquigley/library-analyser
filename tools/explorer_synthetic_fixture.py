"""Disposable public synthetic v10 catalogue for integrity diagnostics.

This outward tool owns its temporary directory and accepts no catalogue, audio,
path or metadata inputs. Construction is not request timing. Schema and graph
promotion belong to the ordinary writer; bounded bulk fixture inserts reuse
its public stage/evidence contracts, without copying DDL or weakening readers.
"""
from contextlib import closing, contextmanager
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import tempfile

from music_analyzer.application.dto.analysis import StageResult
from music_analyzer.application.use_cases.graph_feature_evidence import build_graph_feature_evidence
from music_analyzer.domain.analysis import ScoreWindow, summarize_scores
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.library_duration_policy import DurationVerification, active_library_duration_policy
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository
from music_explorer.application.use_cases.explorer import BuildMoodAxisGraph
from music_explorer.infrastructure.explorer_readonly import ReadOnlyExplorerSQLiteRepository
from music_explorer.interface_adapters.mood_axis_graph_http import to_indexed_mood_axis_graph_http


_TIMESTAMP = '2020-01-01 00:00:00'
_COUNT_QUERIES = {
    name: 'SELECT count(*) FROM ' + name for name in (
        'tracks', 'active_tracks', 'locations', 'active_locations', 'runs', 'stages',
        'graph_feature_evidence', 'graph_builds', 'graph_edges', 'graph_build_edges',
        'graph_positioned_edges', 'graph_build_positioned_edges',
    )
}
_COUNT_QUERIES.update({
    'excluded_tracks': "SELECT count(*) FROM track_audio WHERE status='excluded'",
    'unavailable_tracks': 'SELECT count(DISTINCT track_id) FROM locations WHERE available=0',
    'current_graph_feature_evidence': 'SELECT count(*) FROM graph_feature_evidence WHERE is_current=1',
    'historical_graph_feature_evidence': 'SELECT count(*) FROM graph_feature_evidence WHERE is_current=0',
    'current_graph_builds': 'SELECT count(*) FROM graph_builds WHERE is_current=1',
})


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def _validate_options(track_count, seed, history_count, allow_large):
    if (type(track_count) is not int or not 12 <= track_count <= 20000
            or type(seed) is not int or not 0 <= seed < 2 ** 32
            or type(history_count) is not int or not 1 <= history_count <= 3
            or type(allow_large) is not bool):
        raise ValueError('Invalid public synthetic fixture options')
    if track_count > 12 and not allow_large:
        raise ValueError('Large synthetic fixture requires explicit opt-in')


def _stages(rng, positioned):
    def scored(name, labels, provenance):
        windows = tuple(ScoreWindow(float(i * 30), float((i + 1) * 30),
                                    tuple(round(rng.random(), 6) for _ in labels))
                        for i in range(2))
        return StageResult(name, provenance, 'Public synthetic scores; no audio inference',
                           windows=windows, summary=summarize_scores(labels, windows, 180.0))

    return (
        StageResult('bpm', (('algorithm', 'public-synthetic-bpm'),), '',
                    (('bpm', float(rng.randrange(90, 161))),)),
        StageResult('key', (('algorithm', 'public-synthetic-key'),), '', (('key', '8A'),)),
        StageResult('genres', (('algorithm', 'public-synthetic-genres'),), '',
                    (('genre', 'house'), ('genre', 'deep house'))),
        scored('mood', ('happy', 'dark'), (('model', 'public-synthetic-mood'),)),
        scored('energy', ('valence', 'arousal'),
               (('model', 'emomusic-msd-musicnn-2' if positioned else 'public-incompatible-energy'),
                ('scale', 'native_valence_arousal_regression'))),
    )


def _populate(path, track_count, seed, history_count):
    rng = random.Random(seed)
    eligible = []
    positioned = []
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('PRAGMA foreign_keys=ON')
        # Each twelve-track block includes an excluded, an unpositioned and two
        # unavailable tracks. Availability is intentionally not eligibility.
        for index in range(track_count):
            slot = index % 12
            excluded = slot == 9
            has_position = slot != 8
            available = slot not in (10, 11)
            digest = hashlib.sha256(f'public-synthetic:{seed}:{index}'.encode()).hexdigest()
            identity = FileIdentity(digest, 1000 + index)
            track = identity.track_id
            location = f'/public-synthetic/track-{index:05d}.flac'
            db.execute('INSERT INTO tracks VALUES(?,?,?)', (track, digest, identity.size))
            db.execute('INSERT INTO locations VALUES(?,?,?,?,?)',
                       (location, track, 1, 'flac', int(available)))
            db.execute('INSERT INTO scan_roots VALUES(?,?)', ('/public-synthetic', location))
            common = (('title', ('Duplicate étude %_ 日本' if slot < 2 else f'Public étude {index}')),
                      ('artist', f'Synthetic ensemble {index % 4}'))
            db.execute('INSERT INTO track_metadata VALUES(?,?,?,?)',
                       (track, _canonical_json(common).decode(), '[]', '[]'))
            duration = 1300.0 if excluded else 180.0
            decision = active_library_duration_policy(DurationVerification(duration, 'mutagen'))
            db.execute('INSERT INTO track_audio VALUES(?,?,?,?,?)',
                       (track, duration, 'mutagen', 'eligible' if decision.active else 'excluded',
                        decision.warning or ''))
            if not excluded:
                eligible.append(track)
                if has_position:
                    positioned.append(track)
            for history in range(history_count):
                run = f'public-run-{seed}-{index:05d}-{history}'
                stages = _stages(rng, has_position)
                db.execute('INSERT INTO runs(id,location,status,created_at) VALUES(?,?,?,?)',
                           (run, location, 'completed', _TIMESTAMP))
                db.execute('INSERT INTO run_tracks VALUES(?,?)', (run, track))
                db.executemany('INSERT INTO stages VALUES(?,?,?)',
                               ((run, stage.stage, _canonical_json(asdict(stage)).decode())
                                for stage in stages))
                if not excluded:
                    evidence = build_graph_feature_evidence(track, run, stages)
                    db.execute('''INSERT INTO graph_feature_evidence
                                  (track_id,run_id,fingerprint,evidence_json,is_current,created_at)
                                  VALUES(?,?,?,?,?,?)''',
                               (track, run, evidence.fingerprint, evidence.payload_json(),
                                int(history == history_count - 1), _TIMESTAMP))
    return sorted(eligible), sorted(positioned)


def _chain(tracks):
    return tuple(ProjectionEdge(a, b, 0.25, 2) for a, b in zip(tracks, tracks[1:]))


def _snapshots(writer, path, eligible, positioned, history_count):
    for history in range(history_count):
        build_id = writer.replace_graph_snapshot(
            _chain(eligible), 10, f'public-synthetic-snapshot-{history}',
            positioned_edges=_chain(positioned))
        # The writer uses operational UUIDs/timestamps. Normalize only these
        # public fixture-owned values, including all foreign-key references.
        # Deferred constraints retain FK enforcement throughout the transaction.
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN')
            db.execute('PRAGMA defer_foreign_keys=ON')
            public_id = f'public-build-{history}'
            for table in ('graph_build_edges', 'graph_build_positioned_edges',
                          'graph_build_positioned_snapshots'):
                db.execute(f'UPDATE {table} SET build_id=? WHERE build_id=?', (public_id, build_id))
            db.execute('''UPDATE graph_builds SET id=?, attempt_revision=?,
                          created_at=?,completed_at=? WHERE id=?''',
                       (public_id, f'public-attempt-{history}', _TIMESTAMP, _TIMESTAMP, build_id))
            for table in ('graph_edges', 'graph_build_edges', 'graph_positioned_edges',
                          'graph_build_positioned_edges', 'graph_build_positioned_snapshots'):
                db.execute(f'UPDATE {table} SET built_at=?', (_TIMESTAMP,))


def _manifest(path, track_count, seed, history_count, body):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        counts = {name: db.execute(query).fetchone()[0] for name, query in _COUNT_QUERIES.items()}
        stages = dict(db.execute('SELECT stage,count(*) FROM stages GROUP BY stage'))
        schema_version = db.execute('PRAGMA user_version').fetchone()[0]
        application_id = db.execute('PRAGMA application_id').fetchone()[0]
    decoded = json.loads(body)
    graph_counts = {name: len(decoded[name]) for name in ('nodes', 'links', 'unpositioned')}
    manifest = {
        'source': 'public-synthetic-sqlite', 'schema_version': schema_version,
        'application_id': application_id, 'seed': seed, 'track_count': track_count,
        'history_count': history_count, 'counts': counts,
        'distributions': {
            'stages': stages,
            'evidence': {'current': counts['current_graph_feature_evidence'],
                         'historical': counts['historical_graph_feature_evidence']},
            'positioning': {'positioned': graph_counts['nodes'],
                            'unpositioned': graph_counts['unpositioned']},
        },
        'graph': {'source': 'sqlite-backed', 'sha256': hashlib.sha256(body).hexdigest(),
                  'body_bytes': len(body), 'counts': graph_counts},
    }
    manifest['content_sha256'] = hashlib.sha256(_canonical_json(manifest)).hexdigest()
    return manifest


@contextmanager
def public_synthetic_fixture(track_count=12, seed=70, history_count=2, allow_large=False):
    """Yield ``db_path``, canonical indexed-v3 ``graph_body`` and aggregate manifest.

    Twelve tracks is the default and non-opt-in bound. Explicitly acknowledged
    profiles span 12..20000 tracks and 1..3 histories. All construction and
    consumer failures propagate, while the owned root and sidecars are removed.
    The returned path must not be used after this context exits. Hashes certify
    logical public content, not raw SQLite pages, live WAL or measured latency.
    """
    _validate_options(track_count, seed, history_count, allow_large)
    # Bind ownership before creation: a caller's temp-parent alias may be
    # unlinked or retargeted while the fixture is alive. Cleanup must retain
    # the same canonical parent used to create the owned root.
    temp_parent = Path(tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(prefix='explorer-public-synthetic-', dir=temp_parent) as directory:
        path = (Path(directory) / 'catalogue.sqlite').resolve()
        writer = SQLiteAnalysisRepository(str(path))
        eligible, positioned = _populate(path, track_count, seed, history_count)
        _snapshots(writer, path, eligible, positioned, history_count)
        repository = ReadOnlyExplorerSQLiteRepository(str(path))
        body = _canonical_json(to_indexed_mood_axis_graph_http(BuildMoodAxisGraph(repository).execute()))
        yield {'db_path': path, 'graph_body': body,
               'manifest': _manifest(path, track_count, seed, history_count, body)}
