"""D3a strict metadata row policy; controls run first, then callable scanner RED."""
from contextlib import closing
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from music_analyzer.application.dto.catalogue import TrackMetadata
from music_analyzer.application.use_cases.metadata_validation import validate_metadata
from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d3_public_fixture import create_public_retained_database, replace_stage


class RuntimeCursor:
    """Observe the public cursor boundary, independent of Delivery internals."""
    def __init__(self,cursor,owner,target):
        self.cursor,self.owner,self.target=cursor,owner,target

    def fetchone(self):
        o=self.owner
        if self.target and o.cancel:
            o.interrupts+=1
            raise KeyboardInterrupt('public phase cancellation')
        row=self.cursor.fetchone()
        key='target' if self.target else 'other'
        o.eof[key]+=int(row is None)
        if row is not None:
            o.rows[key]+=1
            o.total_rows+=1
            o.total_utf8+=sum(len(v.encode('utf-8')) for v in row if isinstance(v,str))
        return row

    def __iter__(self):
        while (row:=self.fetchone()) is not None: yield row

    def close(self):
        self.owner.closed['target' if self.target else 'other']+=1
        self.cursor.close()

    def __getattr__(self,name): return getattr(self.cursor,name)


class RuntimeConnection:
    def __init__(self,connection,owner): self.connection,self.owner=connection,owner

    def execute(self,sql,*args):
        o=self.owner; text=' '.join(sql.lower().split())
        if 'pragma_application_id' in text and o.on_pin and not o.pin_writes:
            o.on_pin(); o.pin_writes+=1
        target='from '+o.table in text
        if target and o.entry_rows is None:
            o.entry_rows,o.entry_utf8=o.total_rows,o.total_utf8
            if o.on_entry: o.on_entry(o)
        return RuntimeCursor(self.connection.execute(sql,*args),o,target)

    def close(self):
        self.owner.connection_closes+=1
        self.connection.close()
        if self.owner.fail_close:
            raise sqlite3.OperationalError('public final cleanup failure')

    def __getattr__(self,name): return getattr(self.connection,name)


class RuntimeObservation:
    def __init__(self,table='track_metadata',*,on_entry=None,on_pin=None,cancel=False,fail_close=False):
        self.real_connect=sqlite3.connect
        self.table,self.on_entry,self.on_pin=table,on_entry,on_pin
        self.cancel,self.fail_close=cancel,fail_close
        self.total_rows=self.total_utf8=self.pin_writes=self.interrupts=self.connection_closes=0
        self.entry_rows=self.entry_utf8=None
        self.rows=dict(target=0,other=0); self.eof=dict(target=0,other=0); self.closed=dict(target=0,other=0)
        self.calls=[]; self.now=0

    def connect(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        return RuntimeConnection(self.real_connect(*args,**kwargs),self)


def check(scan, owner='metadata'):
    return next(c for c in scan.checks if c.check_id == owner)


def findings(scan, owner='metadata'):
    return [(f.code, f.count, f.count_precision) for f in scan.findings if f.check_id == owner]


class PhaseCursor:
    """Public cursor protocol fault seam, never a private reader or fake scanner.

    Value SELECTs are distinguished from size preflights. A delivered envelope
    is still counted only by the scanner, not by this protocol observer.
    """
    def __init__(self, cursor, owner, target, preflight):
        self.cursor, self.owner, self.target, self.preflight = cursor, owner, target, preflight
        self.delivered = 0

    def fetchone(self):
        o = self.owner
        if self.target and not self.preflight and o.read_after == self.delivered:
            o.fired += 1
            raise sqlite3.OperationalError('public injected phase read failure')
        row = self.cursor.fetchone()
        if self.target and not self.preflight and o.missing_once and o.fired == 0 and row is not None:
            row = None; o.fired += 1
        key = 'target' if self.target else 'other'
        o.rows[key] += int(row is not None)
        o.eof[key] += int(row is None)
        if row is not None:
            self.delivered += 1
            if self.target and self.preflight and o.bad_size:
                row = (.5,) + tuple(row[1:]); o.fired += 1
            if self.target and not self.preflight:
                for value in row:
                    if isinstance(value, str):
                        o.largest_text = max(o.largest_text, len(value.encode('utf-8', errors='surrogatepass')))
        return row

    def __iter__(self):
        while (row := self.fetchone()) is not None:
            yield row

    def close(self):
        self.cursor.close()
        self.owner.closed['target' if self.target else 'other'] += 1
        if self.target and not self.preflight and self.owner.fail_close:
            self.owner.fired += 1
            raise sqlite3.OperationalError('public injected phase cleanup failure')

    def __getattr__(self, name):
        return getattr(self.cursor, name)


class PhaseConnection:
    def __init__(self, connection, owner):
        self.connection, self.owner = connection, owner

    def execute(self, sql, *args):
        text = ' '.join(sql.lower().split())
        target = 'from ' + self.owner.table in text
        return PhaseCursor(self.connection.execute(sql, *args), self.owner, target,
                           'case typeof' in text)

    def __getattr__(self, name):
        return getattr(self.connection, name)


class PhaseObservation:
    def __init__(self, table='track_metadata', *, read_after=None, fail_close=False, bad_size=False, missing_once=False):
        self.real_connect = sqlite3.connect
        self.table, self.read_after, self.fail_close, self.bad_size = table, read_after, fail_close, bad_size
        self.missing_once = missing_once
        self.fired = self.largest_text = 0
        self.rows = dict(target=0, other=0)
        self.eof = dict(target=0, other=0)
        self.closed = dict(target=0, other=0)
        self.connections = 0

    def connect(self, *args, **kwargs):
        self.connections += 1
        return PhaseConnection(self.real_connect(*args, **kwargs), self)


class MetadataCase(unittest.TestCase):
    def public(self, version=10):
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        path = Path(td.name) / 'public.sqlite'
        self.ids = create_public_retained_database(path, version)
        return path

    def update(self, path, common='[]', tags='[]', warnings='[]', row=1):
        with closing(sqlite3.connect(path)) as db:
            db.execute('UPDATE track_metadata SET common_json=?,tags_json=?,warnings_json=? WHERE track_id=?',
                       (common, tags, warnings, self.ids[row])); db.commit()

    def exhausted(self, scan, expected=()):
        c = check(scan)
        self.assertEqual((c.state, c.count, c.count_unit, c.count_precision), ('completed', 2, 'rows', 'exact'))
        self.assertEqual(findings(scan), [(code, 1, 'exact') for code in expected])
        self.assertEqual(scan.stop_reason, 'completed')


class MetadataControls(MetadataCase):
    def test_transparent_target_nontarget_eof_cleanup_and_scanner(self):
        path = self.public(); o = PhaseObservation()
        with closing(o.connect(path)) as db:
            for query in ('SELECT common_json,tags_json,warnings_json FROM track_metadata', 'SELECT status FROM runs'):
                c = db.execute(query); self.assertEqual(len(list(c)), 2 if 'metadata' in query else 8); c.close()
        self.assertEqual(o.rows, dict(target=2, other=8))
        self.assertEqual(o.eof, dict(target=1, other=1))
        self.assertEqual(o.closed, dict(target=1, other=1))
        plain = SQLiteIntegrityScanner().scan(str(path))
        with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect', o.connect):
            wrapped = SQLiteIntegrityScanner().scan(str(path))
        self.assertEqual(wrapped, plain); self.assertFalse(plain.findings)

    def test_fault_modes_are_real_cursor_faults_and_nontarget_is_unchanged(self):
        path = self.public()
        for options in ({'read_after': 1}, {'fail_close': True}, {'bad_size': True}, {'missing_once': True}):
            with self.subTest(options=options):
                o = PhaseObservation(**options)
                with closing(o.connect(path)) as db:
                    c = db.execute('SELECT status FROM runs'); self.assertEqual(len(list(c)), 8); c.close()
                    query = ('SELECT CASE typeof(common_json) WHEN \'text\' THEN length(CAST(common_json AS BLOB)) END FROM track_metadata'
                             if o.bad_size else 'SELECT common_json FROM track_metadata')
                    c = db.execute(query); first = c.fetchone()
                    if o.bad_size: self.assertEqual(first, (.5,))
                    if o.missing_once:
                        self.assertIsNone(first); self.assertIsNotNone(c.fetchone())
                    if o.read_after is not None:
                        with self.assertRaises(sqlite3.OperationalError): c.fetchone()
                    if o.fail_close:
                        with self.assertRaises(sqlite3.OperationalError): c.close()
                    else: c.close()
                self.assertEqual(o.fired, 1); self.assertEqual(o.rows['other'], 8)
                self.assertEqual(o.eof['other'], 1); self.assertEqual(o.closed['target'], 1)

    def test_strict_validator_accepts_duplicates_empty_and_rejects_coercion(self):
        validate_metadata(TrackMetadata(common=[['', ''], ['', ['', 'x']]], tags=[['', []], ['', ['']]], warnings=['', '']))
        for kwargs in ({'common': {'title': 'x'}}, {'common': [[1, 'x']]}, {'common': [['x', [1]]]},
                       {'tags': [['x', 'text']]}, {'warnings': 'text'}, {'warnings': [1]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError): validate_metadata(TrackMetadata(**kwargs))


class MetadataTests(MetadataCase):
    def test_every_supported_version_includes_inactive_metadata(self):
        for version in range(6, 11):
            with self.subTest(version=version): self.exhausted(SQLiteIntegrityScanner().scan(str(self.public(version))))

    def test_empty_duplicate_keys_and_strings_are_preserved(self):
        path = self.public()
        self.update(path, '[["",""],["",["", "x"]]]', '[["",[]],["",[""]]]', '["",""]')
        self.exhausted(SQLiteIntegrityScanner().scan(str(path)))

    def test_strict_common_tags_warnings_no_coercion_and_one_row_or(self):
        cases = [('{}','[]','[]'), ('[[1,"x"]]','[]','[]'), ('[["x",[1]]]','[]','[]'),
                 ('[]','[["x","text"]]','[]'), ('[]','[]','"text"'), ('[]','[]','[1]'),
                 ('{}','{}','[1]')]
        for common, tags, warnings in cases:
            with self.subTest(common=common, tags=tags, warnings=warnings):
                path = self.public(); self.update(path, common, tags, warnings)
                self.exhausted(SQLiteIntegrityScanner().scan(str(path)), ('metadata_contract_invalid',))

    def test_components_parse_independently_json_and_contract_coexist(self):
        for documents, expected in [ (('{','[','{'), ('metadata_json_invalid',)),
                                    (('{','{}','[]'), ('metadata_json_invalid','metadata_contract_invalid')),
                                    (('[]','{','[1]'), ('metadata_json_invalid','metadata_contract_invalid')) ]:
            with self.subTest(documents=documents):
                path = self.public(); self.update(path, *documents)
                self.exhausted(SQLiteIntegrityScanner().scan(str(path)), expected)

    def test_empty_metadata_stream_is_completed_exact_zero(self):
        path = self.public()
        with closing(sqlite3.connect(path)) as db: db.execute('DELETE FROM track_metadata'); db.commit()
        c = check(SQLiteIntegrityScanner().scan(str(path)))
        self.assertEqual((c.state,c.count,c.count_precision), ('completed',0,'exact'))

    def test_read_prefix_and_cleanup_are_lower_bound_not_exact(self):
        for options, count, stop in [({'read_after':0},0,'read_error'), ({'read_after':1},1,'read_error'),
                                      ({'fail_close':True},2,'cleanup_error')]:
            with self.subTest(options=options):
                path=self.public(); o=PhaseObservation(**options)
                with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',o.connect):
                    scan=SQLiteIntegrityScanner().scan(str(path))
                c=check(scan)
                self.assertEqual((c.state,c.count,c.count_precision),('interrupted',count,'lower_bound'))
                self.assertEqual(scan.stop_reason,stop); self.assertGreater(o.fired,0)
                self.assertFalse(findings(scan)); self.assertEqual(o.connections,1)

    def test_observed_corrupt_prefix_retains_lower_bound_finding(self):
        path=self.public(); self.update(path,'{',row=0); o=PhaseObservation(read_after=1)
        with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',o.connect):
            scan=SQLiteIntegrityScanner().scan(str(path))
        self.assertEqual(findings(scan),[('metadata_json_invalid',1,'lower_bound')])
        self.assertEqual((check(scan).count,check(scan).count_precision),(1,'lower_bound'))
        self.assertEqual(scan.stop_reason,'read_error')

    def test_missing_delivery_suppresses_unreliable_content(self):
        path=self.public(); self.update(path,'{','{}','[1]',row=0); o=PhaseObservation(missing_once=True)
        with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',o.connect):
            scan=SQLiteIntegrityScanner().scan(str(path))
        self.assertGreater(o.fired,0,'metadata row delivery seam must be reached')
        codes=[f.code for f in scan.findings if f.check_id=='metadata']
        self.assertIn('metadata_delivery_invalid',codes)
        self.assertNotIn('metadata_json_invalid',codes); self.assertNotIn('metadata_contract_invalid',codes)

    def test_unreliable_delivery_suppresses_content_findings(self):
        path=self.public(); self.update(path,'{','{}','[1]'); o=PhaseObservation(bad_size=True)
        with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',o.connect):
            scan=SQLiteIntegrityScanner().scan(str(path))
        self.assertGreater(o.fired,0,'metadata admission must consume size envelopes')
        codes=[f.code for f in scan.findings if f.check_id=='metadata']
        self.assertIn('metadata_delivery_invalid',codes)
        self.assertNotIn('metadata_json_invalid',codes); self.assertNotIn('metadata_contract_invalid',codes)


def enable_wal(path):
    with closing(sqlite3.connect(path)) as db:
        if db.execute('PRAGMA journal_mode=WAL').fetchone()!=('wal',):
            raise AssertionError('public WAL mode required')


def corrupt_after_pin(path,observation):
    # Exactly one additional connection while the read snapshot is pinned.
    with closing(observation.real_connect(path)) as writer:
        writer.execute("UPDATE track_metadata SET common_json='{' WHERE rowid=(SELECT min(rowid) FROM track_metadata)")
        writer.execute("UPDATE stages SET result='{' WHERE rowid=(SELECT min(rowid) FROM stages)")
        writer.commit()


class RuntimeControls(MetadataCase):
    def test_transparent_phase_entry_global_observation_eof_and_close(self):
        path=self.public(6)
        for table,expected in (('track_metadata',2),('stages',8)):
            with self.subTest(table=table):
                entries=[]; o=RuntimeObservation(table,on_entry=lambda obs: entries.append((obs.entry_rows,obs.entry_utf8)))
                with closing(o.connect(path)) as db:
                    c=db.execute('SELECT id FROM tracks'); self.assertEqual(len(list(c)),2); c.close()
                    c=db.execute('SELECT * FROM '+table); self.assertEqual(len(list(c)),expected); c.close()
                self.assertEqual(entries,[(2,142)])
                self.assertEqual(o.rows,dict(target=expected,other=2))
                self.assertEqual(o.eof,dict(target=1,other=1)); self.assertEqual(o.closed,dict(target=1,other=1))
                self.assertEqual(o.connection_closes,1)
                plain=SQLiteIntegrityScanner().scan(str(path)); transparent=RuntimeObservation(table)
                with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',transparent.connect):
                    wrapped=SQLiteIntegrityScanner().scan(str(path))
                self.assertEqual(wrapped,plain); self.assertFalse(plain.findings)
                self.assertEqual(len(transparent.calls),1); self.assertEqual(transparent.connection_closes,1)

    def test_real_wal_callback_commits_but_pinned_reader_keeps_both_old_documents(self):
        path=self.public(6); enable_wal(path); o=RuntimeObservation()
        o.on_pin=lambda: corrupt_after_pin(path,o)
        with closing(o.connect(path.as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('BEGIN').close()
            c=db.execute('SELECT common_json FROM track_metadata ORDER BY rowid'); before=list(c); c.close()
            c=db.execute('SELECT application_id FROM pragma_application_id'); self.assertEqual(c.fetchone(),(0x4D414E41,)); c.close()
            c=db.execute('SELECT common_json FROM track_metadata ORDER BY rowid'); self.assertEqual(list(c),before); c.close()
            c=db.execute('SELECT result FROM stages ORDER BY rowid'); self.assertTrue(all(row[0]!='{' for row in c)); c.close()
        self.assertEqual(o.pin_writes,1); self.assertEqual(o.connection_closes,1)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT common_json FROM track_metadata ORDER BY rowid').fetchone(),('{',))
            self.assertEqual(db.execute('SELECT result FROM stages ORDER BY rowid').fetchone(),('{',))

    def test_cancel_and_final_connection_cleanup_faults_are_targeted(self):
        path=self.public(6)
        for table in ('track_metadata','stages'):
            with self.subTest(table=table):
                o=RuntimeObservation(table,cancel=True,fail_close=True); db=o.connect(path)
                c=db.execute('SELECT id FROM tracks'); self.assertEqual(len(list(c)),2); c.close()
                c=db.execute('SELECT * FROM '+table)
                with self.assertRaises(KeyboardInterrupt): c.fetchone()
                c.close()
                with self.assertRaises(sqlite3.OperationalError): db.close()
                self.assertEqual((o.interrupts,o.connection_closes),(1,1))
                self.assertEqual(o.rows,dict(target=0,other=2)); self.assertEqual(o.closed,dict(target=1,other=1))


class RuntimeTests(MetadataCase):
    def assert_interrupted(self,scan,owner,stop,count=None):
        c=check(scan,owner)
        self.assertEqual((c.state,c.count_precision),('interrupted','lower_bound'))
        if count is not None: self.assertEqual(c.count,count)
        else: self.assertGreaterEqual(c.count,0)
        self.assertEqual(scan.stop_reason,stop); self.assertFalse(scan.implemented_scope_complete)
        self.assertFalse(findings(scan,owner),'operational stop is not a corruption verdict')
        if owner=='retained_stages':
            prior=check(scan)
            self.assertEqual((prior.state,prior.count,prior.count_precision),('completed',2,'exact'))

    def test_both_new_phases_share_the_original_real_wal_snapshot(self):
        path=self.public(6); enable_wal(path); o=RuntimeObservation()
        o.on_pin=lambda: corrupt_after_pin(path,o)
        with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',o.connect):
            scan=SQLiteIntegrityScanner().scan(str(path))
        self.assertEqual((o.pin_writes,len(o.calls),o.connection_closes),(1,1,1))
        self.assertIn('mode=ro',o.calls[0][0][0]); self.assertIs(o.calls[0][1]['uri'],True)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('SELECT common_json FROM track_metadata ORDER BY rowid').fetchone(),('{',))
            self.assertEqual(db.execute('SELECT result FROM stages ORDER BY rowid').fetchone(),('{',))
        fresh=SQLiteIntegrityScanner().scan(str(path))
        for owner,count,code in (('metadata',2,'metadata_json_invalid'),('retained_stages',8,'stage_json_invalid')):
            with self.subTest(owner=owner,view='pinned'):
                c=check(scan,owner); self.assertEqual((c.state,c.count,c.count_precision),('completed',count,'exact'))
                self.assertFalse(findings(scan,owner),'writer committed only after the shared snapshot was pinned')
            with self.subTest(owner=owner,view='fresh'):
                self.assertEqual(findings(fresh,owner),[(code,1,'exact')])

    def test_shared_row_and_utf8_budgets_include_all_earlier_phase_deliveries(self):
        # Independent baseline cursor observation computes caps; never inspect or
        # reset Delivery counters. A new per-phase meter would evade these caps.
        for table,owner in (('track_metadata','metadata'),('stages','retained_stages')):
            for budget,field in (('MAX_ROWS','entry_rows'),('MAX_UTF8_BYTES','entry_utf8')):
                with self.subTest(owner=owner,budget=budget):
                    path=self.public(6); baseline=RuntimeObservation(table)
                    with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',baseline.connect):
                        SQLiteIntegrityScanner().scan(str(path))
                    consumed=getattr(baseline,field)
                    self.assertIsNotNone(consumed,'baseline must reach new phase before calibrating shared cap')
                    self.assertGreater(consumed,0)
                    cap=consumed if budget=='MAX_ROWS' else consumed+1
                    o=RuntimeObservation(table)
                    with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',o.connect), patch(
                            'music_analyzer.infrastructure.persistence.integrity.'+budget,cap):
                        scan=SQLiteIntegrityScanner().scan(str(path))
                    self.assert_interrupted(scan,owner,'row_limit' if budget=='MAX_ROWS' else 'utf8_limit',
                                            0 if budget=='MAX_ROWS' else None)
                    self.assertEqual(o.connection_closes,1)

    def test_finding_group_budget_is_shared_with_earlier_owners(self):
        for owner in ('metadata','retained_stages'):
            with self.subTest(owner=owner):
                path=self.public(6)
                if owner=='metadata':
                    # Literal public tracks DDL has no size CHECK: valid SQL,
                    # genuine existing core policy corruption, not schema drift.
                    with closing(sqlite3.connect(path)) as db:
                        db.execute('UPDATE tracks SET size=-1 WHERE id=?',(self.ids[0],)); db.commit()
                    self.update(path,'{',row=0)
                    earlier=('core_rows','track_size_invalid')
                else:
                    self.update(path,'{',row=0); replace_stage(path,'{',raw=True)
                    earlier=('metadata','metadata_json_invalid')
                with patch('music_analyzer.infrastructure.persistence.integrity.MAX_GROUPS',1):
                    scan=SQLiteIntegrityScanner().scan(str(path))
                self.assertEqual(scan.stop_reason,'finding_limit')
                self.assertTrue(scan.findings_truncated)
                self.assertIn(earlier,[(f.check_id,f.code) for f in scan.findings])
                self.assertFalse(findings(scan,owner),'attempted excess group must not bypass the shared cap')
                c=check(scan,owner)
                self.assertEqual((c.state,c.count_precision),('interrupted','lower_bound'))
                self.assertGreaterEqual(c.count,1)

    def test_absolute_deadline_is_not_reset_on_new_phase_entry(self):
        for table,owner in (('track_metadata','metadata'),('stages','retained_stages')):
            with self.subTest(owner=owner):
                path=self.public(6); o=RuntimeObservation(table,on_entry=lambda obs: setattr(obs,'now',121))
                with patch('music_analyzer.infrastructure.persistence.integrity.monotonic',lambda:o.now), patch(
                        'music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',o.connect):
                    scan=SQLiteIntegrityScanner().scan(str(path))
                self.assert_interrupted(scan,owner,'deadline',0)
                self.assertEqual(o.connection_closes,1)

    def test_cancellation_wins_over_final_cleanup_for_each_new_phase(self):
        from music_analyzer.application.use_cases.check_integrity import CheckIntegrity
        for table,owner in (('track_metadata','metadata'),('stages','retained_stages')):
            with self.subTest(owner=owner):
                path=self.public(6); o=RuntimeObservation(table,cancel=True,fail_close=True)
                with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',o.connect):
                    report=CheckIntegrity(SQLiteIntegrityScanner()).execute(str(path))
                self.assertEqual((report.stop_reason,report.exit_code,report.complete),('cancelled',130,False))
                self.assertEqual(o.interrupts,1); self.assertEqual(o.connection_closes,1)
                codes=[f.code for f in report.findings if f.check_id=='resource_access']
                self.assertIn('cancelled',codes); self.assertIn('cleanup_failed',codes)
                c=check(report,owner)
                self.assertEqual((c.state,c.count,c.count_precision),('interrupted',0,'lower_bound'))

    def test_final_connection_cleanup_preserves_both_drained_phase_counts(self):
        path=self.public(6); o=RuntimeObservation(fail_close=True)
        with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',o.connect):
            scan=SQLiteIntegrityScanner().scan(str(path))
        self.assertEqual(scan.stop_reason,'cleanup_error'); self.assertEqual(o.connection_closes,1)
        for owner,count in (('metadata',2),('retained_stages',8)):
            with self.subTest(owner=owner):
                c=check(scan,owner)
                self.assertEqual((c.state,c.count,c.count_precision),('completed',count,'exact'))
        self.assertEqual((check(scan,'resource_access').state,check(scan,'resource_access').count_precision),
                         ('interrupted','lower_bound'))
