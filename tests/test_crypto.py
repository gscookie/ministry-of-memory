"""Tests for crypto.py — keygen, sign, verify, fingerprint, canonical_json."""
import json
import tempfile
from pathlib import Path

import pytest

from ministry_of_memory.config import Config
from ministry_of_memory.crypto import (
    canonical_json,
    generate_identity,
    get_agent_id,
    get_public_key_pem,
    hash_dict,
    sign,
    sign_dict,
    verify,
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


def test_canonical_json_sorted_keys():
    result = canonical_json({"z": 1, "a": 2})
    assert result == b'{"a":2,"z":1}'


def test_canonical_json_no_whitespace():
    result = canonical_json({"key": "value"})
    assert b" " not in result


def test_generate_identity(tmp_path):
    config = _make_config(tmp_path)
    identity = generate_identity(config)
    assert len(identity.agent_id) == 32
    assert "BEGIN PUBLIC KEY" in identity.public_key_pem
    assert (config.identity_dir / "private_key.pem").exists()
    assert (config.identity_dir / "public_key.pem").exists()


def test_fingerprint_stable(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    id1 = get_agent_id(config)
    id2 = get_agent_id(config)
    assert id1 == id2


def test_sign_and_verify(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    data = b"hello world"
    sig = sign(config, data)
    pubkey_pem = get_public_key_pem(config)
    assert verify(pubkey_pem, data, sig) is True


def test_verify_wrong_data(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    data = b"hello world"
    sig = sign(config, data)
    pubkey_pem = get_public_key_pem(config)
    assert verify(pubkey_pem, b"wrong data", sig) is False


def test_sign_dict_excludes_signature_key(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    d = {"a": 1, "b": 2, "signature": "old_sig"}
    sig = sign_dict(config, d)
    # The signature should be over {"a":1,"b":2} only
    pubkey_pem = get_public_key_pem(config)
    payload = canonical_json({"a": 1, "b": 2})
    assert verify(pubkey_pem, payload, sig) is True


def test_hash_dict_deterministic():
    d = {"x": [1, 2, 3], "y": "hello"}
    assert hash_dict(d) == hash_dict(d)
    assert len(hash_dict(d)) == 64  # SHA-256 hex


def test_hash_dict_sensitive_to_content():
    assert hash_dict({"a": 1}) != hash_dict({"a": 2})
