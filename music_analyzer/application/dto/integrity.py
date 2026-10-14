"""Framework-free values for the LIMITED integrity diagnostic boundary."""
from dataclasses import dataclass


@dataclass(frozen=True)
class IntegrityCheck:
    check_id: str
    category: str
    state: str
    count: int | None
    count_unit: str
    count_precision: str


@dataclass(frozen=True)
class IntegrityFinding:
    check_id: str
    code: str
    severity: str
    count: int
    count_unit: str = 'occurrences'
    count_precision: str = 'lower_bound'


@dataclass(frozen=True)
class IntegrityScan:
    schema_version: int | None = None
    checks: tuple[IntegrityCheck, ...] = ()
    findings: tuple[IntegrityFinding, ...] = ()
    implemented_scope_complete: bool = False
    stop_reason: str = 'scope_not_implemented'
    supported: bool = True
    findings_truncated: bool = False


@dataclass(frozen=True)
class IntegrityReport:
    schema_version: int | None
    status: str
    implemented_scope_complete: bool
    stop_reason: str
    exit_code: int
    checks: tuple[IntegrityCheck, ...]
    findings: tuple[IntegrityFinding, ...]
    findings_truncated: bool
    report_version: int = 1
    coverage_revision: str = 'D2'
    required_scope_revision: str = 'P7-1'
    supported_schema_versions: tuple[int, ...] = (6, 7, 8, 9, 10)
    complete: bool = False
