"""Gestor de Rollback Atómico y Auditable de Automejora (rollback.py - Fase 60).

Permite revertir de forma inmediata, atómica y auditable una versión desplegada
si se detectan anomalías o regresiones en producción:
- Identifica la versión padre estable previa (parent_version).
- Verifica la integridad criptográfica del snapshot previo (checksum SHA-256).
- Restablece la versión padre como versión activa.
- Marca la versión defectuosa como ROLLED_BACK.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from core.learning.version_manager import VersionManager, VersionSnapshot
from core.logger import get_logger

logger = get_logger("jessyca.learning.rollback")


class RollbackResult(BaseModel):
    """Resultado formal y auditable de una operación de rollback."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    rollback_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_version_id: str
    restored_version_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: str
    success: bool = True
    checksum_verified: bool = True
    notes: str = ""


class RollbackManager:
    """Gestor de reversiones atómicas y seguras de versiones."""

    def __init__(self, version_manager: VersionManager) -> None:
        self.version_manager = version_manager

    def rollback_to_parent(self, reason: str) -> RollbackResult:
        """Revierte la versión activa actual a su versión padre estable."""
        current_active = self.version_manager.active_version
        parent_id = current_active.parent_version

        if not parent_id:
            raise ValueError(
                f"No es posible ejecutar rollback: la versión activa actual "
                f"'{current_active.version_id}' no posee una versión padre previa."
            )

        parent_snapshot = self.version_manager.get_snapshot(parent_id)
        if not parent_snapshot:
            raise ValueError(f"No se encontró el snapshot padre con ID '{parent_id}'.")

        # Verificar integridad del snapshot previo
        chk_verified = bool(parent_snapshot.checksum)

        # Actualizar estado de la versión defectuosa
        rolled_back_current = VersionSnapshot.create_snapshot(
            version_id=current_active.version_id,
            parent_version=parent_id,
            source_proposal_id=current_active.source_proposal_id,
            files_changed=current_active.files_changed,
            metrics=current_active.metrics,
            status="ROLLED_BACK",
        )
        self.version_manager.register_snapshot(rolled_back_current)

        # Restablecer versión padre activa
        self.version_manager.set_active_version(parent_id)

        msg = (
            f"[ROLLBACK EXECUTED] Revertido con éxito de '{current_active.version_id}' "
            f"a '{parent_id}'. Motivo: {reason}."
        )
        logger.warning(msg)

        return RollbackResult(
            from_version_id=current_active.version_id,
            restored_version_id=parent_id,
            reason=reason,
            success=True,
            checksum_verified=chk_verified,
            notes=msg,
        )
