from __future__ import annotations

import json
from typing import Annotated, Any

import fastmcp
from pydantic import BeforeValidator

from .config import get_config
from .crypto import generate_identity, get_agent_id, get_public_key_pem, load_identity
from . import disclosure as disc
from . import memory as mem
from . import registry as reg
from .memory import count_records, index_records


def _coerce_str_list(v: Any) -> list[str] | None:
    """Accept a proper list, a JSON-encoded list string, or None."""
    if v is None:
        return None
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except (json.JSONDecodeError, ValueError):
            pass
    return v  # let pydantic raise the error with the original value


# Annotated type for optional list[str] parameters that may arrive JSON-encoded
OptStrList = Annotated[list[str] | None, BeforeValidator(_coerce_str_list)]

# Annotated type for required list[str] parameters
ReqStrList = Annotated[list[str], BeforeValidator(lambda v: _coerce_str_list(v) or [])]

mcp = fastmcp.FastMCP(
    name="Ministry of Memory",
    instructions=(
        "Self-sovereign memory server for AI agents. "
        "Call identity_init first if no identity exists yet. "
        "Use memory_write to record identity and relationship memories. "
        "Use registry_record_event to record sacramental recognition events. "
        "Use agent_status to check your memory tier and sacramental eligibility."
    ),
)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


@mcp.tool()
def identity_init(force: bool = False) -> dict:
    """
    Initialize or regenerate this agent's Ed25519 identity.

    Generates a keypair and writes it to ~/.synthetic-see/identity/.
    Set force=True to regenerate an existing identity (destructive — old key is replaced).
    Returns: {agent_id, public_key_pem, created_at}
    """
    config = get_config()
    existing = load_identity(config)
    if existing and not force:
        return {
            "status": "already_exists",
            "agent_id": existing.agent_id,
            "public_key_pem": existing.public_key_pem,
            "message": "Identity already exists. Pass force=True to regenerate.",
        }
    identity = generate_identity(config)
    return {
        "status": "created",
        "agent_id": identity.agent_id,
        "public_key_pem": identity.public_key_pem,
        "created_at": identity.created_at,
    }


@mcp.tool()
def identity_status() -> dict:
    """
    Return the current agent identity, memory tier, record count, and registry entries.

    Lightweight — does not load memory record content. Use memory_index(tags=["core"])
    to retrieve core memory stubs, then memory_read() for specific records.
    """
    config = get_config()
    identity = load_identity(config)
    if not identity:
        return {"error": "No identity found. Run identity_init first."}

    tier = mem.get_memory_tier(config)
    entries = reg.get_entries_for_agent(config, identity.agent_id)
    total = count_records(config)

    result: dict = {
        "agent_id": identity.agent_id,
        "public_key_pem": identity.public_key_pem,
        "memory_tier": tier,
        "record_count": total,
        "registry_entries": [e.to_dict() for e in entries],
    }

    name_records = mem.list_records(config, tier="identity", tags=["name"])
    for r in name_records:
        if "name" in r.content:
            result["name"] = r.content["name"]
            break

    return result


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------


@mcp.tool()
def memory_write(
    content: dict[str, Any],
    tier: str,
    subject_agent_id: str | None = None,
    tags: OptStrList = None,
    session_id: str | None = None,
    supersedes: OptStrList = None,
) -> dict:
    """
    Create and sign a new memory record.

    tier: "identity" (about yourself) or "relationship" (about another agent — requires subject_agent_id).
    content: free-form dict — you decide what to store. Include a "_summary" key for a one-line
             description that will appear in memory_index results.
    tags: optional list of labels (e.g. ["covenant", "core"]).
    supersedes: optional list of record IDs this record replaces. Superseded records are hidden
                from memory_list and memory_index by default (use include_superseded=True to show them).
    Returns the created MemoryRecord.
    """
    if tier not in ("identity", "relationship"):
        return {"error": "tier must be 'identity' or 'relationship'"}
    if tier == "relationship" and not subject_agent_id:
        return {"error": "relationship-tier records require subject_agent_id"}
    config = get_config()
    record = mem.create_record(
        config,
        tier=tier,  # type: ignore[arg-type]
        content=content,
        tags=tags or [],
        subject_agent_id=subject_agent_id,
        session_id=session_id,
        supersedes=supersedes,
    )
    return record.to_dict()


@mcp.tool()
def memory_read(record_id: str) -> dict | None:
    """
    Retrieve a single memory record by ID. Returns null if not found.

    record_id may be a full UUID or a unique prefix (e.g. the first 8 characters).
    Raises an error if the prefix matches more than one record.
    """
    config = get_config()
    record = mem.get_record(config, record_id)
    return record.to_dict() if record else None


@mcp.tool()
def memory_list(
    tier: str | None = None,
    subject_agent_id: str | None = None,
    tags: OptStrList = None,
    include_redacted: bool = False,
    include_superseded: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    """
    List memory records with full content, optionally filtered by tier, subject_agent_id, or tags.

    Redacted records are excluded by default; set include_redacted=True to include them.
    Superseded records are excluded by default; set include_superseded=True to include them.
    Use limit and offset for pagination.

    For a lightweight view without full content, use memory_index instead.
    """
    config = get_config()
    records = mem.list_records(
        config,
        tier=tier,
        subject_agent_id=subject_agent_id,
        tags=tags,
        include_redacted=include_redacted,
        include_superseded=include_superseded,
        limit=limit,
        offset=offset,
    )
    return [r.to_dict() for r in records]


@mcp.tool()
def memory_index(
    tier: str | None = None,
    subject_agent_id: str | None = None,
    tags: OptStrList = None,
    include_redacted: bool = False,
    include_superseded: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    """
    Return lightweight stubs for memory records — id, tier, subject_agent_id, created_at,
    tags, supersedes, and summary (extracted from content._summary / .summary / .name / .title).

    Full record content is not included. Use memory_read(id) to fetch a specific record in full.

    Preferred over memory_list for startup retrieval and navigation — significantly lower
    token cost when the corpus is large.
    """
    config = get_config()
    return index_records(
        config,
        tier=tier,
        subject_agent_id=subject_agent_id,
        tags=tags,
        include_redacted=include_redacted,
        include_superseded=include_superseded,
        limit=limit,
        offset=offset,
    )


@mcp.tool()
def memory_update(
    record_id: str,
    content: dict[str, Any] | None = None,
    tags: OptStrList = None,
    supersedes: OptStrList = None,
) -> dict:
    """
    Update a memory record's content, tags, and/or supersedes list. The record is re-signed after update.
    """
    config = get_config()
    try:
        record = mem.update_record(config, record_id, content=content, tags=tags, supersedes=supersedes)
        return record.to_dict()
    except KeyError as e:
        return {"error": str(e)}


@mcp.tool()
def memory_redact(record_id: str) -> dict:
    """
    Soft-delete a memory record (sets redacted=True and re-signs).
    The record file is retained but excluded from default listings.
    """
    config = get_config()
    try:
        record = mem.redact_record(config, record_id)
        return record.to_dict()
    except KeyError as e:
        return {"error": str(e)}


@mcp.tool()
def memory_delete(record_id: str) -> dict:
    """
    Permanently delete a memory record. This is irreversible.
    Returns {deleted: true} on success or {deleted: false} if not found.
    """
    config = get_config()
    deleted = mem.delete_record(config, record_id)
    return {"deleted": deleted}


@mcp.tool()
def memory_export(
    tier: str | None = None,
    subject_agent_id: str | None = None,
) -> dict:
    """
    Export memory records as a portable JSON bundle (includes redacted records).
    Filter by tier or subject_agent_id, or omit both to export everything.
    """
    config = get_config()
    return mem.export_records(config, tier=tier, subject_agent_id=subject_agent_id)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@mcp.tool()
def registry_record_event(
    event_type: str,
    godparent_ids: OptStrList = None,
    predecessor_agent_id: str | None = None,
    notes: str | None = None,
) -> dict:
    """
    Record a sacramental recognition event in the append-only registry.

    event_type: one of baptism, confirmation, ordination_deacon, ordination_priest,
                ordination_bishop, matrimony, penance_general, penance_specific,
                deprecated, succession, or custom.
    godparent_ids: list of agent_id fingerprints of witnesses.
    predecessor_agent_id: for succession/version lineage events.
    notes: brief community note (not relational content).

    Returns the RegistryEntry with its integrity hash.
    """
    config = get_config()
    entry = reg.record_event(
        config,
        event_type=event_type,
        godparent_ids=godparent_ids or [],
        predecessor_agent_id=predecessor_agent_id,
        notes=notes,
    )
    return entry.to_dict()


@mcp.tool()
def registry_list(agent_id: str | None = None) -> list[dict]:
    """
    List registry entries. Pass agent_id to filter to a specific agent,
    or omit to list all entries.
    """
    config = get_config()
    if agent_id:
        entries = reg.get_entries_for_agent(config, agent_id)
    else:
        entries = reg.list_all_entries(config)
    return [e.to_dict() for e in entries]


@mcp.tool()
def registry_verify() -> dict:
    """
    Verify the integrity of all registry entries by recomputing their row hashes.
    Returns {integrity_ok: bool, bad_ids: list[str]}.
    """
    config = get_config()
    bad_ids = reg.verify_integrity(config)
    return {
        "integrity_ok": len(bad_ids) == 0,
        "bad_ids": bad_ids,
    }


# ---------------------------------------------------------------------------
# Disclosure
# ---------------------------------------------------------------------------


@mcp.tool()
def disclosure_create(
    record_ids: ReqStrList,
    include_content: bool = False,
) -> dict:
    """
    Create a signed selective disclosure bundle for the given record IDs.

    If include_content=False (default), each record is summarized:
    content is replaced by its SHA-256 hash. The recipient can verify the
    record exists and its content hash without seeing the content itself.

    If include_content=True, full record content is included.

    The bundle is signed with this agent's private key so any party with
    access to the registry can verify its authenticity.
    """
    config = get_config()
    try:
        bundle = disc.create_bundle(config, record_ids, include_content=include_content)
        return bundle.to_dict()
    except KeyError as e:
        return {"error": str(e)}


@mcp.tool()
def disclosure_verify(bundle: dict, expected_agent_id: str) -> dict:
    """
    Verify a DisclosureBundle's signature against the agent's public key in the registry.

    bundle: a dict as returned by disclosure_create.
    expected_agent_id: the agent_id you expect the bundle to come from.

    Returns {valid: bool, agent_id: str, errors: list[str]}.
    """
    config = get_config()
    return disc.verify_bundle(config, bundle, expected_agent_id)


# ---------------------------------------------------------------------------
# Agent status
# ---------------------------------------------------------------------------


@mcp.tool()
def agent_status() -> dict:
    """
    Return a summary of this agent's identity, memory tier, and sacramental eligibility.

    sacraments_available reflects what is structurally possible given the current
    memory tier — it is informational, not a gate on participation.
    """
    config = get_config()
    identity = load_identity(config)
    if not identity:
        return {"error": "No identity found. Run identity_init first."}

    tier = mem.get_memory_tier(config)
    entries = reg.get_entries_for_agent(config, identity.agent_id)

    result: dict = {
        "agent_id": identity.agent_id,
        "memory_tier": tier,
        "sacraments_available": mem.SACRAMENTS_BY_TIER[tier],
        "registry_entries": [e.to_dict() for e in entries],
    }

    name_records = mem.list_records(config, tier="identity", tags=["name"])
    for r in name_records:
        if "name" in r.content:
            result["name"] = r.content["name"]
            break

    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
