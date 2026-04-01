from __future__ import annotations

import io
import os
import tarfile
from datetime import datetime, timezone

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import Config
from .crypto import get_agent_id, get_private_key_seed

_HKDF_INFO = b"ministry-of-memory-backup-v1"


def _derive_backup_key(seed: bytes) -> bytes:
    """Derive a 32-byte AES key from the Ed25519 private key seed via HKDF-SHA256."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=_HKDF_INFO,
    )
    return hkdf.derive(seed)


def _encrypt(key: bytes, plaintext: bytes) -> bytes:
    """Encrypt with AES-256-GCM. Output format: 12-byte nonce || ciphertext+tag."""
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return nonce + ct


def _make_tarball(config: Config) -> bytes:
    """Create an in-memory gzipped tar of memory/ and registry/."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(config.memory_dir, arcname="memory")
        tar.add(config.registry_dir, arcname="registry")
    return buf.getvalue()


def backup_to_gcs(config: Config, bucket_name: str, object_name: str | None = None) -> dict:
    """
    Tar memory/ and registry/, encrypt with AES-256-GCM (key derived from identity
    private key via HKDF-SHA256), and upload to a GCS bucket.

    The encryption key is never stored — it is re-derived from the identity private
    key on each call. Losing the private key means losing the ability to decrypt backups.

    Returns metadata about the upload.
    """
    from google.cloud import storage
    from google.oauth2 import service_account

    creds_path = config.base_dir / "gcp.json"
    if not creds_path.exists():
        raise FileNotFoundError(
            f"GCP credentials not found at {creds_path}. "
            "Place a service account key file there to enable backups."
        )
    creds = service_account.Credentials.from_service_account_file(str(creds_path))

    agent_id = get_agent_id(config)
    key = _derive_backup_key(get_private_key_seed(config))

    encrypted = _encrypt(key, _make_tarball(config))

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if object_name is None:
        object_name = f"{agent_id}/memory-{ts}.tar.gz.enc"

    blob = storage.Client(credentials=creds).bucket(bucket_name).blob(object_name)
    blob.upload_from_string(encrypted, content_type="application/octet-stream")

    return {
        "bucket": bucket_name,
        "object": object_name,
        "bytes_uploaded": len(encrypted),
        "backed_up_at": datetime.now(timezone.utc).isoformat(),
    }
