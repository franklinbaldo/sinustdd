"""Versioned OKF evidence ledger and strict sequential verification for sinustdd cycles."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml
from okf_parser import validate_path
from okf_parser.duckdb import attach_okf
from okf_parser.parser import DocumentParseError, parse_document
from okf_parser.service import init_bundle

from sinustdd.models import Phase

EVIDENCE_ROOT = Path(".sinustdd/evidence")
_PHASE_ORDER = [Phase.BASELINE, Phase.RED, Phase.GREEN, Phase.REFACTOR]
_SPEC_TEMPLATE = "specs/{slug}.md"
_SPEC_EXCLUDE = ("specs/**",)
_EVIDENCE_SPEC = Path("specs/sinustddevidence.md")
_EVIDENCE_DECLARED_SCHEMA = Path("specs/sinustddevidence.schema.sql")
_RELATIONAL_SCHEMA = Path("okf.schema.sql")

_DECLARED_SCHEMA_SQL = '''CREATE TABLE "SinusTddEvidence" (
    schema_version BIGINT,
    cycle_id VARCHAR,
    phase VARCHAR,
    repository_ref VARCHAR,
    previous_evidence_digest VARCHAR
);
'''

_RELATIONAL_SCHEMA_SQL = '''CREATE TABLE "SinusTddEvidence" (
    cycle_id VARCHAR,
    phase VARCHAR,
    PRIMARY KEY (cycle_id, phase)
);
'''


def _legacy_digest(document: dict[str, Any]) -> str:
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _okf_value(value: Any) -> Any:
    """Canonicalize values to the scalar-preserving model used by okf-parser."""
    if isinstance(value, dict):
        return {str(key): _okf_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_okf_value(item) for item in value]
    if value is None:
        return None
    return str(value)


def _timestamp_prefix(now: datetime | None = None) -> str:
    instant = now or datetime.now(UTC)
    return instant.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def get_phase_evidence_path(root: Path, cycle_id: str, phase: Phase) -> Path:
    """Return the legacy phase path kept for backwards compatibility."""
    return root / EVIDENCE_ROOT / cycle_id / f"{phase.value}.md"


def _phase_candidates(root: Path, cycle_id: str, phase: Phase) -> list[Path]:
    cycle_dir = root / EVIDENCE_ROOT / cycle_id
    if not cycle_dir.is_dir():
        return []
    legacy = cycle_dir / f"{phase.value}.md"
    candidates = list(cycle_dir.glob(f"*-{phase.value}.md"))
    if legacy.is_file():
        candidates.append(legacy)
    return sorted(set(candidates), key=lambda p: p.name)


def find_phase_evidence_path(root: Path, cycle_id: str, phase: Phase) -> Path | None:
    """Resolve one phase witness across timestamped and historical filenames.

    More than one witness for the same phase is ambiguous and therefore invalid.
    """
    candidates = _phase_candidates(root, cycle_id, phase)
    if len(candidates) == 1:
        return candidates[0]
    return None


def _parse(path: Path):
    try:
        return parse_document(path)
    except (DocumentParseError, OSError, UnicodeError):
        return None


def _latest_parsed_digest(root: Path, cycle_id: str) -> str | None:
    for phase in reversed(_PHASE_ORDER):
        path = find_phase_evidence_path(root, cycle_id, phase)
        if path is None:
            continue
        parsed = _parse(path)
        if parsed is not None:
            return parsed.parsed_digest
    return None


def _ensure_evidence_contract(evidence_dir: Path) -> None:
    """Bootstrap the OKF type contract using the same service path as `okf-parser init`."""
    result = init_bundle(
        str(evidence_dir),
        _SPEC_TEMPLATE,
        _SPEC_EXCLUDE,
        write=True,
        infer_schema=True,
    )
    schema_result = result.get("schemas")
    created: set[str] = set()
    if isinstance(schema_result, dict):
        values = schema_result.get("created", [])
        if isinstance(values, list):
            created = {str(value) for value in values}

    declared_path = evidence_dir / _EVIDENCE_DECLARED_SCHEMA
    if _EVIDENCE_DECLARED_SCHEMA.as_posix() in created:
        # `init --infer-schema` gives a starter inferred from observed evidence. Sinos then
        # authors the stable causal projection that every repository should expose.
        declared_path.write_text(_DECLARED_SCHEMA_SQL, encoding="utf-8")
    elif not declared_path.is_file():
        msg = "okf-parser init did not create the SinusTddEvidence declared schema"
        raise RuntimeError(msg)

    relational_path = evidence_dir / _RELATIONAL_SCHEMA
    if not relational_path.is_file():
        relational_path.write_text(_RELATIONAL_SCHEMA_SQL, encoding="utf-8")

    spec_path = evidence_dir / _EVIDENCE_SPEC
    if not spec_path.is_file():
        msg = "okf-parser init did not create the SinusTddEvidence specification"
        raise RuntimeError(msg)


def write_phase_evidence(
    *,
    root: Path | None = None,
    cycle_id: str,
    phase: Phase,
    repository_ref: str,
    payload: dict[str, Any],
) -> tuple[Path, str]:
    """Write one immutable v2 witness as timestamp-prefixed authored OKF Markdown."""
    repo_root = root or Path.cwd()
    evidence_dir = repo_root / EVIDENCE_ROOT
    cycle_dir = evidence_dir / cycle_id
    cycle_dir.mkdir(parents=True, exist_ok=True)

    if _phase_candidates(repo_root, cycle_id, phase):
        msg = f"Phase evidence already exists for {cycle_id}/{phase.value}"
        raise FileExistsError(msg)

    path = cycle_dir / f"{_timestamp_prefix()}-{phase.value}.md"
    previous_digest = _latest_parsed_digest(repo_root, cycle_id)
    canonical_payload = _okf_value(payload)

    frontmatter: dict[str, Any] = {
        "type": "SinusTddEvidence",
        "title": f"{cycle_id} {phase.value} witness",
        "description": f"Causal TDD evidence for {phase.value} phase",
        "schema_version": "2",
        "cycle_id": cycle_id,
        "phase": phase.value,
        "repository_ref": repository_ref,
    }
    if previous_digest is not None:
        frontmatter["previous_evidence_digest"] = previous_digest

    reserved = set(frontmatter)
    overlap = reserved.intersection(canonical_payload)
    if overlap:
        names = ", ".join(sorted(overlap))
        msg = f"evidence payload collides with reserved frontmatter fields: {names}"
        raise ValueError(msg)
    frontmatter.update(canonical_payload)

    yaml_frontmatter = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()
    body = (
        f"# {phase.value.title()} witness\n\n"
        "Repository evidence emitted by Sinos. Structured witness data lives in OKF frontmatter.\n"
    )
    path.write_text(f"---\n{yaml_frontmatter}\n---\n\n{body}", encoding="utf-8")

    try:
        _ensure_evidence_contract(evidence_dir)
        report = validate_path(
            evidence_dir,
            _SPEC_EXCLUDE,
            relational_schema=evidence_dir / _RELATIONAL_SCHEMA,
        )
        if not report.is_conformant:
            msg = "Generated Sinos evidence is not OKF-conformant"
            raise ValueError(msg)
        parsed = parse_document(path)
    except Exception:
        path.unlink(missing_ok=True)
        raise

    return path, parsed.parsed_digest


def _legacy_payload(body: str) -> dict[str, Any] | None:
    match = re.search(r"```json\n(.*?)\n```", body, re.DOTALL)
    if match is None:
        return None
    try:
        payload = json.loads(match.group(1))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _verify_legacy_ledger(root: Path, cycle_id: str) -> bool:
    previous_hash: str | None = None
    seen_phases: list[Phase] = []

    for phase in _PHASE_ORDER:
        candidates = _phase_candidates(root, cycle_id, phase)
        if len(candidates) > 1:
            return False
        if not candidates:
            continue

        parsed = _parse(candidates[0])
        if parsed is None:
            return False
        frontmatter = parsed.frontmatter
        cur_sha = frontmatter.get("sha256")
        repo_ref = frontmatter.get("repository_ref")
        cur_prev = frontmatter.get("previous_evidence_sha256")
        payload = _legacy_payload(parsed.body)
        if not isinstance(cur_sha, str) or not isinstance(repo_ref, str) or payload is None:
            return False
        if cur_prev is not None and not isinstance(cur_prev, str):
            return False

        expected = _legacy_digest(
            {
                "cycle_id": cycle_id,
                "phase": phase.value,
                "repository_ref": repo_ref,
                "payload": payload,
                "previous_evidence_sha256": cur_prev,
            }
        )
        if cur_sha != expected or cur_prev != previous_hash:
            return False
        previous_hash = cur_sha
        seen_phases.append(phase)

    return not (seen_phases and seen_phases != _PHASE_ORDER[: len(seen_phases)])


def _verify_v2_ledger(root: Path, cycle_id: str) -> bool:
    evidence_dir = root / EVIDENCE_ROOT
    relational_path = evidence_dir / _RELATIONAL_SCHEMA
    report = validate_path(
        evidence_dir,
        _SPEC_EXCLUDE,
        relational_schema=relational_path,
    )
    if not report.is_conformant:
        return False

    con = duckdb.connect()
    try:
        attach_okf(
            con,
            evidence_dir,
            schema="okf",
            overwrite=True,
            exclude=_SPEC_EXCLUDE,
            spec_template=_SPEC_TEMPLATE,
        )
        row = con.execute(
            '''
            WITH evidence AS (
                SELECT
                    typed.phase,
                    typed.previous_evidence_digest,
                    concepts.parsed_digest,
                    CASE typed.phase
                        WHEN 'baseline' THEN 1
                        WHEN 'red' THEN 2
                        WHEN 'green' THEN 3
                        WHEN 'refactor' THEN 4
                        ELSE NULL
                    END AS phase_rank
                FROM okf_types."SinusTddEvidence" AS typed
                JOIN okf.concepts AS concepts
                  ON concepts.concept_id = typed.__okf_concept_id
                WHERE typed.cycle_id = ? AND typed.schema_version = 2
            ), ordered AS (
                SELECT
                    *,
                    row_number() OVER (ORDER BY phase_rank) AS position,
                    lag(parsed_digest) OVER (ORDER BY phase_rank) AS expected_previous_digest
                FROM evidence
            )
            SELECT
                count(*) AS evidence_count,
                count(*) = count(DISTINCT phase) AS unique_phases,
                coalesce(
                    bool_and(phase_rank IS NOT NULL AND phase_rank = position),
                    false
                ) AS contiguous_prefix,
                coalesce(
                    bool_and(
                        CASE
                            WHEN position = 1 THEN previous_evidence_digest IS NULL
                            ELSE previous_evidence_digest = expected_previous_digest
                        END
                    ),
                    false
                ) AS digest_chain_ok
            FROM ordered
            ''',
            [cycle_id],
        ).fetchone()
    except (duckdb.Error, RuntimeError, ValueError):
        return False
    finally:
        con.close()

    if row is None:
        return False
    evidence_count, unique_phases, contiguous_prefix, digest_chain_ok = row
    return bool(evidence_count and unique_phases and contiguous_prefix and digest_chain_ok)


def verify_ledger(root: Path, cycle_id: str) -> bool:
    """Verify one cycle through OKF/DuckDB v2, with a read-only v1 compatibility path."""
    versions: list[str | None] = []
    for phase in _PHASE_ORDER:
        path = find_phase_evidence_path(root, cycle_id, phase)
        if path is None:
            continue
        parsed = _parse(path)
        if parsed is None:
            return False
        version = parsed.frontmatter.get("schema_version")
        versions.append(version if isinstance(version, str) else None)

    if not versions:
        return True
    if all(version == "2" for version in versions):
        return _verify_v2_ledger(root, cycle_id)
    if all(version is None for version in versions):
        return _verify_legacy_ledger(root, cycle_id)
    return False
