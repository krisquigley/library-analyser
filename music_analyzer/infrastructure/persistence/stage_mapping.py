"""Compatibility import for the established pure retained-stage mapper.

Persistence and existing reader callers share the inward mapping policy; JSON
and storage concerns remain in their adapters.
"""
from music_analyzer.application.use_cases.stage_result_mapping import stage_from_mapping


__all__ = ['stage_from_mapping']
