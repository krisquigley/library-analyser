import unittest
from music_analyzer.domain.review import effective_value, validate_override


class ReviewPolicyTests(unittest.TestCase):
    def test_manual_annotation_has_precedence_without_mutating_automatic_evidence(self):
        evidence = (('bpm', 120.),)
        self.assertEqual(effective_value(evidence, '121'), '121')
        self.assertEqual(effective_value(evidence, None), evidence)
        self.assertEqual(evidence, (('bpm', 120.),))

    def test_only_explicit_supported_nonblank_bounded_annotations(self):
        for field in ('bpm', 'key', 'genres', 'mood', 'instruments', 'energy'):
            validate_override(field, None)
            validate_override(field, 'é')
        for field, value in [('other', 'x'), ('key', '  '), ('bpm', 120), ('mood', 'x'*4097)]:
            with self.assertRaises(ValueError): validate_override(field, value)
