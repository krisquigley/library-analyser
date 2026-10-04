from contextlib import closing, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from music_analyzer.application.dto.analysis import AnalysisError, AudioSource, StageResult
from music_analyzer.application.dto.catalogue import Inventory, ScannedFile, TrackMetadata
from music_analyzer.domain.analysis import ScoreSummary
from music_analyzer.domain.catalogue import FileIdentity
from music_analyzer.domain.projection import ProjectionEdge
from music_analyzer.frameworks.cli.main import main as analyzer_main
from music_analyzer.infrastructure.persistence.analysis import SQLiteAnalysisRepository


DEFAULT_BACKFILL_LIMIT = 100


def _register_track(repository, suffix, location):
    identity = FileIdentity(suffix * 64, 123 + len(suffix))
    repository.register(Inventory('/music', (
        ScannedFile(location, identity, 1, 'flac', TrackMetadata(duration_seconds=180.0, duration_source='mutagen')),
    ), (), True))
    return identity


def _graph_relevant_stages(seed=0):
    return (
        StageResult('bpm', (('algorithm', 'test-bpm'),), 'steady enough for graph feature', (('bpm', 120.0 + seed),)),
        StageResult('key', (('algorithm', 'test-key'),), 'classifier top label only', (('key', f'{8 + seed}A'),)),
        StageResult('genres', (('algorithm', 'test-genre'),), 'multi-label summary', (('genre', 'house'), ('genre', 'deep house'))),
        StageResult(
            'mood',
            (('algorithm', 'test-mood'),),
            'uncalibrated mood scores',
            summary=ScoreSummary(('happy', 'dark'), (0.75, 0.20), (0.70, 0.10), (0.80, 0.30), 1.0),
        ),
        StageResult(
            'energy',
            (('algorithm', 'test-energy'),),
            'uncalibrated energy score',
            summary=ScoreSummary(('energy',), (0.66,), (0.60,), (0.70,), 1.0),
        ),
    )


def _complete_run(repository, identity, location, seed=0):
    run_id = repository.start(AudioSource(location, identity.track_id))
    for stage in _graph_relevant_stages(seed):
        repository.save_stage(run_id, stage)
    repository.finish(run_id, 'completed', '')
    return run_id


def _remove_all_feature_evidence(path):
    with closing(sqlite3.connect(path)) as db:
        db.execute('DELETE FROM graph_feature_evidence')
        db.commit()


def _current_evidence_rows(path):
    with closing(sqlite3.connect(path)) as db:
        return tuple(db.execute(
            'SELECT track_id,run_id,fingerprint,evidence_json,is_current FROM graph_feature_evidence '
            'WHERE is_current=1 ORDER BY track_id'
        ))


def _run_backfill(path, *extra_args):
    stdout = io.StringIO()
    stderr = io.StringIO()
    argv = ['graph', 'evidence-backfill', '--database', str(path), *extra_args]
    with redirect_stdout(stdout), redirect_stderr(stderr):
        try:
            code = analyzer_main(argv)
        except SystemExit as exc:  # argparse uses SystemExit for missing/invalid commands.
            code = int(exc.code or 0)
    return code, stdout.getvalue(), stderr.getvalue()


class GraphFeatureEvidenceBackfillRedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'analysis.sqlite'

    def test_explicit_backfill_populates_missing_current_evidence_for_historical_v10_completed_run(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = _register_track(repository, 'a', '/music/a.flac')
        latest_run = _complete_run(repository, identity, '/music/a.flac')
        _remove_all_feature_evidence(self.path)

        code, stdout, stderr = _run_backfill(self.path)

        self.assertEqual((code, stderr), (0, ''))
        self.assertIn('backfilled=1', stdout)
        rows = _current_evidence_rows(self.path)
        self.assertEqual(len(rows), 1)
        track_id, run_id, fingerprint, payload_json, is_current = rows[0]
        self.assertEqual((track_id, run_id, is_current), (identity.track_id, latest_run, 1))
        self.assertRegex(fingerprint, r'^[0-9a-f]{64}$')
        payload = json.loads(payload_json)
        self.assertEqual(payload['track_id'], identity.track_id)
        self.assertEqual(payload['run_id'], latest_run)
        self.assertEqual(payload['feature_contract_version'], 'graph-feature-evidence-v1')
        self.assertEqual(set(payload['features']), {'bpm', 'key', 'genres', 'mood', 'energy'})

    def test_limit_uses_bounded_keyset_batches_and_repeated_invocation_resumes_idempotently(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        expected = []
        for index, suffix in enumerate(('a', 'b', 'c')):
            location = f'/music/{suffix}.flac'
            identity = _register_track(repository, suffix, location)
            run_id = _complete_run(repository, identity, location, seed=index)
            expected.append((identity.track_id, run_id))
        _remove_all_feature_evidence(self.path)

        first = _run_backfill(self.path, '--limit', '1')
        first_rows = _current_evidence_rows(self.path)
        second = _run_backfill(self.path, '--limit', '1')
        second_rows = _current_evidence_rows(self.path)
        final = _run_backfill(self.path, '--limit', str(DEFAULT_BACKFILL_LIMIT))
        final_rows = _current_evidence_rows(self.path)
        again = _run_backfill(self.path)

        self.assertEqual(first[0], 0, first[2])
        self.assertIn('backfilled=1', first[1])
        self.assertEqual(len(first_rows), 1)
        self.assertEqual(second[0], 0, second[2])
        self.assertIn('backfilled=1', second[1])
        self.assertEqual(len(second_rows), 2)
        self.assertEqual(final[0], 0, final[2])
        self.assertEqual([(track_id, run_id) for track_id, run_id, _fingerprint, _payload, _current in final_rows], sorted(expected))
        self.assertEqual(again[0], 0, again[2])
        self.assertIn('backfilled=0', again[1])
        self.assertEqual(_current_evidence_rows(self.path), final_rows)

    def test_latest_failed_run_clears_stale_older_current_evidence_instead_of_republishing_it(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = _register_track(repository, 'a', '/music/a.flac')
        completed_run = _complete_run(repository, identity, '/music/a.flac')
        failed_run = repository.start(AudioSource('/music/a.flac', identity.track_id))
        repository.save_stage(failed_run, StageResult('bpm', (('algorithm', 'test-bpm'),), 'partial', (('bpm', 90.0),)))
        repository.finish(failed_run, 'failed', 'key unavailable')
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE graph_feature_evidence SET is_current=1 WHERE run_id=?', (completed_run,))
            db.commit()

        code, stdout, stderr = _run_backfill(self.path)

        self.assertEqual((code, stderr), (0, ''))
        self.assertIn('cleared_stale=1', stdout)
        self.assertEqual(_current_evidence_rows(self.path), ())

    def test_source_rechecked_inside_atomic_write_before_publishing_current_evidence(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = _register_track(repository, 'a', '/music/a.flac')
        stale_run = _complete_run(repository, identity, '/music/a.flac')
        _remove_all_feature_evidence(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            quoted_run = "'" + stale_run.replace("'", "''") + "'"
            db.execute(
                f"""
                CREATE TRIGGER simulate_latest_run_race
                BEFORE INSERT ON graph_feature_evidence
                WHEN NEW.run_id = {quoted_run}
                BEGIN
                    UPDATE runs SET status='failed', detail='concurrent failure before commit' WHERE id=NEW.run_id;
                END
                """
            )
            db.commit()

        code, stdout, stderr = _run_backfill(self.path)

        self.assertEqual((code, stderr), (0, ''))
        self.assertIn('stale_skipped=1', stdout)
        self.assertEqual(_current_evidence_rows(self.path), ())
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT status FROM runs WHERE id=?', (stale_run,)).fetchone(), ('failed',))

    def test_existing_warm_graph_snapshot_contract_and_ready_state_are_unchanged_by_backfill(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = _register_track(repository, 'a', '/music/a.flac')
        other = _register_track(repository, 'b', '/music/b.flac')
        run_id = _complete_run(repository, identity, '/music/a.flac')
        _complete_run(repository, other, '/music/b.flac')
        build_id = repository.replace_graph_snapshot((ProjectionEdge(identity.track_id, other.track_id, 0.25, 2),), 10, 'source-fp')
        _remove_all_feature_evidence(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            before_build = db.execute('SELECT id,is_current,status,source_fingerprint FROM graph_builds WHERE id=?', (build_id,)).fetchone()
            before_edges = tuple(db.execute('SELECT source_track_id,target_track_id,score,distance,supported_group_count,distance_policy_version,neighbour_policy_version FROM graph_build_edges WHERE build_id=?', (build_id,)))
            before_positioned = tuple(db.execute('SELECT build_id FROM graph_build_positioned_snapshots WHERE build_id=?', (build_id,)))

        code, stdout, stderr = _run_backfill(self.path)

        self.assertEqual((code, stderr), (0, ''))
        self.assertIn('backfilled=2', stdout)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT id,is_current,status,source_fingerprint FROM graph_builds WHERE id=?', (build_id,)).fetchone(), before_build)
            self.assertEqual(tuple(db.execute('SELECT source_track_id,target_track_id,score,distance,supported_group_count,distance_policy_version,neighbour_policy_version FROM graph_build_edges WHERE build_id=?', (build_id,))), before_edges)
            self.assertEqual(tuple(db.execute('SELECT build_id FROM graph_build_positioned_snapshots WHERE build_id=?', (build_id,))), before_positioned)
        self.assertIn((identity.track_id, run_id), [(track_id, run_id) for track_id, run_id, _fingerprint, _payload, _current in _current_evidence_rows(self.path)])


class GraphFeatureEvidenceBackfillRemediationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'analysis.sqlite'

    def test_stale_publish_cannot_delete_newer_current_evidence_for_latest_completed_run(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = _register_track(repository, 'a', '/music/a.flac')
        older_run = _complete_run(repository, identity, '/music/a.flac', seed=0)
        newer_run = _complete_run(repository, identity, '/music/a.flac', seed=1)
        newer_before = _current_evidence_rows(self.path)
        self.assertEqual(newer_before[0][1], newer_run)

        stats = repository._publish_historical_graph_feature_evidence(
            repository._build_historical_graph_feature_evidence(identity.track_id, older_run)
        )

        self.assertEqual(stats, 'stale_skipped')
        self.assertEqual(_current_evidence_rows(self.path), newer_before)

    def test_corrupt_current_evidence_for_latest_run_is_repaired_not_counted_already_current(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = _register_track(repository, 'a', '/music/a.flac')
        run_id = _complete_run(repository, identity, '/music/a.flac')
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE graph_feature_evidence SET fingerprint=?, evidence_json=? WHERE run_id=?', ('bad', '{bad', run_id))
            db.commit()

        code, stdout, stderr = _run_backfill(self.path)

        self.assertEqual((code, stderr), (0, ''))
        self.assertIn('backfilled=1', stdout)
        row = _current_evidence_rows(self.path)[0]
        self.assertRegex(row[2], r'^[0-9a-f]{64}$')
        json.loads(row[3])

    def test_limit_one_counts_one_actionable_mutation_and_does_not_clear_and_backfill_same_invocation(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        a = _register_track(repository, 'a', '/music/a.flac')
        a_run = _complete_run(repository, a, '/music/a.flac')
        fail = repository.start(AudioSource('/music/a.flac', a.track_id))
        repository.finish(fail, 'failed', 'failed')
        b = _register_track(repository, 'b', '/music/b.flac')
        b_run = _complete_run(repository, b, '/music/b.flac')
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE graph_feature_evidence SET is_current=1 WHERE run_id=?', (a_run,))
            db.execute('DELETE FROM graph_feature_evidence WHERE run_id=?', (b_run,))
            db.commit()

        code, stdout, stderr = _run_backfill(self.path, '--limit', '1')

        self.assertEqual((code, stderr), (0, ''))
        self.assertIn('cleared_stale=1', stdout)
        self.assertIn('backfilled=0', stdout)
        self.assertEqual(_current_evidence_rows(self.path), ())

    def test_oversized_stage_is_rejected_by_size_preflight_before_fetching_result(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = _register_track(repository, 'a', '/music/a.flac')
        run_id = _complete_run(repository, identity, '/music/a.flac')
        _remove_all_feature_evidence(self.path)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute('UPDATE stages SET result=? WHERE run_id=? AND stage=?', ('x' * (24 * 1024 * 1024), run_id, 'bpm'))
            db.commit()

        with self.assertRaisesRegex(AnalysisError, 'Oversized stored stage'):
            repository.backfill_graph_feature_evidence()

    def test_stale_failed_candidate_clear_does_not_demote_newer_completed_current_evidence(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = _register_track(repository, 'a', '/music/a.flac')
        older_run = _complete_run(repository, identity, '/music/a.flac', seed=0)
        newer_run = repository.start(AudioSource('/music/a.flac', identity.track_id))
        for stage in _graph_relevant_stages(seed=1):
            repository.save_stage(newer_run, stage)
        stale_read_candidates = ((identity.track_id, newer_run, 'failed'),)
        original_candidates = repository._graph_feature_backfill_candidates
        original_clear = repository._clear_stale_graph_feature_current

        def stale_candidates():
            yield from stale_read_candidates

        def complete_newer_before_clear(*args):
            repository.finish(newer_run, 'completed', '')
            return original_clear(*args)

        repository._graph_feature_backfill_candidates = stale_candidates
        repository._clear_stale_graph_feature_current = complete_newer_before_clear
        self.addCleanup(setattr, repository, '_graph_feature_backfill_candidates', original_candidates)
        self.addCleanup(setattr, repository, '_clear_stale_graph_feature_current', original_clear)

        stats = repository.backfill_graph_feature_evidence()

        self.assertEqual(stats['cleared_stale_current'], 0)
        rows = _current_evidence_rows(self.path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], newer_run)
        self.assertNotEqual(rows[0][1], older_run)

    def test_finishing_older_running_run_after_newer_completed_run_keeps_newer_current_evidence_and_graph_snapshot(self):
        repository = SQLiteAnalysisRepository(str(self.path))
        identity = _register_track(repository, 'a', '/music/a.flac')
        other = _register_track(repository, 'b', '/music/b.flac')
        older_run = repository.start(AudioSource('/music/a.flac', identity.track_id))
        for stage in _graph_relevant_stages(seed=0):
            repository.save_stage(older_run, stage)
        newer_run = _complete_run(repository, identity, '/music/a.flac', seed=1)
        build_id = repository.replace_graph_snapshot((ProjectionEdge(identity.track_id, other.track_id, 0.25, 2),), 10, 'source-fp')
        newer_before = _current_evidence_rows(self.path)
        self.assertEqual(newer_before[0][1], newer_run)

        repository.finish(older_run, 'completed', '')

        self.assertEqual(_current_evidence_rows(self.path), newer_before)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT is_current,status FROM graph_builds WHERE id=?', (build_id,)).fetchone(), (1, 'completed'))
