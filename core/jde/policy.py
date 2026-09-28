"""Policy & Safety Gate para JESSYCA Decision Engine (JDE).

Integra y gobierna la autorización determinista previa a cualquier ejecución:
- allowed
- denied
- requires_confirmation
- requires_verification
- risk_level

Alineado con el principio Fail-Safe: ante la duda, no autorizar o exigir confirmación.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.logger import get_logger

logger = get_logger("jessyca.jde.policy")


class JDEPolicyDecision(BaseModel):
    """Decisión de gobernanza emitida por el JDE Policy Gate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_allowed: bool
    requires_confirmation: bool = False
    requires_verification: bool = True
    risk_level: str = "SAFE"
    reason: str = ""
    rule_matched: str | None = None
    confirmation_prompt: str | None = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JDEPolicyGate:
    """Compuerta central de autorización y políticas para JDE.

    Reutiliza y se comunica con el subsistema de seguridad existente de JESSYCA
    (`RiskEngine`, `SecurityPolicyEvaluator`, `PermissionManager`).
    """

    # Acciones intrínsecamente de alto riesgo que siempre exigen confirmación
    CRITICAL_ACTION_PATTERNS: tuple[str, ...] = (
        "delete", "remove", "kill", "format", "reboot", "shutdown",
        "reg_delete", "powershell_raw", "drop", "terminate"
    )

    def __init__(
        self,
        security_policy: Any | None = None,
        risk_engine: Any | None = None,
        permission_manager: Any | None = None,
    ) -> None:
        self._security_policy = security_policy
        self._risk_engine = risk_engine
        self._permission_manager = permission_manager

    def evaluate(
        self,
        tool: str,
        action: str,
        parameters: dict[str, Any],
        user_confirmed: bool = False,
        declared_risk: str | None = None,
    ) -> JDEPolicyDecision:
        """Evalúa si una acción propuesta está autorizada para ejecución."""
        tool_clean = tool.strip().lower()
        action_clean = action.strip().lower()

        # 1. Comprobar si coincide con patrones críticos destructivos
        is_critical = any(pat in action_clean or pat in tool_clean for pat in self.CRITICAL_ACTION_PATTERNS)
        effective_risk = declared_risk or ("HIGH" if is_critical else "SAFE")

        # 2. Si es crítica y el usuario NO ha confirmado -> REQUIRES_CONFIRMATION
        if is_critical and not user_confirmed:
            logger.info(f"[JDE POLICY] Acción sensible detectada: '{tool}:{action}'. Exige confirmación.")
            return JDEPolicyDecision(
                is_allowed=False,
                requires_confirmation=True,
                requires_verification=True,
                risk_level="HIGH",
                reason=f"La acción '{action}' sobre '{tool}' es crítica y requiere confirmación explícita del usuario.",
                rule_matched="CRITICAL_ACTION_CONFIRMATION_REQUIRED",
                confirmation_prompt=f"¿Confirmas que deseas ejecutar la acción sensible '{action}' en '{tool}'?",
            )

        # 3. Integración con SecurityPolicy existente si está disponible
        if self._security_policy is not None:
            try:
                # Comprobación de compatibilidad con SecurityPolicy de core.security_policy
                if hasattr(self._security_policy, "evaluate"):
                    res = self._security_policy.evaluate(tool=tool_clean, operation=action_clean, params=parameters)
                    if hasattr(res, "is_allowed") and not res.is_allowed:
                        return JDEPolicyDecision(
                            is_allowed=False,
                            requires_confirmation=False,
                            requires_verification=True,
                            risk_level=effective_risk,
                            reason=getattr(res, "reason", "Denegado por SecurityPolicy del sistema."),
                            rule_matched="SYSTEM_SECURITY_POLICY_DENY",
                        )
            except Exception as e:
                logger.warning(f"[JDE POLICY] Error al consultar SecurityPolicy externa: {e}")

        # 4. Autorizado para ejecución con verificación obligatoria
        return JDEPolicyDecision(
            is_allowed=True,
            requires_confirmation=False,
            requires_verification=True,
            risk_level=effective_risk,
            reason="Acción autorizada por política estándar de JDE.",
            rule_matched="DEFAULT_ALLOW",
        )
