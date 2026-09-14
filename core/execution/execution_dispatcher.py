"""Execution Dispatcher para ActionIntentContract (Fase 64.2.3).

Despachador central y determinista encargado de tomar una acción formalmente
AUTORIZADA por el Execution Gate y canalizarla hacia el subsistema de Skills
existente (SkillRegistry / BaseSkill / SkillManager).

REGLAS Y RESPONSABILIDADES:
1. Recibe exclusivamente una acción AUTORIZADA (ExecutionDecision con can_proceed_to_execution=True).
2. Valida la presencia e integridad de: action_id, skill, operation, arguments y autorización.
3. Resuelve el skill/plugin mediante el SkillRegistry existente (sin crear un segundo registro).
4. Ejecuta exactamente UNA operación de la Skill.
5. Captura el resultado y lo transforma en ActionExecutionReport compatible con Fase 64.1.
6. Estados deterministas diferenciados:
   - SUCCESS: Ejecución completada y verificada exitosamente.
   - FAILED: La skill o la verificación reportó fallo.
   - REJECTED: La acción no estaba autorizada o fue denegada.
   - NOT_FOUND: Skill u operación no encontrada en el catálogo.
   - INVALID_ARGUMENTS: Parámetros inválidos o incompletos para la operación.
   - TIMEOUT: Límite de tiempo de ejecución excedido.
   - EXCEPTION: Excepción no controlada durante el despacho o ejecución.
7. ANTI-FALSE SUCCESS:
   Bajo ninguna circunstancia declara SUCCESS ni claims_success=True si la skill devolvió
   False, lanzó excepción, reportó error o carece de verificación determinista.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.action_intent_contract import (
    ActionExecutionReport,
    ActionIntentContract,
    PostActionFeedback,
)
from core.execution.action_execution_bridge import (
    build_post_action_feedback,
)
from core.execution.execution_gate_bridge import (
    ExecutionDecision,
    GateDecisionType,
)
from core.execution.execution_verifier import (
    get_execution_verifier,
)
from core.logger import get_logger
from skills.skill_models import SkillContext, SkillResult
from skills.skill_registry import SkillRegistry, get_skill_registry

logger = get_logger("jessyca.execution.dispatcher")


class DispatchStatus(StrEnum):
    """Estados canónicos de despacho y ejecución de la acción."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    NOT_FOUND = "NOT_FOUND"
    INVALID_ARGUMENTS = "INVALID_ARGUMENTS"
    TIMEOUT = "TIMEOUT"
    EXCEPTION = "EXCEPTION"


@dataclass(frozen=True)
class DispatchResult:
    """Resultado formal e inmutable del despacho de una acción.

    Conserva la trazabilidad completa (action_id, skill, operation, métricas,
    estado determinista y el contrato enriquecido con ActionExecutionReport).
    """

    action_id: str
    skill_id: str
    operation: str
    status: DispatchStatus
    is_success: bool
    execution_report: ActionExecutionReport
    contract: ActionIntentContract
    duration_ms: float
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class ExecutionDispatcher:
    """Despachador central de ejecución de acciones sobre el catálogo de Skills."""

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        verifier: Any | None = None,
    ) -> None:
        self.registry = registry or get_skill_registry()
        self.verifier = verifier or get_execution_verifier()

    def dispatch(
        self,
        decision: ExecutionDecision,
        timeout_seconds: float = 30.0,
    ) -> DispatchResult:
        """Despacha la acción autorizada a la skill correspondiente.

        GARANTÍA:
        - Si la acción no está formalmente autorizada por ExecutionGate, emite REJECTED
          sin invocar ninguna skill ni realizar llamadas del sistema.
        - Ejecuta exactamente UNA operación.
        - Anti-False Success garantizado.
        """
        start_perf = time.perf_counter()
        t_start = datetime.now(UTC)

        action_id = decision.contract.request_id
        contract = decision.contract
        spec = decision.execution_spec

        skill_name = (spec.skill_id if spec and spec.skill_id else decision.skill_id) or ""
        op_name = (spec.tool_name if spec and spec.tool_name is not None else decision.operation) or ""
        if not op_name:
            op_name = decision.action_intent.intent_name if decision.action_intent else ""
        params = dict(decision.parameters or {})




        # ── 1. VALIDACIÓN DE AUTORIZACIÓN (SECURITY & GATE BARRIER) ──
        if not decision.can_proceed_to_execution or decision.decision_type != GateDecisionType.EXECUTE:
            elapsed_ms = (time.perf_counter() - start_perf) * 1000.0
            t_end = datetime.now(UTC)
            logger.warning(
                f"[DISPATCH REJECTED] Acción [{action_id}] no autorizada para ejecución "
                f"(DecisionType={decision.decision_type}, Reason={decision.reason})."
            )
            report = ActionExecutionReport(
                skill_id=skill_name or None,
                tool_name=op_name or None,
                execution_status="denied",
                is_verified=False,
                claims_success=False,
                evidence={},
                error_code="UNAUTHORIZED_OR_BLOCKED",
            )
            feedback = PostActionFeedback(
                spoken_response="La acción no está autorizada para su ejecución.",
                response_text=decision.reason,
            )
            updated_contract = contract.model_copy(
                update={
                    "execution_report": report,
                    "post_action_feedback": feedback,
                }
            )
            return DispatchResult(
                action_id=action_id,
                skill_id=skill_name,
                operation=op_name,
                status=DispatchStatus.REJECTED,
                is_success=False,
                execution_report=report,
                contract=updated_contract,
                duration_ms=elapsed_ms,
                output={},
                error=decision.reason or "Acción no autorizada por ExecutionGate",
                started_at=t_start,
                completed_at=t_end,
            )

        # ── 2. VALIDACIÓN DE IDENTIFICADORES Y ARGUMENTOS BÁSICOS ──
        if not skill_name or not skill_name.strip():
            return self._build_error_dispatch(
                action_id=action_id,
                skill_id=skill_name,
                operation=op_name,
                status=DispatchStatus.NOT_FOUND,
                error_code="MISSING_SKILL_ID",
                error_msg="No se especificó un identificador de Skill válido.",
                contract=contract,
                start_perf=start_perf,
                t_start=t_start,
            )

        if not op_name or not op_name.strip():
            return self._build_error_dispatch(
                action_id=action_id,
                skill_id=skill_name,
                operation=op_name,
                status=DispatchStatus.NOT_FOUND,
                error_code="MISSING_OPERATION",
                error_msg=f"No se especificó una operación válida para la skill '{skill_name}'.",
                contract=contract,
                start_perf=start_perf,
                t_start=t_start,
            )

        # ── 3. RESOLUCIÓN DE LA SKILL EN EL REGISTRY EXISTENTE ──
        clean_name = skill_name.split("@")[0].strip()
        skill_inst = self.registry.lookup(skill_name)
        if skill_inst is None:
            # Fallback de búsqueda tolerante a sufijo de versión si aplica
            skill_inst = self.registry.lookup(clean_name)


        if skill_inst is None:
            logger.error(f"[DISPATCH NOT_FOUND] Skill '{skill_name}' no encontrada en el registro.")
            return self._build_error_dispatch(
                action_id=action_id,
                skill_id=skill_name,
                operation=op_name,
                status=DispatchStatus.NOT_FOUND,
                error_code="SKILL_NOT_FOUND",
                error_msg=f"La skill '{skill_name}' no está registrada en el sistema.",
                contract=contract,
                start_perf=start_perf,
                t_start=t_start,
            )

        # 3.1 Validación de existencia de operación en la skill
        if hasattr(skill_inst, "definition") and skill_inst.definition:
            allowed_tools = set(skill_inst.definition.required_tools)
            manifest = getattr(skill_inst.definition, "manifest", None)
            if manifest and manifest.required_tools:
                allowed_tools.update(manifest.required_tools)

            # Mapeos semánticos canónicos de operaciones
            op_norm = op_name.lower().replace("_", ".").strip()
            matches = any(
                op_norm in t.lower() or t.lower() in op_norm or op_name.lower() in t.lower() or t.lower() in op_name.lower()
                for t in allowed_tools
            ) if allowed_tools else True

            # Casos específicos conocidos de compatibilidad en JESSYCA:
            if not matches:
                if clean_name == "windows.apps" and any(k in op_name.lower() for k in ("open", "abrir", "launch", "close", "cerrar", "kill", "inspect")):
                    matches = True
                elif clean_name == "windows.screenshot" and any(k in op_name.lower() for k in ("screenshot", "screen", "pantalla", "capture")):
                    matches = True
                elif clean_name == "windows.media" and any(k in op_name.lower() for k in ("media", "play", "video", "reproduce")):
                    matches = True

            if not matches:
                logger.error(f"[DISPATCH NOT_FOUND] Operación '{op_name}' no soportada por la skill '{skill_name}'.")
                return self._build_error_dispatch(
                    action_id=action_id,
                    skill_id=skill_name,
                    operation=op_name,
                    status=DispatchStatus.NOT_FOUND,
                    error_code="OPERATION_NOT_FOUND",
                    error_msg=f"La operación '{op_name}' no está soportada por la skill '{skill_name}'.",
                    contract=contract,
                    start_perf=start_perf,
                    t_start=t_start,
                )


        # ── 4. VALIDACIÓN DE ARGUMENTOS SEGÚN LA SKILL Y OPERACIÓN ──

        arg_valid, arg_err = self._validate_arguments_for_skill(skill_name, op_name, params)
        if not arg_valid:
            logger.warning(f"[DISPATCH INVALID_ARGUMENTS] Skill '{skill_name}' op '{op_name}': {arg_err}")
            return self._build_error_dispatch(
                action_id=action_id,
                skill_id=skill_name,
                operation=op_name,
                status=DispatchStatus.INVALID_ARGUMENTS,
                error_code="INVALID_ARGUMENTS",
                error_msg=arg_err or "Argumentos requeridos ausentes o inválidos.",
                contract=contract,
                start_perf=start_perf,
                t_start=t_start,
            )

        # ── 5. EJECUCIÓN EXACTAMENTE DE UNA OPERACIÓN ──
        logger.info(f"[DISPATCH START] action_id={action_id} skill={skill_name} operation={op_name}")
        exec_output: dict[str, Any] = {}
        exec_error: str | None = None
        exec_failed = False
        exec_timeout = False

        # Inyectar trazabilidad en los parámetros de la llamada
        params_with_meta = dict(params)
        params_with_meta["action_id"] = action_id
        params_with_meta["request_id"] = action_id
        params_with_meta["execution_id"] = f"exec-{action_id}"
        if "accion" not in params_with_meta and "action" not in params_with_meta:
            params_with_meta["accion"] = self._map_operation_to_skill_action(op_name)

        try:
            # Compatibilidad dual: BaseSkill moderna execute() o ejecutar()
            if hasattr(skill_inst, "execute"):
                s_ctx = SkillContext(
                    skill_id=skill_inst.skill_id,
                    intent=op_name,
                    parameters=params_with_meta,
                    timeout_seconds=timeout_seconds,
                    session_id=contract.session_id,
                )
                res_obj = skill_inst.execute(s_ctx)
                if isinstance(res_obj, SkillResult):
                    exec_output = res_obj.output if isinstance(res_obj.output, dict) else {"result": res_obj.output}
                    exec_failed = not res_obj.success or not exec_output.get("exito", True)
                    exec_error = res_obj.error or exec_output.get("mensaje") if exec_failed else None
                elif isinstance(res_obj, dict):
                    exec_output = res_obj
                    exec_failed = not bool(res_obj.get("exito", False))
                    exec_error = str(res_obj.get("mensaje")) if exec_failed else None
            else:
                raw_dict = skill_inst.ejecutar(params_with_meta)
                exec_output = raw_dict if isinstance(raw_dict, dict) else {"result": raw_dict}
                exec_failed = not bool(exec_output.get("exito", False))
                exec_error = str(exec_output.get("mensaje")) if exec_failed else None

        except TimeoutError as tex:
            logger.error(f"[DISPATCH TIMEOUT] Acción [{action_id}] excedió el timeout de {timeout_seconds}s: {tex}")
            exec_timeout = True
            exec_error = f"Tiempo de espera agotado ({timeout_seconds}s)."
        except Exception as exc:
            logger.error(f"[DISPATCH EXCEPTION] Excepción no controlada en [{action_id}] ({skill_name}.{op_name}): {exc}", exc_info=True)
            return self._build_error_dispatch(
                action_id=action_id,
                skill_id=skill_name,
                operation=op_name,
                status=DispatchStatus.EXCEPTION,
                error_code="EXECUTION_EXCEPTION",
                error_msg=f"Excepción en la ejecución de la skill: {exc}",
                contract=contract,
                start_perf=start_perf,
                t_start=t_start,
            )

        elapsed_ms = (time.perf_counter() - start_perf) * 1000.0
        t_end = datetime.now(UTC)

        # ── 6. EVALUACIÓN Y CONVERSIÓN DE RESULTADO A ACTIONEXECUTIONREPORT ──
        if exec_timeout:
            return self._build_error_dispatch(
                action_id=action_id,
                skill_id=skill_name,
                operation=op_name,
                status=DispatchStatus.TIMEOUT,
                error_code="TIMEOUT",
                error_msg=exec_error or "Límite de tiempo excedido.",
                contract=contract,
                start_perf=start_perf,
                t_start=t_start,
            )

        # Extraer o construir evidencia determinista
        evidence_dict = exec_output.get("evidence") if isinstance(exec_output.get("evidence"), dict) else None
        target_name = (
            params.get("nombre_app")
            or params.get("app_name")
            or params.get("target")
            or decision.action_intent.target
            or op_name
        )

        if evidence_dict is None:
            # Si la skill no produjo evidencia directa pero se reportó exitosa
            if not exec_failed:
                # Consultar al verifier central si aplica
                v_res = self.verifier.verify_execution(
                    action=op_name,
                    target=str(target_name),
                    parameters=exec_output,
                    timeout_seconds=0.5,
                )
                evidence_dict = v_res.to_dict()
            else:
                evidence_dict = {
                    "verification_type": "skill_output",
                    "target": str(target_name),
                    "is_verified": False,
                    "details": {"error": exec_error},
                }

        is_verified = bool(evidence_dict and evidence_dict.get("is_verified", False))
        claims_success = bool(not exec_failed and is_verified)

        # ANTI-FALSE SUCCESS ABSOLUTO:
        if exec_failed or not is_verified:
            claims_success = False

        status_str = "success" if claims_success else "failed"
        dispatch_status = DispatchStatus.SUCCESS if claims_success else DispatchStatus.FAILED

        report = ActionExecutionReport(
            skill_id=skill_name,
            tool_name=op_name,
            execution_status=status_str,
            is_verified=is_verified,
            claims_success=claims_success,
            evidence=evidence_dict or {},
            error_code=exec_error if not claims_success else None,
        )

        response_msg = str(exec_output.get("mensaje") or ("Operación completada." if claims_success else "Fallo en la operación."))
        feedback = build_post_action_feedback(
            execution_report=report,
            response_text=response_msg,
            spoken_text=response_msg,
        ) or PostActionFeedback(spoken_response=response_msg, response_text=response_msg)


        updated_contract = contract.model_copy(
            update={
                "execution_report": report,
                "post_action_feedback": feedback,
            }
        )

        logger.info(
            f"[DISPATCH COMPLETED] action_id={action_id} skill={skill_name} status={dispatch_status.value} "
            f"claims_success={claims_success} is_verified={is_verified} duration={elapsed_ms:.1f}ms"
        )

        return DispatchResult(
            action_id=action_id,
            skill_id=skill_name,
            operation=op_name,
            status=dispatch_status,
            is_success=claims_success,
            execution_report=report,
            contract=updated_contract,
            duration_ms=elapsed_ms,
            output=exec_output,
            error=exec_error if not claims_success else None,
            started_at=t_start,
            completed_at=t_end,
        )

    def _validate_arguments_for_skill(
        self,
        skill_name: str,
        operation: str,
        params: dict[str, Any],
    ) -> tuple[bool, str | None]:
        """Valida que los argumentos indispensables estén presentes antes de ejecutar."""
        clean_skill = skill_name.split("@")[0].strip()

        if clean_skill == "windows.apps":
            app = params.get("app_name") or params.get("nombre_app") or params.get("app") or params.get("target")
            if not app or not str(app).strip():
                return False, "El parámetro 'app_name' o 'nombre_app' es obligatorio para windows.apps."

        elif clean_skill == "files.search":
            q = params.get("query") or params.get("filename") or params.get("target")
            if not q or not str(q).strip():
                return False, "El parámetro 'query' o 'filename' es obligatorio para files.search."

        elif clean_skill == "browser.search":
            q = params.get("query") or params.get("topic")
            if not q or not str(q).strip():
                return False, "El parámetro 'query' es obligatorio para browser.search."

        return True, None

    def _map_operation_to_skill_action(self, op_name: str) -> str:
        """Mapea el nombre de la operación a la acción requerida por la skill subyacente."""
        clean = (op_name or "").lower()
        if any(k in clean for k in ("open", "abrir", "launch")):
            return "abrir"
        if any(k in clean for k in ("close", "cerrar", "kill", "terminate")):
            return "cerrar"
        return clean

    def _build_error_dispatch(
        self,
        action_id: str,
        skill_id: str,
        operation: str,
        status: DispatchStatus,
        error_code: str,
        error_msg: str,
        contract: ActionIntentContract,
        start_perf: float,
        t_start: datetime,
    ) -> DispatchResult:
        """Construye un DispatchResult de error preservando identificadores y Anti-False Success."""
        elapsed_ms = (time.perf_counter() - start_perf) * 1000.0
        t_end = datetime.now(UTC)

        report = ActionExecutionReport(
            skill_id=skill_id or None,
            tool_name=operation or None,
            execution_status="failed",
            is_verified=False,
            claims_success=False,
            evidence={"error": error_msg},
            error_code=error_code,
        )
        feedback = PostActionFeedback(
            spoken_response="Ocurrió un error al despachar la acción.",
            response_text=error_msg,
        )
        updated_contract = contract.model_copy(
            update={
                "execution_report": report,
                "post_action_feedback": feedback,
            }
        )

        return DispatchResult(
            action_id=action_id,
            skill_id=skill_id,
            operation=operation,
            status=status,
            is_success=False,
            execution_report=report,
            contract=updated_contract,
            duration_ms=elapsed_ms,
            output={},
            error=error_msg,
            started_at=t_start,
            completed_at=t_end,
        )


__all__ = [
    "DispatchResult",
    "DispatchStatus",
    "ExecutionDispatcher",
]
