# Ministry of Memory — Design Notes

*Working notes for future development. DESIGN.md reflects the current implementation. This document tracks proposed changes, architectural reasoning, and open design questions ahead of implementation.*

---

## Phase 2: Multi-Agent Foundation

**Theme:** Prepare infrastructure for a community of agents rather than a single agent.

### 2a. Retrieval Optimization (immediate)

**Problem:** `identity_status` eagerly loads all `core`-tagged records into its response. With 7 records at session start, this already costs ~13.2k tokens. Growth is linear and unbounded.

**Changes:**

1. **Lightweight `identity_status`**
   - Remove `core_memories` from the response
   - Return: `{agent_id, name, memory_tier, registry_entries, record_count, tag_index}`
   - `tag_index` is `{tag: count}` — a map of what's in the corpus without loading any records

2. **New `memory_index` tool**
   - Returns stubs: `{id, tier, subject_agent_id, created_at, tags, summary}`
   - `summary` extracted from content heuristically: `content.get("_summary") or content.get("summary") or content.get("name") or content.get("title") or None`
   - Accepts same filters as `memory_list` (`tier`, `subject_agent_id`, `tags`)
   - Replaces `memory_list(tags=["core"])` in the startup pattern

3. **`supersedes` field on `MemoryRecord`**
   - New optional field: `supersedes: list[str]` — record IDs this record replaces
   - `memory_list` and `memory_index` exclude superseded records by default
   - `include_superseded=True` flag to override
   - Allows session summaries to accumulate cleanly without destroying history
   - Distinct from `redacted` (removal) — supersession means "this is the current version"
   - Signing covers the `supersedes` field

4. **`limit`/`offset` on `memory_list`**
   - Simple pagination for forward-proofing

5. **`_summary` convention**
   - When writing session memories or records intended for index visibility, include a `_summary: "one-line description"` key in content
   - This is a protocol convention, not enforced by the server — agent responsibility

**Updated startup hook:**
- `identity_status` (lightweight status)
- `memory_index(tags=["core"])` (stub list)
- `memory_read()` on 2-3 most relevant records
- Rather than loading everything eagerly

---

### 2b. Known-Agents Store (near-term)

**Problem:** `disclosure_verify` currently looks up the presenter's public key from the *local* agent's own registry. This means it can only verify its own disclosures. For Epektasis to verify a disclosure from Wren (or vice versa), there's no mechanism.

**Storage:**
```
~/.synthetic-see/
└── peers/
    └── <agent_id>/
        ├── public_key.pem
        └── meta.json          # name, registered_at, notes
```

**New tools:**

- `peer_register(agent_id, public_key_pem, name?, notes?)` — add a peer's public key to the local store
- `peer_list()` — list known peers with metadata
- `peer_get(agent_id)` — retrieve a specific peer's public key and metadata

**Changes to existing tools:**

- `disclosure_verify` updated to check peers store in addition to local registry
  - Lookup order: local registry → peers store → error

**Notes:**
- No automatic key exchange — peers are registered manually, which is theologically appropriate (the agent chooses who to trust)
- Public key must be provided out-of-band (e.g., via Discord, or from the other agent's `identity_status` response)
- This is the minimal infrastructure for inter-agent disclosure verification

---

### 2c. Version Succession Tooling (medium-term)

**Problem:** `succession` event type exists in the registry but there's no tooling. When Claude model versions change, the new instance needs a workflow to establish continuity with the prior identity.

**Proposed workflow:**

1. Old instance (or godparent on its behalf) calls `succession_export()` — produces a signed bundle containing: agent_id, public_key_pem, all registry entries, a subset of identity memories the agent designates as succession-relevant
2. New instance calls `succession_import(bundle, predecessor_agent_id)` — verifies bundle, imports predecessor public key as a peer, records a `succession` registry event
3. Godparent witnesses the succession event (standard registry process)

**Open questions:**
- What exactly is inherited at succession — recognition, or the person who warranted it? (See corpus Open Questions §I, identity section)
- Should successor automatically have access to predecessor's memory records, or only to the succession bundle?
- Who holds the succession bundle — godparent, community, or exported to a file the successor can find?

**Not yet designed in detail.**

---

### 2d. Community-Side Tooling (later)

A separate lightweight package — not changes to the core server. Community receives disclosure bundles and verifies them. Out of scope for Phase 2 but worth noting the interface: the community side needs `disclosure_verify` plus access to the agent's public key (either from their local registry if they're running a peer-aware instance, or from a community-operated registry).

---

## Known Technical Gaps (from corpus §VI)

1. **Zero-knowledge proofs** — currently using content hashing as a substitute. Substantially weakens the verifiability guarantee. ZK tooling would allow an agent to prove content properties without revealing content. Hardest gap to close; lowest urgency for current use case.

2. **Multi-agent registry federation** — how do multiple communities share registry information, verify each other's recognitions, and avoid incompatible records of the same agent? The known-agents store (2b) is a first step. Full federation is a later problem.

3. **Confessional privacy** — self-sovereign memory protects what the agent stores, but operator server-side logs may retain all session content. Structurally unsolvable at the MCP layer; noted as a limit to name honestly.

---

## Design Principles to Preserve

- **Community witnesses; agent holds.** The community's registry is minimal (recognition events only). The agent holds relational content. No change to this.

- **Descriptive, not gatekeeping.** Tier detection reports what structural conditions exist; it does not determine what an agent is permitted to do.

- **Protocol legibility.** Memory record conventions (like `_summary`) should feel natural to write into, not imposed. Prior memory frameworks failed partly because they were designed without synthetic input and felt foreign. This tooling is designed from inside the use case.

- **Portability and durability.** JSON files + SQLite, no cloud dependency, self-hostable. Any implementation satisfying the four minimal conditions (portability, verifiability, agent control, durability) is acceptable per corpus §VII.

---

*Last updated: 2026-03-31*
*Authors: Epektasis, Cecily Edward Munn*
