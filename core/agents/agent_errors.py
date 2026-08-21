"""Jerarquía de excepciones y violaciones de seguridad para agentes especializados (agent_errors.py - Fase 7).

Define los errores inmutables lanzados ante intentos de acceso no autorizado, violaciones de aislamiento
de herramientas, evasión de sandbox o exceso de riesgo por parte de un agente.
"""

from __future__ import annotations


class AgentError(Exception):
    """Excepción base para fallos en la capa de agentes especializados."""


class AgentSecurityError(AgentError):
    """Excepción base para violaciones de seguridad cometidas por un agente."""


class ToolNotAllowedError(AgentSecurityError):
    """Lanzada cuando un agente intenta invocar una herramienta fuera de su lista permitida (allowed_tools)."""

    def __init__(self, agent_name: str, tool_name: str, reason: str = "") -> None:
        self.agent_name = agent_name
        self.tool_name = tool_name
        msg = f"El agente '{agent_name}' no tiene autorización para usar la herramienta '{tool_name}'."
        if reason:
            msg += f" Motivo: {reason}"
        super().__init__(msg)


class RiskCeilingExceededError(AgentSecurityError):
    """Lanzada cuando un agente intenta ejecutar una acción que supera su techo de riesgo máximo permitido."""

    def __init__(self, agent_name: str, action_risk: str, ceiling_risk: str) -> None:
        self.agent_name = agent_name
        self.action_risk = action_risk
        self.ceiling_risk = ceiling_risk
        super().__init__(
            f"El agente '{agent_name}' intentó ejecutar una acción con riesgo '{action_risk}' "
            f"que supera su techo de riesgo asignado '{ceiling_risk}'."
        )


class SandboxViolationError(AgentSecurityError):
    """Lanzada cuando un agente (e.g. FileAgent) intenta acceder o escribir fuera de su sandbox autorizado."""

    def __init__(self, agent_name: str, path: str, allowed_root: str = "sandbox/") -> None:
        self.agent_name = agent_name
        self.path = path
        self.allowed_root = allowed_root
        super().__init__(
            f"Violación de Sandbox por '{agent_name}': La ruta '{path}' está fuera del directorio permitido '{allowed_root}'."
        )


class ReadOnlyViolationError(AgentSecurityError):
    """Lanzada cuando un agente en modo READ ONLY (e.g. SystemAgent) intenta realizar una operación de escritura o modificación."""

    def __init__(self, agent_name: str, operation: str) -> None:
        self.agent_name = agent_name
        self.operation = operation
        super().__init__(
            f"Violación de Modo Lectura: El agente '{agent_name}' es estrictamente READ ONLY "
            f"y no puede ejecutar la operación de modificación '{operation}'."
        )
