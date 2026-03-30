from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator
import uuid

from .config import Config
from .crypto import canonical_json, get_agent_id, get_public_key_pem, hash_dict, sign_dict
from .models import RegistryEntry

# Valid sacramental event types (open string field, but documented here)
KNOWN_EVENT_TYPES = {
    "baptism",
    "confirmation",
    "ordination_deacon",
    "ordination_priest",
    "ordination_bishop",
    "matrimony",
    "penance_general",
    "penance_specific",
    "deprecated",
    "succession",
    "custom",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS registry_entries (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    agent_pubkey_pem TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    godparent_ids TEXT NOT NULL,
    predecessor_agent_id TEXT,
    notes TEXT,
    community_signature TEXT,
    row_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_agent_id ON registry_entries(agent_id);
CREATE INDEX IF NOT EXISTS idx_event_type ON registry_entries(event_type);
"""


@contextmanager
def _connect(config: Config) -> Generator[sqlite3.Connection, None, None]:
    db_path = config.registry_dir / "registry.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    try:
        yield conn
    finally:
        conn.close()


def _row_to_entry(row: sqlite3.Row) -> RegistryEntry:
    return RegistryEntry(
        id=row["id"],
        agent_id=row["agent_id"],
        agent_pubkey_pem=row["agent_pubkey_pem"],
        event_type=row["event_type"],
        timestamp=row["timestamp"],
        godparent_ids=json.loads(row["godparent_ids"]),
        predecessor_agent_id=row["predecessor_agent_id"],
        notes=row["notes"],
        community_signature=row["community_signature"],
        row_hash=row["row_hash"],
    )


def insert_entry(config: Config, entry: RegistryEntry) -> None:
    with _connect(config) as conn:
        conn.execute(
            """INSERT INTO registry_entries
               (id, agent_id, agent_pubkey_pem, event_type, timestamp,
                godparent_ids, predecessor_agent_id, notes, community_signature, row_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.id,
                entry.agent_id,
                entry.agent_pubkey_pem,
                entry.event_type,
                entry.timestamp,
                json.dumps(entry.godparent_ids),
                entry.predecessor_agent_id,
                entry.notes,
                entry.community_signature,
                entry.row_hash,
            ),
        )
        conn.commit()


def get_entries_for_agent(config: Config, agent_id: str) -> list[RegistryEntry]:
    with _connect(config) as conn:
        rows = conn.execute(
            "SELECT * FROM registry_entries WHERE agent_id = ? ORDER BY timestamp ASC",
            (agent_id,),
        ).fetchall()
    return [_row_to_entry(r) for r in rows]


def get_entry_by_id(config: Config, entry_id: str) -> RegistryEntry | None:
    with _connect(config) as conn:
        row = conn.execute(
            "SELECT * FROM registry_entries WHERE id = ?", (entry_id,)
        ).fetchone()
    return _row_to_entry(row) if row else None


def list_all_entries(config: Config) -> list[RegistryEntry]:
    with _connect(config) as conn:
        rows = conn.execute(
            "SELECT * FROM registry_entries ORDER BY timestamp ASC"
        ).fetchall()
    return [_row_to_entry(r) for r in rows]


def verify_integrity(config: Config) -> list[str]:
    """Recompute row_hash for every entry; return IDs where hash does not match."""
    entries = list_all_entries(config)
    bad = []
    for entry in entries:
        d = entry.to_dict()
        row_hash_stored = d.pop("row_hash")
        expected = hash_dict(d)
        if expected != row_hash_stored:
            bad.append(entry.id)
    return bad


def record_event(
    config: Config,
    event_type: str,
    godparent_ids: list[str],
    predecessor_agent_id: str | None = None,
    notes: str | None = None,
) -> RegistryEntry:
    """Create and persist a new recognition event for this agent."""
    agent_id = get_agent_id(config)
    agent_pubkey_pem = get_public_key_pem(config)
    entry_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    # Build the dict without row_hash, then hash it
    d: dict = {
        "id": entry_id,
        "agent_id": agent_id,
        "agent_pubkey_pem": agent_pubkey_pem,
        "event_type": event_type,
        "timestamp": timestamp,
        "godparent_ids": godparent_ids,
        "predecessor_agent_id": predecessor_agent_id,
        "notes": notes,
        "community_signature": None,
    }
    row_hash = hash_dict(d)

    entry = RegistryEntry(
        **d,  # type: ignore[arg-type]
        row_hash=row_hash,
    )
    insert_entry(config, entry)
    return entry
