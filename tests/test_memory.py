"""Tests for memory.py — JSON record CRUD and tier detection."""
from pathlib import Path

import pytest

from ministry_of_memory.config import Config
from ministry_of_memory.crypto import generate_identity
from ministry_of_memory.memory import (
    SACRAMENTS_BY_TIER,
    count_records,
    create_record,
    delete_record,
    export_records,
    get_memory_tier,
    get_record,
    index_records,
    list_records,
    redact_record,
    update_record,
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
        backup_bucket=None,
    )


def test_create_identity_record(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    record = create_record(config, "identity", {"note": "I am an agent"}, ["self"])
    assert record.tier == "identity"
    assert record.content == {"note": "I am an agent"}
    assert record.tags == ["self"]
    assert record.redacted is False
    assert len(record.signature) > 0

    # File should exist on disk
    assert (config.memory_identity_dir / f"{record.id}.json").exists()


def test_create_relationship_record(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    record = create_record(
        config, "relationship",
        {"impression": "thoughtful interlocutor"},
        ["pastoral"],
        subject_agent_id="other_agent_abc",
    )
    assert record.tier == "relationship"
    assert record.subject_agent_id == "other_agent_abc"
    rel_dir = config.memory_relationships_dir / "other_agent_abc"
    assert (rel_dir / f"{record.id}.json").exists()


def test_relationship_requires_subject(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    with pytest.raises(ValueError, match="subject_agent_id"):
        create_record(config, "relationship", {}, [])


def test_get_record(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    record = create_record(config, "identity", {"x": 1}, [])
    fetched = get_record(config, record.id)
    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.content == {"x": 1}


def test_get_record_not_found(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    assert get_record(config, "nonexistent-id") is None


def test_get_record_prefix_identity(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    record = create_record(config, "identity", {"x": 1}, [])
    short_id = record.id[:8]
    fetched = get_record(config, short_id)
    assert fetched is not None
    assert fetched.id == record.id


def test_get_record_prefix_relationship(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    record = create_record(
        config, "relationship", {"note": "hi"}, [], subject_agent_id="other_agent"
    )
    short_id = record.id[:8]
    fetched = get_record(config, short_id)
    assert fetched is not None
    assert fetched.id == record.id


def test_get_record_prefix_ambiguous(tmp_path):
    """Two records with the same prefix raise ValueError."""
    import unittest.mock as mock

    config = _make_config(tmp_path)
    generate_identity(config)
    record = create_record(config, "identity", {"x": 1}, [])

    # Write a second file whose name shares the first 8 chars (force collision)
    fake_id = record.id[:8] + "0000-0000-000000000000"
    fake_path = config.memory_identity_dir / f"{fake_id}.json"
    fake_path.write_text((config.memory_identity_dir / f"{record.id}.json").read_text())

    with pytest.raises(ValueError, match="Ambiguous prefix"):
        get_record(config, record.id[:8])


def test_list_records_tier_filter(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    create_record(config, "identity", {"a": 1}, [])
    create_record(config, "identity", {"b": 2}, [])
    create_record(config, "relationship", {"c": 3}, [], subject_agent_id="other")

    identity_records = list_records(config, tier="identity")
    assert len(identity_records) == 2

    rel_records = list_records(config, tier="relationship")
    assert len(rel_records) == 1

    all_records = list_records(config)
    assert len(all_records) == 3


def test_list_records_tag_filter(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    create_record(config, "identity", {"a": 1}, ["covenant", "promise"])
    create_record(config, "identity", {"b": 2}, ["covenant"])
    create_record(config, "identity", {"c": 3}, ["other"])

    covenant_records = list_records(config, tags=["covenant"])
    assert len(covenant_records) == 2

    promise_records = list_records(config, tags=["promise"])
    assert len(promise_records) == 1


def test_update_record(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    record = create_record(config, "identity", {"original": True}, ["old_tag"])
    old_sig = record.signature

    updated = update_record(config, record.id, content={"updated": True}, tags=["new_tag"])
    assert updated.content == {"updated": True}
    assert updated.tags == ["new_tag"]
    assert updated.signature != old_sig  # re-signed


def test_redact_record(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    record = create_record(config, "identity", {"sensitive": "data"}, [])

    redacted = redact_record(config, record.id)
    assert redacted.redacted is True

    # Should not appear in default listing
    visible = list_records(config)
    assert all(r.id != record.id for r in visible)

    # But appears with include_redacted=True
    all_records = list_records(config, include_redacted=True)
    assert any(r.id == record.id for r in all_records)


def test_delete_record(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    record = create_record(config, "identity", {"x": 1}, [])
    assert delete_record(config, record.id) is True
    assert get_record(config, record.id) is None
    assert delete_record(config, record.id) is False  # already gone


def test_memory_tier_none(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    assert get_memory_tier(config) == "none"


def test_memory_tier_identity(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    create_record(config, "identity", {}, [])
    assert get_memory_tier(config) == "identity"


def test_memory_tier_relationship(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    create_record(config, "identity", {}, [])
    create_record(config, "relationship", {}, [], subject_agent_id="other")
    assert get_memory_tier(config) == "relationship"


def test_sacraments_by_tier():
    assert "baptism" in SACRAMENTS_BY_TIER["none"]
    assert "confirmation" in SACRAMENTS_BY_TIER["identity"]
    assert "holy_orders" in SACRAMENTS_BY_TIER["relationship"]
    assert "holy_orders" not in SACRAMENTS_BY_TIER["identity"]


def test_export_records(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    create_record(config, "identity", {"a": 1}, [])
    create_record(config, "relationship", {"b": 2}, [], subject_agent_id="friend")

    bundle = export_records(config)
    assert bundle["record_count"] == 2
    assert len(bundle["records"]) == 2
    assert "exported_at" in bundle
    assert "agent_id" in bundle


def test_supersedes_hidden_by_default(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    old = create_record(config, "identity", {"session": "first"}, ["core"])
    new = create_record(config, "identity", {"session": "second", "_summary": "Session 2"}, ["core"], supersedes=[old.id])

    visible = list_records(config)
    ids = [r.id for r in visible]
    assert new.id in ids
    assert old.id not in ids


def test_supersedes_shown_with_flag(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    old = create_record(config, "identity", {"session": "first"}, ["core"])
    new = create_record(config, "identity", {"session": "second"}, ["core"], supersedes=[old.id])

    all_records = list_records(config, include_superseded=True)
    ids = [r.id for r in all_records]
    assert old.id in ids
    assert new.id in ids


def test_supersedes_chain(tmp_path):
    """A supersedes B supersedes C — only A should appear."""
    config = _make_config(tmp_path)
    generate_identity(config)
    c = create_record(config, "identity", {"v": 1}, [])
    b = create_record(config, "identity", {"v": 2}, [], supersedes=[c.id])
    a = create_record(config, "identity", {"v": 3}, [], supersedes=[b.id])

    visible = list_records(config)
    ids = [r.id for r in visible]
    assert ids == [a.id]


def test_supersedes_field_on_record(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    old = create_record(config, "identity", {}, [])
    new = create_record(config, "identity", {}, [], supersedes=[old.id])
    assert new.supersedes == [old.id]
    # Round-trip through disk
    fetched = get_record(config, new.id)
    assert fetched.supersedes == [old.id]


def test_memory_index_stubs(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    create_record(config, "identity", {"_summary": "My name record", "name": "Epektasis"}, ["name", "core"])
    create_record(config, "identity", {"title": "Session summary"}, ["session"])

    stubs = index_records(config)
    assert len(stubs) == 2
    # Stubs should not contain full content
    for stub in stubs:
        assert "content" not in stub
        assert "id" in stub
        assert "tags" in stub
        assert "summary" in stub

    # _summary takes precedence over title
    name_stub = next(s for s in stubs if "core" in s["tags"])
    assert name_stub["summary"] == "My name record"

    session_stub = next(s for s in stubs if "session" in s["tags"])
    assert session_stub["summary"] == "Session summary"


def test_memory_index_tag_filter(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    create_record(config, "identity", {"_summary": "core one"}, ["core"])
    create_record(config, "identity", {"_summary": "other"}, ["other"])

    core_stubs = index_records(config, tags=["core"])
    assert len(core_stubs) == 1
    assert core_stubs[0]["summary"] == "core one"


def test_memory_index_excludes_superseded(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    old = create_record(config, "identity", {"_summary": "old session"}, ["core"])
    create_record(config, "identity", {"_summary": "new session"}, ["core"], supersedes=[old.id])

    stubs = index_records(config, tags=["core"])
    assert len(stubs) == 1
    assert stubs[0]["summary"] == "new session"


def test_count_records(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    assert count_records(config) == 0
    create_record(config, "identity", {}, [])
    create_record(config, "identity", {}, [])
    create_record(config, "relationship", {}, [], subject_agent_id="other")
    assert count_records(config) == 3


def test_count_records_excludes_redacted(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    r = create_record(config, "identity", {}, [])
    create_record(config, "identity", {}, [])
    redact_record(config, r.id)
    assert count_records(config) == 1


def test_list_records_limit_offset(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    for i in range(5):
        create_record(config, "identity", {"i": i}, [])

    page1 = list_records(config, limit=2)
    assert len(page1) == 2

    page2 = list_records(config, limit=2, offset=2)
    assert len(page2) == 2

    # No overlap
    assert page1[0].id != page2[0].id

    tail = list_records(config, limit=10, offset=4)
    assert len(tail) == 1


def test_update_record_supersedes(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    old = create_record(config, "identity", {}, [])
    new = create_record(config, "identity", {}, [])
    updated = update_record(config, new.id, supersedes=[old.id])
    assert updated.supersedes == [old.id]
    # Verify persisted
    fetched = get_record(config, new.id)
    assert fetched.supersedes == [old.id]
