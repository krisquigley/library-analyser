"""Single-worker policy. Completed reuse is identity + full recipe equality only.

One attempt per selected track per invocation, at most three per recipe unless
explicitly forced. Interrupted attempts count too, avoiding poison-job loops.
"""
from dataclasses import replace
from music_analyzer.application.ports.batch import BatchJob, BatchQueue


class AnalyzeBatch:
    MAX_ATTEMPTS = 3

    def __init__(self, queue: BatchQueue, resolve, analyze, verify):
        self.queue, self.resolve, self.analyze, self.verify = queue, resolve, analyze, verify

    def execute(self, fingerprint, limit=None, retry_failed=False, force=False, max_duration=900):
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
            raise ValueError('Limit must be a positive integer')
        with self.queue.exclusive():
            self.queue.recover()
            recipe = fingerprint() if callable(fingerprint) else fingerprint
            if not recipe:
                raise ValueError('A verified analysis fingerprint is required')
            dispatched = 0
            for track in self.queue.tracks():
                previous = self.queue.get_job(track)
                same = previous is not None and previous.fingerprint == recipe
                if same and not force:
                    if previous.state == 'completed' and self.verify(track):
                        continue
                    if previous.attempts >= self.MAX_ATTEMPTS:
                        continue
                    if previous.state == 'failed' and not retry_failed:
                        continue
                if limit is not None and dispatched >= limit:
                    break
                attempts = previous.attempts if same and not force else 0
                job = BatchJob(track, recipe, 'pending', attempts)
                self.queue.put_job(job)
                job = replace(job, state='running', attempts=attempts + 1)
                self.queue.put_job(job)
                dispatched += 1
                try:
                    source = self.resolve(track)
                    report = self.analyze(source, max_duration)
                    if report.status != 'completed':
                        job = replace(job, state='failed', run_id=report.run_id, detail=report.detail)
                    elif not self.verify(track):
                        job = replace(job, state='failed', run_id=report.run_id,
                                      detail='Track identity changed during analysis; rescan required')
                    else:
                        job = replace(job, state='completed', run_id=report.run_id)
                except KeyboardInterrupt:
                    self.queue.put_job(replace(job, state='pending', detail='Interrupted; retry on next dispatch'))
                    raise
                except Exception as error:
                    job = replace(job, state='failed', detail=str(error))
                self.queue.put_job(job)
            return self.queue.status()
