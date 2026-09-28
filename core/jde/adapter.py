"""Adaptador de Observación Shadow para JessycaLocalAgent (core/jde/adapter.py).

Permite vincular el contexto de ejecución de `JessycaLocalAgent._execute_unified_pipeline()`
hacia `JDEShadowMode` de forma completamente segura, tipada y sin impacto en la producción.

Invariantes:
1. NUNCA propaga excepciones al agente principal (Fail-Safe total).
2. NUNCA altera el objeto `JessycaResponse`.
3. NUNCA realiza llamadas a ejecutores del sistema operativo.
4. Redacta secretos automáticamente.
"""

from __future__ import annotations

import time
from typing import Any

from core.jde.models import DecisionRequest, VerificationRequirement
from core.jde.shadow import JDEShadowMode, ShadowEvaluation, get_jde_shadow_mode
from core.logger import get_logger

logger = get_logger("jessyca.jde.adapter")


class LocalAgentExecutionContext:
    """Contenedor de contexto de un turno ejecutado por JessycaLocalAgent."""

    def __init__(
        self,
        request_id: str,
        user_input: str,
        intent: str,
        tool: str | None,
        action: str | None,
        parameters: dict[str, Any],
        exec_success: bool,
        current_message: str,
        is_verified: bool = False,
        execution_result: Any = None,
        security_level: Any = None,
        confidence: float = 1.0,
    ) -> None:
        self.request_id = request_id
        self.user_input = user_input
        self.intent = intent
        self.tool = tool or "unknown_tool"
        self.action = action or intent
        self.parameters = parameters
        self.exec_success = exec_success
        self.current_message = current_message
        self.is_verified = is_verified
        self.execution_result = execution_result
        self.security_level = str(security_level.value) if hasattr(security_level, "value") else str(security_level or "SAFE")
        self.confidence = confidence


class JDEShadowAdapter:
    """Adaptador que transforma el contexto de ejecución del agente en DecisionRequest de JDE."""

    def __init__(self, shadow_mode: JDEShadowMode | None = None) -> None:
        self.shadow_mode = shadow_mode or get_jde_shadow_mode()

    def observe(self, ctx: LocalAgentExecutionContext) -> ShadowEvaluation | None:
        """Observa pasivamente una ejecución sin alterar en absoluto la respuesta de producción."""
        try:
            # 1. Resolver estrategia y target de verificación declarativo
            tool_clean = ctx.tool.lower()
            intent_clean = ctx.intent.lower()

            target_val = (
                ctx.parameters.get("app_name")
                or ctx.parameters.get("nombre_app")
                or ctx.parameters.get("query")
                or ctx.parameters.get("url")
                or ctx.action
            )

            verification_requirements: list[VerificationRequirement] = []
            if "browser" in tool_clean or "youtube" in tool_clean:
                strat = "youtube_playback" if "youtube" in tool_clean else "browser_tab"
                verification_requirements.append(
                    VerificationRequirement(strategy=strat, target=str(target_val))
                )
            elif "app" in tool_clean or "notepad" in str(target_val).lower() or "calc" in str(target_val).lower():
                verification_requirements.append(
                    VerificationRequirement(strategy="window_visible", target=str(target_val))
                )
            elif "cmd" in tool_clean or "powershell" in tool_clean:
                verification_requirements.append(
                    VerificationRequirement(strategy="process_running", target=str(target_val))
                )
            elif "computer_use" in tool_clean:
                verification_requirements.append(
                    VerificationRequirement(strategy="window_visible", target=str(target_val))
                )
            elif ctx.tool != "unknown_tool":
                verification_requirements.append(
                    VerificationRequirement(strategy="process", target=str(target_val))
                )

            # 2. Construir DecisionRequest representativo
            dec_req = DecisionRequest(
                request_id=ctx.request_id,
                user_request=ctx.user_input,
                intent=ctx.intent,
                proposed_action=ctx.action,
                tool=ctx.tool,
                parameters=ctx.parameters,
                risk_level=ctx.security_level,
                confidence=ctx.confidence,
                verification_requirements=verification_requirements,
            )

            # 3. Determinar estado de verificación y ejecución reportado por el sistema actual
            raw_exec_status = "OK" if ctx.exec_success else "ERROR"
            raw_verif_status = "VERIFIED_TRUE" if ctx.is_verified else "UNVERIFIABLE"

            if ctx.execution_result is not None:
                if hasattr(ctx.execution_result, "status"):
                    stat_val = getattr(ctx.execution_result.status, "value", str(ctx.execution_result.status))
                    if "verification_failed" in stat_val.lower():
                        raw_verif_status = "VERIFICATION_FAILED"
                    elif "succeeded" in stat_val.lower() and ctx.is_verified:
                        raw_verif_status = "VERIFIED_TRUE"
                    elif "unknown" in stat_val.lower():
                        raw_exec_status = "OK"
                        raw_verif_status = "UNVERIFIABLE"

            # 4. Enviar a evaluación en modo Shadow
            evaluation = self.shadow_mode.evaluate_shadow(
                request=dec_req,
                current_system_success=ctx.exec_success,
                current_system_message=ctx.current_message,
                current_system_verified=ctx.is_verified,
                execution_status=raw_exec_status,
                verification_status=raw_verif_status,
            )
            return evaluation

        except Exception as ex:
            # PRINCIPIO FAIL-SAFE: Un error en Shadow Mode NUNCA debe tumbar la interacción con el usuario
            logger.warning(f"[JDE SHADOW ADAPTER ERROR] Excepción no crítica en observación: {ex}")
            return None


_GLOBAL_ADAPTER: JDEShadowAdapter | None = None


def get_jde_shadow_adapter() -> JDEShadowAdapter:
    global _GLOBAL_ADAPTER
    if _GLOBAL_ADAPTER is None:
        _GLOBAL_ADAPTER = JDEShadowAdapter()
    return _GLOBAL_ADAPTER
