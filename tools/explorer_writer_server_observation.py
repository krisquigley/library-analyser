"""Bound repeated B evidence leaf telemetry for writer/browser correctness runs.

Reader operations still execute unchanged. Only diagnostic span retention is
sampled; parent inclusive durations remain actual but child-exclusive durations
cannot be reconstructed from omitted intervals. This is not a full microprofile.
"""
from contextlib import contextmanager
from tools.explorer_http_server_observation import ServerObservation


class BoundedWriterServerObservation(ServerObservation):
    LEAF_PHASES = frozenset(('validation_evidence_preflight', 'validation_evidence_fetch',
                            'validation_evidence_decode', 'validation_evidence_payload'))
    LIMIT_PER_PHASE_REQUEST = 16

    @contextmanager
    def span(self, phase):
        context = getattr(self.local, 'context', None)
        if context is None or phase not in self.LEAF_PHASES:
            with super().span(phase) as span:
                yield span
            return
        sampling = context.setdefault('sampling', {})
        counts = sampling.setdefault(phase, {'observed': 0, 'omitted': 0, 'omitted_failed': 0})
        if counts['observed'] < self.LIMIT_PER_PHASE_REQUEST:
            counts['observed'] += 1
            with super().span(phase) as span:
                yield span
        else:
            counts['omitted'] += 1
            try:
                yield None
            except StopIteration:
                raise
            except BaseException:
                counts['omitted_failed'] += 1
                raise

    def sampling_report(self):
        """Aggregate bounded labels only; no request identities or payloads."""
        phases = {}
        for request in self.requests:
            for phase, counts in request.get('sampling', {}).items():
                totals = phases.setdefault(phase, {'observed': 0, 'omitted': 0, 'omitted_failed': 0})
                for key in totals:
                    totals[key] += counts[key]
        return {'status': 'sampled' if any(count['omitted'] for count in phases.values()) else 'complete',
                'limit_per_phase_request': self.LIMIT_PER_PHASE_REQUEST,
                'phases': phases,
                'exclusive_duration_status': 'unavailable-when-sampled'}
