"""Small serial admission packets, never a giant size/encoding campaign.

Run each large test method in a separate bounded command. Each owns one database
at a time (<80MiB by construction), no more than one open connection. Native
SQLite allocation/timing is not certified by these functional assertions.
"""
from contextlib import closing
import json
import sqlite3
import unittest
from unittest.mock import patch

from music_analyzer.application.use_cases.check_integrity import CheckIntegrity
from music_analyzer.infrastructure.persistence.integrity import SQLiteIntegrityScanner
from tests.integration.infrastructure.integrity_d3_public_fixture import create_public_retained_database, replace_stage, stage_payload
from tests.integration.infrastructure.test_integrity_d3_metadata import MetadataCase, PhaseObservation, check, findings

LIMIT = 16 * 1024 * 1024


def sized_document(size):
    """Exact UTF8 bytes, with multibyte text proving characters != bytes."""
    value = stage_payload(); value['padding'] = ''
    base = json.dumps(value, ensure_ascii=False)
    remaining = size - len(base.encode('utf-8'))
    value['padding'] = '\u00e9' * (remaining // 2) + 'x' * (remaining % 2)
    return json.dumps(value, ensure_ascii=False)


def split_utf16_document():
    """Place one UTF16 surrogate pair across the 4096-byte storage fragment."""
    prefix='{"padding":"'
    bom=b'\xff\xfe'
    padding=(4094-len(bom)-len(prefix.encode('utf-16le')))//2
    text=prefix+'x'*padding+'\U0001f600'+'",'+json.dumps(stage_payload(),ensure_ascii=False)[1:]
    return bom+text.encode('utf-16le')


class AdmissionControls(MetadataCase):
    def test_small_encoding_packet_and_transparent_stage_proxy(self):
        raw = json.dumps(stage_payload())
        for encoding in ('utf-8-sig', 'utf-16', 'utf-32'):
            with self.subTest(encoding=encoding): self.assertEqual(json.loads(raw.encode(encoding)), stage_payload())
        self.assertEqual(len(sized_document(4097).encode('utf-8')),4097)
        self.assertLess(len(sized_document(4097)),4097)
        split=split_utf16_document()
        self.assertEqual(split[4094:4098],b'\x3d\xd8\x00\xde')
        decoded=json.loads(split)
        self.assertEqual(decoded.pop('padding')[-1],'\U0001f600')
        self.assertEqual(decoded,stage_payload())
        path=self.public(); o=PhaseObservation('stages')
        with closing(o.connect(path)) as db:
            for query in ('SELECT result FROM stages','SELECT common_json FROM track_metadata'):
                c=db.execute(query); self.assertEqual(len(list(c)),8 if 'stages' in query else 2); c.close()
        self.assertEqual(o.rows,dict(target=8,other=2)); self.assertEqual(o.eof,dict(target=1,other=1))
        self.assertEqual(o.closed,dict(target=1,other=1))
        plain=SQLiteIntegrityScanner().scan(str(path))
        with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',o.connect):
            wrapped=SQLiteIntegrityScanner().scan(str(path))
        self.assertEqual(wrapped,plain); self.assertFalse(plain.findings)

    def test_raw_blob_surrogate_is_distinct_from_escaped_json_surrogate(self):
        raw=b'{"padding":"\xed\xa0\x80"}'
        parsed=json.loads(raw)
        self.assertEqual(parsed['padding'],'\ud800')
        with self.assertRaises(UnicodeEncodeError): raw.decode('utf-8',errors='surrogatepass').encode('utf-8')
        escaped=json.dumps({'padding':'\ud800'})
        self.assertTrue(escaped.isascii()); self.assertEqual(json.loads(escaped),parsed)


class RetainedAdmissionTests(MetadataCase):
    def stage_completed(self,scan,codes=()):
        c=check(scan,'retained_stages')
        self.assertEqual((c.state,c.count,c.count_precision),('completed',8,'exact'))
        self.assertEqual(findings(scan,'retained_stages'),[(code,1,'exact') for code in codes])
        self.assertEqual(scan.stop_reason,'completed')
        self.assertTrue(scan.implemented_scope_complete)
        class Retained:
            def scan(self, database, deadline_seconds=120):
                return scan
        self.assertEqual(CheckIntegrity(Retained()).execute('public.sqlite').exit_code, 1 if codes else 0)

    def boundary(self,size,oversized):
        path=self.public(); raw=sized_document(size)
        self.assertEqual(len(raw.encode('utf-8')),size)
        replace_stage(path,raw,raw=True); del raw
        o=PhaseObservation('stages')
        with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',o.connect):
            scan=SQLiteIntegrityScanner().scan(str(path))
        self.stage_completed(scan,('stage_payload_oversized',) if oversized else ())
        self.assertEqual(o.connections,1,'all phases must share the pinned connection')
        if oversized:
            self.assertLessEqual(o.largest_text,LIMIT,'oversized whole document must not cross Python cursor delivery')

    def test_under_utf8_boundary(self): self.boundary(LIMIT-1,False)
    def test_exact_utf8_boundary(self): self.boundary(LIMIT,False)
    def test_over_utf8_boundary_is_admitted_before_whole_document(self): self.boundary(LIMIT+1,True)

    def test_metadata_has_no_new_sixteen_mib_domain_cap(self):
        path=self.public()
        common=json.dumps([['public','x'*(LIMIT+1)]])
        self.update(path,common); del common
        self.exhausted(SQLiteIntegrityScanner().scan(str(path)))

    def test_small_blob_encodings_text_bom_and_embedded_nul_packet(self):
        cases=[(sqlite3.Binary(split_utf16_document()),())]
        for encoding in ('utf-8-sig','utf-16','utf-32'):
            cases.append((sqlite3.Binary(json.dumps(stage_payload()).encode(encoding)),()))
        value=stage_payload(); value['values']=[['text','\u0000']]
        cases.append((json.dumps(value),()))
        cases.extend([('\ufeff'+json.dumps(stage_payload()),('stage_json_invalid',)),
                      (json.dumps(stage_payload())+'\u0000',('stage_json_invalid',))])
        for raw,codes in cases:
            with self.subTest(kind=type(raw).__name__,codes=codes):
                path=self.public(); replace_stage(path,raw,raw=True)
                self.stage_completed(SQLiteIntegrityScanner().scan(str(path)),codes)

    def test_utf16_text_storage_counts_decoded_utf8_not_storage_bytes(self):
        # Small functional encoding control, not another large boundary campaign.
        path=self.public()
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute('PRAGMA encoding').fetchone(),('UTF-8',))
        # Set connection encoding BEFORE the literal historical scaffold creates
        # its first schema object. No post-hoc version downgrade or schema change.
        path16=path.with_name('utf16.sqlite')
        real_connect=sqlite3.connect
        def utf16_connect(*args,**kwargs):
            db=real_connect(*args,**kwargs)
            db.execute("PRAGMA encoding='UTF-16le'").close()
            return db
        with patch('sqlite3.connect',utf16_connect):
            create_public_retained_database(path16,6)
        value=stage_payload(); value['values']=[['text','é\u0000雪']]
        replace_stage(path16,value)
        with closing(sqlite3.connect(path16)) as db:
            self.assertEqual(db.execute('PRAGMA encoding').fetchone(),('UTF-16le',))
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone(),('ok',))
        self.stage_completed(SQLiteIntegrityScanner().scan(str(path16)))

    def test_raw_blob_surrogate_is_operational_escaped_surrogate_is_preserved(self):
        for raw,operational in [(json.dumps(stage_payload()).replace('public retained control','\\ud800'),False),
                                (sqlite3.Binary(json.dumps(stage_payload()).encode().replace(b'public retained control',b'\xed\xa0\x80')),True)]:
            with self.subTest(operational=operational):
                path=self.public(); replace_stage(path,raw,raw=True)
                scan=SQLiteIntegrityScanner().scan(str(path))
                if operational:
                    self.assertEqual(scan.stop_reason,'read_error'); self.assertFalse(scan.implemented_scope_complete)
                    self.assertFalse(findings(scan,'retained_stages'),'codec sizing failure is not corruption')
                else: self.stage_completed(scan)

    def test_retained_late_prefix_and_cleanup_precision(self):
        for options,count,stop in [({'read_after':1},1,'read_error'),({'fail_close':True},8,'cleanup_error')]:
            with self.subTest(options=options):
                path=self.public(); o=PhaseObservation('stages',**options)
                with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',o.connect):
                    scan=SQLiteIntegrityScanner().scan(str(path))
                c=check(scan,'retained_stages')
                self.assertEqual((c.state,c.count,c.count_precision),('interrupted',count,'lower_bound'))
                self.assertEqual(scan.stop_reason,stop); self.assertGreater(o.fired,0)
                self.assertEqual(check(scan).count_precision,'exact','earlier drained metadata survives later failure')
                self.assertFalse(findings(scan,'retained_stages'))

    def test_retained_observed_corrupt_prefix_is_lower_bound(self):
        path=self.public(); replace_stage(path,'{',raw=True); o=PhaseObservation('stages',read_after=1)
        with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',o.connect):
            scan=SQLiteIntegrityScanner().scan(str(path))
        self.assertEqual(findings(scan,'retained_stages'),[('stage_json_invalid',1,'lower_bound')])
        c=check(scan,'retained_stages')
        self.assertEqual((c.count,c.count_precision),(1,'lower_bound'))
        self.assertEqual(scan.stop_reason,'read_error')

    def test_retained_missing_delivery_suppresses_content(self):
        path=self.public(); replace_stage(path,'{',raw=True); o=PhaseObservation('stages',missing_once=True)
        with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',o.connect):
            scan=SQLiteIntegrityScanner().scan(str(path))
        self.assertGreater(o.fired,0,'retained delivery seam must be reached')
        codes=[f.code for f in scan.findings if f.check_id=='retained_stages']
        self.assertIn('stage_delivery_invalid',codes)
        self.assertNotIn('stage_json_invalid',codes); self.assertNotIn('stage_contract_invalid',codes)

    def test_retained_unreliable_size_suppresses_content_findings(self):
        path=self.public(); replace_stage(path,'{',raw=True); o=PhaseObservation('stages',bad_size=True)
        with patch('music_analyzer.infrastructure.persistence.integrity.sqlite3.connect',o.connect):
            scan=SQLiteIntegrityScanner().scan(str(path))
        self.assertGreater(o.fired,0,'retained admission must consume size envelopes')
        codes=[f.code for f in scan.findings if f.check_id=='retained_stages']
        self.assertIn('stage_delivery_invalid',codes)
        self.assertNotIn('stage_json_invalid',codes); self.assertNotIn('stage_contract_invalid',codes)
