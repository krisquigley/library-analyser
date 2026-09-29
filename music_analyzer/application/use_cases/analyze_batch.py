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

    def execute(self, fingerprint, limit=None, retry_failed=False, force=False, max_duration=900, selected_tracks=None):
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
            raise ValueError('Limit must be a positive integer')
        explicit_selection = selected_tracks is not None
        selected = tuple(dict.fromkeys(selected_tracks)) if explicit_selection else ()
        if explicit_selection and not selected:
            return self.queue.status()
        if selected and not retry_failed:
            raise ValueError('Catalogue track selection retries failed jobs only; pass --retry-failed')
        with self.queue.exclusive():
            self.queue.recover()
            recipe = fingerprint() if callable(fingerprint) else fingerprint
            if not recipe:
                raise ValueError('A verified analysis fingerprint is required')
            catalogue_tracks = self.queue.tracks()
            unknown = tuple(track for track in selected if track not in catalogue_tracks)
            if unknown:
                raise ValueError('Unknown catalogue track ID: ' + ', '.join(unknown))
            tracks = selected or catalogue_tracks
            dispatched = 0
            for track in tracks:
                previous = self.queue.get_job(track)
                same = previous is not None and previous.fingerprint == recipe
                if not force and previous is not None and previous.state == 'completed' and self.verify(track):
                    continue
                if selected and (previous is None or previous.state != 'failed'):
                    continue
                if not force:
                    if same and previous.attempts >= self.MAX_ATTEMPTS:
                        self.queue.put_job(replace(previous, state='failed', detail='Attempt budget exhausted; --force required'))
                        continue
                    if same and previous.state == 'failed' and not retry_failed:
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
                    job = self.queue.get_job(track) or job
                    self.queue.put_job(replace(job, state='pending', detail='Interrupted; retry on next dispatch'))
                    raise
                except Exception as error:
                    job = self.queue.get_job(track) or job
                    job = replace(job, state='failed', detail=str(error))
                self.queue.put_job(job)
            return self.queue.status()
