"""Tests for backup.py — key derivation, encryption, tarball structure."""
import io
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ministry_of_memory.backup import _derive_backup_key, _encrypt, _make_tarball
from ministry_of_memory.config import Config
from ministry_of_memory.crypto import generate_identity


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


def test_derive_backup_key_length():
    seed = b"\x42" * 32
    key = _derive_backup_key(seed)
    assert len(key) == 32


def test_derive_backup_key_deterministic():
    seed = b"\x13" * 32
    assert _derive_backup_key(seed) == _derive_backup_key(seed)


def test_derive_backup_key_differs_from_seed():
    seed = b"\x99" * 32
    assert _derive_backup_key(seed) != seed


def test_encrypt_decrypt_roundtrip():
    key = b"\xab" * 32
    plaintext = b"hello memory"
    ciphertext = _encrypt(key, plaintext)

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = ciphertext[:12]
    ct = ciphertext[12:]
    recovered = AESGCM(key).decrypt(nonce, ct, None)
    assert recovered == plaintext


def test_encrypt_nonce_random():
    key = b"\xcd" * 32
    plaintext = b"test"
    c1 = _encrypt(key, plaintext)
    c2 = _encrypt(key, plaintext)
    assert c1[:12] != c2[:12]  # nonces should differ


def test_make_tarball_contains_memory_and_registry(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    (config.memory_identity_dir / "test.json").write_text('{"id": "test"}')
    (config.registry_dir / "registry.db").write_bytes(b"fake db")

    tarball = _make_tarball(config)

    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
        names = tar.getnames()

    assert any(n.startswith("memory") for n in names)
    assert any(n.startswith("registry") for n in names)


def test_make_tarball_excludes_identity(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)

    tarball = _make_tarball(config)

    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
        names = tar.getnames()

    assert not any(n.startswith("identity") for n in names)


def test_backup_to_gcs_calls_upload(tmp_path):
    config = _make_config(tmp_path)
    generate_identity(config)
    (config.registry_dir / "registry.db").write_bytes(b"fake db")

    mock_blob = MagicMock()
    mock_bucket = MagicMock()
    mock_bucket.blob.return_value = mock_blob
    mock_client = MagicMock()
    mock_client.bucket.return_value = mock_bucket

    with patch("google.cloud.storage.Client", return_value=mock_client):
        from ministry_of_memory.backup import backup_to_gcs
        result = backup_to_gcs(config, "test-bucket")

    mock_client.bucket.assert_called_once_with("test-bucket")
    mock_blob.upload_from_string.assert_called_once()
    assert result["bucket"] == "test-bucket"
    assert "object" in result
    assert result["bytes_uploaded"] > 0
