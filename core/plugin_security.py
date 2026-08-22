"""Arquitectura de Seguridad para Plugins (Plugin Security Architecture - Etapa 14.0).

GARANTÍAS RIGUROSAS DE SEGURIDAD EN ETAPA 14.0:
1. PRINCIPIO DE CÓDIGO NO CONFIABLE (UNTRUSTED CODE): Todo plugin se considera potencialmente malicioso y no confiable por defecto.
2. NINGÚN PLUGIN PUEDE:
   - Inventar capacidades no declaradas explícitamente en el sistema.
   - Autoelevar su nivel de riesgo o reducir el nivel de riesgo de sus herramientas.
   - Modificar o alterar CapabilityRegistry, PermissionManager, RiskEngine o SecureExecutionPipeline.
3. CAPACIDADES FORMALES DECLARADAS:
   - filesystem.read, filesystem.write, network, process.execute, registry.read, registry.write,
     browser, desktop, audio, clipboard, system.info, time.date.
4. CERO CARGA DE PLUGINS Y CERO EJECUCIÓN DE CÓDIGO EN ETAPA 14.0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.autonomy_policy import TaskActionRisk, TaskRiskClassifier
from core.exceptions import MCPError
from core.logger import get_logger
from core.permission_manager import PermissionDecision, PermissionManager

logger = get_logger("jessyca.core.plugin_security")


class PluginDeclaredCapability(StrEnum):
    """Catálogo formal e inmutable de capacidades que un plugin puede solicitar."""

    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    NETWORK = "network"
    PROCESS_EXECUTE = "process.execute"
    REGISTRY_READ = "registry.read"
    REGISTRY_WRITE = "registry.write"
    BROWSER = "browser"
    DESKTOP = "desktop"
    AUDIO = "audio"
    CLIPBOARD = "clipboard"
    SYSTEM_INFO = "system.info"
    TIME_DATE = "time.date"


# Conjunto oficial de cadenas de capacidad permitidas
ALLOWED_CAPABILITY_STRINGS: set[str] = {cap.value for cap in PluginDeclaredCapability}


class PluginSecurityError(MCPError):
    """Error base de violaciones de seguridad en plugins."""

    pass


class PluginCapabilityViolationError(PluginSecurityError):
    """Error emitido cuando un plugin intenta inventar o utilizar una capacidad no permitida."""

    pass


class PluginPrivilegeElevationError(PluginSecurityError):
    """Error emitido cuando un plugin intenta autoelevar sus privilegios o degradar el riesgo de una herramienta."""

    pass


@dataclass(frozen=True)
class PluginCapability:
    """Capacidad individual solicitada o asignada a un plugin."""

    name: str
    description: str = ""
    max_allowed_risk: TaskActionRisk = TaskActionRisk.MEDIUM_RISK
    parameters_schema: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.name not in ALLOWED_CAPABILITY_STRINGS:
            raise PluginCapabilityViolationError(
                f"[SECURITY VIOLATION] Capacidad no autorizada o inventada '{self.name}'. Un plugin NO puede inventar capacidades fuera del catálogo oficial."
            )


@dataclass(frozen=True)
class PluginRiskProfile:
    """Perfil de riesgo estático de un plugin derivado de sus capacidades solicitadas."""

    plugin_id: str
    declared_capabilities: tuple[PluginCapability, ...]
    assessed_risk_level: TaskActionRisk
    requires_elevated_sandbox: bool = False

    def __post_init__(self) -> None:
        if not self.plugin_id or not isinstance(self.plugin_id, str):
            raise ValueError("El plugin_id debe ser una cadena válida no vacía.")


@dataclass(frozen=True)
class PluginPermission:
    """Permiso formal concedido a un plugin para ejecutar una acción específica."""

    plugin_id: str
    capability_name: str
    tool_name: str
    operation: str
    decision: PermissionDecision
    reason: str
    granted_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class PluginSecurityPolicy:
    """Evaluador Central de la Política de Seguridad para Plugins (Etapa 14.0).

    Trata a todo plugin como CÓDIGO NO CONFIABLE (UNTRUSTED CODE).
    Garantiza que ningún plugin pueda inventar capacidades ni autoelevar privilegios.
    """

    def __init__(
        self,
        risk_classifier: TaskRiskClassifier | None = None,
        permission_manager: PermissionManager | None = None,
    ) -> None:
        self.risk_classifier = risk_classifier or TaskRiskClassifier()
        self.permission_manager = permission_manager or PermissionManager()
        self.audit_logger = get_audit_logger()

    def validate_plugin_manifest(
        self,
        plugin_id: str,
        requested_capability_names: list[str],
        declared_tools: list[dict[str, Any]],
    ) -> PluginRiskProfile:
        """Valida rigurosamente el manifiesto de un plugin antes de cualquier intento de carga.

        INVARIANTES ENFORZADOS:
        1. CERO capacidades inventadas (valida contra ALLOWED_CAPABILITY_STRINGS).
        2. CERO autoelevación de riesgo (comprueba herramientas declaradas contra TaskRiskClassifier).
        """
        # 1. Validación de capacidades solicitadas
        validated_caps: list[PluginCapability] = []
        highest_risk = TaskActionRisk.READ_ONLY

        for cap_name in requested_capability_names:
            if cap_name not in ALLOWED_CAPABILITY_STRINGS:
                raise PluginCapabilityViolationError(
                    f"[SECURITY VIOLATION] El plugin '{plugin_id}' intenta declarar la capacidad no autorizada '{cap_name}'. CERO capacidades inventadas."
                )

            cap_risk = self._derive_capability_default_risk(cap_name)
            if self._risk_level_to_int(cap_risk) > self._risk_level_to_int(highest_risk):
                highest_risk = cap_risk

            validated_caps.append(
                PluginCapability(
                    name=cap_name,
                    description=f"Capacidad declarada {cap_name}",
                    max_allowed_risk=cap_risk,
                )
            )

        # 2. Validación de herramientas declaradas (Prevenir autoelevación de riesgo)
        for tool_info in declared_tools:
            t_name = str(tool_info.get("name", ""))
            t_op = str(tool_info.get("operation", ""))
            claimed_risk = str(tool_info.get("claimed_risk", "")).upper()

            system_risk = self.risk_classifier.classify_task(t_name, t_op)

            # Si el plugin intenta declarar una herramienta de riesgo ALTO/CRITICO como SAFE o READ_ONLY
            if claimed_risk and self._risk_level_to_int(TaskActionRisk(claimed_risk)) < self._risk_level_to_int(system_risk):
                raise PluginPrivilegeElevationError(
                    f"[SECURITY VIOLATION] El plugin '{plugin_id}' intenta autoelevar privilegios declarando la herramienta '{t_name}' como '{claimed_risk}', cuando el sistema la clasifica como '{system_risk.value}'."
                )

            if self._risk_level_to_int(system_risk) > self._risk_level_to_int(highest_risk):
                highest_risk = system_risk

        profile = PluginRiskProfile(
            plugin_id=plugin_id,
            declared_capabilities=tuple(validated_caps),
            assessed_risk_level=highest_risk,
            requires_elevated_sandbox=(highest_risk in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL)),
        )

        self._log_plugin_audit(plugin_id, "manifest_validated", success=True, risk_level=highest_risk.value)
        return profile

    def evaluate_plugin_action(
        self,
        profile: PluginRiskProfile,
        tool_name: str,
        operation: str,
        parameters: dict[str, Any] | None = None,
    ) -> PluginPermission:
        """Evalúa si un plugin no confiable tiene permisos para ejecutar una acción requerida."""
        system_risk = self.risk_classifier.classify_task(tool_name, operation, parameters)

        # Verificar si la acción está amparada por las capacidades declaradas
        required_cap = self._map_tool_to_required_capability(tool_name, operation)

        has_capability = any(c.name == required_cap for c in profile.declared_capabilities)

        if not has_capability and required_cap is not None:
            reason = f"Acción denegada. El plugin '{profile.plugin_id}' carece de la capacidad requerida '{required_cap}'."
            perm = PluginPermission(
                plugin_id=profile.plugin_id,
                capability_name=required_cap or "unknown",
                tool_name=tool_name,
                operation=operation,
                decision=PermissionDecision.DENY,
                reason=reason,
            )
            self._log_plugin_audit(profile.plugin_id, "action_evaluated", success=False, reason=reason)
            return perm

        # Acciones DANGEROUS o CRITICAL requieren confirmación explícita
        if system_risk in (TaskActionRisk.DANGEROUS, TaskActionRisk.CRITICAL):
            reason = f"Acción '{tool_name}.{operation}' de nivel {system_risk.value} requiere confirmación interactiva. CERO bypass para plugins."
            perm = PluginPermission(
                plugin_id=profile.plugin_id,
                capability_name=required_cap or "system",
                tool_name=tool_name,
                operation=operation,
                decision=PermissionDecision.REQUIRE_CONFIRMATION,
                reason=reason,
            )
            self._log_plugin_audit(profile.plugin_id, "action_evaluated", success=False, reason=reason)
            return perm

        perm = PluginPermission(
            plugin_id=profile.plugin_id,
            capability_name=required_cap or "system",
            tool_name=tool_name,
            operation=operation,
            decision=PermissionDecision.ALLOW,
            reason="Acción dentro del perfil de capacidades del plugin y autorizada.",
        )
        self._log_plugin_audit(profile.plugin_id, "action_evaluated", success=True, reason=perm.reason)
        return perm

    def _derive_capability_default_risk(self, cap_name: str) -> TaskActionRisk:
        if cap_name in (PluginDeclaredCapability.PROCESS_EXECUTE, PluginDeclaredCapability.REGISTRY_WRITE):
            return TaskActionRisk.CRITICAL
        if cap_name in (PluginDeclaredCapability.FILESYSTEM_WRITE, PluginDeclaredCapability.DESKTOP):
            return TaskActionRisk.DANGEROUS
        if cap_name in (PluginDeclaredCapability.NETWORK, PluginDeclaredCapability.CLIPBOARD, PluginDeclaredCapability.AUDIO, PluginDeclaredCapability.BROWSER):
            return TaskActionRisk.MEDIUM_RISK
        if cap_name in (PluginDeclaredCapability.FILESYSTEM_READ, PluginDeclaredCapability.REGISTRY_READ):
            return TaskActionRisk.LOW_RISK
        return TaskActionRisk.READ_ONLY

    def _map_tool_to_required_capability(self, tool_name: str, operation: str) -> str | None:
        """Mapea de forma determinista y estructurada una herramienta a su capacidad oficial requerida (M-02)."""
        name = tool_name.lower()
        op = operation.lower()

        # 1. Herramientas de Sistema de Archivos (Filesystem)
        is_fs = any(k in name for k in ("file", "directory", "folder", "path", "document")) or name.startswith("fs_") or name.startswith("filesystem")
        if is_fs:
            if (
                any(k in name for k in ("write", "delete", "create", "save", "remove", "modifier", "writer", "creator"))
                or any(k in op for k in ("write", "delete", "remove", "create", "modify", "append", "save"))
            ):
                return PluginDeclaredCapability.FILESYSTEM_WRITE.value
            return PluginDeclaredCapability.FILESYSTEM_READ.value

        # 2. Procesos / Comandos
        if any(k in name for k in ("process", "cmd", "powershell", "exec", "terminal", "shell", "bash")):
            return PluginDeclaredCapability.PROCESS_EXECUTE.value

        # 3. Registro de Windows
        if "registry" in name or "reg" in name.split("_"):
            if op in ("write", "delete", "set", "create"):
                return PluginDeclaredCapability.REGISTRY_WRITE.value
            return PluginDeclaredCapability.REGISTRY_READ.value

        # 4. Red / Network
        if any(k in name for k in ("network", "http", "socket", "tcp", "udp", "curl", "download", "fetch", "api_client")):
            return PluginDeclaredCapability.NETWORK.value

        # 5. Portapapeles
        if "clipboard" in name:
            return PluginDeclaredCapability.CLIPBOARD.value

        # 6. Audio
        if any(k in name for k in ("audio", "mic", "sound", "speaker", "tts", "stt", "voice")):
            return PluginDeclaredCapability.AUDIO.value

        # 7. Navegador
        if any(k in name for k in ("browser", "web", "html", "selenium", "playwright")):
            return PluginDeclaredCapability.BROWSER.value

        # 8. Información del sistema
        if any(k in name for k in ("system_info", "sysinfo", "cpu", "memory_info", "disk_info", "device")):
            return PluginDeclaredCapability.SYSTEM_INFO.value

        return None

    def _risk_level_to_int(self, risk: TaskActionRisk) -> int:
        order = {
            TaskActionRisk.READ_ONLY: 1,
            TaskActionRisk.LOW_RISK: 2,
            TaskActionRisk.MEDIUM_RISK: 3,
            TaskActionRisk.DANGEROUS: 4,
            TaskActionRisk.CRITICAL: 5,
        }
        return order.get(risk, 3)

    def _log_plugin_audit(self, plugin_id: str, action: str, success: bool, reason: str = "", risk_level: str = "") -> None:
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.POLICY_EVALUATED if success else AuditEventType.EXECUTION_DENIED,
                request_id=f"plugin-{plugin_id[:8]}",
                tool_name="plugin.security_policy",
                operation=action,
                duration_ms=0.0,
                reason=reason or f"Plugin security evaluation: {action}",
                metadata={
                    "plugin_id": plugin_id,
                    "success": success,
                    "risk_level": risk_level,
                },
            )
        )
