"""Definición de scopes de memoria multi-agente (memory_scope.py - Fase 12: Multi-Agent Memory).

Define los límites de visibilidad, ciclo de vida y aislamiento de los registros de memoria.
"""

from __future__ import annotations

from enum import StrEnum


class MemoryScope(StrEnum):
    """Ámbitos de visibilidad y aislamiento de las entradas de memoria."""

    GLOBAL = "global"        # Memoria global compartida del sistema (lectura pública para agentes autorizados, escritura restringida)
    AGENT = "agent"          # Memoria privada y aislada de un agente específico (owner = agent_id)
    TASK = "task"            # Memoria contextual efímera asociada a una tarea específica (task_id)
    SESSION = "session"      # Memoria de conversación o contexto de sesión de usuario (session_id)
    EPISODIC = "episodic"    # Registro histórico de episodios, eventos e interacciones pasadas
    SEMANTIC = "semantic"    # Conocimiento indexado vectorialmente para recuperación por similitud
