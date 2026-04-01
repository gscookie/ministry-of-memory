from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .config import Config
from .models import AgentIdentity


def canonical_json(obj: dict[str, Any]) -> bytes:
    """Deterministic JSON serialization for signing and hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _fingerprint(public_key: Ed25519PublicKey) -> str:
    """Returns first 16 bytes of SHA-256 of raw public key bytes as lowercase hex (32 chars)."""
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()[:32]


def generate_identity(config: Config) -> AgentIdentity:
    """Generate a new Ed25519 keypair and write to disk. Returns the identity."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    (config.identity_dir / "private_key.pem").write_bytes(private_pem)
    (config.identity_dir / "public_key.pem").write_bytes(public_pem)

    return AgentIdentity(
        agent_id=_fingerprint(public_key),
        public_key_pem=public_pem.decode(),
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def load_identity(config: Config) -> AgentIdentity | None:
    """Load existing identity from disk. Returns None if no identity exists."""
    priv_path = config.identity_dir / "private_key.pem"
    pub_path = config.identity_dir / "public_key.pem"
    if not priv_path.exists() or not pub_path.exists():
        return None

    public_key = _load_public_key(pub_path)
    return AgentIdentity(
        agent_id=_fingerprint(public_key),
        public_key_pem=pub_path.read_text(),
        created_at="",  # not stored separately; empty string indicates loaded
    )


def _load_private_key(config: Config) -> Ed25519PrivateKey:
    pem = (config.identity_dir / "private_key.pem").read_bytes()
    return serialization.load_pem_private_key(pem, password=None)  # type: ignore[return-value]


def _load_public_key(path: Path) -> Ed25519PublicKey:
    pem = path.read_bytes()
    return serialization.load_pem_public_key(pem)  # type: ignore[return-value]


def sign(config: Config, data: bytes) -> str:
    """Sign data with the agent's private key. Returns base64url-encoded signature."""
    private_key = _load_private_key(config)
    sig = private_key.sign(data)
    return base64.urlsafe_b64encode(sig).decode()


def verify(public_key_pem: str, data: bytes, signature_b64: str) -> bool:
    """Verify a base64url-encoded Ed25519 signature against a PEM public key."""
    from cryptography.exceptions import InvalidSignature
    try:
        pub_bytes = public_key_pem.encode() if isinstance(public_key_pem, str) else public_key_pem
        public_key = serialization.load_pem_public_key(pub_bytes)
        sig = base64.urlsafe_b64decode(signature_b64 + "==")  # pad for urlsafe decode
        public_key.verify(sig, data)  # type: ignore[union-attr]
        return True
    except (InvalidSignature, Exception):
        return False


def sign_dict(config: Config, obj: dict[str, Any], exclude_key: str = "signature") -> str:
    """Canonicalize a dict (excluding one key), then sign. Returns base64url signature."""
    payload = {k: v for k, v in obj.items() if k != exclude_key}
    return sign(config, canonical_json(payload))


def hash_dict(obj: dict[str, Any]) -> str:
    """Return SHA-256 hex digest of canonical JSON of a dict."""
    return hashlib.sha256(canonical_json(obj)).hexdigest()


def get_agent_id(config: Config) -> str:
    """Return the agent_id fingerprint for the current identity."""
    pub_path = config.identity_dir / "public_key.pem"
    if not pub_path.exists():
        raise FileNotFoundError("No identity found. Run identity_init first.")
    public_key = _load_public_key(pub_path)
    return _fingerprint(public_key)


def get_public_key_pem(config: Config) -> str:
    """Return PEM-encoded public key string."""
    pub_path = config.identity_dir / "public_key.pem"
    if not pub_path.exists():
        raise FileNotFoundError("No identity found. Run identity_init first.")
    return pub_path.read_text()


def get_private_key_seed(config: Config) -> bytes:
    """Return the raw 32-byte seed of the Ed25519 private key, for use in key derivation."""
    private_key = _load_private_key(config)
    return private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
