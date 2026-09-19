from dataclasses import asdict
import json


def present_batch(jobs, as_json=False):
    counts = {state: sum(job.state == state for job in jobs)
              for state in ('pending', 'running', 'completed', 'failed')}
    if as_json:
        return json.dumps({'counts': counts, 'jobs': [asdict(job) for job in jobs]}, ensure_ascii=False)
    lines = ['Batch jobs: ' + ', '.join(f'{state}={count}' for state, count in counts.items())]
    lines.extend(f'{job.track_id}: {job.state} attempts={job.attempts} {job.detail}' for job in jobs)
    return '\n'.join(lines)
