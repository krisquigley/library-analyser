from dataclasses import asdict
import json


def present_batch(jobs, as_json=False, ineligible=None):
    ineligible = dict(ineligible or {})
    counts = {state: sum(job.state == state for job in jobs)
              for state in ('pending', 'running', 'completed', 'failed')}
    exclusion_counts = {'excluded_or_unknown': len(ineligible)}
    if as_json:
        return json.dumps({'counts': counts, 'exclusion_counts': exclusion_counts, 'ineligible_tracks': ineligible, 'jobs': [asdict(job) for job in jobs]}, ensure_ascii=False)
    lines = ['Batch jobs: ' + ', '.join(f'{state}={count}' for state, count in counts.items())]
    if ineligible:
        lines.append('Active-library exclusions: ' + str(len(ineligible)))
        lines.extend(f'{track}: excluded {reason}' for track, reason in sorted(ineligible.items()))
    lines.extend(f'{job.track_id}: {job.state} attempts={job.attempts} {job.detail}' for job in jobs)
    return '\n'.join(lines)
