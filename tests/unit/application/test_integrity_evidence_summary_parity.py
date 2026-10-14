"""Independent summary equality controls; no production builder supplies the oracle."""
from copy import deepcopy
import hashlib
import json
import unittest

from music_analyzer.application.use_cases.integrity_evidence import classify_payload

TRACK = 'sha256:' + 'a' * 64
RUN = 'public-summary-parity'


def public_payload(mean=1, displayed=1):
    empty = {'values': [], 'summary_values': [], 'summary': None,
             'provenance': [], 'uncertainty': ''}
    features = {name: deepcopy(empty) for name in ('bpm', 'key', 'genres', 'mood', 'energy')}
    features['mood']['summary'] = {
        'labels': ['public'], 'mean': [mean], 'minimum': [0], 'maximum': [1],
        'coverage': 1, 'provisional': False, 'uncertainty': '',
    }
    features['mood']['summary_values'] = [['public', displayed]]
    return {'feature_contract_version': 'graph-feature-evidence-v1',
            'track_id': TRACK, 'run_id': RUN, 'features': features}


def classify(value):
    canonical = json.dumps(value, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=False, allow_nan=False).encode('utf-8')
    digest = hashlib.sha256(canonical).hexdigest()
    return tuple(code.value for code in classify_payload(TRACK, RUN, digest, value))


class SummaryEqualityParity(unittest.TestCase):
    def test_healthy_numeric_equality_control(self):
        for mean in (0, 1, 0.5):
            with self.subTest(mean=mean):
                self.assertEqual(classify(public_payload(mean, mean)), ())

    def test_true_equals_one_and_false_equals_zero(self):
        for mean, displayed in ((1, True), (0, False)):
            with self.subTest(mean=mean, displayed=displayed):
                self.assertEqual(classify(public_payload(mean, displayed)), ())

    def test_unequal_boolean_control_remains_invalid(self):
        for mean, displayed in ((0, True), (1, False)):
            with self.subTest(mean=mean, displayed=displayed):
                self.assertEqual(classify(public_payload(mean, displayed)),
                                 ('evidence_summary_invalid',))

    def test_finite_nonboolean_vectors_and_coverage_remain_required(self):
        for name in ('mean', 'minimum', 'maximum', 'coverage'):
            for invalid in (True, False, '1', None):
                with self.subTest(name=name, invalid=invalid):
                    value = public_payload()
                    summary = value['features']['mood']['summary']
                    summary[name] = invalid if name == 'coverage' else [invalid]
                    self.assertEqual(classify(value), ('evidence_summary_invalid',))

    def test_nonfinite_vectors_and_coverage_remain_invalid(self):
        # Nonfinite payloads cannot have a canonical allow_nan=False fingerprint;
        # a syntactically valid digest independently reaches the summary predicate.
        for name in ('mean', 'minimum', 'maximum', 'coverage'):
            for invalid in (float('inf'), -float('inf'), float('nan')):
                with self.subTest(name=name, invalid=invalid):
                    value = public_payload()
                    value['features']['mood']['summary'][name] = invalid if name == 'coverage' else [invalid]
                    codes = classify_payload(TRACK, RUN, 'b' * 64, value)
                    self.assertEqual(tuple(code.value for code in codes), ('evidence_summary_invalid',))

    def test_malformed_or_unequal_pairs_remain_invalid(self):
        for pairs in (None, [], [['wrong', 1]], [['public']], [['public', 1, 2]],
                      ['public'], [[1, 1]], [['public', '1']], [['public', 1], ['public', 1]]):
            with self.subTest(pairs=pairs):
                value = public_payload()
                value['features']['mood']['summary_values'] = pairs
                self.assertEqual(classify(value), ('evidence_summary_invalid',))
