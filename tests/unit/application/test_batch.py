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
        self.assertEqual(self.calls, ['a', 'b', 'a'])
        batch.execute('new-fingerprint', limit=1, force=True)
        self.assertEqual(len(self.calls), 4)

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
        batch.execute('fp', limit=1)
        self.assertEqual(self.queue.jobs['a'].state, 'failed')

    def test_invalid_limits(self):
        batch = self.build()
        for limit in (0, -1):
            with self.assertRaises(ValueError): batch.execute('fp', limit=limit)
