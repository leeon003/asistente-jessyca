"""Sub-sistema de Memoria Multi-Agente de JESSYCA 3.0 (Fase 12).

Exporta las clases, modelos y utilidades para la gestión de memoria global, privada por agente,
efímera por tarea y semántica con control de acceso por políticas y procedencia.
"""

from core.memory.memory_access import (
    MemoryAccessControl,
    MemoryPromotionRequest,
    MemoryShareRequest,
)
from core.memory.memory_entry import MemoryEntry
from core.memory.memory_exceptions import (
    InvalidProvenanceError,
    MemoryAccessDeniedError,
    MemoryError,
    MemoryIsolationViolationError,
    MemoryNotFoundError,
    MemoryPoisoningError,
    MemoryPromotionError,
    MemoryScopeError,
)
from core.memory.memory_manager import (
    MemoryManager,
    get_memory_manager,
)
from core.memory.memory_policy import MemoryPolicy
from core.memory.memory_provenance import (
    AUTHORITATIVE_VERIFIER_SOURCES,
    MemoryConfidence,
    MemoryProvenance,
    ProvenanceSource,
)
from core.memory.memory_scope import MemoryScope

__all__ = [
    "AUTHORITATIVE_VERIFIER_SOURCES",
    "InvalidProvenanceError",
    "MemoryAccessControl",
    "MemoryAccessDeniedError",
    "MemoryConfidence",
    "MemoryEntry",
    "MemoryError",
    "MemoryIsolationViolationError",
    "MemoryManager",
    "MemoryNotFoundError",
    "MemoryPoisoningError",
    "MemoryPolicy",
    "MemoryPromotionError",
    "MemoryPromotionRequest",
    "MemoryProvenance",
    "MemoryScope",
    "MemoryScopeError",
    "MemoryShareRequest",
    "ProvenanceSource",
    "get_memory_manager",
]
