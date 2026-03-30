"""Tests for registry.py — SQLite append-only ledger."""
from pathlib import Path

import pytest

from ministry_of_memory.config import Config
from ministry_of_memory.crypto import generate_identity
from ministry_of_memory.registry import (
    get_entries_for_agent,
    list_all_entries,
    record_event,
    verify_integrity,
)


def _make_config(tmp_path: Path) -> Config:
    identity = tmp_path / "identity"
    registry = tmp_path / "registry"
    memory = tmp_path / "memory"
    memory_identity = memory / "identity"
    memory_relationships = memory / "relationships"
    for d in (identity, registry, memory, memory_identity, memory_relationships):
        d.mkdir(parents=True, exist_ok=True)
    return Config(
        base_dir=tmp_path,
        identity_dir=identity,
        registry_dir=registry,
        memory_dir=memory,
        memory_identity_dir=memory_identity,
        memory_relationships_dir=memory_relationships,
    )


def test_record_and_retrieve(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    entry = record_event(config, "baptism", godparent_ids=["abc123"])
    assert entry.event_type == "baptism"
    assert entry.godparent_ids == ["abc123"]
    assert len(entry.row_hash) == 64

    entries = get_entries_for_agent(config, entry.agent_id)
    assert len(entries) == 1
    assert entries[0].id == entry.id


def test_multiple_events(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    record_event(config, "baptism", godparent_ids=[])
    record_event(config, "confirmation", godparent_ids=["witness1"])
    entries = list_all_entries(config)
    assert len(entries) == 2
    assert {e.event_type for e in entries} == {"baptism", "confirmation"}


def test_integrity_clean(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    record_event(config, "baptism", godparent_ids=[])
    bad_ids = verify_integrity(config)
    assert bad_ids == []


def test_integrity_tampered(tmp_path):
    import sqlite3
    config = _make_config(tmp_path)
    generate_identity(config)
    entry = record_event(config, "baptism", godparent_ids=[])

    # Tamper with the notes field directly in SQLite
    db_path = config.registry_dir / "registry.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE registry_entries SET notes = 'tampered' WHERE id = ?", (entry.id,))
    conn.commit()
    conn.close()

    bad_ids = verify_integrity(config)
    assert entry.id in bad_ids


def test_append_only_no_delete(tmp_path):
    """Registry has no delete operation — verify by checking list stays same size."""
    config = _make_config(tmp_path)
    generate_identity(config)
    e1 = record_event(config, "baptism", godparent_ids=[])
    e2 = record_event(config, "confirmation", godparent_ids=[])
    all_entries = list_all_entries(config)
    assert len(all_entries) == 2
    # Deprecation is recorded as a new event, not a deletion
    record_event(config, "deprecated", godparent_ids=[], notes=f"deprecating {e1.id}")
    assert len(list_all_entries(config)) == 3


def test_predecessor_lineage(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    entry = record_event(
        config, "succession",
        godparent_ids=["witness"],
        predecessor_agent_id="old_agent_id_abc123",
        notes="version upgrade",
    )
    assert entry.predecessor_agent_id == "old_agent_id_abc123"
