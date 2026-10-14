"""Fixed-query evidence delivery details for the read-only diagnostic."""
import codecs
import json
import sqlite3

from music_analyzer.application.use_cases.integrity_evidence import (
    EvidenceCode, classify_envelope, classify_fingerprint_syntax,
    classify_links, classify_payload,
)

DOMAIN_BYTES = 16 << 20


def _charge(delivery, text):
    from music_analyzer.infrastructure.persistence.integrity import MAX_UTF8_BYTES, AdmissionStop
    size = len(text.encode('utf-8'))
    if size > MAX_UTF8_BYTES - delivery.utf8_bytes:
        raise AdmissionStop('utf8_limit')
    delivery.utf8_bytes += size
    return size


def _document_size(delivery, track, run, storage, kind):
    """Count decoded document UTF8 with bounded fragments, including actual NUL."""
    if kind == 'text' and delivery.encoding == 'UTF-8':
        return storage, None
    decoder = None
    total = 0
    for offset in range(1, storage + 1, 4096):
        cursor = delivery.execute(
            'SELECT substr(CAST(evidence_json AS BLOB),?,4096) '
            'FROM graph_feature_evidence WHERE track_id=? AND run_id=?',
            (offset, track, run))
        try:
            row = delivery.one(cursor)
            if (row is None or not isinstance(row[0], bytes)
                    or len(row[0]) != min(4096, storage - offset + 1)):
                return None, EvidenceCode.DELIVERY_INVALID
            fragment = row[0]
            if decoder is None:
                codec = (json.detect_encoding(fragment) if kind == 'blob'
                         else {'UTF-16le': 'utf-16-le', 'UTF-16be': 'utf-16-be'}[delivery.encoding])
                decoder = codecs.getincrementaldecoder(codec)(errors='surrogatepass' if kind == 'blob' else 'strict')
            try:
                decoded = decoder.decode(fragment, final=offset + len(fragment) > storage)
            except UnicodeError:
                if kind == 'blob':
                    return None, EvidenceCode.JSON_INVALID
                raise
            try:
                total += _charge(delivery, decoded)
            except UnicodeEncodeError:
                if kind == 'blob':
                    return None, EvidenceCode.FINGERPRINT_INVALID
                raise
            if total > DOMAIN_BYTES:
                return total, None
        except (sqlite3.Error, OSError, UnicodeError):
            delivery.observe_error()
            raise
        finally:
            delivery.close_all(cursor)
    return total, None


def _admit_full_row(delivery, track, run, storage, kind, decoded_size):
    from music_analyzer.infrastructure.persistence.integrity import MAX_VALUE_BYTES, MAX_UTF8_BYTES, AdmissionStop
    bound = storage * (delivery.encoding_factor if kind == 'text' else 1)
    if bound > MAX_VALUE_BYTES:
        raise AdmissionStop('value_limit')
    utf8_bound = bound if kind == 'text' else decoded_size
    # The envelope already delivered these identities in this pinned snapshot.
    # The full row repeats them, so admit their UTF8 again before fetching it.
    utf8_bound += sum(len(value.encode('utf-8')) for value in (track, run)
                      if isinstance(value, str))
    if utf8_bound > MAX_UTF8_BYTES - delivery.utf8_bytes:
        raise AdmissionStop('utf8_limit')


def _full_row(delivery, cursor, track, run, storage, kind, decoded_size):
    _admit_full_row(delivery, track, run, storage, kind, decoded_size)
    row = delivery.one(cursor)
    if row is not None:
        for value in row:
            if isinstance(value, str):
                _charge(delivery, value)
        if isinstance(row[2], bytes):
            # Bounded preflight proved decoded size in this pinned snapshot.
            delivery.utf8_bytes += decoded_size
    return row


def _payload(delivery, track, run, fingerprint, storage, kind, decoded_size, record):
    _admit_full_row(delivery, track, run, storage, kind, decoded_size)
    cursor = delivery.execute('SELECT track_id,run_id,evidence_json FROM graph_feature_evidence '
                              'WHERE track_id=? AND run_id=?', (track, run))
    try:
        row = _full_row(delivery, cursor, track, run, storage, kind, decoded_size)
        if row is None:
            record(EvidenceCode.DELIVERY_INVALID)
            return
        if row[:2] != (track, run):
            record(EvidenceCode.DELIVERY_INVALID)
        else:
            raw = row[2]
            try:
                if not isinstance(raw, (str, bytes, bytearray)):
                    record(EvidenceCode.JSON_INVALID)
                else:
                    try:
                        parsed = json.loads(raw)
                    except (ValueError, UnicodeError, RecursionError):
                        record(EvidenceCode.JSON_INVALID)
                    else:
                        for code in classify_payload(track, run, fingerprint, parsed):
                            record(code)
                        del parsed
            finally:
                del raw
        del row
        if _full_row(delivery, cursor, track, run, storage, kind, decoded_size) is not None:
            record(EvidenceCode.DELIVERY_INVALID)
    except (sqlite3.Error, OSError, UnicodeError):
        delivery.observe_error()
        raise
    finally:
        delivery.close_all(cursor)


def scan_evidence(delivery, owner):
    from music_analyzer.infrastructure.persistence.integrity import check, finding
    counts = {}
    delivery.evidence_findings[owner] = counts
    delivery.evidence_work[owner] = 0
    current = owner == 'current_evidence'
    if current:
        # Normally prevented by the genuine partial unique index. Diagnose the
        # exceptional relation once per violating track, not per row or pair.
        duplicates = delivery.rows('SELECT 1 AS marker FROM graph_feature_evidence WHERE is_current=1 '
                                   'GROUP BY track_id HAVING count(*)>1', ('marker',))
        try:
            for _ in duplicates:
                delivery.claim_group(owner, EvidenceCode.LINK_INVALID.value)
                counts[EvidenceCode.LINK_INVALID.value] = counts.get(EvidenceCode.LINK_INVALID.value, 0) + 1
        finally:
            duplicates.close()
    where = 'is_current=1' if current else 'is_current IS NOT 1'
    columns = ('track_id', 'run_id', 'is_current', 'fingerprint', 'payload_type',
               '"length(evidence_json)"')
    rows = delivery.rows('SELECT track_id,run_id,is_current,fingerprint,typeof(evidence_json) AS payload_type,'
                         'length(CAST(evidence_json AS BLOB)) AS "length(evidence_json)"'
                         ' FROM graph_feature_evidence WHERE ' + where + ' ORDER BY track_id,run_id', columns)
    try:
        for track, run, flag, fingerprint, kind, storage in rows:
            delivery.evidence_work[owner] += 1
            seen = set()

            def record(code):
                if code not in seen:
                    delivery.claim_group(owner, code.value)
                    counts[code.value] = counts.get(code.value, 0) + 1
                    seen.add(code)

            for code in classify_envelope(track, run, flag) + classify_fingerprint_syntax(fingerprint):
                record(code)
            completed = delivery.scalar('SELECT EXISTS(SELECT 1 FROM runs WHERE id=? AND status=\'completed\') AS n', ('n',), (run,))
            pair = delivery.scalar('SELECT EXISTS(SELECT 1 FROM run_tracks WHERE track_id=? AND run_id=?) AS n', ('n',), (track, run))
            latest = delivery.scalar('SELECT EXISTS(SELECT 1 FROM runs WHERE id=? AND id=(SELECT runs.id FROM runs JOIN run_tracks ON run_tracks.run_id=runs.id WHERE run_tracks.track_id=? ORDER BY runs.rowid DESC LIMIT 1)) AS n', ('n',), (run, track)) if current else True
            for code in classify_links(run_completed=bool(completed), pair_exists=bool(pair), current=current, latest_matches=bool(latest)):
                record(code)
            if kind in ('text', 'blob'):
                if isinstance(storage, bool) or not isinstance(storage, int) or storage < 0:
                    record(EvidenceCode.DELIVERY_INVALID)
                    continue
                size, code = _document_size(delivery, track, run, storage, kind)
                if code is not None:
                    record(code)
                    continue
                if size > DOMAIN_BYTES:
                    record(EvidenceCode.PAYLOAD_OVERSIZED)
                    continue
                _payload(delivery, track, run, fingerprint, storage, kind, size, record)
            else:
                record(EvidenceCode.JSON_INVALID)
    finally:
        rows.close()
    return check(owner, 'completed', delivery.evidence_work[owner], 'rows'), tuple(
        finding(owner, code, count) for code, count in counts.items())
