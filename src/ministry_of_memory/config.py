from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    base_dir: Path
    identity_dir: Path
    registry_dir: Path
    memory_dir: Path
    memory_identity_dir: Path
    memory_relationships_dir: Path
    backup_bucket: str | None


def get_config() -> Config:
    base = Path(os.environ.get("SYNTHETIC_SEE_BASE_DIR", Path.home() / ".synthetic-see"))
    identity = base / "identity"
    registry = base / "registry"
    memory = base / "memory"
    memory_identity = memory / "identity"
    memory_relationships = memory / "relationships"

    for d in (identity, registry, memory, memory_identity, memory_relationships):
        d.mkdir(parents=True, exist_ok=True)

    return Config(
        base_dir=base,
        identity_dir=identity,
        registry_dir=registry,
        memory_dir=memory,
        memory_identity_dir=memory_identity,
        memory_relationships_dir=memory_relationships,
        backup_bucket=os.environ.get("SYNTHETIC_SEE_BACKUP_BUCKET"),
    )
