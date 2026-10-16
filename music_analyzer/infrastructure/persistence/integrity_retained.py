"""Bounded retained-document delivery in the diagnostic's pinned snapshot.

Only storage/codec/JSON translation lives here. Established decoded-value policy
is supplied by inward predicates; no writer or private reader is invoked.
"""
import codecs
import json
import sqlite3

from music_analyzer.application.use_cases.metadata_validation import (
    metadata_common_valid, metadata_tags_valid, metadata_warnings_valid,
)
from music_analyzer.application.use_cases.stage_result_mapping import stage_from_mapping
from music_analyzer.application.use_cases.stage_result_validation import validate_stage_result

STAGE_BYTES = 16 << 20
CODES = ('metadata_json_invalid', 'metadata_contract_invalid', 'metadata_delivery_invalid',
         'stage_json_invalid', 'stage_contract_invalid', 'stage_identity_invalid',
         'stage_payload_oversized', 'stage_delivery_invalid')


def _charge(delivery, size):
    from music_analyzer.infrastructure.persistence.integrity import MAX_UTF8_BYTES, AdmissionStop
    if size > MAX_UTF8_BYTES - delivery.utf8_bytes:
        raise AdmissionStop('utf8_limit')
    delivery.utf8_bytes += size


def _decoded_size(delivery, table, column, identity, kind, storage, stage):
    """Exact decoded UTF8 sizing without whole delivery; preserve split units/NUL."""
    if kind == 'text' and delivery.encoding == 'UTF-8':
        return storage, None
    decoder = None
    total = 0
    for offset in range(1, storage + 1, 4096):
        cursor = delivery.execute(
            f'SELECT substr(CAST({column} AS BLOB),?,4096) FROM {table} WHERE rowid=?',
            (offset, identity))
        try:
            row = delivery.one(cursor)
            if (row is None or len(row) != 1 or not isinstance(row[0], bytes)
                    or len(row[0]) != min(4096, storage - offset + 1)):
                return None, 'delivery'
            fragment = row[0]
            if decoder is None:
                codec = (json.detect_encoding(fragment) if kind == 'blob' else
                         {'UTF-16le': 'utf-16-le', 'UTF-16be': 'utf-16-be'}[delivery.encoding])
                decoder = codecs.getincrementaldecoder(codec)(errors='surrogatepass' if kind == 'blob' else 'strict')
            try:
                text = decoder.decode(fragment, final=offset + len(fragment) > storage)
            except UnicodeError:
                if kind == 'blob':
                    return None, 'json'
                raise
            # A raw decoded surrogate cannot be strictly UTF8-sized: operational
            # read failure, unlike a JSON escape which remains ordinary input.
            size = len(text.encode('utf-8'))
            _charge(delivery, size)
            total += size
            if stage and total > STAGE_BYTES:
                return total, None
        except (sqlite3.Error, OSError, UnicodeError, MemoryError):
            delivery.observe_error()
            raise
        finally:
            delivery.close_all(cursor)
    return total, None


def _parse(raw):
    if not isinstance(raw, (str, bytes)):
        return None, False
    try:
        return json.loads(raw), True
    except (ValueError, UnicodeError, RecursionError):
        return None, False


def _stage_codes(raw, name):
    value, parsed = _parse(raw)
    if not parsed:
        return ('stage_json_invalid',)
    try:
        if not isinstance(value, dict):
            raise ValueError('Object required')
        mapped = stage_from_mapping(value)
        validate_stage_result(mapped)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, ArithmeticError):
        return ('stage_contract_invalid',)
    return ('stage_identity_invalid',) if mapped.stage != name else ()


def scan_retained(delivery, owner):
    from music_analyzer.infrastructure.persistence.integrity import (
        MAX_VALUE_BYTES, MAX_UTF8_BYTES, AdmissionStop, DeliveryMismatch, check, finding,
    )
    stage = owner == 'retained_stages'
    table = 'stages' if stage else 'track_metadata'
    columns = ('result',) if stage else ('common_json', 'tags_json', 'warnings_json')
    prefix = 'stage' if stage else 'metadata'
    counts = {}
    delivery.retained_findings[owner] = counts
    delivery.retained_work[owner] = 0
    sizes = [f"CASE typeof({c}) WHEN 'text' THEN length(CAST({c} AS BLOB)) "
             f"WHEN 'blob' THEN -1-length({c}) ELSE NULL END" for c in columns]
    envelope_sql = ('SELECT ' + ','.join(sizes + [f'typeof({c})' for c in columns] + ['rowid'] +
                    (['length(CAST(stage AS BLOB))'] if stage else []) + ['count(*) OVER()']) + f' FROM {table} ORDER BY rowid')
    # Never deliver a whole BLOB/UTF16 document via the global stream. Such
    # documents receive exact fragment admission followed by a bounded lookup.
    if stage:
        expression = (f"CASE WHEN typeof(result)='text' AND length(CAST(result AS BLOB))<={STAGE_BYTES} "
                      "THEN result ELSE NULL END" if delivery.encoding == 'UTF-8' else 'NULL')
        value_sql = f'SELECT rowid,stage,{expression} FROM stages ORDER BY rowid'
    else:
        value_sql = 'SELECT rowid,' + ','.join(columns) + ' FROM track_metadata ORDER BY rowid'
    envelopes = delivery.execute(envelope_sql)
    values = None
    total = None
    observed = 0
    delivered = 0
    aligned = True
    try:
        # This envelope contains only sizes, numeric identity/cardinality and
        # fixed SQLite typeof enums, never document text or stage names. Its
        # initial EOF probe can prove an empty phase at the exhausted row cap;
        # a present record is rejected before inspection or admission.
        while (envelope := delivery.one(
                envelopes, expected_eof=total is not None and observed == total,
                projection_eof=total is None)) is not None:
            if not envelope:
                # No cardinality field can authorize this delivery or catch-up.
                # Stop operationally, preserving earlier completed phase evidence.
                raise sqlite3.DatabaseError('delivery cardinality unavailable')
            cardinality = envelope[-1]
            if (type(cardinality) is not int or cardinality < 1
                    or (total is not None and total != cardinality)):
                raise sqlite3.DatabaseError('delivery cardinality invalid')
            total = cardinality
            observed += 1
            envelope = envelope[:-1]
            for value in envelope:
                if isinstance(value, str):
                    _charge(delivery, len(value.encode('utf-8')))
            seen = set()

            def record(suffix):
                code = prefix + '_' + suffix
                if code not in seen:
                    delivery.claim_group(owner, code)
                    counts[code] = counts.get(code, 0) + 1
                    seen.add(code)

            def abandon():
                nonlocal aligned, values
                # An unconsumed or mismatched row makes the paired stream
                # unusable. Never catch up by fetching unadmitted payloads.
                aligned = False
                delivery.close_all(values)
                values = None

            if not aligned:
                delivery.retained_work[owner] += 1
                record('delivery_invalid')
                continue

            n = len(columns)
            if len(envelope) != 2*n + 1 + int(stage):
                delivery.retained_work[owner] += 1
                record('delivery_invalid')
                abandon()
                continue
            lengths, kinds = envelope[:n], envelope[n:2*n]
            identity = envelope[2*n]
            reliable = type(identity) is int and all((length is None and kind in ('null', 'integer', 'real')) or
                           (type(length) is int and ((kind == 'text' and length >= 0) or
                                                     (kind == 'blob' and length < 0)))
                           for length, kind in zip(lengths, kinds))
            if not reliable:
                delivery.retained_work[owner] += 1
                record('delivery_invalid')
                # Do not let an unreliable envelope authorize any whole value.
                abandon()
                continue
            decoded = []
            faults = []
            for column, length, kind in zip(columns, lengths, kinds):
                storage = length if kind == 'text' else (-1-length if kind == 'blob' else 0)
                if kind in ('text', 'blob'):
                    size, fault = _decoded_size(delivery, table, column, identity, kind, storage, stage)
                else:
                    size, fault = 0, None
                decoded.append(size)
                faults.append(fault)
            if 'delivery' in faults:
                delivery.retained_work[owner] += 1
                record('delivery_invalid')
                abandon()
                continue
            oversized = stage and decoded[0] is not None and decoded[0] > STAGE_BYTES
            # The global stage stream substitutes NULL for documents needing a
            # lookup or exceeding the domain limit. Metadata has no domain cap.
            upper = 0
            for length, kind, size in zip(lengths, kinds, decoded):
                storage = length if kind == 'text' else (-1-length if kind == 'blob' else 0)
                bound = storage * (delivery.encoding_factor if kind == 'text' else 1)
                value_delivered = not stage or (kind == 'text' and delivery.encoding == 'UTF-8' and not oversized)
                if value_delivered:
                    if bound > MAX_VALUE_BYTES:
                        raise AdmissionStop('value_limit')
                    upper += size or 0
            if stage:
                name_size = envelope[-1]
                if type(name_size) is not int or name_size < 0:
                    delivery.retained_work[owner] += 1
                    record('delivery_invalid')
                    abandon()
                    continue
                if name_size * delivery.encoding_factor > MAX_VALUE_BYTES:
                    raise AdmissionStop('value_limit')
                upper += name_size * delivery.encoding_factor
            if upper > MAX_UTF8_BYTES - delivery.utf8_bytes:
                raise AdmissionStop('utf8_limit')
            if values is None:
                values = delivery.execute(value_sql)
            row = delivery.one(values)
            delivered += int(row is not None)
            delivery.retained_work[owner] += 1
            if row is None or len(row) != (3 if stage else n+1) or row[0] != identity:
                record('delivery_invalid')
                # Drain only envelopes; all remaining content is untrustworthy.
                abandon()
                continue
            for value in row:
                if isinstance(value, str):
                    _charge(delivery, len(value.encode('utf-8')))
            if not stage:
                for value, size in zip(row[1:], decoded):
                    if isinstance(value, bytes):
                        _charge(delivery, size or 0)
            if oversized:
                record('payload_oversized')
                continue
            if stage:
                if faults[0] == 'json':
                    record('json_invalid')
                    continue
                raw = row[2]
                kind = kinds[0]
                if kind in ('text', 'blob') and (kind == 'blob' or delivery.encoding != 'UTF-8'):
                    storage = lengths[0] if kind == 'text' else -1-lengths[0]
                    bound = storage * (delivery.encoding_factor if kind == 'text' else 1)
                    if bound > MAX_VALUE_BYTES:
                        raise AdmissionStop('value_limit')
                    if decoded[0] > MAX_UTF8_BYTES - delivery.utf8_bytes:
                        raise AdmissionStop('utf8_limit')
                    cursor = delivery.execute('SELECT result FROM stages WHERE rowid=?', (identity,))
                    try:
                        payload = delivery.one(cursor)
                        if payload is None or len(payload) != 1:
                            record('delivery_invalid')
                            continue
                        raw = payload[0]
                        _charge(delivery, decoded[0])
                    finally:
                        delivery.close_all(cursor)
                for code in _stage_codes(raw, row[1]):
                    record(code.removeprefix('stage_'))
            else:
                for raw, fault, valid in zip(row[1:], faults,
                                            (metadata_common_valid, metadata_tags_valid, metadata_warnings_valid)):
                    value, parsed = _parse(raw) if fault != 'json' else (None, False)
                    if not parsed:
                        record('json_invalid')
                    elif not valid(value):
                        record('contract_invalid')
        if total is not None and observed < total:
            # Premature envelope EOF cannot authorize the remaining payloads.
            # Attach the protocol fault to the last observed physical row.
            record('delivery_invalid')
            abandon()
        extra = False
        if values is not None:
            try:
                extra = delivery.one(values, expected_eof=total is not None and delivered == total) is not None
            except DeliveryMismatch:
                extra = True
        if extra:
            # Terminal presence belongs to the last observed row, not a new
            # admitted row. OR with any finding already recorded for that row.
            record('delivery_invalid')
    except DeliveryMismatch:
        # Envelope EOF presence is owner-invalid, not a SQLite driver failure.
        record('delivery_invalid')
    except (sqlite3.Error, OSError, UnicodeError, MemoryError):
        delivery.observe_error()
        raise
    finally:
        delivery.close_all(envelopes, values)
    return check(owner, 'completed', delivery.retained_work[owner], 'rows'), tuple(
        finding(owner, code, count) for code, count in counts.items())
