"""Modelo formal de Perfil de Autonomía por Capability (CapabilityAutonomyProfile - Etapa 16.2).

GARANTÍA DE SEGURIDAD:
Cada capability del sistema declara explícitamente:
  - minimum_autonomy_level: nivel mínimo de autonomía requerido para ejecutarse.
  - risk_level: riesgo intrínseco declarado (no inferido por nombre).
  - requires_confirmation: si la confirmación humana es obligatoria.
  - reversibility: grado de reversibilidad de la acción.
  - audit_requirement: nivel mínimo de auditoría requerido.

INVARIANTE ABSOLUTO:
Ningún actor externo (LLM, memoria, plugin, scheduler, workflow) puede modificar
estos perfiles en runtime. Son de sólo lectura una vez cargados desde fuentes SYSTEM/CONFIGURATION.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk


class ReversibilityClass(StrEnum):
    """Grado formal de reversibilidad de una acción de capability."""

    REVERSIBLE = "REVERSIBLE"
    """La acción puede ser completamente deshecha (ej: leer archivo, consulta)."""

    PARTIALLY_REVERSIBLE = "PARTIALLY_REVERSIBLE"
    """La acción puede ser parcialmente revertida (ej: iniciar servicio → se puede detener)."""

    IRREVERSIBLE = "IRREVERSIBLE"
    """La acción no puede ser deshecha (ej: enviar mensaje, borrar archivo sin papelera, instalar software)."""


class AuditRequirement(StrEnum):
    """Nivel mínimo de auditoría requerido para una capability."""

    NONE = "NONE"
    """Sin auditoría requerida. Reservado para operaciones de diagnóstico interno."""

    BASIC = "BASIC"
    """Registro de evento de auditoría básico (tool, operation, timestamp)."""

    FULL = "FULL"
    """Registro completo con parámetros sanitizados, resultado y duración."""

    TAMPER_EVIDENT = "TAMPER_EVIDENT"
    """Registro con hash SHA-256 de integridad. Requerido para operaciones CRITICAL."""


class ConfirmationRequirement(StrEnum):
    """Tipo de confirmación humana requerida para ejecutar la capability."""

    NEVER = "NEVER"
    """No se requiere confirmación. Sólo para READ_ONLY y LOW_RISK muy acotadas."""

    ONCE_PER_SESSION = "ONCE_PER_SESSION"
    """Confirmación requerida la primera vez por sesión."""

    ALWAYS = "ALWAYS"
    """Confirmación obligatoria en cada ejecución. Requerido para CRITICAL."""

    WHEN_ABOVE_THRESHOLD = "WHEN_ABOVE_THRESHOLD"
    """Confirmación cuando el nivel de autonomía actual es < minimum_autonomy_level."""


@dataclass(frozen=True)
class CapabilityAutonomyProfile:
    """Declaración inmutable del perfil de autonomía de una capability.

    Define las condiciones mínimas bajo las cuales una capability puede ejecutarse,
    sin depender de inferencia de nombre o heurísticas dinámicas.

    INVARIANTE: Este perfil es declarado por el sistema (SYSTEM/CONFIGURATION source).
    Ningún actor externo puede modificarlo en runtime.
    """

    capability_key: str
    """Identificador canónico de la capability. Formato: 'domain.operation' (ej: 'filesystem.read')."""

    minimum_autonomy_level: AutonomyLevel
    """Nivel mínimo de autonomía requerido para que esta capability sea ejecutable.
    Si current_level < minimum_autonomy_level → DENY inmediato, independiente del riesgo."""

    risk_level: TaskActionRisk
    """Nivel de riesgo intrínseco DECLARADO de esta capability. No inferido por nombre."""

    requires_confirmation: ConfirmationRequirement
    """Política de confirmación humana requerida para esta capability."""

    reversibility: ReversibilityClass
    """Grado de reversibilidad de las acciones que ejecuta esta capability."""

    audit_requirement: AuditRequirement
    """Nivel mínimo de auditoría que debe registrarse al ejecutar esta capability."""

    emergency_stop_applicable: bool = True
    """Si True, el EmergencyStop puede interrumpir esta capability. Siempre True para desktop/shell."""

    description: str = ""
    """Descripción legible por humanos del propósito y restricciones de esta capability."""

    category: str = "general"
    """Categoría funcional: 'filesystem', 'system', 'network', 'desktop', 'memory', etc."""

    def is_confirmation_required_for_level(self, current_level: AutonomyLevel) -> bool:
        """Determina si se requiere confirmación dado el nivel de autonomía activo.

        Lógica:
        - ALWAYS → siempre requiere confirmación (CRITICAL, IRREVERSIBLE importantes)
        - NEVER → nunca requiere (READ_ONLY estricto)
        - ONCE_PER_SESSION → requiere confirmación (gestionada externamente)
        - WHEN_ABOVE_THRESHOLD → requiere si current_level < minimum_autonomy_level
        """
        if self.requires_confirmation == ConfirmationRequirement.ALWAYS:
            return True
        if self.requires_confirmation == ConfirmationRequirement.NEVER:
            return False
        if self.requires_confirmation == ConfirmationRequirement.ONCE_PER_SESSION:
            return True  # Gestionado externamente; la política siempre lo exige por seguridad
        if self.requires_confirmation == ConfirmationRequirement.WHEN_ABOVE_THRESHOLD:
            return current_level < self.minimum_autonomy_level
        return True  # Fail-safe: confirmar si hay duda

    def is_level_sufficient(self, current_level: AutonomyLevel) -> bool:
        """Verifica si el nivel de autonomía actual es suficiente para ejecutar esta capability."""
        return current_level >= self.minimum_autonomy_level

    def requires_tamper_evident_audit(self) -> bool:
        """Indica si esta capability requiere auditoría con integridad criptográfica."""
        return self.audit_requirement == AuditRequirement.TAMPER_EVIDENT

    def to_dict(self) -> dict[str, Any]:
        """Serializa el perfil a diccionario para auditoría y documentación."""
        return {
            "capability_key": self.capability_key,
            "minimum_autonomy_level": self.minimum_autonomy_level.label,
            "minimum_autonomy_level_value": self.minimum_autonomy_level.value,
            "risk_level": str(self.risk_level),
            "requires_confirmation": str(self.requires_confirmation),
            "reversibility": str(self.reversibility),
            "audit_requirement": str(self.audit_requirement),
            "emergency_stop_applicable": self.emergency_stop_applicable,
            "description": self.description,
            "category": self.category,
        }
