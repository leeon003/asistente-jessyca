"""Modelos de datos y estructuras tipadas para evaluación de intenciones y aclaración conversacional (Fase 2)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class IntentStatus(StrEnum):
    """Estados formales de evaluación de una intención del usuario."""

    CLEAR = "CLEAR"
    AMBIGUOUS = "AMBIGUOUS"
    INCOMPLETE = "INCOMPLETE"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID = "INVALID"


@dataclass
class ParsedIntent:
    """Resultado estructurado y tipado devuelto por la interpretación del Brain."""

    estado: IntentStatus = IntentStatus.CLEAR
    respuesta_hablada: str = ""
    skill: str | None = None
    parametros: dict[str, Any] | None = field(default_factory=dict)
    pregunta_aclaratoria: str | None = None
    parametro_faltante: str | None = None
    candidatos: list[str] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convierte la instancia en un diccionario estándar compatible con el contrato histórico."""
        return {
            "estado": self.estado.value,
            "respuesta_hablada": self.respuesta_hablada,
            "skill": self.skill,
            "parametros": self.parametros,
            "pregunta_aclaratoria": self.pregunta_aclaratoria,
            "parametro_faltante": self.parametro_faltante,
            "candidatos": self.candidatos,
            "error": self.error,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Acceso tipo diccionario para compatibilidad hacia atrás con consumidores legados."""
        return self.to_dict().get(key, default)

    def __getitem__(self, key: str) -> Any:
        """Permite indexación de diccionario obj['key']."""
        return self.to_dict()[key]

    def __contains__(self, key: object) -> bool:
        """Soporta operador 'in' para verificar existencia de claves."""
        return key in self.to_dict()


@dataclass
class PendingIntent:
    """Intención pausada en espera de aclaración o suministro de parámetros por parte del usuario."""

    skill_nombre: str
    parametros_parciales: dict[str, Any] = field(default_factory=dict)
    parametro_esperado: str | None = None
    candidatos_posibles: list[str] = field(default_factory=list)
    pregunta_formulada: str = ""
    timestamp: float = field(default_factory=time.time)
    intentos: int = 0
    estado_origen: IntentStatus = IntentStatus.INCOMPLETE

    def ha_expirado(self, ttl_segundos: float = 60.0) -> bool:
        """Verifica si la intención pendiente ha superado el tiempo de vida máximo."""
        return (time.time() - self.timestamp) > ttl_segundos


@dataclass
class ValidationResult:
    """Resultado determinista de la validación estructural y de suficiencia realizada por IntentValidator."""

    is_valid: bool
    status: IntentStatus
    skill_name: str | None = None
    validated_parameters: dict[str, Any] = field(default_factory=dict)
    missing_parameter: str | None = None
    clarification_prompt: str | None = None
    candidates: list[str] = field(default_factory=list)
    reason: str = ""


__all__ = [
    "IntentStatus",
    "ParsedIntent",
    "PendingIntent",
    "ValidationResult",
]
