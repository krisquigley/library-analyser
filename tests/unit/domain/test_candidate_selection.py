import unittest

from music_analyzer.domain.candidate_selection import (
    CandidateFeatures,
    FeatureEvidence,
    SelectionControl,
    SelectionRequest,
    rank_candidates,
)


def evidence(values=(), summary=(), manual=None, source='automatic'):
    return FeatureEvidence(values=tuple(values), summary_values=tuple(summary), manual_text=manual, effective_source=source)


def features(track_id, **fields):
    base = {name: FeatureEvidence() for name in ('bpm', 'key', 'energy', 'mood', 'genres')}
    base.update(fields)
    return CandidateFeatures(track_id=track_id, fields=base)


class CandidateSelectionDomainTests(unittest.TestCase):
    def test_rejects_invalid_controls_and_allows_zero_weight_hard(self):
        with self.assertRaises(ValueError):
            SelectionControl('tempo', 'soft', float('nan'))
        with self.assertRaises(ValueError):
            SelectionControl('tempo', 'hard', -1)
        with self.assertRaises(ValueError):
            SelectionControl('mood', 'hard', 1, within='both')
        control = SelectionControl('tempo', 'hard', 0, {'tolerance': 0.06})
        self.assertEqual(control.weight, 0)

    def test_manual_text_masks_automatic_evidence_without_false_missing_claim(self):
        current = features('a', bpm=evidence((('bpm', 120.0),)))
        candidate = features('b', bpm=evidence((('bpm', 121.0),), manual='about 121', source='manual_text'))
        result = rank_candidates(current, [candidate], SelectionRequest((SelectionControl('tempo', 'soft', 1),)))
        self.assertEqual(result.candidates[0].tier, 'eligible_insufficient_evidence')
        self.assertIsNone(result.candidates[0].score)
        self.assertIn('tempo: candidate bpm has unresolved manual text', result.candidates[0].explanation.missing_evidence)
        self.assertNotIn('missing result', ' '.join(result.candidates[0].explanation.missing_evidence))

    def test_tempo_log_symmetric_threshold_and_octave_opt_in(self):
        current = features('a', bpm=evidence((('bpm', 100.0),)))
        inside = features('b', bpm=evidence((('bpm', 106.0),)))
        half = features('c', bpm=evidence((('bpm', 50.0),)))
        hard = SelectionControl('tempo', 'hard', 0, {'tolerance': 0.06})
        result = rank_candidates(current, [inside, half], SelectionRequest((hard,)))
        self.assertEqual([c.track_id for c in result.candidates], ['b'])
        self.assertEqual(result.excluded_summary['tempo_hard_failed'], 1)
        octave = SelectionControl('tempo', 'hard', 0, {'tolerance': 0.06, 'allow_octaves': True})
        result = rank_candidates(current, [half], SelectionRequest((octave,)))
        self.assertEqual(result.candidates[0].explanation.relation_labels, ('tempo:2.0x',))

    def test_energy_directionality_and_hard_intersection(self):
        current = features('a', energy=evidence(summary=(('arousal', 0.0), ('valence', 0.2))))
        up = features('b', energy=evidence(summary=(('arousal', 0.8),)))
        down = features('c', energy=evidence(summary=(('arousal', -0.5),)))
        result = rank_candidates(current, [up, down], SelectionRequest((SelectionControl('energy', 'hard', 0, {'energy_mode': 'rise'}),)))
        self.assertEqual([c.track_id for c in result.candidates], ['b'])
        reverse = rank_candidates(up, [current], SelectionRequest((SelectionControl('energy', 'hard', 0, {'energy_mode': 'fall'}),)))
        self.assertEqual([c.track_id for c in reverse.candidates], ['a'])

    def test_mood_include_exclude_any_all_partial_missing_labels(self):
        current = features('a')
        happy_calm = features('b', mood=evidence(summary=(('happy', 0.8), ('calm', 0.7), ('angry', 0.1))))
        happy_only = features('c', mood=evidence(summary=(('happy', 0.8),)))
        controls = (SelectionControl('mood', 'hard', 0, {'include': ('happy', 'calm'), 'threshold': 0.5}, within='all'),)
        result = rank_candidates(current, [happy_calm, happy_only], SelectionRequest(controls))
        self.assertEqual([c.track_id for c in result.candidates], ['b'])
        soft = SelectionControl('mood', 'soft', 1, {'include': ('happy',), 'exclude': ('angry',)})
        result = rank_candidates(current, [happy_calm], SelectionRequest((soft,)))
        contribs = result.candidates[0].explanation.contributions
        self.assertEqual([c.control for c in contribs], ['mood_include', 'mood_exclude'])
        self.assertGreater(result.candidates[0].score, 0.8)

    def test_genre_vector_alignment_no_implicit_zeros_and_novelty(self):
        current = features('a', genres=evidence(summary=(('house', 1.0), ('techno', 0.0)), values=(('model', 'discogs'),)))
        candidate = features('b', genres=evidence(summary=(('house', 0.0), ('techno', 1.0)), values=(('model', 'discogs'),)))
        incompatible = features('c', genres=evidence(summary=(('rock', 1.0),), values=(('model', 'other'),)))
        control = SelectionControl('genre', 'soft', 1, {'genre_mode': 'prefer_novelty'})
        result = rank_candidates(current, [candidate, incompatible], SelectionRequest((control,)))
        self.assertEqual(result.candidates[0].track_id, 'b')
        self.assertEqual(result.candidates[1].tier, 'eligible_insufficient_evidence')
        self.assertIn('genre: incompatible label/model alignment', result.candidates[1].explanation.missing_evidence)

    def test_harmonic_same_relative_ambiguity_and_tie_multiplier(self):
        current = features('a', key=evidence((('key', 'A'), ('scale', 'minor'), ('strength', 0.9))))
        relative = features('b', key=evidence((('key', 'C'), ('scale', 'major'))))
        same = features('c', key=evidence((('key', 'A'), ('scale', 'minor'))))
        ambiguous = features('d', key=evidence((('key', 'A/C'), ('scale', 'minor'))))
        result = rank_candidates(current, [relative, same, ambiguous], SelectionRequest((SelectionControl('harmony', 'soft', 1),)))
        self.assertEqual([c.track_id for c in result.candidates], ['b', 'c', 'd'])
        self.assertIn(result.candidates[0].explanation.relation_labels[0], ('harmony:relative_major_minor', 'harmony:same_key'))
        self.assertEqual(result.candidates[2].tier, 'eligible_insufficient_evidence')

    def test_all_controls_zero_soft_weights_are_eligible_unscored_deterministic(self):
        current = features('a', bpm=evidence((('bpm', 100.0),)), energy=evidence(summary=(('arousal', 0.0),)), genres=evidence(summary=(('house', 1.0),)), key=evidence((('key', 'C'), ('scale', 'major'))))
        b = features('b', bpm=evidence((('bpm', 100.0),)), energy=evidence(summary=(('arousal', 0.2),)), mood=evidence(summary=(('happy', 0.9),)), genres=evidence(summary=(('house', 1.0),)), key=evidence((('key', 'C'), ('scale', 'major'))))
        c = features('c', bpm=evidence((('bpm', 101.0),)), energy=evidence(summary=(('arousal', 0.1),)), mood=evidence(summary=(('happy', 0.8),)), genres=evidence(summary=(('house', 0.9),)), key=evidence((('key', 'A'), ('scale', 'minor'))))
        controls = tuple(SelectionControl(name, 'soft', 0) for name in ('energy', 'mood', 'genre', 'tempo', 'harmony'))
        result = rank_candidates(current, [c, b], SelectionRequest(controls))
        self.assertEqual([(x.track_id, x.tier, x.score) for x in result.candidates], [('b', 'eligible_unscored', None), ('c', 'eligible_unscored', None)])

    def test_projection_coordinates_do_not_affect_ranking_and_hard_conflicts_reported(self):
        current = features('a', bpm=evidence((('bpm', 100.0),)), key=evidence((('key', 'C'), ('scale', 'major'))), energy=evidence(summary=(('arousal', 0),)))
        b = features('b', projection=(999, 999, 999), bpm=evidence((('bpm', 100.0),)), key=evidence((('key', 'C'), ('scale', 'major'))), energy=evidence(summary=(('arousal', 1),)))
        c = features('c', projection=(-1, -1, -1), bpm=evidence((('bpm', 130.0),)), key=evidence((('key', 'F#'), ('scale', 'major'))), energy=evidence(summary=(('arousal', -1),)))
        controls = (SelectionControl('tempo', 'hard', 0), SelectionControl('harmony', 'hard', 0), SelectionControl('energy', 'soft', 1, {'energy_mode': 'rise'}))
        result = rank_candidates(current, [c, b], SelectionRequest(controls))
        self.assertEqual([x.track_id for x in result.candidates], ['b'])
        self.assertEqual(result.excluded_summary['tempo_hard_failed'], 1)
        self.assertEqual(result.excluded_summary['harmony_hard_failed'], 1)

    def test_explicit_exclusions_are_removed_before_ranking_and_reported(self):
        current = features('a', bpm=evidence((('bpm', 100.0),)))
        excluded = features('b', bpm=evidence((('bpm', 100.0),)))
        included = features('c', bpm=evidence((('bpm', 100.0),)))
        result = rank_candidates(current, [excluded, included], SelectionRequest((SelectionControl('tempo', 'soft', 1),), exclude_track_ids=('b',)))
        self.assertEqual([candidate.track_id for candidate in result.candidates], ['c'])
        self.assertEqual(result.excluded_summary['explicitly_excluded'], 1)

    def test_hard_only_and_all_off_are_unscored_not_missing(self):
        current = features('a', bpm=evidence((('bpm', 100.0),)))
        candidate = features('b', bpm=evidence((('bpm', 100.0),)))
        hard_only = rank_candidates(current, [candidate], SelectionRequest((SelectionControl('tempo', 'hard', 0),)))
        all_off = rank_candidates(current, [candidate], SelectionRequest((SelectionControl('tempo', 'off', 0),)))
        self.assertEqual(hard_only.candidates[0].tier, 'eligible_unscored')
        self.assertEqual(all_off.candidates[0].tier, 'eligible_unscored')
        self.assertEqual(hard_only.candidates[0].explanation.missing_evidence, ())

    def test_genre_move_toward_labels_uses_genres_field_with_any_all_and_exclusion(self):
        current = features('a')
        candidate = features('b', genres=evidence(summary=(('house', 0.8), ('techno', 0.2), ('rock', 0.9))))
        include_any = SelectionControl('genre', 'hard', 0, {'genre_mode': 'move_toward_labels', 'include': ('house', 'disco'), 'threshold': 0.5}, within='any')
        result = rank_candidates(current, [candidate], SelectionRequest((include_any,)))
        self.assertEqual([c.track_id for c in result.candidates], ['b'])
        exclude = SelectionControl('genre', 'hard', 0, {'genre_mode': 'move_toward_labels', 'exclude': ('techno', 'rock'), 'threshold': 0.5}, within='any')
        result = rank_candidates(current, [candidate], SelectionRequest((exclude,)))
        self.assertEqual(result.candidates, ())

    def test_hard_label_exclusions_require_selected_evidence_and_honor_any_all(self):
        current = features('a')
        missing_excluded = features('b', mood=evidence(summary=(('happy', 0.9),)))
        one_excluded = features('c', mood=evidence(summary=(('angry', 0.9), ('sad', 0.1))))
        all_excluded = features('d', mood=evidence(summary=(('angry', 0.9), ('sad', 0.8))))

        missing_result = rank_candidates(current, [missing_excluded], SelectionRequest((SelectionControl('mood', 'hard', 0, {'exclude': ('angry',), 'threshold': 0.5}),)))
        self.assertEqual(missing_result.candidates, ())
        self.assertEqual(missing_result.excluded_summary['mood_hard_failed'], 1)

        all_result = rank_candidates(current, [one_excluded, all_excluded], SelectionRequest((SelectionControl('mood', 'hard', 0, {'exclude': ('angry', 'sad'), 'threshold': 0.5}, within='all'),)))
        self.assertEqual([candidate.track_id for candidate in all_result.candidates], ['c'])
        self.assertEqual(all_result.excluded_summary['mood_hard_failed'], 1)

    def test_rejects_malformed_numeric_parameters_before_ranking(self):
        current = features('a', bpm=evidence((('bpm', 100.0),)), energy=evidence(summary=(('arousal', 0.0),)), genres=evidence(summary=(('house', 1.0),), values=(('model', 'discogs'),)))
        candidate = features('b', bpm=evidence((('bpm', 100.0),)), energy=evidence(summary=(('arousal', 0.5),)), genres=evidence(summary=(('house', 0.5),), values=(('model', 'discogs'),)))
        invalid_controls = (
            SelectionControl('tempo', 'soft', 1, {'tolerance': -0.1}),
            SelectionControl('energy', 'soft', 1, {'energy_mode': 'rise', 'delta_target': 0}),
            SelectionControl('energy', 'soft', 1, {'hold_tolerance': float('nan')}),
            SelectionControl('mood', 'soft', 1, {'include': ('happy',), 'threshold': float('inf')}),
            SelectionControl('genre', 'soft', 1, {'genre_mode': 'prefer_novelty', 'novelty_min_distance': 0.2, 'novelty_target_distance': 0.2}),
        )
        for control in invalid_controls:
            with self.subTest(control=control):
                with self.assertRaisesRegex(ValueError, 'finite|positive|coherent|threshold'):
                    rank_candidates(current, [candidate], SelectionRequest((control,)))

    def test_hard_failures_return_bounded_no_match_diagnostics(self):
        current = features('a', bpm=evidence((('bpm', 100.0),)), key=evidence((('key', 'C'), ('scale', 'major'))))
        candidate = features('b', bpm=evidence((('bpm', 140.0),)), key=evidence((('key', 'F#'), ('scale', 'major'))))
        result = rank_candidates(current, [candidate], SelectionRequest((SelectionControl('tempo', 'hard', 0), SelectionControl('harmony', 'hard', 0))))
        self.assertEqual(result.candidates, ())
        self.assertEqual(len(result.no_match_details), 1)
        detail = result.no_match_details[0]
        self.assertEqual(detail.track_id, 'b')
        self.assertEqual(set(detail.failed_rules), {'tempo: hard failed', 'harmony: hard failed'})
        self.assertIn('tempo:1.0x', detail.relation_labels)
        self.assertIn('harmony:unsupported', detail.relation_labels)

    def test_harmony_respects_selected_relations_and_ambiguity_uncertainty(self):
        current = features('a', key=evidence((('key', 'A'), ('scale', 'minor'))))
        relative = features('b', key=evidence((('key', 'C'), ('scale', 'major'))))
        ambiguous = features('c', key=FeatureEvidence(values=(('key', 'C'), ('scale', 'major')), effective_source='automatic', uncertainty='ambiguous between C and G'))
        same_only = SelectionControl('harmony', 'hard', 0, {'relations': ('same_key',)})
        result = rank_candidates(current, [relative, ambiguous], SelectionRequest((same_only,)))
        self.assertEqual(result.candidates, ())
        self.assertGreaterEqual(result.excluded_summary['harmony_hard_failed'], 2)


if __name__ == '__main__':
    unittest.main()
