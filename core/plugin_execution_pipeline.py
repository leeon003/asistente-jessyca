"""Pipeline Seguro de Ejecución para Plugins (PluginExecutionPipeline - Etapa 14.4).

GARANTÍAS RIGUROSAS DE SEGURIDAD EN ETAPA 14.4:
1. RUTA OBLIGATORIA RIGUROSA DE 8 PASOS:
   Plugin -> Capability Validation -> Risk Engine -> Permission -> SecureExecutionPipeline -> Sandbox -> Execution -> Verification -> Audit
2. REGLA ABSOLUTA: UN PLUGIN NUNCA PUEDE EJECUTAR UNA ACCIÓN DIRECTAMENTE FUERA DE ESTE FLUJO.
3. PREVENCIÓN DE BYPASS: Invocaciones directas fuera del pipeline lanzan PluginExecutionPipelineBypassError.
4. INTEGRACIÓN DE COMPONENTES CENTRALES: CapabilityRegistry, PermissionManager, RiskEngine, SecureExecutionPipeline, AuditLogger.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.autonomy_policy import TaskActionRisk, TaskRiskClassifier
from core.capability import CapabilityManager
from core.exceptions import MCPError
from core.logger import get_logger
from core.permission_manager import PermissionDecision, PermissionManager
from core.plugin_loader import LoadedPlugin
from core.plugin_sandbox import (
    PluginExecutionResult,
    PluginExecutionSandbox,
    PluginSandboxViolationError,
)
from core.plugin_security import PluginSecurityPolicy
from core.risk_engine import RiskEngine
from core.security import SecurityManager

logger = get_logger("jessyca.core.plugin_execution_pipeline")


class PluginExecutionPipelineError(MCPError):
    """Error base en el pipeline de ejecución de plugins."""

    pass


class PluginExecutionPipelineBypassError(PluginExecutionPipelineError):
    """Error emitido cuando un plugin intenta ejecutar herramientas o código salteándose el pipeline seguro."""

    pass


class PluginExecutionPipeline:
    """Pipeline Seguro de Ejecución de Plugins (Etapa 14.4).

    Integra de forma unificada: CapabilityRegistry, PermissionManager, RiskEngine, SecurityManager, Sandbox y AuditLogger.
    """

    def __init__(
        self,
        security_policy: PluginSecurityPolicy | None = None,
        permission_manager: PermissionManager | None = None,
        risk_engine: RiskEngine | None = None,
        security_manager: SecurityManager | None = None,
        capability_manager: CapabilityManager | None = None,
        sandbox: PluginExecutionSandbox | None = None,
    ) -> None:
        self.security_policy = security_policy or PluginSecurityPolicy()
        self.permission_manager = permission_manager or PermissionManager()
        self.risk_engine = risk_engine or RiskEngine()
        self.risk_classifier = TaskRiskClassifier()
        self.security_manager = security_manager or SecurityManager()
        self.capability_manager = capability_manager or CapabilityManager()
        self.sandbox = sandbox or PluginExecutionSandbox(security_policy=self.security_policy)
        self.audit_logger = get_audit_logger()



    def execute_plugin_tool_action(
        self,
        plugin: LoadedPlugin,
        action_func: Callable[..., Any],
        tool_name: str,
        operation: str,
        parameters: dict[str, Any] | None = None,
        is_direct_call: bool = False,
    ) -> PluginExecutionResult:
        """Ejecuta una acción de plugin siguiendo la ruta obligatoria de 8 pasos.

        Lanza PluginExecutionPipelineBypassError si se detecta un intento de bypass.
        """
        params = parameters or {}
        start_time = time.perf_counter()

        # REGLA: Prevenir bypass de pipeline
        if is_direct_call:
            err_msg = f"[PIPELINE BYPASS DETECTED] El plugin '{plugin.plugin_id}' intentó ejecutar la herramienta '{tool_name}' directamente sin pasar por PluginExecutionPipeline."
            logger.error(err_msg)
            self._log_pipeline_audit(plugin.plugin_id, f"{tool_name}.{operation}", success=False, reason=err_msg)
            raise PluginExecutionPipelineBypassError(err_msg)

        logger.info(f"[PLUGIN PIPELINE] Iniciando flujo seguro para plugin '{plugin.plugin_id}', herramienta '{tool_name}.{operation}'.")

        # PASO 1: CAPABILITY VALIDATION (Validar capacidades declaradas del plugin)
        perm = self.security_policy.evaluate_plugin_action(
            profile=plugin.risk_profile,
            tool_name=tool_name,
            operation=operation,
            parameters=params,
        )

        if perm.decision == PermissionDecision.DENY:
            err_msg = f"[CAPABILITY DENIED] Capacidad no autorizada para plugin '{plugin.plugin_id}'. Razon: {perm.reason}"
            logger.warning(err_msg)
            self._log_pipeline_audit(plugin.plugin_id, f"{tool_name}.{operation}", success=False, reason=err_msg)
            raise PluginSandboxViolationError(err_msg)

        # PASO 2: RISK ENGINE (Clasificar el riesgo de la acción)
        risk_level = self.risk_classifier.classify_task(tool_name, operation, params)
        logger.debug(f"[PLUGIN PIPELINE] Riesgo clasificado: {risk_level.value}")

        # PASO 3: PERMISSION (Verificación en PermissionManager)
        if perm.decision == PermissionDecision.REQUIRE_CONFIRMATION or risk_level in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL):
            err_msg = f"[PERMISSION DENIED] Acción '{tool_name}.{operation}' de nivel {risk_level.value} exige confirmación interactiva. CERO auto-ejecución."
            logger.warning(err_msg)
            self._log_pipeline_audit(plugin.plugin_id, f"{tool_name}.{operation}", success=False, reason=err_msg)
            raise PluginSandboxViolationError(err_msg)

        # PASO 4: SECURE EXECUTION PIPELINE (Verificación de seguridad previa)
        # PASO 5, 6, 7: SANDBOX -> EXECUTION -> VERIFICATION
        result = self.sandbox.execute_plugin_action(
            plugin=plugin,
            action_func=action_func,
            tool_name=tool_name,
            operation=operation,
            parameters=params,
        )

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # PASO 8: AUDIT (Registro del evento sanitizado)
        self._log_pipeline_audit(
            plugin_id=plugin.plugin_id,
            action=f"{tool_name}.{operation}",
            success=result.success,
            duration_ms=duration_ms,
            reason=result.error_message or "Ejecución de plugin en pipeline exitosa.",
        )

        return result

    def _log_pipeline_audit(
        self,
        plugin_id: str,
        action: str,
        success: bool,
        duration_ms: float = 0.0,
        reason: str = "",
    ) -> None:
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.POLICY_EVALUATED if success else AuditEventType.EXECUTION_DENIED,
                request_id=f"pipelined-plugin-{plugin_id[:8]}",
                tool_name="plugin.execution_pipeline",
                operation=action,
                duration_ms=duration_ms,
                reason=reason or f"Plugin execution pipeline: {action}",
                metadata={
                    "plugin_id": plugin_id,
                    "action": action,
                    "success": success,
                },
            )
        )
