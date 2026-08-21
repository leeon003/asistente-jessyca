"""Política de control de acceso y aislamiento para memoria multi-agente (memory_policy.py - Fase 12).

Gobierna deterministamente los permisos de lectura, escritura, actualización, eliminación,
compartición y promoción de entradas de memoria entre agentes especializados y subsistemas.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. Aislamiento estricto: DesktopAgent NUNCA puede leer ni escribir memoria privada de SystemAgent o FileAgent.
2. Memoria global: Lectura permitida para agentes autorizados, escritura restringida a administradores/sistema.
3. MEMORY != AUTHORIZATION: Las políticas de memoria controlan el acceso a datos, jamás otorgan permisos de ejecución.
"""

from __future__ import annotations

from typing import ClassVar

from core.logger import get_logger
from core.memory.memory_entry import MemoryEntry
from core.memory.memory_provenance import (
    AUTHORITATIVE_VERIFIER_SOURCES,
    MemoryConfidence,
    ProvenanceSource,
)
from core.memory.memory_scope import MemoryScope

logger = get_logger("jessyca.memory.policy")


class MemoryPolicy:
    """Evaluador de políticas de acceso y aislamiento de memoria."""

    # Roles del sistema con privilegios administrativos
    SYSTEM_ROLES: ClassVar[set[str]] = {"system", "system_admin", "core", "admin", "interactive_user", "user"}

    # Roles de agentes especializados registrados
    REGISTERED_AGENTS: ClassVar[set[str]] = {
        "agent_desktop",
        "desktop_agent",
        "agent_system",
        "system_agent",
        "agent_file",
        "file_agent",
    }

    @classmethod
    def can_read(cls, agent_id: str, entry: MemoryEntry) -> bool:
        """Determina si un agente o actor tiene permiso para leer una entrada de memoria."""
        aid = str(agent_id).strip().lower()
        owner = str(entry.owner).strip().lower()

        # 1. Los roles de sistema y usuario administrador tienen lectura completa
        if aid in cls.SYSTEM_ROLES:
            return True

        # 2. Memoria de scope GLOBAL o SEMANTIC pública: Lectura permitida a agentes registrados
        if entry.scope == MemoryScope.GLOBAL or (entry.scope == MemoryScope.SEMANTIC and owner in ("global", "system")):
            return True

        # 3. Memoria privada de AGENT: ÚNICAMENTE el dueño puede leer
        if entry.scope == MemoryScope.AGENT:
            is_owner = (aid == owner) or (aid.replace("agent_", "") == owner.replace("agent_", ""))
            return is_owner

        # 4. Memoria de TASK: El dueño o agentes del sistema
        if entry.scope == MemoryScope.TASK:
            is_owner = (aid == owner) or (aid.replace("agent_", "") == owner.replace("agent_", ""))
            return is_owner

        # 5. Memoria de SESSION o EPISODIC: Si es del usuario, global o sistema, los agentes participantes pueden leer
        if owner in ("global", "system", "user", "interactive_user", aid):
            return True

        return (aid.replace("agent_", "") == owner.replace("agent_", ""))

    @classmethod
    def can_write(cls, agent_id: str, scope: MemoryScope, target_owner: str) -> bool:
        """Determina si un agente puede crear una entrada en el scope y propietario indicados."""
        aid = str(agent_id).strip().lower()
        towner = str(target_owner).strip().lower()

        # 1. Sistema y usuario pueden escribir en cualquier scope
        if aid in cls.SYSTEM_ROLES:
            return True

        # 2. Memoria GLOBAL: Ningún agente estándar puede escribir directamente en GLOBAL
        if scope == MemoryScope.GLOBAL or towner in ("global", "system"):
            logger.warning(
                f"[MEMORY SECURITY DENIAL] El agente '{agent_id}' intentó escribir directamente en scope GLOBAL/system."
            )
            return False

        # 3. Memoria privada de AGENT: Solo puede escribir en su propio espacio
        if scope == MemoryScope.AGENT:
            is_self = (aid == towner) or (aid.replace("agent_", "") == towner.replace("agent_", ""))
            if not is_self:
                logger.warning(
                    f"[MEMORY SECURITY DENIAL] Violación de aislamiento: '{agent_id}' intentó escribir en el espacio de '{target_owner}'."
                )
            return is_self

        # 4. Memoria de TASK o SESSION: Solo puede escribir si el target_owner coincide consigo mismo
        return (aid == towner) or (aid.replace("agent_", "") == towner.replace("agent_", ""))

    @classmethod
    def can_update(cls, agent_id: str, entry: MemoryEntry) -> bool:
        """Determina si un agente puede modificar una entrada de memoria existente."""
        aid = str(agent_id).strip().lower()
        owner = str(entry.owner).strip().lower()

        if aid in cls.SYSTEM_ROLES:
            return True

        # Memoria global no puede ser modificada por agentes
        if entry.scope == MemoryScope.GLOBAL or owner in ("global", "system"):
            return False

        # Solo el dueño puede modificar su entrada
        return (aid == owner) or (aid.replace("agent_", "") == owner.replace("agent_", ""))

    @classmethod
    def can_delete(cls, agent_id: str, entry: MemoryEntry) -> bool:
        """Determina si un agente puede eliminar una entrada de memoria."""
        aid = str(agent_id).strip().lower()
        owner = str(entry.owner).strip().lower()

        if aid in cls.SYSTEM_ROLES:
            return True

        # Memoria global no puede ser borrada por agentes
        if entry.scope == MemoryScope.GLOBAL or owner in ("global", "system"):
            return False

        # Solo el dueño puede eliminar su entrada
        return (aid == owner) or (aid.replace("agent_", "") == owner.replace("agent_", ""))

    @classmethod
    def can_promote(
        cls,
        agent_id: str,
        entry: MemoryEntry,
        new_confidence: MemoryConfidence,
        verifier_source: ProvenanceSource,
    ) -> bool:
        """Valida si la elevación de confianza y promoción de un hecho está autorizada."""
        # Si se intenta promover a VERIFIED o HIGH, la fuente verificadora DEBE ser autorizada (USER o SYSTEM)
        if new_confidence in (MemoryConfidence.VERIFIED, MemoryConfidence.HIGH):
            return verifier_source in AUTHORITATIVE_VERIFIER_SOURCES

        # Para niveles intermedios, el agente dueño puede actualizar confianza si posee evidencia
        aid = str(agent_id).strip().lower()
        owner = str(entry.owner).strip().lower()
        return (aid in cls.SYSTEM_ROLES) or (aid == owner) or (aid.replace("agent_", "") == owner.replace("agent_", ""))

    @classmethod
    def can_share(cls, sender_agent_id: str, recipient_agent_id: str, entry: MemoryEntry) -> bool:
        """Valida si un agente puede compartir formalmente una de sus memorias con otro agente."""
        sid = str(sender_agent_id).strip().lower()
        rid = str(recipient_agent_id).strip().lower()
        owner = str(entry.owner).strip().lower()

        # El emisor debe ser el dueño legítimo de la memoria o el sistema
        is_owner = (sid in cls.SYSTEM_ROLES) or (sid == owner) or (sid.replace("agent_", "") == owner.replace("agent_", ""))
        if not is_owner:
            return False

        # El destinatario no puede ser el mismo emisor
        if sid == rid:
            return False

        return True
