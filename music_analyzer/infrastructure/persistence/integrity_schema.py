"""Dedicated diagnostic copies of the stable FULL-reader schema contract.

Readers keep ownership of their literals and remain unchanged. No writer tolerance.
"""

_EXPECTED_SCHEMA = {
    'runs': {
        'columns': ((('id', 'TEXT', False, 1), ('location', 'TEXT', True, 0), ('status', 'TEXT', True, 0),
                     ('detail', 'TEXT', True, 0), ('created_at', 'TEXT', True, 0)),
                    (('id', 'TEXT', False, 1), ('location', 'TEXT', False, 0), ('status', 'TEXT', False, 0),
                     ('detail', 'TEXT', False, 0), ('created_at', 'TEXT', False, 0))),
        'foreign_keys': ((),),
        'unique_indexes': (),
        'checks': (("CHECK(status IN ('running','completed','failed','interrupted'))",), ()),
    },
    'stages': {
        'columns': ((('run_id', 'TEXT', True, 1), ('stage', 'TEXT', True, 2), ('result', 'TEXT', True, 0)),
                    (('run_id', 'TEXT', False, 1), ('stage', 'TEXT', False, 2), ('result', 'TEXT', False, 0))),
        'foreign_keys': ((('runs', ('run_id',), ('id',)),), ()),
        'unique_indexes': (),
        'checks': ((),),
    },
    'tracks': {
        'columns': ((('id', 'TEXT', False, 1), ('sha256', 'TEXT', True, 0), ('size', 'INTEGER', True, 0)),),
        'foreign_keys': ((),),
        'unique_indexes': (('sha256',),),
        'checks': ((),),
    },
    'locations': {
        'columns': ((('path', 'TEXT', False, 1), ('track_id', 'TEXT', True, 0), ('mtime_ns', 'INTEGER', True, 0),
                     ('format', 'TEXT', True, 0), ('available', 'INTEGER', True, 0)),),
        'foreign_keys': ((('tracks', ('track_id',), ('id',)),),),
        'unique_indexes': (),
        'checks': (('CHECK(available IN (0,1))',),),
    },
    'scan_roots': {
        'columns': ((('root', 'TEXT', True, 1), ('path', 'TEXT', True, 2)),),
        'foreign_keys': ((('locations', ('path',), ('path',)),),),
        'unique_indexes': (),
        'checks': ((),),
    },
    'batch_jobs': {
        'columns': ((('track_id', 'TEXT', False, 1), ('fingerprint', 'TEXT', True, 0), ('state', 'TEXT', True, 0),
                     ('attempts', 'INTEGER', True, 0), ('run_id', 'TEXT', False, 0), ('detail', 'TEXT', True, 0)),),
        'foreign_keys': ((('tracks', ('track_id',), ('id',)),),),
        'unique_indexes': (),
        'checks': (("CHECK(state IN ('pending','running','completed','failed'))", 'CHECK(attempts >= 0)'),),
    },
    'run_tracks': {
        'columns': ((('run_id', 'TEXT', False, 1), ('track_id', 'TEXT', True, 0)),),
        'foreign_keys': ((('runs', ('run_id',), ('id',)), ('tracks', ('track_id',), ('id',))),),
        'unique_indexes': (),
        'checks': ((),),
    },
    'overrides': {
        'columns': ((('track_id', 'TEXT', True, 1), ('field', 'TEXT', True, 2), ('value', 'TEXT', True, 0)),),
        'foreign_keys': ((('tracks', ('track_id',), ('id',)),),),
        'unique_indexes': (),
        'checks': ((),),
    },
    'track_metadata': {
        'columns': ((('track_id', 'TEXT', False, 1), ('common_json', 'TEXT', True, 0), ('tags_json', 'TEXT', True, 0), ('warnings_json', 'TEXT', True, 0)),),
        'foreign_keys': ((('tracks', ('track_id',), ('id',)),),),
        'unique_indexes': (),
        'checks': ((),),
    },
    'track_audio': {
        'columns': ((('track_id', 'TEXT', False, 1), ('duration_seconds', 'REAL', False, 0), ('duration_source', 'TEXT', True, 0), ('status', 'TEXT', True, 0), ('reason', 'TEXT', True, 0)),),
        'foreign_keys': ((('tracks', ('track_id',), ('id',)),),),
        'unique_indexes': (),
        'checks': (("CHECK(status IN ('eligible','excluded','unknown'))",),),
    },
}

_EXPECTED_GRAPH_SCHEMA = {
    'graph_edges': {
        'columns': ((('source_track_id', 'TEXT', True, 1), ('target_track_id', 'TEXT', True, 2), ('score', 'REAL', True, 0),
                     ('distance', 'REAL', True, 0), ('supported_group_count', 'INTEGER', True, 0),
                     ('distance_policy_version', 'TEXT', True, 0), ('neighbour_policy_version', 'TEXT', True, 0),
                     ('built_at', 'TEXT', True, 0)),),
        'foreign_keys': ((('tracks', ('source_track_id',), ('id',)), ('tracks', ('target_track_id',), ('id',))),),
        'unique_indexes': (),
        'checks': (('CHECK(source_track_id < target_track_id)', 'CHECK(score >= 0.0 AND score <= 1.0)', 'CHECK(distance >= 0.0 AND distance <= 1.0)'),),
    },
    'graph_builds': {
        'columns': ((('id', 'TEXT', False, 1), ('status', 'TEXT', True, 0), ('detail', 'TEXT', True, 0),
                     ('edge_count', 'INTEGER', True, 0), ('sparse_k', 'INTEGER', True, 0), ('source_fingerprint', 'TEXT', True, 0),
                     ('source_revision', 'TEXT', True, 0), ('attempt_revision', 'TEXT', True, 0),
                     ('distance_policy_version', 'TEXT', True, 0), ('neighbour_policy_version', 'TEXT', True, 0),
                     ('is_current', 'INTEGER', True, 0), ('created_at', 'TEXT', True, 0), ('completed_at', 'TEXT', False, 0)),),
        'foreign_keys': ((),),
        'unique_indexes': (),
        'checks': (("CHECK(status IN ('building','completed','failed','interrupted'))", 'CHECK(edge_count >= 0)', 'CHECK(sparse_k >= 0)', 'CHECK(is_current IN (0,1))', "CHECK(status = 'completed' OR is_current = 0)"),),
    },
    'graph_build_edges': {
        'columns': ((('build_id', 'TEXT', True, 1), ('source_track_id', 'TEXT', True, 2), ('target_track_id', 'TEXT', True, 3), ('score', 'REAL', True, 0),
                     ('distance', 'REAL', True, 0), ('supported_group_count', 'INTEGER', True, 0),
                     ('distance_policy_version', 'TEXT', True, 0), ('neighbour_policy_version', 'TEXT', True, 0),
                     ('built_at', 'TEXT', True, 0)),),
        'foreign_keys': ((('graph_builds', ('build_id',), ('id',)), ('tracks', ('source_track_id',), ('id',)), ('tracks', ('target_track_id',), ('id',))),),
        'unique_indexes': (),
        'checks': (('CHECK(source_track_id < target_track_id)', 'CHECK(score >= 0.0 AND score <= 1.0)', 'CHECK(distance >= 0.0 AND distance <= 1.0)'),),
    },
}

_EXPECTED_GRAPH_SCHEMA_LEGACY = {
    **_EXPECTED_GRAPH_SCHEMA,
    'graph_builds': {
        **_EXPECTED_GRAPH_SCHEMA['graph_builds'],
        'columns': ((('id', 'TEXT', False, 1), ('status', 'TEXT', True, 0), ('detail', 'TEXT', True, 0),
                     ('edge_count', 'INTEGER', True, 0), ('sparse_k', 'INTEGER', True, 0), ('source_fingerprint', 'TEXT', True, 0),
                     ('distance_policy_version', 'TEXT', True, 0), ('neighbour_policy_version', 'TEXT', True, 0),
                     ('is_current', 'INTEGER', True, 0), ('created_at', 'TEXT', True, 0), ('completed_at', 'TEXT', True, 0)),),
        'checks': (("CHECK(status IN ('completed','failed'))", 'CHECK(edge_count >= 0)', 'CHECK(sparse_k >= 0)', 'CHECK(is_current IN (0,1))', "CHECK(status = 'completed' OR is_current = 0)"),),
    },
}

_EXPECTED_POSITIONED_GRAPH_SCHEMA = {
    'graph_positioned_edges': _EXPECTED_GRAPH_SCHEMA['graph_edges'],
    'graph_build_positioned_edges': _EXPECTED_GRAPH_SCHEMA['graph_build_edges'],
    'graph_build_positioned_snapshots': {
        'columns': ((('build_id', 'TEXT', False, 1), ('edge_count', 'INTEGER', True, 0), ('built_at', 'TEXT', True, 0)),),
        'foreign_keys': ((('graph_builds', ('build_id',), ('id',)),),),
        'unique_indexes': (),
        'checks': (('CHECK(edge_count >= 0)',),),
    },
}

_EXPECTED_GRAPH_INDEXES = {('idx_graph_edges_source_track_id', 'index'), ('idx_graph_edges_target_track_id', 'index'), ('idx_graph_build_edges_build_id', 'index'), ('idx_graph_build_edges_source_track_id', 'index'), ('idx_graph_build_edges_target_track_id', 'index'), ('idx_graph_builds_one_current', 'index')}

_EXPECTED_POSITIONED_GRAPH_INDEXES = {('idx_graph_positioned_edges_source_track_id', 'index'), ('idx_graph_positioned_edges_target_track_id', 'index'), ('idx_graph_build_positioned_edges_build_id', 'index'), ('idx_graph_build_positioned_edges_source_track_id', 'index'), ('idx_graph_build_positioned_edges_target_track_id', 'index')}

_EXPECTED_GRAPH_FEATURE_SCHEMA = {
    'graph_feature_evidence': {
        'columns': ((('track_id', 'TEXT', True, 1), ('run_id', 'TEXT', True, 2), ('fingerprint', 'TEXT', True, 0),
                     ('evidence_json', 'TEXT', True, 0), ('is_current', 'INTEGER', True, 0), ('created_at', 'TEXT', True, 0)),),
        'foreign_keys': ((('runs', ('run_id',), ('id',)), ('tracks', ('track_id',), ('id',))),),
        'unique_indexes': (),
        'checks': (('CHECK(is_current IN (0,1))',),),
    },
}

_EXPECTED_GRAPH_FEATURE_INDEXES = {('idx_graph_feature_evidence_one_current_per_track', 'index'), ('idx_graph_feature_evidence_run_id', 'index')}

_EXPECTED_VIEWS = {
    'active_tracks': (
        ('id', 'sha256', 'size'),
        "CREATE VIEW active_tracks AS SELECT t.id,t.sha256,t.size FROM tracks t JOIN track_audio a ON a.track_id=t.id WHERE a.status='eligible'",
    ),
    'active_locations': (
        ('path', 'track_id', 'mtime_ns', 'format', 'available'),
        "CREATE VIEW active_locations AS SELECT l.path,l.track_id,l.mtime_ns,l.format,l.available FROM locations l JOIN track_audio a ON a.track_id=l.track_id WHERE l.available=1 AND a.status='eligible'",
    ),
}
