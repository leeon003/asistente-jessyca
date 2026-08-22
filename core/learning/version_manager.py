"""Gestor de Versiones y Snapshots de Automejora (version_manager.py - Fase 60).

Define las estructuras y lógica para el versionamiento inmutable del sistema:
- VersionSnapshot (captura auditable con checksum SHA-256)
- ImprovementCandidate (candidato a versión v2-candidate)
- VersionManager (control de historial, ramas de candidatos y versión activa)
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.logger import get_logger

logger = get_logger("jessyca.learning.version_manager")


class CandidateStatus(StrEnum):
    """Estados formales del ciclo de vida de un candidato a mejora."""

    CREATED = "CREATED"
    SANDBOXED = "SANDBOXED"
    TESTING = "TESTING"
    TESTS_PASSED = "TESTS_PASSED"
    TESTS_FAILED = "TESTS_FAILED"
    EVALUATED = "EVALUATED"
    APPROVED = "APPROVED"
    DEPLOYED = "DEPLOYED"
    DISCARDED = "DISCARDED"
    ROLLED_BACK = "ROLLED_BACK"


class VersionSnapshot(BaseModel):
    """Instantánea inmutable de una versión del sistema con integridad criptográfica."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    version_id: str
    parent_version: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_proposal_id: str | None = None
    files_changed: list[str] = Field(default_factory=list)
    tests_passed: bool = True
    metrics: dict[str, float] = Field(default_factory=dict)
    status: str = "ACTIVE"
    checksum: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serializa el snapshot en un diccionario JSON."""
        return self.model_dump(mode="json")

    @classmethod
    def create_snapshot(
        cls,
        version_id: str,
        parent_version: str | None = None,
        source_proposal_id: str | None = None,
        files_changed: list[str] | None = None,
        metrics: dict[str, float] | None = None,
        status: str = "ACTIVE",
    ) -> VersionSnapshot:
        """Crea un snapshot calculando su checksum canónico SHA-256."""
        now = datetime.now(UTC)
        files = files_changed or []
        mets = metrics or {"success_rate": 1.0, "avg_latency_ms": 100.0}

        payload = {
            "version_id": version_id,
            "parent_version": parent_version,
            "created_at": now.isoformat(),
            "source_proposal_id": source_proposal_id,
            "files_changed": sorted(files),
            "metrics": mets,
            "status": status,
        }
        canonical_str = json.dumps(payload, sort_keys=True)
        chk = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

        return cls(
            version_id=version_id,
            parent_version=parent_version,
            created_at=now,
            source_proposal_id=source_proposal_id,
            files_changed=files,
            tests_passed=True,
            metrics=mets,
            status=status,
            checksum=chk,
        )


class ImprovementCandidate(BaseModel):
    """Representación de un candidato a versión experimental (ej. v2-candidate)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    candidate_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    version_tag: str = "v2-candidate"
    parent_version: str = "v1.0.0"
    source_proposal_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    affected_files: list[str] = Field(default_factory=list)
    staged_changes: dict[str, str] = Field(default_factory=dict)
    status: CandidateStatus = CandidateStatus.CREATED
    tests_run: int = 0
    tests_passed: bool = False
    candidate_metrics: dict[str, float] = Field(default_factory=dict)
    rejection_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class VersionManager:
    """Gestor del historial de versiones y candidatos de automejora."""

    def __init__(self, initial_version: str = "v1.0.0") -> None:
        self._lock = threading.RLock()
        self._snapshots: dict[str, VersionSnapshot] = {}
        self._candidates: dict[str, ImprovementCandidate] = {}

        # Crear versión inicial base
        base_snapshot = VersionSnapshot.create_snapshot(
            version_id=initial_version,
            parent_version=None,
            metrics={"success_rate": 1.0, "failure_rate": 0.0, "avg_latency_ms": 150.0},
            status="ACTIVE",
        )
        self._snapshots[initial_version] = base_snapshot
        self._active_version_id = initial_version

    @property
    def active_version(self) -> VersionSnapshot:
        with self._lock:
            return self._snapshots[self._active_version_id]

    def get_snapshot(self, version_id: str) -> VersionSnapshot | None:
        with self._lock:
            return self._snapshots.get(version_id)

    def list_snapshots(self) -> list[VersionSnapshot]:
        with self._lock:
            return sorted(self._snapshots.values(), key=lambda s: s.created_at)

    def register_snapshot(self, snapshot: VersionSnapshot) -> None:
        with self._lock:
            self._snapshots[snapshot.version_id] = snapshot

    def set_active_version(self, version_id: str) -> None:
        with self._lock:
            if version_id not in self._snapshots:
                raise ValueError(f"No existe el snapshot con ID '{version_id}'.")
            self._active_version_id = version_id
            logger.info(f"[VERSION MANAGER] Versión activa establecida en '{version_id}'.")

    def create_candidate(
        self,
        source_proposal_id: str,
        version_tag: str,
        affected_files: list[str],
        staged_changes: dict[str, str],
    ) -> ImprovementCandidate:
        """Crea un nuevo candidato a mejora a partir de una propuesta."""
        with self._lock:
            candidate = ImprovementCandidate(
                version_tag=version_tag,
                parent_version=self._active_version_id,
                source_proposal_id=source_proposal_id,
                affected_files=affected_files,
                staged_changes=staged_changes,
                status=CandidateStatus.CREATED,
            )
            self._candidates[candidate.candidate_id] = candidate
            logger.info(f"[VERSION MANAGER] Creado candidato '{version_tag}' ({candidate.candidate_id}) derivado de {self._active_version_id}.")
            return candidate

    def get_candidate(self, candidate_id: str) -> ImprovementCandidate | None:
        with self._lock:
            return self._candidates.get(candidate_id)

    def update_candidate(self, candidate: ImprovementCandidate) -> None:
        with self._lock:
            self._candidates[candidate.candidate_id] = candidate
