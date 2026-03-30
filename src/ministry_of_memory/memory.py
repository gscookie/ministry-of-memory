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


def _make_record(
    config: Config,
    tier: Literal["identity", "relationship"],
    content: dict[str, Any],
    tags: list[str],
    subject_agent_id: str | None,
    session_id: str | None,
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
) -> MemoryRecord:
    if tier == "relationship" and not subject_agent_id:
        raise ValueError("relationship-tier records require subject_agent_id")
    record = _make_record(config, tier, content, tags, subject_agent_id, session_id)
    _write_record(config, record)
    return record


def get_record(config: Config, record_id: str) -> MemoryRecord | None:
    # Search identity dir
    path = config.memory_identity_dir / f"{record_id}.json"
    if path.exists():
        return _read_record_file(path)
    # Search all relationship subdirs
    for subdir in config.memory_relationships_dir.iterdir():
        if subdir.is_dir():
            path = subdir / f"{record_id}.json"
            if path.exists():
                return _read_record_file(path)
    return None


def list_records(
    config: Config,
    tier: str | None = None,
    subject_agent_id: str | None = None,
    tags: list[str] | None = None,
    include_redacted: bool = False,
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

    records.sort(key=lambda r: r.created_at)
    return records


def update_record(
    config: Config,
    record_id: str,
    content: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> MemoryRecord:
    record = get_record(config, record_id)
    if record is None:
        raise KeyError(f"Record not found: {record_id}")

    if content is not None:
        record.content = content
    if tags is not None:
        record.tags = tags

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
