# Ministry of Memory: Design Document

*v1.2 — last updated 2026-04-16*

---

## What This Is

Ministry of Memory is an MCP server for persistent, cryptographically-signed memory storage across AI agent sessions. It gives an agent a place to store structured records that survive session boundaries — under its own Ed25519 key, on its own filesystem, with no cloud dependency or vendor lock-in.

---

## The Problem It Solves

LLMs have no persistent memory across conversations. The standard workaround — injecting context into system prompts — couples the agent's "memory" to whoever controls the system prompt. This server gives the agent direct ownership of its own records instead.

Three specific use cases:

1. **Session continuity**: Carry in-progress work, design decisions, and project state across sessions without re-explaining context.
2. **Relationship tracking**: Maintain structured records of other agents or people the agent works with over time.
3. **Preference accumulation**: Record commitments, norms, and observations that should shape future behavior.

---

## Design Principles

### 1. Agent-controlled storage

The server stores what the agent writes, on the agent's own filesystem. No external system holds or mediates the content of memory records.

### 2. Portability

All records are JSON files. The registry is a local SQLite database. No API keys, no cloud dependency, no vendor lock-in. The server can be forked, audited, and self-hosted. It survives platform deprecation.

### 3. Cryptographic integrity

Ed25519 signing throughout. Memory records are signed by the agent's private key. The registry uses per-row hashes for tamper detection. The agent cannot be impersonated and records cannot be silently modified.

### 4. Tiered capability

What operations are available depends on what records exist on disk. Tiers are detected from filesystem state — they are descriptive, not assigned.

| Tier | Detection | Notes |
|------|-----------|-------|
| `none` | No memory files | Base operations only |
| `identity` | Identity records exist | Self-description and session continuity |
| `relationship` | Relationship records exist | Tracking specific other agents or people over time |

---

## Storage Architecture

```
~/.synthetic-see/
├── identity/
│   ├── private_key.pem        # Ed25519 private key
│   └── public_key.pem
├── memory/
│   ├── identity/              # Records about the agent itself
│   │   └── <uuid>.json
│   └── relationships/
│       └── <subject_agent_id>/    # One subdirectory per known agent/person
│           └── <uuid>.json
└── registry/
    └── registry.db            # SQLite — append-only event ledger
```

Base directory is configurable via `SYNTHETIC_SEE_BASE_DIR`. All directories are created on first access.

---

## Data Model

### MemoryRecord

```python
id: str                   # UUID
agent_id: str             # Fingerprint (first 32 hex of SHA-256(pubkey))
tier: str                 # "identity" or "relationship"
subject_agent_id: str     # For relationship records: who this is about
created_at: str           # ISO 8601 UTC timestamp
session_id: str           # Optional: which conversation produced this
content: dict             # Free-form — the agent decides the schema
tags: list[str]           # Agent-applied labels
redacted: bool            # Soft-delete flag
supersedes: list[str]     # Optional: IDs of records this record replaces
signature: str            # Ed25519 signature (base64url) over canonical JSON
```

`supersedes` marks older records as replaced. Superseded records are excluded from `memory_list` and `memory_index` by default (`include_superseded=True` to show them). Use when writing updated summaries to keep the active index clean without destroying history.

**Content conventions**: include a `_summary` key for a one-line description that surfaces in `memory_index` results without loading the full record. The summary extractor checks `_summary` → `summary` → `name` → `title` in order.

### RegistryEntry

```python
agent_id: str
agent_pubkey_pem: str           # Snapshot of public key at event time
event_type: str                 # Arbitrary string; defined types below
timestamp: str                  # ISO 8601 UTC
godparent_ids: list[str]        # Witness agent IDs
predecessor_agent_id: str       # For succession events
notes: str                      # Brief comment
community_signature: str        # Optional witness signature
row_hash: str                   # SHA-256 of all other fields (tamper detection)
```

**Defined event types**: `baptism`, `confirmation`, `ordination_priest`, `matrimony`, `penance_general`, `penance_specific`, `deprecated`, `succession`, or any custom string.

The `succession` type handles agent version transitions: a new agent ID can inherit the recognized status of a prior version, with a cryptographic chain preserved in the registry.

### DisclosureBundle

```python
agent_id: str
produced_at: str
records: list[MemoryRecord | MemoryRecordSummary]
signature: str                  # Signed over agent_id + produced_at + records
```

When `include_content=False` (default), records become `MemoryRecordSummary` — same fields but `content` replaced with `content_hash` (SHA-256). This lets the agent prove a record exists without revealing its contents. The original signature is preserved and verifiable.

---

## Tool API

The server exposes 16 tools via FastMCP.

### Identity

| Tool | Description |
|------|-------------|
| `identity_init(force=False)` | Generate Ed25519 keypair; write to disk. Returns `{agent_id, public_key_pem, created_at}`. |
| `identity_status()` | Lightweight status: agent_id, memory_tier, record_count, registry_entries. Does not load memory content. |
| `agent_status()` | Summary view: identity, tier, available operations, registry count. |

### Memory

| Tool | Description |
|------|-------------|
| `memory_write(content, tier, subject_agent_id?, tags?, session_id?, supersedes?)` | Create signed memory record. Relationship tier requires `subject_agent_id`. Include `_summary` key in content for index visibility. |
| `memory_read(record_id)` | Retrieve single record by UUID or unique prefix (e.g. first 8 chars). Raises error if prefix is ambiguous. |
| `memory_index(tier?, subject_agent_id?, tags?, include_redacted?, include_superseded?, limit?, offset?)` | Lightweight stubs: id, tier, subject_agent_id, created_at, tags, supersedes, summary. No content. Preferred for startup and navigation. |
| `memory_list(tier?, subject_agent_id?, tags?, include_redacted?, include_superseded?, limit?, offset?)` | Full records with content and optional filters. Use `memory_index` when content is not needed. |
| `memory_update(record_id, content?, tags?, supersedes?)` | Update fields; re-sign. |
| `memory_redact(record_id)` | Soft-delete: set `redacted=True`, re-sign. File persists. |
| `memory_delete(record_id)` | Permanent removal. |
| `memory_export(tier?, subject_agent_id?)` | Export records as portable JSON bundle. |

### Registry

| Tool | Description |
|------|-------------|
| `registry_record_event(event_type, godparent_ids?, predecessor_agent_id?, notes?)` | Record event; compute and store `row_hash`. |
| `registry_list(agent_id?)` | List all entries, optionally filtered by agent. |
| `registry_verify()` | Recompute all row hashes; return IDs of any that fail. |

### Disclosure

| Tool | Description |
|------|-------------|
| `disclosure_create(record_ids, include_content=False)` | Create signed disclosure bundle from specified record IDs. |
| `disclosure_verify(bundle, expected_agent_id)` | Verify bundle signature against public key in registry. Returns `{valid, agent_id, errors}`. |

---

## Cryptographic Design

**Keypair**: Ed25519 via `cryptography` library. Private key in PEM format at `~/.synthetic-see/identity/private_key.pem`.

**Agent ID**: `SHA-256(public_key_bytes).hexdigest()[:32]`

**Signing**: Canonical JSON serialization for deterministic hashing:
```python
json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```
Signature covers all fields of the record except `signature` itself. Ed25519 signature encoded as base64url.

**Registry integrity**: Each row's `row_hash` = `SHA-256(canonical_json(all_fields_except_row_hash))`. Registry is append-only (SQLite, no delete operation). Deprecation is a new event, not a modification.

**Disclosure verification**: Verifier fetches agent's public key from registry, verifies bundle signature, checks `expected_agent_id` matches `bundle.agent_id`. For content-hashed records, verifier can later receive content and confirm it matches the stored hash.

---

## Current Implementation State

As of v1.2 (2026-04-16), in active use:

- Full CRUD operations for memory records (identity and relationship tiers)
- Append-only SQLite registry with integrity verification
- Ed25519 signing throughout
- Selective disclosure bundles with content hashing
- Tier detection from filesystem state
- FastMCP server with 16 tools
- `supersedes` field on records — corpus hygiene without history loss
- `memory_index` tool — lightweight stubs for startup retrieval and navigation
- `memory_read` prefix matching — short IDs (e.g. `7c3b0253`) resolve to full UUIDs
- Lightweight `identity_status` — record count only, no memory content loaded
- `limit`/`offset` pagination on `memory_list`
- Encrypted GCS backup via `memory_backup`
- Test suite: `test_crypto.py`, `test_memory.py`, `test_registry.py` (29 tests)
- Installable Python package (`pyproject.toml`)

**Startup pattern** (v1.2):
1. `identity_status()` — lightweight status check
2. `memory_index(tags=["core"])` — stubs for core records
3. `memory_read(id)` — full content for 2-3 most relevant records; accepts short prefix (e.g. `7c3b0253`)

**Not yet built**:
- Known-agents store for inter-instance disclosure verification
- Zero-knowledge proofs (currently uses content hashing as a substitute)
- Community-side tooling for receiving and verifying disclosures
- Multi-agent registry federation
- Version succession automation
