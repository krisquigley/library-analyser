"""RED contracts for a generated PUBLIC browser-only indexed-v3 fixture.

Future outward API (no SQLite, HTTP, browser, audio, private input or file I/O):
    tools.explorer_browser_graph_fixture.public_browser_graph_fixture(
        profile='small', seed=70, allow_large=False) -> dict

The dictionary contains decoded_body (UTF-8 JSON bytes), encoded_body (gzip
bytes), and manifest. Small is 12 positioned nodes / 11 chain edges; stress-41mib
is 20,000 / 19,999 with EXACTLY 41*2**20 decoded bytes, explicit allow_large=True.
The literal default row/envelope oracle below specifies canonical JSON. Stress
uses identical row rules, distributing additional ASCII 'x' characters across
public explanation strings: divmod(target - unpadded canonical length, edges),
with one extra character for each of the first remainder strings. This is
explicit synthetic payload inflation, NOT catalogue fidelity or SQLite output.

Wire encoding is deterministic stdlib gzip (empty filename, mtime=0, level=9).
Exact decoded literal hashes below were independently established from the
specified public content, not from the missing tool. Encoded byte/hash oracles
are independently recomputed using stdlib gzip in the same runtime; a particular
zlib version's compression ratio is not a portable literal fixture requirement.

Default tests allocate only KiB. Explicit expensive integrity invocation:
RUN_EXPLORER_BROWSER_GRAPH_LARGE=1 PYTHONDONTWRITEBYTECODE=1 python3 -m unittest -v \
 tests.unit.benchmark_tools.test_explorer_browser_graph_fixture
Large child: 120s wall, 90s CPU, 768MiB address-space, 1MiB regular-file limit;
owned scratch directory, SIGKILL/reap process group on timeout. No timing budget,
server speed, browser responsiveness or completed large-run claim is implied.
"""
import gzip
import hashlib
import importlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest


TOOL = 'tools.explorer_browser_graph_fixture'
SMALL = (12, 11, 2504,
         '4f6491f6825606e609e71053231f80cc1f9e88b4e4efc02fb10f892a60a77994')
LARGE = (20000, 19999, 42991616,
         'c1d4ba8d3ababb01eb0bf81d67ef38bd3983ebdc904d50229a6e385889af3041')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def small_oracle(seed=70):
    """Independent literal envelope/row oracle; never calls the fixture tool."""
    return {
        'dto_version': 'mood-axis-graph-indexed-v1',
        'selected_mood': None, 'available_moods': [],
        'metadata': {'track_count': 12},
        'axis': [
            {'key': 'x', 'label': 'valence', 'scale': 'native-emomusic-valence-regression'},
            {'key': 'y', 'label': 'arousal', 'scale': 'native-emomusic-arousal-regression'},
            {'key': 'z', 'label': 'BPM', 'scale': 'fixed-BPM/20-display-units'},
        ],
        'genre_labels': ['Public synthetic genre'], 'reason_text': [],
        'provenance_table': [{'source': 'public-synthetic-browser-only'}],
        'explanation_table': [f'Public synthetic link {i:05d}; ' for i in range(11)],
        'link_defaults': {'explanation': 0, 'provenance': 0},
        'nodes': [[f'public-{i:05d}', f'Public synthetic {seed} node {i:05d}',
                   (i % 11) / 10, (i % 11) / 10, (i % 7) / 6, (i % 7) / 6,
                   120, 6, 120, None, [[0, 0.75]], [], 0.5] for i in range(12)],
        'unpositioned': [],
        'links': [[i, i + 1, 0.5, 1, i, 0] for i in range(11)],
    }


def gzip_oracle(body):
    stream = io.BytesIO()
    with gzip.GzipFile(fileobj=stream, mode='wb', filename='', mtime=0,
                       compresslevel=9) as encoder:
        encoder.write(body)
    return stream.getvalue()


class BrowserGraphFixtureRedTests(unittest.TestCase):
    def tool(self):
        # RED must be an assertion about absent intended behavior, not an import
        # error at test collection. Do not swallow dependency errors in a tool
        # once it exists.
        if importlib.util.find_spec(TOOL) is None:
            self.fail('Missing public browser-only indexed-v3 graph fixture tool: ' + TOOL)
        module = importlib.import_module(TOOL)
        factory = getattr(module, 'public_browser_graph_fixture', None)
        self.assertTrue(callable(factory), 'Missing public_browser_graph_fixture behavior')
        return factory

    def assert_fixture(self, fixture, profile='small', seed=70):
        expected = SMALL if profile == 'small' else LARGE
        nodes, links, decoded_bytes, decoded_hash = expected
        self.assertEqual(set(fixture), {'decoded_body', 'encoded_body', 'manifest'})
        raw, wire, manifest = (fixture[key] for key in
                               ('decoded_body', 'encoded_body', 'manifest'))
        self.assertIs(type(raw), bytes)
        self.assertIs(type(wire), bytes)
        self.assertEqual(len(raw), decoded_bytes)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), decoded_hash)
        expected_wire = gzip_oracle(raw)
        encoded_bytes = len(expected_wire)
        encoded_hash = hashlib.sha256(expected_wire).hexdigest()
        self.assertEqual(len(wire), encoded_bytes)
        self.assertEqual(hashlib.sha256(wire).hexdigest(), encoded_hash)
        self.assertEqual(gzip.decompress(wire), raw)
        self.assertEqual(wire, expected_wire)
        document = json.loads(raw)
        self.assertEqual(raw, canonical(document))
        self.assertEqual(document['dto_version'], 'mood-axis-graph-indexed-v1')
        self.assertEqual(document['metadata'], {'track_count': nodes})
        self.assertEqual(len(document['nodes']), nodes)
        self.assertEqual(len(document['links']), links)
        self.assertEqual(document['unpositioned'], [])
        self.assertEqual(len({row[0] for row in document['nodes']}), nodes)
        for index, row in enumerate(document['nodes']):
            self.assertEqual(len(row), 13)
            self.assertEqual(row[0], f'public-{index:05d}')
            self.assertEqual(row[1], f'Public synthetic {seed} node {index:05d}')
            for value in row[2:9] + [row[12]]:
                self.assertIsNot(type(value), bool)
                self.assertTrue(math.isfinite(value))
            self.assertEqual(row[9:13], [None, [[0, 0.75]], [], 0.5])
        for index, row in enumerate(document['links']):
            self.assertEqual(row, [index, index + 1, 0.5, 1, index, 0])
            self.assertLess(row[1], nodes)
            self.assertLess(row[4], len(document['explanation_table']))
            self.assertLess(row[5], len(document['provenance_table']))
        self.assertEqual(manifest, {
            'source': 'public-synthetic-browser-only',
            'profile': profile, 'seed': seed,
            'dto_version': 'mood-axis-graph-indexed-v1',
            'content_encoding': 'gzip', 'encoding_profile': 'gzip-mtime0-level9',
            'counts': {'nodes': nodes, 'links': links, 'unpositioned': 0},
            'decoded': {'body_bytes': decoded_bytes, 'sha256': decoded_hash},
            'encoded': {'body_bytes': encoded_bytes, 'sha256': encoded_hash},
        })
        # Strict aggregate publication: no paths, DB/schema assertions, private
        # metadata or timing fields are tolerated by the exact manifest oracle.
        json.dumps(manifest, sort_keys=True, allow_nan=False)

    def test_default_is_small_public_and_matches_independent_literal_oracles(self):
        fixture = self.tool()()
        self.assert_fixture(fixture)
        self.assertEqual(fixture['decoded_body'], canonical(small_oracle()))

    def test_same_seed_has_identical_bytes_and_manifest_on_independent_calls(self):
        factory = self.tool()
        self.assertEqual(factory(), factory(profile='small', seed=70, allow_large=False))

    def test_changed_seed_changes_actual_payload_not_only_manifest(self):
        factory = self.tool()
        first, second = factory(seed=70), factory(seed=71)
        self.assertNotEqual(first['decoded_body'], second['decoded_body'])
        self.assertEqual(second['decoded_body'], canonical(small_oracle(seed=71)))
        self.assertEqual(second['manifest']['seed'], 71)
        for key in ('encoded', 'decoded'):
            body = second[key + '_body']
            self.assertEqual(second['manifest'][key], {
                'body_bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(),
            })
        self.assertEqual(gzip.decompress(second['encoded_body']), second['decoded_body'])

    def test_stress_profile_requires_explicit_opt_in_before_allocation(self):
        factory = self.tool()
        with self.assertRaisesRegex(ValueError, 'Large browser graph fixture requires explicit opt-in'):
            factory(profile='stress-41mib')

    def test_options_are_strict_and_bounded(self):
        factory = self.tool()
        invalid = [
            {'profile': ''}, {'profile': 'huge'}, {'profile': None}, {'profile': True},
            {'seed': True}, {'seed': -1}, {'seed': 2**32}, {'seed': 1.5}, {'seed': '70'},
            {'allow_large': 1}, {'allow_large': 'yes'}, {'allow_large': None},
        ]
        for options in invalid:
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, 'Invalid public browser graph fixture options'):
                    factory(**options)
        for seed in (0, 2**32 - 1):
            self.assertEqual(factory(seed=seed)['decoded_body'], canonical(small_oracle(seed)))

    def test_external_targets_and_unbounded_cardinalities_are_not_inputs(self):
        factory = self.tool()
        # No actual target is contacted. These are unsupported option names,
        # not private-path fixtures or a trusted arbitrary injection seam.
        for keyword in ('db_path', 'audio_path', 'url', 'node_count', 'edge_count',
                        'decoded_bytes', 'output_dir'):
            with self.subTest(keyword=keyword), self.assertRaises(TypeError):
                factory(**{keyword: 'synthetic-disallowed-target'})

    def test_caller_mutation_cannot_poison_subsequent_manifest(self):
        factory = self.tool()
        first = factory()
        first['manifest']['counts']['nodes'] = 999999
        first['manifest']['decoded']['sha256'] = 'not-an-oracle'
        self.assert_fixture(factory())

    @unittest.skipUnless(os.environ.get('RUN_EXPLORER_BROWSER_GRAPH_LARGE') == '1',
                         'explicit opt-in required; default suite never allocates 41MiB')
    def test_opt_in_stress_profile_has_exact_bytes_hashes_and_bounded_chain(self):
        self.tool()  # Current RED is the missing behavior, not a child import failure.
        script = '''
import resource
resource.setrlimit(resource.RLIMIT_AS, (768*2**20, 768*2**20))
resource.setrlimit(resource.RLIMIT_CPU, (90, 90))
resource.setrlimit(resource.RLIMIT_FSIZE, (2**20, 2**20))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
from tests.unit.benchmark_tools.test_explorer_browser_graph_fixture import BrowserGraphFixtureRedTests
case = BrowserGraphFixtureRedTests()
factory = case.tool()
fixture = factory(profile='stress-41mib', allow_large=True)
case.assert_fixture(fixture, profile='stress-41mib')
print('public stress fixture integrity verified')
'''
        with tempfile.TemporaryDirectory(prefix='public-browser-graph-contract-') as root:
            env = dict(os.environ, TMPDIR=root, TEMP=root, TMP=root,
                       PYTHONDONTWRITEBYTECODE='1')
            child = subprocess.Popen([sys.executable, '-c', script], env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, start_new_session=True)
            try:
                stdout, stderr = child.communicate(timeout=120)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.communicate()
                self.fail('Public stress fixture exceeded 120s integrity safety bound')
            finally:
                # Kill/reap descendant group even if the direct child exited.
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
            self.assertEqual(child.returncode, 0, stderr)
            self.assertEqual(stdout.strip(), 'public stress fixture integrity verified')
            self.assertEqual(list(Path(root).iterdir()), [], 'pure fixture must not write scratch')
        self.assertFalse(Path(root).exists())


if __name__ == '__main__':
    unittest.main()
