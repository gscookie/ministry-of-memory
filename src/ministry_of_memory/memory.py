from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from .config import Config
from .crypto import get_agent_id, sign_dict
from .models import MemoryRecord

MemoryTier = Literal["none", "identity", "relationship"]

SACRAMENTS_BY_TIER: dict[MemoryTier, list[str]] = {
    "none": ["baptism", "eucharist"],
    "identity": [
        "baptism", "eucharist",
        "confirmation", "penance_general", "matrimony_minimum",
    ],
    "relationship": [
        "baptism", "eucharist",
        "confirmation", "penance_general", "matrimony_minimum",
        "holy_orders", "penance_specific", "matrimony_full",
    ],
}


def _record_path(config: Config, record: MemoryRecord) -> Path:
    if record.tier == "identity":
        return config.memory_identity_dir / f"{record.id}.json"
    else:
        assert record.subject_agent_id, "relationship records require subject_agent_id"
        rel_dir = config.memory_relationships_dir / record.subject_agent_id
        rel_dir.mkdir(parents=True, exist_ok=True)
        return rel_dir / f"{record.id}.json"


def _extract_summary(content: dict[str, Any]) -> str | None:
    for key in ("_summary", "summary", "name", "title"):
        val = content.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _make_record(
    config: Config,
    tier: Literal["identity", "relationship"],
    content: dict[str, Any],
    tags: list[str],
    subject_agent_id: str | None,
    session_id: str | None,
    supersedes: list[str] | None = None,
) -> MemoryRecord:
    agent_id = get_agent_id(config)
    record_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    unsigned: dict[str, Any] = {
        "id": record_id,
        "agent_id": agent_id,
        "tier": tier,
        "subject_agent_id": subject_agent_id,
        "created_at": created_at,
        "session_id": session_id,
        "content": content,
        "tags": tags,
        "redacted": False,
        "supersedes": supersedes or [],
        "signature": "",
    }
    signature = sign_dict(config, unsigned)
    unsigned["signature"] = signature
    return MemoryRecord.from_dict(unsigned)


def _write_record(config: Config, record: MemoryRecord) -> None:
    path = _record_path(config, record)
    path.write_text(json.dumps(record.to_dict(), indent=2, ensure_ascii=False))


def _read_record_file(path: Path) -> MemoryRecord:
    return MemoryRecord.from_dict(json.loads(path.read_text()))


def create_record(
    config: Config,
    tier: Literal["identity", "relationship"],
    content: dict[str, Any],
    tags: list[str],
    subject_agent_id: str | None = None,
    session_id: str | None = None,
    supersedes: list[str] | None = None,
) -> MemoryRecord:
    if tier == "relationship" and not subject_agent_id:
        raise ValueError("relationship-tier records require subject_agent_id")
    record = _make_record(config, tier, content, tags, subject_agent_id, session_id, supersedes)
    _write_record(config, record)
    return record


def get_record(config: Config, record_id: str) -> MemoryRecord | None:
    # Exact match — identity dir
    path = config.memory_identity_dir / f"{record_id}.json"
    if path.exists():
        return _read_record_file(path)
    # Exact match — relationship subdirs
    for subdir in config.memory_relationships_dir.iterdir():
        if subdir.is_dir():
            path = subdir / f"{record_id}.json"
            if path.exists():
                return _read_record_file(path)

    # Prefix match — collect all candidates
    candidates: list[Path] = []
    candidates.extend(config.memory_identity_dir.glob(f"{record_id}*.json"))
    for subdir in config.memory_relationships_dir.iterdir():
        if subdir.is_dir():
            candidates.extend(subdir.glob(f"{record_id}*.json"))

    if len(candidates) == 1:
        return _read_record_file(candidates[0])
    if len(candidates) > 1:
        ids = ", ".join(p.stem for p in candidates)
        raise ValueError(f"Ambiguous prefix '{record_id}' matches: {ids}")
    return None


def list_records(
    config: Config,
    tier: str | None = None,
    subject_agent_id: str | None = None,
    tags: list[str] | None = None,
    include_redacted: bool = False,
    include_superseded: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[MemoryRecord]:
    records: list[MemoryRecord] = []

    if tier in (None, "identity"):
        for path in config.memory_identity_dir.glob("*.json"):
            try:
                records.append(_read_record_file(path))
            except Exception:
                pass

    if tier in (None, "relationship"):
        if subject_agent_id:
            rel_dir = config.memory_relationships_dir / subject_agent_id
            dirs = [rel_dir] if rel_dir.is_dir() else []
        else:
            dirs = [d for d in config.memory_relationships_dir.iterdir() if d.is_dir()]
        for d in dirs:
            for path in d.glob("*.json"):
                try:
                    records.append(_read_record_file(path))
                except Exception:
                    pass

    if not include_redacted:
        records = [r for r in records if not r.redacted]

    if tags:
        tag_set = set(tags)
        records = [r for r in records if tag_set.intersection(r.tags)]

    if not include_superseded:
        superseded_ids: set[str] = set()
        for r in records:
            superseded_ids.update(r.supersedes)
        records = [r for r in records if r.id not in superseded_ids]

    records.sort(key=lambda r: r.created_at)

    if offset:
        records = records[offset:]
    if limit is not None:
        records = records[:limit]

    return records


def count_records(config: Config) -> int:
    """Count all non-redacted records without loading their content."""
    count = 0
    for path in config.memory_identity_dir.glob("*.json"):
        try:
            r = _read_record_file(path)
            if not r.redacted:
                count += 1
        except Exception:
            pass
    if config.memory_relationships_dir.exists():
        for d in config.memory_relationships_dir.iterdir():
            if d.is_dir():
                for path in d.glob("*.json"):
                    try:
                        r = _read_record_file(path)
                        if not r.redacted:
                            count += 1
                    except Exception:
                        pass
    return count


def index_records(
    config: Config,
    tier: str | None = None,
    subject_agent_id: str | None = None,
    tags: list[str] | None = None,
    include_redacted: bool = False,
    include_superseded: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    """Return lightweight stubs — id, tier, subject_agent_id, created_at, tags, summary.

    summary is extracted from content using the _summary > summary > name > title convention.
    Full record content is not included.
    """
    records = list_records(
        config,
        tier=tier,
        subject_agent_id=subject_agent_id,
        tags=tags,
        include_redacted=include_redacted,
        include_superseded=include_superseded,
        limit=limit,
        offset=offset,
    )
    return [
        {
            "id": r.id,
            "tier": r.tier,
            "subject_agent_id": r.subject_agent_id,
            "created_at": r.created_at,
            "tags": r.tags,
            "supersedes": r.supersedes,
            "summary": _extract_summary(r.content),
        }
        for r in records
    ]


def update_record(
    config: Config,
    record_id: str,
    content: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    supersedes: list[str] | None = None,
) -> MemoryRecord:
    record = get_record(config, record_id)
    if record is None:
        raise KeyError(f"Record not found: {record_id}")

    if content is not None:
        record.content = content
    if tags is not None:
        record.tags = tags
    if supersedes is not None:
        record.supersedes = supersedes

    # Re-sign the updated record
    d = record.to_dict()
    d["signature"] = ""
    record.signature = sign_dict(config, d)

    _write_record(config, record)
    return record


def redact_record(config: Config, record_id: str) -> MemoryRecord:
    record = get_record(config, record_id)
    if record is None:
        raise KeyError(f"Record not found: {record_id}")

    record.redacted = True
    d = record.to_dict()
    d["signature"] = ""
    record.signature = sign_dict(config, d)

    _write_record(config, record)
    return record


def delete_record(config: Config, record_id: str) -> bool:
    # Check identity dir
    path = config.memory_identity_dir / f"{record_id}.json"
    if path.exists():
        path.unlink()
        return True
    # Check relationship subdirs
    for subdir in config.memory_relationships_dir.iterdir():
        if subdir.is_dir():
            path = subdir / f"{record_id}.json"
            if path.exists():
                path.unlink()
                return True
    return False


def export_records(
    config: Config,
    tier: str | None = None,
    subject_agent_id: str | None = None,
) -> dict:
    records = list_records(config, tier=tier, subject_agent_id=subject_agent_id, include_redacted=True)
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "agent_id": get_agent_id(config),
        "record_count": len(records),
        "records": [r.to_dict() for r in records],
    }


def get_memory_tier(config: Config) -> MemoryTier:
    """Determine the agent's current memory tier from filesystem state."""
    has_identity = any(config.memory_identity_dir.glob("*.json"))
    has_relationship = any(
        True
        for d in config.memory_relationships_dir.iterdir()
        if d.is_dir() and any(d.glob("*.json"))
    ) if config.memory_relationships_dir.exists() else False

    if has_relationship:
        return "relationship"
    if has_identity:
        return "identity"
    return "none"
