"""Real SQLite lock errors, sampled before cleanup; owned children are bounded."""
import json
import os
from pathlib import Path
import select
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from tests.integration.infrastructure.integrity_d1_public_fixture import create_public_core_database


CHILD = r'''
import json, os, signal, sqlite3, sys, time
from unittest.mock import patch
from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from music_analyzer.application.use_cases.check_integrity import CheckIntegrity
real_connect = sqlite3.connect
mode = sys.argv[2]
observed = {}
class Connection:
    def __init__(self, connection):
        self.connection = connection
    def __getattr__(self, name):
        return getattr(self.connection, name)
    def set_progress_handler(self, handler, steps):
        if handler is not None:
            self.deadline = handler.__self__.deadline
            observed['deadline'] = self.deadline
        return self.connection.set_progress_handler(handler, steps)
    def execute(self, sql, *args):
        if sql == 'SELECT 1 FROM sqlite_master LIMIT 1':
            if mode == 'expired':
                print('ready', flush=True)
                os.kill(os.getpid(), signal.SIGSTOP)
            else:
                # A genuine early BUSY refusal, not a simulated SQLite error.
                self.connection.execute('PRAGMA busy_timeout=1').close()
            try:
                return self.connection.execute(sql, *args)
            except sqlite3.Error as error:
                observed['error_at'] = time.monotonic()
                observed['error_code'] = error.sqlite_errorcode
                raise
        return self.connection.execute(sql, *args)
    def close(self):
        if mode == 'early':
            time.sleep(max(0, self.deadline + .05 - time.monotonic()))
        self.connection.close()
        observed['closed_at'] = time.monotonic()
with patch('sqlite3.connect', lambda *a, **k: Connection(real_connect(*a, **k))):
    report = CheckIntegrity(SQLiteIntegrityScanner()).execute(sys.argv[1], deadline_seconds=.5)
observed.update(stop=report.stop_reason, status=report.status, exit_code=report.exit_code,
                findings=[f.code for f in report.findings])
print(json.dumps(observed), flush=True)
'''


class IntegrityD1BusyDeadline(unittest.TestCase):
    def locked_scan(self, mode):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'public.sqlite'
            create_public_core_database(path, 6)
            lock = sqlite3.connect(path)
            child = None
            try:
                lock.execute('BEGIN EXCLUSIVE')
                child = subprocess.Popen([sys.executable, '-c', CHILD, str(path), mode],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                         text=True, start_new_session=True)
                if mode == 'expired':
                    ready, _, _ = select.select([child.stdout], [], [], 5)
                    self.assertTrue(ready, 'child must reach real recognition query')
                    self.assertEqual(child.stdout.readline().strip(), 'ready')
                    # Scheduling pause exceeds the actual audit deadline, not a clock fake.
                    time.sleep(.7)
                    os.kill(child.pid, signal.SIGCONT)
                stdout, stderr = child.communicate(timeout=10)
                self.assertEqual(child.returncode, 0, stderr)
                return json.loads(stdout)
            finally:
                if child is not None:
                    if child.poll() is None:
                        os.killpg(child.pid, signal.SIGKILL)
                    child.communicate(timeout=5)
                lock.rollback()
                lock.close()

    def test_initial_busy_returning_after_actual_deadline_is_incomplete(self):
        result = self.locked_scan('expired')
        self.assertEqual(result['error_code'], sqlite3.SQLITE_BUSY)
        self.assertGreater(result['error_at'], result['deadline'])
        self.assertEqual((result['stop'], result['status'], result['exit_code']),
                         ('deadline', 'incomplete', 4))
        self.assertIn('deadline_exceeded', result['findings'])
        self.assertNotIn('initial_access_failed', result['findings'])

    def test_early_busy_stays_unreadable_when_only_cleanup_expires(self):
        result = self.locked_scan('early')
        self.assertEqual(result['error_code'], sqlite3.SQLITE_BUSY)
        self.assertLess(result['error_at'], result['deadline'])
        self.assertGreater(result['closed_at'], result['deadline'])
        self.assertEqual((result['stop'], result['status'], result['exit_code']),
                         ('unreadable_database', 'unsupported', 3))
        self.assertIn('initial_access_failed', result['findings'])
        self.assertNotIn('deadline_exceeded', result['findings'])
