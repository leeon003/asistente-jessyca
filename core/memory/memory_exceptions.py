"""Jerarquía de excepciones tipadas para el subsistema de memoria multi-agente (memory_exceptions.py - Fase 12).

Define los errores específicos para violaciones de acceso, aislamiento entre agentes, fallos de procedencia,
intentos de envenenamiento de memoria y promociones no autorizadas.
"""

from __future__ import annotations

from core.exceptions import MCPError


class MemoryError(MCPError):
    """Excepción base para todos los errores del subsistema de memoria de JESSYCA 3.0."""

    pass


class MemoryAccessDeniedError(MemoryError):
    """Emitida cuando un agente o componente intenta acceder a una memoria sin autorización de política."""

    pass


class MemoryIsolationViolationError(MemoryAccessDeniedError):
    """Emitida cuando un agente intenta acceder o modificar la memoria privada de otro agente sin delegación."""

    pass


class MemoryScopeError(MemoryError):
    """Emitida cuando se especifica un scope de memoria inválido o incompatible."""

    pass


class InvalidProvenanceError(MemoryError):
    """Emitida cuando los datos de procedencia de una memoria son inconsistentes, corruptos o inválidos."""

    pass


class MemoryPoisoningError(MemoryError):
    """Emitida cuando se detecta un intento de inyección de comandos o auto-autorización en memoria."""

    pass


class MemoryPromotionError(MemoryError):
    """Emitida cuando se intenta promover un claim a hecho verificado sin la evidencia o autoridad requerida."""

    pass


class MemoryNotFoundError(MemoryError):
    """Emitida cuando no se encuentra una entrada de memoria solicitada."""

    pass
