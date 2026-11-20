"""Formal Chromium gate runner: supervisor policy and result classification.

These tests never start Podman or a browser; they pin the argv the runner
hands to Podman and how it classifies evidence, so a silent weakening of the
supervisor (memory, swap, OOM group, network, core dumps, scratch bounds) or
a fallback to Docker fails here.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import explorer_browser_gate as gate

MIB = 2**20


def config(**overrides):
    values = dict(repo=Path('/repo'), wheelhouse=Path('/wh'), evidence=Path('/ev'))
    values.update(overrides)
    return gate.GateConfig(**values)


def flag_values(argv, flag):
    return [argv[i + 1] for i, item in enumerate(argv) if item == flag]


class PodmanArgvTests(unittest.TestCase):
    def setUp(self):
        self.argv = gate.podman_run_argv(config(), 'gate-x')

    def test_uses_podman_never_docker(self):
        self.assertEqual(self.argv[:2], ['podman', 'run'])
        self.assertNotIn('docker', ' '.join(self.argv))

    def test_memory_ceiling_without_swap_and_group_oom(self):
        self.assertEqual(flag_values(self.argv, '--memory'), ['4g'])
        self.assertEqual(flag_values(self.argv, '--memory-swap'), ['4g'])  # swap.max=0
        self.assertEqual(flag_values(self.argv, '--cgroup-conf'), ['memory.oom.group=1'])
        self.assertEqual(flag_values(self.argv, '--cgroupns'), ['private'])

    def test_isolated_bounded_and_without_core_dumps(self):
        self.assertEqual(flag_values(self.argv, '--network'), ['none'])
        self.assertIn('--rm', self.argv)
        self.assertEqual(flag_values(self.argv, '--name'), ['gate-x'])
        self.assertIn('core=0', flag_values(self.argv, '--ulimit'))
        self.assertIn(f'fsize={512 * MIB}', flag_values(self.argv, '--ulimit'))

    def test_scratch_is_size_capped_tmpfs(self):
        tmpfs = dict(item.split(':', 1) for item in flag_values(self.argv, '--tmpfs'))
        self.assertIn('size=1g', tmpfs['/scratch'])
        self.assertIn('size=128m', tmpfs['/bscratch'])

    def test_inputs_are_read_only_and_only_evidence_is_writable(self):
        volumes = flag_values(self.argv, '-v')
        self.assertIn('/wh:/wheelhouse:ro,Z', volumes)
        self.assertIn('/repo/tests:/suite/tests:ro,Z', volumes)
        self.assertIn('/repo/tools:/suite/tools:ro,Z', volumes)
        writable = [v for v in volumes if ':ro' not in v]
        self.assertEqual(writable, ['/ev:/evidence:rw,Z'])

    def test_image_is_digest_pinned_and_modules_follow(self):
        index = self.argv.index(gate.IMAGE)
        self.assertRegex(gate.IMAGE, r'@sha256:[0-9a-f]{64}$')
        self.assertIn(gate.PLAYWRIGHT_VERSION, gate.IMAGE)
        self.assertEqual(self.argv[index + 1:], ['bash', '/suite/tools/explorer_browser_gate_container.sh',
                                                  str(gate.MODULE_DEADLINE_SECONDS), *gate.MODULES])


class ModuleSelectionTests(unittest.TestCase):
    def test_formal_modules_and_opt_ins_exclude_large_stress(self):
        self.assertEqual(len(gate.MODULES), len(set(gate.MODULES)))
        for module in gate.MODULES:
            self.assertTrue((Path(__file__).resolve().parents[2] / 'acceptance' / f'{module}.py').is_file(), module)
        self.assertNotIn('RUN_EXPLORER_BROWSER_DIAGNOSTIC_LARGE', gate.OPT_IN_ENV)
        self.assertEqual(gate.OPT_IN_ENV['EXPLORER_BROWSER_SUPERVISED'], '1')


class ClassificationTests(unittest.TestCase):
    def test_pass_skip_fail_and_deadline(self):
        self.assertEqual(gate.classify_module(0, 'Ran 3 tests in 1s\n\nOK\n')['status'], 'PASS')
        self.assertEqual(gate.classify_module(0, 'Ran 3 tests in 1s\n\nOK (skipped=2)\n'),
                         {'status': 'PASS', 'ran': 3, 'skipped': 2, 'failed': 0})
        self.assertEqual(gate.classify_module(0, 'Ran 2 tests in 1s\n\nOK (skipped=2)\n')['status'], 'SKIP')
        self.assertEqual(gate.classify_module(1, 'Ran 2 tests\n\nFAILED (failures=1, errors=1, skipped=0)\n'),
                         {'status': 'FAIL', 'ran': 2, 'skipped': 0, 'failed': 2})
        self.assertEqual(gate.classify_module(137, 'partial output')['status'], 'FAIL')
        self.assertEqual(gate.classify_module(137, 'partial output')['reason'], 'deadline')

    def test_zero_tests_or_unparsable_success_is_not_a_pass(self):
        self.assertEqual(gate.classify_module(0, 'Ran 0 tests in 0s\n\nOK\n')['status'], 'FAIL')
        self.assertEqual(gate.classify_module(0, 'garbage')['status'], 'FAIL')


class SupervisorTests(unittest.TestCase):
    GOOD = 'memory.max=4294967296\nmemory.swap.max=0\nmemory.oom.group=1\n'

    def test_required_limits_accepted(self):
        self.assertIsNone(gate.supervisor_problem(self.GOOD))
        self.assertIsNone(gate.supervisor_problem(self.GOOD.replace('4294967296', str(2 * 2**30))))

    def test_weakened_or_missing_limits_block(self):
        for text in (self.GOOD.replace('4294967296', 'max'),
                     self.GOOD.replace('4294967296', str(4 * 2**30 + 1)),
                     self.GOOD.replace('swap.max=0', 'swap.max=max'),
                     self.GOOD.replace('oom.group=1', 'oom.group=0'), ''):
            with self.subTest(text=text):
                self.assertIsNotNone(gate.supervisor_problem(text))

    def test_oom_kill_after_run_is_reported(self):
        self.assertEqual(gate.oom_kills('low 0\nmax 3\noom 1\noom_kill 2\n'), 2)


class SummaryTests(unittest.TestCase):
    def evidence(self, files):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name, text in files.items():
            (root / name).write_text(text)
        return root

    def test_missing_podman_blocks_without_fallback(self):
        result = gate.run(config(), which=lambda name: None, runner=None)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertIn('podman', result['reason'])

    def test_summary_blocks_on_supervisor_and_fails_on_oom_or_module(self):
        good = SupervisorTests.GOOD
        files = {'cgroup-before.txt': good, 'cgroup-after.txt': good,
                 'memory-events-after.txt': 'oom_kill 0\n',
                 'a.rc': '0', 'a.log': 'Ran 1 test\n\nOK\n',
                 'b.rc': '0', 'b.log': 'Ran 2 tests\n\nOK (skipped=2)\n'}
        summary = gate.summarize(self.evidence(files), ['a', 'b'])
        self.assertEqual(summary['status'], 'PASS')
        self.assertEqual([m['status'] for m in summary['modules'].values()], ['PASS', 'SKIP'])
        self.assertEqual(gate.summarize(self.evidence(dict(files, **{'cgroup-before.txt': ''})),
                                        ['a', 'b'])['status'], 'BLOCKED')
        self.assertEqual(gate.summarize(self.evidence(dict(files, **{'memory-events-after.txt': 'oom_kill 1\n'})),
                                        ['a', 'b'])['status'], 'FAIL')
        self.assertEqual(gate.summarize(self.evidence(dict(files, **{'b.rc': '1', 'b.log': 'FAILED (errors=1)'})),
                                        ['a', 'b'])['status'], 'FAIL')
        missing = dict(files)
        del missing['b.rc']
        self.assertEqual(gate.summarize(self.evidence(missing), ['a', 'b'])['modules']['b']['status'], 'FAIL')

    def test_container_blocked_marker_is_respected(self):
        summary = gate.summarize(self.evidence({'blocked.txt': 'wheelhouse checksum'}), ['a'])
        self.assertEqual((summary['status'], summary['reason']), ('BLOCKED', 'wheelhouse checksum'))



class WheelSourceTests(unittest.TestCase):
    """#209: the gate's wheel is built from the files git sees, never from an ignored build cache."""

    def test_the_wheel_source_is_what_git_sees_including_uncommitted_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            repo, copy = Path(temp) / 'repo', Path(temp) / 'copy'
            repo.mkdir()
            git = lambda *args: subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)
            git('init', '-q')
            (repo / '.gitignore').write_text('build/\n')
            (repo / 'pkg').mkdir()
            (repo / 'pkg/kept.js').write_text('kept')
            (repo / 'pkg/deleted.js').write_text('deleted')
            git('add', '.')
            git('-c', 'user.email=gate@example.invalid', '-c', 'user.name=gate', 'commit', '-q', '-m', 'synthetic')
            (repo / 'pkg/deleted.js').unlink()
            (repo / 'pkg/kept.js').write_text('edited, not committed')
            (repo / 'pkg/new.js').write_text('new, not committed')
            (repo / 'build/lib/pkg').mkdir(parents=True)
            (repo / 'build/lib/pkg/deleted.js').write_text('stale cache')

            gate.copy_wheel_source(repo, copy)

            files = sorted(path.relative_to(copy).as_posix() for path in copy.rglob('*') if path.is_file())
            self.assertEqual(['.gitignore', 'pkg/kept.js', 'pkg/new.js'], files)
            self.assertEqual('edited, not committed', (copy / 'pkg/kept.js').read_text())

    def test_prepare_builds_the_wheel_from_that_copy(self):
        built = []
        with tempfile.TemporaryDirectory() as temp:
            def run(command, **_):
                if 'wheel' in command:
                    built.append(Path(command[-1]))
                    self.assertTrue((Path(command[-1]) / 'pyproject.toml').is_file(), 'the copy exists while building')
                return subprocess.CompletedProcess(command, 0)
            with patch.object(gate.subprocess, 'run', side_effect=run), \
                    patch.object(gate, 'copy_wheel_source', lambda repo, destination: (destination / 'pyproject.toml').write_text('')):
                gate.prepare(Path(temp) / 'repo', Path(temp) / 'wheelhouse')
        self.assertEqual(1, len(built))
        self.assertNotEqual(Path(temp) / 'repo', built[0], 'never the working tree itself')
        self.assertFalse(built[0].exists(), 'the copy is removed afterwards')


if __name__ == '__main__':
    unittest.main()
