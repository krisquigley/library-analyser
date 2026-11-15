"""Issue #111: a finite stage number must also be representable as a float.

Python integers such as 10**4000 compare as finite and fit stored JSON, but
float()/math.isfinite raise OverflowError in projection and candidate
selection. The domain policy rejects them so the writer fails at origin.
"""
import sys
import unittest

from music_analyzer.application.use_cases.stage_result_validation import validate_stage_result
from music_analyzer.application.dto.analysis import StageResult
from music_analyzer.domain.analysis import finite
from music_explorer.domain.analysis import finite as standalone_finite

TOO_LARGE = (10 ** 4000, -(10 ** 4000), 2 ** 1024, 2 ** 1024 - 2 ** 970)  # last: first int that rounds to overflow
REPRESENTABLE = (0, 1, -7, 10 ** 300, int(sys.float_info.max), 2 ** 1024 - 2 ** 970 - 1, 1.5, sys.float_info.max)


class FloatRepresentableFinitePolicyTests(unittest.TestCase):
    def test_integers_beyond_float_range_are_not_finite(self):
        for policy in (finite, standalone_finite):
            for value in TOO_LARGE:
                with self.subTest(policy=policy.__module__, digits=len(str(abs(value)))):
                    self.assertFalse(policy(value))

    def test_representable_numbers_remain_finite(self):
        for policy in (finite, standalone_finite):
            for value in REPRESENTABLE:
                with self.subTest(policy=policy.__module__, value=type(value).__name__):
                    self.assertTrue(policy(value))
            for value in (float('inf'), float('nan'), True, '1', None):
                with self.subTest(policy=policy.__module__, rejected=repr(value)):
                    self.assertFalse(policy(value))

    def test_stage_validation_rejects_float_overflowing_values(self):
        for stage in (
            StageResult('bpm', (), '', (('bpm', 10 ** 4000),)),
            StageResult('mood', (), '', raw_predictions=(((10 ** 4000,),),)),
        ):
            with self.subTest(stage=stage.stage), self.assertRaises(ValueError):
                validate_stage_result(stage)


if __name__ == '__main__':
    unittest.main()
