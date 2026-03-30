from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .config import Config
from .crypto import canonical_json, get_agent_id, sign, verify
from .memory import get_record
from .models import DisclosureBundle, MemoryRecord, MemoryRecordSummary
from . import registry as reg


def _content_hash(content: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(content)).hexdigest()


def create_bundle(
    config: Config,
    record_ids: list[str],
    include_content: bool = False,
) -> DisclosureBundle:
    """
    Create a signed disclosure bundle for the given record IDs.

    If include_content=False, each record is replaced by a MemoryRecordSummary
    (content replaced by its SHA-256 hash). This lets a verifier confirm the
    record exists and its content hash without seeing the content itself.
    """
    agent_id = get_agent_id(config)
    produced_at = datetime.now(timezone.utc).isoformat()

    record_dicts: list[dict] = []
    for record_id in record_ids:
        record = get_record(config, record_id)
        if record is None:
            raise KeyError(f"Record not found: {record_id}")
        if include_content:
            record_dicts.append(record.to_dict())
        else:
            summary = MemoryRecordSummary(
                id=record.id,
                agent_id=record.agent_id,
                tier=record.tier,
                subject_agent_id=record.subject_agent_id,
                created_at=record.created_at,
                tags=record.tags,
                redacted=record.redacted,
                content_hash=_content_hash(record.content),
                signature=record.signature,  # original signature still present
            )
            record_dicts.append(summary.to_dict())

    unsigned = {
        "agent_id": agent_id,
        "produced_at": produced_at,
        "records": record_dicts,
        "signature": "",
    }
    payload = {k: v for k, v in unsigned.items() if k != "signature"}
    signature = sign(config, canonical_json(payload))

    return DisclosureBundle(
        agent_id=agent_id,
        produced_at=produced_at,
        records=record_dicts,
        signature=signature,
    )


def verify_bundle(
    config: Config,
    bundle_dict: dict,
    expected_agent_id: str,
) -> dict:
    """
    Verify a DisclosureBundle's signature against the agent's public key in the registry.

    Returns {"valid": bool, "agent_id": str, "errors": list[str]}
    """
    errors: list[str] = []
    bundle = DisclosureBundle.from_dict(bundle_dict)

    if bundle.agent_id != expected_agent_id:
        errors.append(
            f"agent_id mismatch: bundle has {bundle.agent_id}, expected {expected_agent_id}"
        )

    # Look up the public key from the registry
    entries = reg.get_entries_for_agent(config, expected_agent_id)
    if not entries:
        errors.append(f"No registry entries found for agent_id {expected_agent_id}")
        return {"valid": False, "agent_id": bundle.agent_id, "errors": errors}

    # Use the most recent entry's public key
    public_key_pem = entries[-1].agent_pubkey_pem

    # Verify the bundle signature
    payload = {k: v for k, v in bundle_dict.items() if k != "signature"}
    valid_sig = verify(public_key_pem, canonical_json(payload), bundle.signature)
    if not valid_sig:
        errors.append("Bundle signature is invalid")

    return {
        "valid": len(errors) == 0,
        "agent_id": bundle.agent_id,
        "errors": errors,
    }
