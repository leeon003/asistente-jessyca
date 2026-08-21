"""Políticas de autorización y control de delegación entre agentes (delegation_policy.py - Fase 9).

Controla estrictamente qué agentes pueden delegar tareas a otros, acotando el scope, la profundidad máxima
y previniendo ciclos infinitos, delegaciones recursivas y escalamiento de privilegios.

GARANTÍA DE SEGURIDAD (INVARIANTES):
1. Un agente NO puede delegar arbitrariamente.
2. Toda delegación debe estar autorizada en la matriz de delegación, tener scope y presupuesto delimitado.
3. Prohibido: Delegación recursiva, ciclos y escalamiento de privilegios. Profundidad máxima: MAX_DELEGATION_DEPTH (2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.agents.delegation")

MAX_DELEGATION_DEPTH: int = 2

# Matriz estricta de delegaciones permitidas: (sender_id, recipient_id) -> Set[allowed_scopes]
ALLOWED_DELEGATIONS: dict[tuple[str, str], frozenset[str]] = {
    # SystemAgent puede delegar verificación visual a DesktopAgent
    ("agent_system", "agent_desktop"): frozenset({
        "visual_verification",
        "screen_check",
        "ui_inspect",
        "verify_ui",
    }),
    # SystemAgent puede delegar persistencia de diagnósticos a FileAgent
    ("agent_system", "agent_file"): frozenset({
        "export_report",
        "save_diagnostics",
        "write_log",
        "save_metrics",
    }),
    # DesktopAgent puede delegar almacenamiento de capturas a FileAgent
    ("agent_desktop", "agent_file"): frozenset({
        "save_screenshot",
        "save_ocr",
        "export_ui",
    }),
}


@dataclass(frozen=True)
class DelegationVerdict:
    """Veredicto determinista de la evaluación de una solicitud de delegación."""

    is_allowed: bool
    reason: str
    authorized_scope: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class DelegationPolicy:
    """Validador central de seguridad para delegaciones inter-agente."""

    @classmethod
    def validate_delegation(
        cls,
        sender_agent_id: str,
        recipient_agent_id: str,
        scope: str,
        delegation_chain: tuple[str, ...] = (),
    ) -> DelegationVerdict:
        """Valida determinísticamente si una delegación entre agentes está formalmente autorizada."""
        # 1. Validación de auto-delegación
        if sender_agent_id == recipient_agent_id:
            msg = f"Auto-delegación no permitida para el agente '{sender_agent_id}'."
            logger.warning(f"[DELEGATION DENIED] {msg}")
            return DelegationVerdict(is_allowed=False, reason=msg)

        # 2. Detección de ciclos y recursión (A -> B -> A)
        full_chain = delegation_chain + (sender_agent_id,)
        if recipient_agent_id in full_chain:
            msg = (
                f"Ciclo de delegación recursiva detectado: "
                f"La cadena [{' -> '.join(full_chain)}] ya contiene al destinatario '{recipient_agent_id}'."
            )
            logger.warning(f"[DELEGATION DENIED] {msg}")
            return DelegationVerdict(is_allowed=False, reason=msg)

        # 3. Límite de profundidad de delegación
        current_depth = len(delegation_chain)
        if current_depth >= MAX_DELEGATION_DEPTH:
            msg = (
                f"Profundidad máxima de delegación excedida ({current_depth} >= {MAX_DELEGATION_DEPTH}). "
                f"Cadena: [{' -> '.join(full_chain)}]."
            )
            logger.warning(f"[DELEGATION DENIED] {msg}")
            return DelegationVerdict(is_allowed=False, reason=msg)

        # 4. Verificación de autorización en la matriz
        pair = (sender_agent_id, recipient_agent_id)
        if pair not in ALLOWED_DELEGATIONS:
            msg = (
                f"Delegación no autorizada: El agente '{sender_agent_id}' NO tiene permiso "
                f"para delegar tareas hacia '{recipient_agent_id}'."
            )
            logger.warning(f"[DELEGATION DENIED] {msg}")
            return DelegationVerdict(is_allowed=False, reason=msg)

        # 5. Verificación de scope permitido
        allowed_scopes = ALLOWED_DELEGATIONS[pair]
        clean_scope = scope.strip().lower()
        if clean_scope not in allowed_scopes:
            msg = (
                f"Scope de delegación no autorizado: El scope '{scope}' no está permitido entre "
                f"'{sender_agent_id}' y '{recipient_agent_id}'. Scopes autorizados: {list(allowed_scopes)}."
            )
            logger.warning(f"[DELEGATION DENIED] {msg}")
            return DelegationVerdict(is_allowed=False, reason=msg)

        logger.info(
            f"[DELEGATION AUTHORIZED] '{sender_agent_id}' -> '{recipient_agent_id}' "
            f"(scope: '{clean_scope}', profundidad: {current_depth + 1})"
        )
        return DelegationVerdict(
            is_allowed=True,
            reason="Delegación autorizada por política.",
            authorized_scope=clean_scope,
        )
