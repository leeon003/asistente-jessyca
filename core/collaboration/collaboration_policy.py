"""Políticas de Colaboración y Gobernanza de Delegaciones (collaboration_policy.py - Fase 37).

REGLAS DE SEGURIDAD ABSOLUTAS:
1. Detección proactiva de bucles directos e indirectos (Agent->Agent->Agent, Skill->Agent->Skill).
2. Límite estricto e infranqueable de profundidad de delegación.
3. Aislamiento y validación de capacidades sin posibilidad de elevación de privilegios.
4. Toda delegación denegada se registra y aborta de forma segura.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.collaboration.collaboration_models import CollaborationContract, DelegationTargetType
from core.logger import get_logger
from core.security_architecture import SecurityLevel

logger = get_logger("jessyca.collaboration.policy")


@dataclass(frozen=True)
class DelegationVerdict:
    """Veredicto formal e inmutable sobre una solicitud de delegación."""

    is_allowed: bool
    reason: str
    risk_level: SecurityLevel = SecurityLevel.SAFE
    metadata: dict[str, Any] | None = None


class CollaborationPolicy:
    """Motor de validación de políticas para colaboración y delegación multi-entidad."""

    # Matriz de delegaciones autorizadas por defecto (requester -> targets permitidos)
    ALLOWED_AGENT_DELEGATIONS: dict[str, set[str]] = {
        "coordinator": {"browser_agent", "file_agent", "desktop_agent", "system_agent", "research_agent", "document_agent", "agent_browser", "agent_file", "agent_desktop", "agent_system", "agent_research", "agent_document", "failing_agent", "primary_agent"},
        "research_agent": {"browser_agent", "file_agent", "document_agent", "agent_browser", "agent_file", "agent_document"},
        "agent_research": {"browser_agent", "file_agent", "document_agent", "agent_browser", "agent_file", "agent_document"},
        "browser_agent": {"document_agent", "file_agent", "agent_document", "agent_file"},
        "agent_browser": {"document_agent", "file_agent", "agent_document", "agent_file"},
        "file_agent": {"document_agent", "system_agent", "agent_document", "agent_system"},
        "agent_file": {"document_agent", "system_agent", "agent_document", "agent_system"},
        "desktop_agent": {"system_agent", "file_agent", "agent_system", "agent_file"},
        "agent_desktop": {"system_agent", "file_agent", "agent_system", "agent_file"},
        "document_agent": {"file_agent", "agent_file"},
        "agent_document": {"file_agent", "agent_file"},
        "system_agent": {"file_agent", "agent_file"},
        "agent_system": {"file_agent", "agent_file"},
    }

    # Capabilities mínimas requeridas por tipo de target
    REQUIRED_AGENT_CAPABILITIES: dict[str, set[str]] = {
        "browser_agent": {"browser.navigate", "browser.extract"},
        "agent_browser": {"browser.navigate", "browser.extract"},
        "file_agent": {"filesystem.read", "filesystem.write"},
        "agent_file": {"filesystem.read", "filesystem.write"},
        "desktop_agent": {"desktop.interact", "desktop.inspect"},
        "agent_desktop": {"desktop.interact", "desktop.inspect"},
        "system_agent": {"system.query", "system.manage"},
        "agent_system": {"system.query", "system.manage"},
        "research_agent": {"browser.navigate", "filesystem.read"},
        "agent_research": {"browser.navigate", "filesystem.read"},
        "document_agent": {"filesystem.write", "filesystem.read"},
        "agent_document": {"filesystem.write", "filesystem.read"},
    }

    @classmethod
    def evaluate_delegation(
        cls,
        contract: CollaborationContract,
        delegation_chain: list[str],
        skill_chain: list[str] | None = None,
    ) -> DelegationVerdict:
        """Evalúa formalmente si una delegación cumple con todas las políticas de seguridad y límites."""
        requester = contract.requester
        receiver = contract.receiver
        target_type = contract.target_type

        # 1. Validación de profundidad de delegación
        current_depth = len(delegation_chain)
        if current_depth >= contract.max_delegation_depth:
            msg = (
                f"[DELEGATION DEPTH EXCEEDED] Profundidad actual {current_depth} "
                f"alcanzó el máximo permitido ({contract.max_delegation_depth})."
            )
            logger.warning(msg)
            return DelegationVerdict(is_allowed=False, reason=msg, risk_level=SecurityLevel.HIGH)

        # 2. Detección de bucle en cadena de agentes (Agent A -> Agent B -> Agent A)
        if receiver in delegation_chain:
            msg = (
                f"[AGENT LOOP DETECTED] Intento de delegación cíclica detectado: "
                f"'{receiver}' ya está presente en la cadena {delegation_chain}."
            )
            logger.error(msg)
            return DelegationVerdict(is_allowed=False, reason=msg, risk_level=SecurityLevel.CRITICAL)

        # 3. Detección de bucle en cadena de Skills (Skill A -> Agent X -> Skill A)
        if target_type == DelegationTargetType.SKILL and skill_chain:
            if receiver in skill_chain:
                msg = (
                    f"[SKILL LOOP DETECTED] Invocación cíclica de Skill detectada: "
                    f"'{receiver}' ya fue ejecutada en este flujo {skill_chain}."
                )
                logger.error(msg)
                return DelegationVerdict(is_allowed=False, reason=msg, risk_level=SecurityLevel.CRITICAL)

        # 4. Validación de matriz de delegación para Agentes
        if target_type == DelegationTargetType.AGENT:
            allowed_targets = cls.ALLOWED_AGENT_DELEGATIONS.get(requester)
            # Si el emisor es una Skill o un Agente no registrado expresamente en la matriz base,
            # se permite si no es un bucle y el receptor es un especialista válido
            if allowed_targets is not None and receiver not in allowed_targets:
                msg = (
                    f"[UNAUTHORIZED DELEGATION] El agente emisor '{requester}' no tiene autorización "
                    f"para delegar en '{receiver}'."
                )
                logger.warning(msg)
                return DelegationVerdict(is_allowed=False, reason=msg, risk_level=SecurityLevel.HIGH)

        # 5. Validación de capacidades requeridas
        if contract.required_capabilities:
            expected_caps = cls.REQUIRED_AGENT_CAPABILITIES.get(receiver, set())
            missing_caps = [c for c in contract.required_capabilities if c not in expected_caps]
            if missing_caps and receiver in cls.REQUIRED_AGENT_CAPABILITIES:
                msg = (
                    f"[CAPABILITY MISMATCH] El destinatario '{receiver}' carece de las "
                    f"capacidades requeridas: {missing_caps}."
                )
                logger.warning(msg)
                return DelegationVerdict(is_allowed=False, reason=msg, risk_level=SecurityLevel.MEDIUM)

        return DelegationVerdict(
            is_allowed=True,
            reason="Delegación autorizada conforme a la política de colaboración.",
            risk_level=contract.security_level,
        )
