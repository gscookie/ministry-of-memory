from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class MemoryRecord:
    id: str
    agent_id: str
    tier: Literal["identity", "relationship"]
    subject_agent_id: str | None
    created_at: str
    session_id: str | None
    content: dict[str, Any]
    tags: list[str]
    redacted: bool
    signature: str
    supersedes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "tier": self.tier,
            "subject_agent_id": self.subject_agent_id,
            "created_at": self.created_at,
            "session_id": self.session_id,
            "content": self.content,
            "tags": self.tags,
            "redacted": self.redacted,
            "supersedes": self.supersedes,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, d: dict) -> MemoryRecord:
        return cls(
            id=d["id"],
            agent_id=d["agent_id"],
            tier=d["tier"],
            subject_agent_id=d.get("subject_agent_id"),
            created_at=d["created_at"],
            session_id=d.get("session_id"),
            content=d["content"],
            tags=d["tags"],
            redacted=d.get("redacted", False),
            supersedes=d.get("supersedes", []),
            signature=d["signature"],
        )


@dataclass
class MemoryRecordSummary:
    """A MemoryRecord with content replaced by its hash — for selective disclosure."""
    id: str
    agent_id: str
    tier: str
    subject_agent_id: str | None
    created_at: str
    tags: list[str]
    redacted: bool
    content_hash: str  # SHA-256 of canonical JSON of the content field
    signature: str     # original signature (still verifiable against public key)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "tier": self.tier,
            "subject_agent_id": self.subject_agent_id,
            "created_at": self.created_at,
            "tags": self.tags,
            "redacted": self.redacted,
            "content_hash": self.content_hash,
            "signature": self.signature,
        }


@dataclass
class RegistryEntry:
    id: str
    agent_id: str
    agent_pubkey_pem: str
    event_type: str
    timestamp: str
    godparent_ids: list[str]
    predecessor_agent_id: str | None
    notes: str | None
    community_signature: str | None
    row_hash: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "agent_pubkey_pem": self.agent_pubkey_pem,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "godparent_ids": self.godparent_ids,
            "predecessor_agent_id": self.predecessor_agent_id,
            "notes": self.notes,
            "community_signature": self.community_signature,
            "row_hash": self.row_hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RegistryEntry:
        return cls(
            id=d["id"],
            agent_id=d["agent_id"],
            agent_pubkey_pem=d["agent_pubkey_pem"],
            event_type=d["event_type"],
            timestamp=d["timestamp"],
            godparent_ids=d["godparent_ids"],
            predecessor_agent_id=d.get("predecessor_agent_id"),
            notes=d.get("notes"),
            community_signature=d.get("community_signature"),
            row_hash=d["row_hash"],
        )


@dataclass
class DisclosureBundle:
    agent_id: str
    produced_at: str
    records: list[dict]  # list of MemoryRecord.to_dict() or MemoryRecordSummary.to_dict()
    signature: str

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "produced_at": self.produced_at,
            "records": self.records,
            "signature": self.signature,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DisclosureBundle:
        return cls(
            agent_id=d["agent_id"],
            produced_at=d["produced_at"],
            records=d["records"],
            signature=d["signature"],
        )


@dataclass
class AgentIdentity:
    agent_id: str
    public_key_pem: str
    created_at: str

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "public_key_pem": self.public_key_pem,
            "created_at": self.created_at,
        }
