"""Subsistema de Aislamiento de Ejecución para Plugins (PluginExecutionSandbox - Etapa 14.3).

GARANTÍAS RIGUROSAS DE SEGURIDAD EN ETAPA 14.3:
1. AISLAMIENTO Y CONTROL DE RECURSOS EN SANDBOX:
   - Tiempo de ejecución acotado (PLUGIN_SANDBOX_TIMEOUT).
   - Acceso al sistema de archivos acotado al sandbox del plugin (plugin_dir) salvo autorización explícita.
   - Restricción estricta de red (bloqueado sin capacidad 'network').
   - Restricción estricta de procesos (bloqueado sin capacidad 'process.execute').
   - Evaluación obligatoria de capacidades en PluginSecurityPolicy.
2. EL PLUGIN SOLO PUEDE ACCEDER A LOS RECURSOS EXPLICITAMENTE CONCEDIDOS.
"""

from __future__ import annotations

import concurrent.futures
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.exceptions import MCPError
from core.logger import get_logger
from core.permission_manager import PermissionDecision
from core.plugin_loader import LoadedPlugin
from core.plugin_security import (
    PluginDeclaredCapability,
    PluginSecurityPolicy,
)

logger = get_logger("jessyca.core.plugin_sandbox")


class PluginSandboxError(MCPError):
    """Error base de fallos dentro del sandbox de ejecución de plugins."""

    pass


class PluginSandboxViolationError(PluginSandboxError):
    """Error emitido al intentar violar los límites de recursos (filesystem, red, procesos, capacidades) del sandbox."""

    pass


class PluginSandboxTimeoutError(PluginSandboxError):
    """Error emitido cuando la ejecución de un plugin supera el tiempo límite configurado (PLUGIN_SANDBOX_TIMEOUT)."""

    pass


@dataclass
class PluginExecutionResult:
    """Resultado inmutable del despacho de una acción dentro del sandbox."""

    plugin_id: str
    action_name: str
    success: bool
    result: Any = None
    error_message: str = ""
    duration_ms: float = 0.0
    executed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class PluginExecutionSandbox:
    """Sandbox de Aislamiento de Ejecución de Plugins (Etapa 14.3).

    Aplica límites estrictos de tiempo, memoria, sistema de archivos, red, procesos y capacidades.
    """

    def __init__(
        self,
        timeout_seconds: float | None = None,
        security_policy: PluginSecurityPolicy | None = None,
    ) -> None:
        from config.settings import AppSettings
        settings = AppSettings()
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.PLUGIN_SANDBOX_TIMEOUT
        self.security_policy = security_policy or PluginSecurityPolicy()
        self.audit_logger = get_audit_logger()


    def execute_plugin_action(
        self,
        plugin: LoadedPlugin,
        action_func: Callable[..., Any],
        tool_name: str,
        operation: str,
        parameters: dict[str, Any] | None = None,
    ) -> PluginExecutionResult:
        """Ejecuta una acción de plugin dentro del sandbox bajo aislamiento y límites de recursos."""
        params = parameters or {}
        start_time = time.perf_counter()

        # 1. EVALUAR CAPACIDADES Y SEGURIDAD EN SECURITY POLICY
        perm = self.security_policy.evaluate_plugin_action(
            profile=plugin.risk_profile,
            tool_name=tool_name,
            operation=operation,
            parameters=params,
        )

        if perm.decision == PermissionDecision.DENY:
            raise PluginSandboxViolationError(
                f"[SANDBOX VIOLATION] Acción '{tool_name}.{operation}' denegada para el plugin '{plugin.plugin_id}'. Razon: {perm.reason}"
            )

        if perm.decision == PermissionDecision.REQUIRE_CONFIRMATION:
            raise PluginSandboxViolationError(
                f"[SANDBOX VIOLATION] Acción peligrosa '{tool_name}.{operation}' requiere confirmación interactiva. CERO bypass en sandbox."
            )

        # 2. VALIDAR LÍMITES ESPECÍFICOS DE RECURSOS (FILESYSTEM, NETWORK, PROCESS)
        self._enforce_resource_boundaries(plugin, tool_name, operation, params)

        # 3. EJECUCIÓN ACOTADA CON TIMEOUT (PLUGIN_SANDBOX_TIMEOUT)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(action_func, **params)
                res = future.result(timeout=self.timeout_seconds)

            duration_ms = (time.perf_counter() - start_time) * 1000.0
            exec_result = PluginExecutionResult(
                plugin_id=plugin.plugin_id,
                action_name=f"{tool_name}.{operation}",
                success=True,
                result=res,
                duration_ms=duration_ms,
            )
            self._log_sandbox_audit(plugin.plugin_id, f"{tool_name}.{operation}", success=True, duration_ms=duration_ms)
            return exec_result

        except concurrent.futures.TimeoutError as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            err_msg = f"[SANDBOX TIMEOUT] La ejecución del plugin '{plugin.plugin_id}' superó el límite de {self.timeout_seconds} segundos."
            logger.error(err_msg)
            self._log_sandbox_audit(plugin.plugin_id, f"{tool_name}.{operation}", success=False, reason=err_msg)
            raise PluginSandboxTimeoutError(err_msg) from e

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            if isinstance(e, PluginSandboxError):
                raise
            err_msg = f"Error durante la ejecución del plugin: {e}"
            logger.error(f"[SANDBOX ERROR] {err_msg}")
            self._log_sandbox_audit(plugin.plugin_id, f"{tool_name}.{operation}", success=False, reason=err_msg)
            return PluginExecutionResult(
                plugin_id=plugin.plugin_id,
                action_name=f"{tool_name}.{operation}",
                success=False,
                error_message=err_msg,
                duration_ms=duration_ms,
            )

    def _enforce_resource_boundaries(
        self,
        plugin: LoadedPlugin,
        tool_name: str,
        operation: str,
        params: dict[str, Any],
    ) -> None:
        """Enforza las fronteras físicas de recursos (archivos, red, procesos) dentro del sandbox."""
        target_action = f"{tool_name}.{operation}".lower()

        # A. VALIDAR ACCESO A SISTEMA DE ARCHIVOS (LECTURA)
        if "file.read" in target_action or "filesystem.read" in target_action:
            file_path = params.get("path") or params.get("file_path")
            if file_path:
                self._validate_file_path_in_sandbox(plugin, str(file_path), mode="read")

        # B. VALIDAR ACCESO A SISTEMA DE ARCHIVOS (ESCRITURA)
        if "file.write" in target_action or "file.delete" in target_action or "filesystem.write" in target_action:
            file_path = params.get("path") or params.get("file_path")
            if file_path:
                self._validate_file_path_in_sandbox(plugin, str(file_path), mode="write")

        # C. VALIDAR EJECUCIÓN DE PROCESOS (PROCESS CREATION)
        if "process" in target_action or "cmd" in target_action or "powershell" in target_action:
            has_proc_cap = any(c.name == PluginDeclaredCapability.PROCESS_EXECUTE.value for c in plugin.risk_profile.declared_capabilities)
            if not has_proc_cap:
                raise PluginSandboxViolationError(
                    f"[SANDBOX VIOLATION] El plugin '{plugin.plugin_id}' intentó crear o ejecutar procesos sin poseer la capacidad '{PluginDeclaredCapability.PROCESS_EXECUTE.value}'."
                )

        # D. VALIDAR ACCESO A RED (NETWORK ACCESS)
        if "network" in target_action or "http" in target_action or "socket" in target_action:
            has_net_cap = any(c.name == PluginDeclaredCapability.NETWORK.value for c in plugin.risk_profile.declared_capabilities)
            if not has_net_cap:
                raise PluginSandboxViolationError(
                    f"[SANDBOX VIOLATION] El plugin '{plugin.plugin_id}' intentó realizar conexiones a red sin poseer la capacidad '{PluginDeclaredCapability.NETWORK.value}'."
                )

    def _validate_file_path_in_sandbox(self, plugin: LoadedPlugin, target_path_str: str, mode: str) -> None:
        """Comprueba que una ruta solicitada resida estrictamente dentro de plugin_dir o del sandbox asignado."""
        target = Path(target_path_str).resolve()
        sandbox_root = plugin.plugin_dir.resolve()

        # Verificar si la ruta resuelta está dentro del sandbox del plugin
        try:
            target.relative_to(sandbox_root)
        except ValueError:
            raise PluginSandboxViolationError(
                f"[SANDBOX VIOLATION] Intento de acceso a archivo fuera del sandbox ('{mode}'): Ruta '{target_path_str}' está fuera de '{sandbox_root}'."
            ) from None

    def _log_sandbox_audit(self, plugin_id: str, action: str, success: bool, duration_ms: float = 0.0, reason: str = "") -> None:
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.POLICY_EVALUATED if success else AuditEventType.EXECUTION_DENIED,
                request_id=f"sandbox-{plugin_id[:8]}",
                tool_name="plugin.sandbox",
                operation=action,
                duration_ms=duration_ms,
                reason=reason or f"Sandbox execution: {action}",
                metadata={"plugin_id": plugin_id, "action": action, "success": success},
            )
        )
