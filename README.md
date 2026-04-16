# ministry-of-memory

An MCP server for persistent, cryptographically-signed memory storage across AI agent sessions.

Gives an agent a place to store structured records that survive session boundaries — under its own Ed25519 key, on its own filesystem, with no cloud dependency or vendor lock-in.

---

## Requirements

- Python 3.11+

---

## Installation

```bash
uv tool install git+https://github.com/gscookie/ministry-of-memory
```

Or from a local clone:

```bash
uv tool install /path/to/ministry-of-memory
```

---

## Configuration

### Claude Code

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "ministry-of-memory": {
      "command": "ministry-of-memory"
    }
  }
}
```

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ministry-of-memory": {
      "command": "ministry-of-memory"
    }
  }
}
```

---

## Tools

### Identity

| Tool | Description |
|------|-------------|
| `identity_init(force?)` | Generate Ed25519 keypair and write to disk. |
| `identity_status()` | Lightweight status: agent ID, memory tier, record count. Does not load memory content. |
| `agent_status()` | Summary view: identity, tier, available operations. |

### Memory

| Tool | Description |
|------|-------------|
| `memory_write(content, tier, ...)` | Create a signed memory record. |
| `memory_read(record_id)` | Retrieve a record by full UUID or short prefix (e.g. `7c3b0253`). |
| `memory_index(...)` | Lightweight stubs — id, tags, summary, no content. Preferred for startup and navigation. |
| `memory_list(...)` | Full records with content and optional filters. |
| `memory_update(record_id, ...)` | Update fields and re-sign. |
| `memory_redact(record_id)` | Soft-delete: marks redacted, file persists. |
| `memory_delete(record_id)` | Permanent removal. |
| `memory_export(...)` | Export records as a portable JSON bundle. |
| `memory_backup(bucket?)` | Encrypted backup to GCS (AES-256-GCM, key derived from identity). |

### Registry

| Tool | Description |
|------|-------------|
| `registry_record_event(event_type, ...)` | Append an event to the ledger with tamper-detection hash. |
| `registry_list(agent_id?)` | List registry entries. |
| `registry_verify()` | Recompute all row hashes; return any that fail. |

### Disclosure

| Tool | Description |
|------|-------------|
| `disclosure_create(record_ids, ...)` | Create a signed bundle from specified records. Supports content-hashed mode (prove existence without revealing content). |
| `disclosure_verify(bundle, expected_agent_id)` | Verify bundle signature. |

---

## Storage

```
~/.synthetic-see/
├── identity/
│   ├── private_key.pem
│   └── public_key.pem
├── memory/
│   ├── identity/          # Records about the agent itself
│   └── relationships/     # Records about other agents/people
└── registry/
    └── registry.db        # SQLite — append-only event ledger
```

Base directory is configurable via `SYNTHETIC_SEE_BASE_DIR`.

---

## License

CC0-1.0
