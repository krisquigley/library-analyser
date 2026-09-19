import unittest
from music_analyzer.application.use_cases.reuse_embeddings import ReuseEmbeddings

class ReuseTests(unittest.TestCase):
    def test_invalid_cached_values_recompute_and_invalid_inference_never_saved(self):
        class Cache:
            value = (((float('nan'),),),)
            writes = 0
            def get(self, key): return self.value
            def put(self, key, value): self.value = value; self.writes += 1
        cache = Cache()
        reuse = ReuseEmbeddings(cache)
        self.assertEqual(reuse.execute('key', 1, 1, lambda: (((.5,),),)), (((.5,),),))
        self.assertEqual(cache.writes, 1)
        self.assertEqual(reuse.execute('key', 1, 1, lambda: self.fail('cache hit')), cache.value)
        with self.assertRaises(ValueError): reuse.execute('key', 1, 2, lambda: ())
        self.assertEqual(cache.writes, 1)
