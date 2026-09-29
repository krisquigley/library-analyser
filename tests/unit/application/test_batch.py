import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from music_analyzer.application.use_cases.analyze_batch import AnalyzeBatch


class Queue:
    def __init__(self):
        self.jobs = {}; self.events = []
    def exclusive(self): return nullcontext()
    def recover(self): self.events.append('recover')
    def tracks(self): return ('a', 'b')
    def get_job(self, track): return self.jobs.get(track)
    def put_job(self, job): self.jobs[job.track_id] = job; self.events.append(job.state)
    def status(self): return tuple(self.jobs.values())


class BatchTests(unittest.TestCase):
    def build(self, outcome='completed'):
        self.queue = Queue(); self.calls = []
        def run(track, duration):
            self.calls.append(track)
            if isinstance(outcome, BaseException): raise outcome
            return SimpleNamespace(status=outcome, run_id='run', detail='detail')
        return AnalyzeBatch(self.queue, lambda t: t, run, lambda t: True)

    def test_limit_and_completed_skip(self):
        batch = self.build()
        batch.execute('fingerprint', limit=1)
        self.assertEqual(self.calls, ['a'])
        batch.execute('fingerprint')
        self.assertEqual(self.calls, ['a', 'b'])
        self.assertEqual(self.queue.events[:3], ['recover', 'pending', 'running'])
        batch.execute('new-fingerprint', limit=1)
        self.assertEqual(self.calls, ['a', 'b'])
        batch.execute('new-fingerprint', limit=1, force=True)
        self.assertEqual(len(self.calls), 3)

    def test_failures_require_explicit_bounded_retry(self):
        batch = self.build(ValueError('bad file'))
        for retry in (False, False, True, True, True):
            batch.execute('fp', retry_failed=retry)
        self.assertEqual(len(self.calls), 6)
        self.assertTrue(all(j.state == 'failed' and j.attempts == 3 for j in self.queue.status()))

    def test_interrupt_checkpoints_and_stops_dispatch(self):
        batch = self.build(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt): batch.execute('fp')
        self.assertEqual(self.calls, ['a'])
        self.assertEqual(self.queue.jobs['a'].state, 'pending')

    def test_changed_identity_cannot_complete(self):
        batch = self.build(); batch.verify = lambda t: False
        self.queue.tracks = lambda: ('a',)
        batch.execute('fp', limit=1)
        self.assertEqual(self.queue.jobs['a'].state, 'failed')

    def test_invalid_limits(self):
        batch = self.build()
        for limit in (0, -1):
            with self.assertRaises(ValueError): batch.execute('fp', limit=limit)

    def test_explicit_catalogue_tracks_only_retry_failed_jobs(self):
        batch = self.build()
        from music_analyzer.application.ports.batch import BatchJob
        self.queue.jobs = {
            'a': BatchJob('a', 'old', 'failed', 1),
            'b': BatchJob('b', 'old', 'completed', 1),
        }
        batch.execute('new', selected_tracks=('a', 'b'), retry_failed=True, max_duration=4757)
        self.assertEqual(self.calls, ['a'])
        self.assertEqual(self.queue.jobs['a'].fingerprint, 'new')
        self.assertEqual(self.queue.jobs['a'].attempts, 1)
        self.assertEqual(self.queue.jobs['b'], BatchJob('b', 'old', 'completed', 1))

    def test_explicit_catalogue_tracks_require_retry_failed(self):
        batch = self.build()
        from music_analyzer.application.ports.batch import BatchJob
        self.queue.jobs = {'a': BatchJob('a', 'old', 'failed', 1)}
        with self.assertRaises(ValueError):
            batch.execute('new', selected_tracks=('a',))
        self.assertEqual(self.calls, [])

    def test_explicit_empty_catalogue_track_selection_is_noop(self):
        batch = self.build()
        from music_analyzer.application.ports.batch import BatchJob
        existing = BatchJob('a', 'old', 'failed', 1)
        self.queue.jobs = {'a': existing}
        result = batch.execute('new', selected_tracks=(), retry_failed=True)
        self.assertEqual(result, (existing,))
        self.assertEqual(self.queue.jobs, {'a': existing})
        self.assertEqual(self.calls, [])
        self.assertEqual(self.queue.events, [])

    def test_unknown_explicit_catalogue_track_is_rejected_before_dispatch(self):
        batch = self.build()
        with self.assertRaises(ValueError):
            batch.execute('fp', selected_tracks=('missing',), retry_failed=True)
        self.assertEqual(self.calls, [])

    def test_exhausted_interruption_becomes_failed(self):
        batch = self.build(KeyboardInterrupt())
        for _ in range(3):
            with self.assertRaises(KeyboardInterrupt): batch.execute('fp', limit=1)
        self.queue.tracks = lambda: ('a',)
        batch.execute('fp', limit=1)
        self.assertEqual(self.queue.jobs['a'].state, 'failed')
