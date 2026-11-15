"""Run the formal Explorer Chromium gates under a Podman resource supervisor.

Two steps, from the repository root:

    python -m tools.explorer_browser_gate prepare --wheelhouse DIR   # network
    python -m tools.explorer_browser_gate run --wheelhouse DIR --evidence DIR

``prepare`` builds the project wheel from the working tree and downloads the
pinned Playwright/greenlet/mutagen wheels for the image's Python, then writes
SHA256SUMS. ``run`` starts one digest-pinned container with no network, a
4 GiB memory ceiling, no swap, group OOM kill, no core dumps and size-capped
tmpfs scratch. Inside, it verifies the checksums, installs the wheelhouse
offline and runs each browser acceptance module against the installed wheel
under a hard deadline. Only unittest logs, cgroup readings and summary.json
are retained: no screenshots, HAR, response bodies or dumps.

Results are PASS, SKIP (every test skipped), FAIL, or BLOCKED (the
supervisor or its prerequisites are missing). Podman is required; there is
no Docker fallback.
"""
from dataclasses import dataclass, field
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

PLAYWRIGHT_VERSION = '1.65.2'
IMAGE = ('mcr.microsoft.com/playwright/python:v1.65.2-noble'
         '@sha256:cbd0a36dc6f6b8e8bb23703cf6cbe19ebe29e5a1ba43271a11a6c8e53c8b65d0')
IMAGE_PYTHON = '3.12'
CONTAINER_SCRIPT = '/suite/tools/explorer_browser_gate_container.sh'
MODULE_DEADLINE_SECONDS = 900
MEMORY_LIMIT_BYTES = 4 * 2**30
FILE_SIZE_LIMIT_BYTES = 512 * 2**20

MODULES = (
    'test_explorer_browser_smoke',
    'test_explorer_startup_performance',
    'test_explorer_xyz_axes',
    'test_explorer_browser_detail_dom',
    'test_explorer_browser_focus_real',
    'test_explorer_browser_pending_search_manual_orbit',
    'test_explorer_browser_diagnostic',
    'test_explorer_browser_latest_selection',
    'test_explorer_db_detail_browser_diagnostic',
)

# The ~41 MiB stress profile (RUN_EXPLORER_BROWSER_DIAGNOSTIC_LARGE) needs
# separate approval and is deliberately absent.
OPT_IN_ENV = {
    'RUN_BROWSER_SMOKE': '1',
    'RUN_EXPLORER_DOM': '1',
    'RUN_EXPLORER_FOCUS_BROWSER': '1',
    'RUN_EXPLORER_PENDING_SEARCH_BROWSER': '1',
    'RUN_EXPLORER_BROWSER_DIAGNOSTIC': '1',
    'RUN_EXPLORER_DB_DETAIL_BROWSER_DIAGNOSTIC': '1',
    'EXPLORER_BROWSER_SUPERVISED': '1',
}


@dataclass(frozen=True)
class GateConfig:
    repo: Path
    wheelhouse: Path
    evidence: Path
    modules: tuple = MODULES
    module_deadline: int = MODULE_DEADLINE_SECONDS
    total_deadline: int = field(default=MODULE_DEADLINE_SECONDS * len(MODULES) + 300)


def podman_run_argv(config, name):
    argv = ['podman', 'run', '--rm', '--name', name, '--network', 'none', '--cgroupns', 'private',
            '--memory', '4g', '--memory-swap', '4g', '--cgroup-conf', 'memory.oom.group=1',
            '--ulimit', 'core=0', '--ulimit', f'fsize={FILE_SIZE_LIMIT_BYTES}', '--shm-size', '256m',
            '--tmpfs', '/scratch:rw,size=1g,mode=1777', '--tmpfs', '/bscratch:rw,size=128m,mode=1777',
            '--tmpfs', '/site:rw,exec,size=512m', '--tmpfs', '/work:rw,size=64m',
            '-v', f'{config.wheelhouse}:/wheelhouse:ro,Z',
            '-v', f'{config.repo / "tests"}:/suite/tests:ro,Z',
            '-v', f'{config.repo / "tools"}:/suite/tools:ro,Z',
            '-v', f'{config.evidence}:/evidence:rw,Z']
    for key, value in OPT_IN_ENV.items():
        argv += ['-e', f'{key}={value}']
    return argv + [IMAGE, 'bash', CONTAINER_SCRIPT, str(config.module_deadline), *config.modules]


def classify_module(rc, log):
    ran = re.search(r'^Ran (\d+) tests?', log, re.M)
    counts = {key: int(value) for key, value in re.findall(r'(failures|errors|skipped)=(\d+)', log)}
    result = {'ran': int(ran.group(1)) if ran else 0, 'skipped': counts.get('skipped', 0),
              'failed': counts.get('failures', 0) + counts.get('errors', 0)}
    if rc in (124, 137, -9):
        return {'status': 'FAIL', 'reason': 'deadline', **result}
    if rc == 0 and ran and result['ran'] > 0 and re.search(r'^OK\b', log, re.M):
        return {'status': 'SKIP' if result['skipped'] == result['ran'] else 'PASS', **result}
    return {'status': 'FAIL', **result}


def _readings(text):
    return dict(line.split('=', 1) for line in text.splitlines() if '=' in line)


def supervisor_problem(cgroup_text):
    values = _readings(cgroup_text)
    try:
        limit = int(values.get('memory.max', ''))
    except ValueError:
        return 'memory.max is not a finite limit'
    if not 0 < limit <= MEMORY_LIMIT_BYTES:
        return 'memory.max exceeds 4 GiB'
    if values.get('memory.swap.max') != '0':
        return 'memory.swap.max is not 0'
    if values.get('memory.oom.group') != '1':
        return 'memory.oom.group is not 1'
    return None


def oom_kills(events_text):
    match = re.search(r'^oom_kill (\d+)$', events_text, re.M)
    return int(match.group(1)) if match else 0


def _read(path):
    return path.read_text() if path.is_file() else ''


def summarize(evidence, modules):
    blocked = _read(evidence / 'blocked.txt').strip()
    if blocked:
        return {'status': 'BLOCKED', 'reason': blocked, 'modules': {}}
    for stage in ('before', 'after'):
        problem = supervisor_problem(_read(evidence / f'cgroup-{stage}.txt'))
        if problem:
            return {'status': 'BLOCKED', 'reason': f'supervisor {stage}: {problem}', 'modules': {}}
    results = {}
    for module in modules:
        rc_text = _read(evidence / f'{module}.rc').strip()
        if not rc_text.lstrip('-').isdigit():
            results[module] = {'status': 'FAIL', 'reason': 'not run', 'ran': 0, 'skipped': 0, 'failed': 0}
            continue
        results[module] = classify_module(int(rc_text), _read(evidence / f'{module}.log'))
    kills = oom_kills(_read(evidence / 'memory-events-after.txt'))
    failed = kills or any(result['status'] == 'FAIL' for result in results.values())
    summary = {'status': 'FAIL' if failed else 'PASS', 'oom_kill': kills, 'modules': results}
    if kills:
        summary['reason'] = 'OOM kill inside the supervisor'
    return summary


def run(config, which=shutil.which, runner=subprocess.run):
    if which('podman') is None:
        return {'status': 'BLOCKED', 'reason': 'podman not found (no Docker fallback)', 'modules': {}}
    name = f'explorer-browser-gate-{uuid.uuid4().hex[:12]}'
    try:
        runner(podman_run_argv(config, name), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
               timeout=config.total_deadline, check=False)
    except subprocess.TimeoutExpired:
        runner(['podman', 'rm', '--force', '--time', '0', name], stdout=subprocess.DEVNULL,
               stderr=subprocess.DEVNULL, check=False)
        return {'status': 'FAIL', 'reason': 'total deadline', 'modules': {}}
    return summarize(config.evidence, config.modules)


def provenance(config):
    head = subprocess.run(['git', '-C', str(config.repo), 'rev-parse', 'HEAD'],
                          capture_output=True, text=True, check=False).stdout.strip()
    dirty = bool(subprocess.run(['git', '-C', str(config.repo), 'status', '--porcelain', '--',
                                 'music_analyzer', 'music_explorer', 'tests', 'tools', 'pyproject.toml'],
                                capture_output=True, text=True, check=False).stdout.strip())
    return {'commit': head, 'source_dirty': dirty, 'image': IMAGE,
            'wheelhouse_sha256sums': _read(config.wheelhouse / 'SHA256SUMS').splitlines()}


def prepare(repo, wheelhouse):
    wheelhouse.mkdir(parents=True, exist_ok=False)
    pip = [sys.executable, '-m', 'pip']
    subprocess.run([*pip, 'wheel', '--no-deps', '--wheel-dir', str(wheelhouse), str(repo)], check=True)
    subprocess.run([*pip, 'download', '--only-binary=:all:', '--implementation', 'cp',
                    '--python-version', IMAGE_PYTHON, '--platform', 'manylinux2014_x86_64',
                    '--dest', str(wheelhouse), f'playwright=={PLAYWRIGHT_VERSION}', 'mutagen>=1.47,<2'],
                   check=True)
    lines = [f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}'
             for path in sorted(wheelhouse.glob('*.whl'))]
    (wheelhouse / 'SHA256SUMS').write_text('\n'.join(lines) + '\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    prep = commands.add_parser('prepare', help='build and download the offline wheelhouse (network)')
    prep.add_argument('--wheelhouse', type=Path, required=True)
    gate = commands.add_parser('run', help='run the supervised browser gates')
    gate.add_argument('--wheelhouse', type=Path, required=True)
    gate.add_argument('--evidence', type=Path, required=True, help='new, empty directory')
    gate.add_argument('--module', action='append', choices=MODULES, help='repeatable; default all')
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    if args.command == 'prepare':
        prepare(repo, args.wheelhouse.resolve())
        return 0
    args.evidence.mkdir(parents=True, exist_ok=False)
    modules = tuple(args.module or MODULES)
    config = GateConfig(repo=repo, wheelhouse=args.wheelhouse.resolve(), evidence=args.evidence.resolve(),
                        modules=modules, total_deadline=MODULE_DEADLINE_SECONDS * len(modules) + 300)
    summary = {**provenance(config), **run(config)}
    (config.evidence / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    for module, result in summary.get('modules', {}).items():
        print(f"{result['status']:7} {module} ran={result['ran']} skipped={result['skipped']} "
              f"failed={result['failed']}{' (' + result['reason'] + ')' if 'reason' in result else ''}")
    print(f"{summary['status']}{': ' + summary['reason'] if 'reason' in summary else ''}")
    return {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[summary['status']]


if __name__ == '__main__':
    raise SystemExit(main())
