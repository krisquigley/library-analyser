"""Bounded public smoke entry point; not a latency/resource acceptance test."""
import json
from pathlib import Path
import subprocess
import sys
import unittest


class GraphReadBenchmarkCliTests(unittest.TestCase):
    def test_module_cli_reports_public_synthetic_integrity_smoke(self):
        result = subprocess.run(
            [sys.executable, '-m', 'tools.graph_read_benchmark', '--synthetic-smoke'],
            cwd=Path(__file__).resolve().parents[3],
            capture_output=True, text=True, timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip(), 'CLI must emit a usable JSON report')
        report = json.loads(result.stdout)
        self.assertIs(report['synthetic_only'], True)
        self.assertEqual(report['scope'], 'public-synthetic-smoke')
        self.assertEqual(report['measurement']['attempted'], 1)
        self.assertEqual(report['measurement']['succeeded'], 1)
        sample = report['measurement']['samples'][0]
        self.assertEqual(sample['outcome'], 'ok')
        self.assertEqual(sample['http_status'], 200)
        self.assertGreater(sample['body_bytes'], 0)
        self.assertEqual(len(sample['sha256']), 64)
        self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
