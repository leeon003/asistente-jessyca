"""Subsistema de Manifiesto de Plugins (PluginManifest - Etapa 14.1).

GARANTÍAS RIGUROSAS DE SEGURIDAD EN ETAPA 14.1:
1. EL MANIFIESTO SE VALIDA ANTES DE CARGAR CUALQUIER CÓDIGO EJECUTABLE.
2. EL MANIFIESTO NO CONCEDE AUTOMÁTICAMENTE PERMISOS.
3. FLUJO OBLIGATORIO: Manifest -> Validation -> Approval -> Registration.
4. RECHAZA RIGUROSAMENTE:
   - Capacidades desconocidas/inventadas.
   - Intentos de autoelevación de riesgo.
   - Manifiestos malformados o incompletos.
   - Capacidades duplicadas.
   - Rutas absolutas, traversal (../) o fuera del sandbox del plugin.
   - Identificadores o versiones (SemVer) no válidas.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.exceptions import MCPError
from core.logger import get_logger
from core.plugin_security import (
    PluginSecurityPolicy,
)

logger = get_logger("jessyca.core.plugin_manifest")

# Regex estricto de identificación de plugin (ej: jessyca-plugin-weather)
PLUGIN_ID_REGEX = re.compile(r"^[a-z0-9\-_]{3,64}$")

# Regex de versión SemVer (ej: 1.0.0, 2.1.4-beta)
SEMVER_REGEX = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$")


class PluginManifestError(MCPError):
    """Error base del subsistema de manifiesto de plugins."""

    pass


class PluginValidationError(PluginManifestError):
    """Error emitido cuando el manifiesto de un plugin es malformado o viola el esquema."""

    pass


class PluginPathSecurityError(PluginManifestError):
    """Error emitido cuando el entrypoint o rutas de un plugin intentan path traversal u operaciones inseguras."""

    pass


class PluginVersionError(PluginManifestError):
    """Error emitido cuando la versión del plugin no cumple SemVer."""

    pass


@dataclass(frozen=True)
class PluginMetadata:
    """Metadatos formales e inmutables del manifiesto de un plugin."""

    plugin_id: str
    name: str
    version: str
    description: str
    author: str
    entrypoint: str


@dataclass(frozen=True)
class PluginManifest:
    """Manifiesto inmutable validado de un plugin."""

    metadata: PluginMetadata
    capabilities: tuple[str, ...]
    permissions: tuple[str, ...]
    tools: tuple[dict[str, Any], ...]
    min_system_version: str = "3.0.0"
    validated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    is_approved: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serializa el manifiesto a un diccionario limpio para auditoría."""
        return {
            "plugin_id": self.metadata.plugin_id,
            "name": self.metadata.name,
            "version": self.metadata.version,
            "author": self.metadata.author,
            "entrypoint": self.metadata.entrypoint,
            "capabilities": list(self.capabilities),
            "permissions": list(self.permissions),
            "tools_count": len(self.tools),
            "min_system_version": self.min_system_version,
            "is_approved": self.is_approved,
            "validated_at": self.validated_at.isoformat(),
        }


class PluginManifestValidator:
    """Validador Riguroso de Manifiestos de Plugins (PluginManifestValidator - Etapa 14.1).

    Garantiza la validación integral del esquema, versión SemVer, capacidades y rutas seguras.
    """

    def __init__(self, security_policy: PluginSecurityPolicy | None = None) -> None:
        self.security_policy = security_policy or PluginSecurityPolicy()
        self.audit_logger = get_audit_logger()

    def validate_manifest_dict(self, raw: dict[str, Any]) -> PluginManifest:
        """Valida rigurosamente la estructura y contenido de un diccionario de manifiesto.

        Lanza PluginValidationError, PluginPathSecurityError o PluginVersionError en caso de fallo.
        """
        if not isinstance(raw, dict):
            raise PluginValidationError("El manifiesto del plugin debe ser un objeto JSON/dict válido.")

        # 1. Validar campos requeridos de la sección principal
        required_fields = ("id", "name", "version", "description", "author", "entrypoint", "capabilities")
        for req in required_fields:
            if req not in raw or raw[req] is None:
                raise PluginValidationError(f"El manifiesto carece del campo obligatorio '{req}'.")

        plugin_id = str(raw["id"]).strip()

        name = str(raw["name"]).strip()
        version = str(raw["version"]).strip()
        description = str(raw["description"]).strip()
        author = str(raw["author"]).strip()
        entrypoint = str(raw["entrypoint"]).strip()

        # 2. Validar Identificador de Plugin
        if not PLUGIN_ID_REGEX.match(plugin_id):
            raise PluginValidationError(
                f"Identificador de plugin inválido '{plugin_id}'. Debe ser alfanumérico en minúsculas (3-64 caracteres) con guiones."
            )

        # 3. Validar Versión (SemVer)
        if not SEMVER_REGEX.match(version):
            raise PluginVersionError(
                f"Versión de plugin inválida '{version}'. Debe seguir el formato SemVer (ej: 1.0.0, 2.1.0-beta)."
            )

        # 4. Validar Seguridad de Rutas (Path Security - Prevenir Path Traversal)
        self._validate_safe_relative_path(entrypoint)

        # 5. Validar Capacidades (Capacidades duplicadas y capacidades desconocidas)
        raw_capabilities = raw.get("capabilities", [])
        if not isinstance(raw_capabilities, list):
            raise PluginValidationError("El campo 'capabilities' debe ser una lista de cadenas.")

        seen_caps = set()
        validated_caps: list[str] = []
        for cap in raw_capabilities:
            cap_str = str(cap).strip()
            if cap_str in seen_caps:
                raise PluginValidationError(f"Capacidad duplicada detectada en el manifiesto: '{cap_str}'.")
            seen_caps.add(cap_str)
            validated_caps.append(cap_str)

        # 6. Validar Permisos y Herramientas Declaradas
        raw_permissions = raw.get("permissions", [])
        if not isinstance(raw_permissions, list):
            raise PluginValidationError("El campo 'permissions' debe ser una lista de cadenas.")
        validated_perms = [str(p).strip() for p in raw_permissions]

        raw_tools = raw.get("tools", [])
        if not isinstance(raw_tools, list):
            raise PluginValidationError("El campo 'tools' debe ser una lista de objetos herramienta.")

        validated_tools: list[dict[str, Any]] = []
        for tool in raw_tools:
            if not isinstance(tool, dict) or "name" not in tool or "operation" not in tool:
                raise PluginValidationError("Cada herramienta declarada en 'tools' debe tener 'name' y 'operation'.")
            validated_tools.append(tool)

        # 7. Validar mediante PluginSecurityPolicy (Rechazar autoelevación de riesgo y capacidades desconocidas)
        self.security_policy.validate_plugin_manifest(
            plugin_id=plugin_id,
            requested_capability_names=validated_caps,
            declared_tools=validated_tools,
        )

        metadata = PluginMetadata(
            plugin_id=plugin_id,
            name=name,
            version=version,
            description=description,
            author=author,
            entrypoint=entrypoint,
        )

        manifest = PluginManifest(
            metadata=metadata,
            capabilities=tuple(validated_caps),
            permissions=tuple(validated_perms),
            tools=tuple(validated_tools),
            min_system_version=str(raw.get("min_system_version", "3.0.0")),
            is_approved=False,  # El manifiesto validado NUNCA se aprueba automáticamente
        )

        self._log_manifest_audit(manifest, success=True)
        return manifest

    def validate_manifest_file(self, file_path: Path | str) -> PluginManifest:
        """Carga y valida un archivo `plugin.json` desde disco."""
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise PluginValidationError(f"El archivo de manifiesto no existe en la ruta: '{path}'")

        try:
            with open(path, encoding="utf-8") as f:
                raw_dict = json.load(f)
            return self.validate_manifest_dict(raw_dict)
        except json.JSONDecodeError as e:
            raise PluginValidationError(f"Error de sintaxis JSON en el archivo de manifiesto: {e}") from e


    def approve_manifest(self, manifest: PluginManifest, reviewer_id: str = "admin") -> PluginManifest:
        """Aprueba formalmente un manifiesto validado.

        Flujo obligatorio: Manifest -> Validation -> Approval -> Registration.
        """
        if manifest.is_approved:
            return manifest

        approved_manifest = PluginManifest(
            metadata=manifest.metadata,
            capabilities=manifest.capabilities,
            permissions=manifest.permissions,
            tools=manifest.tools,
            min_system_version=manifest.min_system_version,
            is_approved=True,
        )
        logger.info(f"[PLUGIN MANIFEST] Manifiesto del plugin '{manifest.metadata.plugin_id}' aprobado por '{reviewer_id}'.")
        self._log_manifest_audit(approved_manifest, success=True, event_action="manifest_approved")
        return approved_manifest

    def _validate_safe_relative_path(self, relative_path: str) -> None:
        """Verifica que una ruta sea estrictamente relativa y segura contra traversal."""
        if not relative_path:
            raise PluginPathSecurityError("La ruta de entrypoint no puede estar vacía.")

        p = Path(relative_path)

        # Rechazar rutas absolutas o con letra de unidad (ej: C:\, /usr/bin)
        if p.is_absolute() or relative_path.startswith("/") or relative_path.startswith("\\") or ":" in relative_path:
            raise PluginPathSecurityError(
                f"[SECURITY VIOLATION] Ruta absoluta no permitida '{relative_path}'. El entrypoint debe ser una ruta relativa dentro del sandbox del plugin."
            )

        # Rechazar path traversal (../ o ..\)
        parts = p.parts
        if ".." in parts:
            raise PluginPathSecurityError(
                f"[SECURITY VIOLATION] Intento de Path Traversal detectado en '{relative_path}'. Prohibido el uso de '..' para salir del directorio del plugin."
            )

    def _log_manifest_audit(self, manifest: PluginManifest, success: bool, event_action: str = "manifest_validated") -> None:
        audit_meta = manifest.to_dict()
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.POLICY_EVALUATED if success else AuditEventType.EXECUTION_DENIED,
                request_id=f"manifest-{manifest.metadata.plugin_id[:8]}",
                tool_name="plugin.manifest_validator",
                operation=event_action,
                duration_ms=0.0,
                reason=f"Plugin manifest {event_action}: success={success}",
                metadata=audit_meta,
            )
        )
