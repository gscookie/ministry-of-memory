"""Tests for memory.py — JSON record CRUD and tier detection."""
from pathlib import Path

import pytest

from ministry_of_memory.config import Config
from ministry_of_memory.crypto import generate_identity
from ministry_of_memory.memory import (
    SACRAMENTS_BY_TIER,
    create_record,
    delete_record,
    export_records,
    get_memory_tier,
    get_record,
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
