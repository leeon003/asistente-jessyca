"""Validador de 5 etapas para el Ecosistema de Plugins 2.0 (ecosystem_validator.py - Fase 28).

Ejecuta el pipeline de validación previa a la carga:
MANIFEST -> SCHEMA VALIDATION -> DEPENDENCY CHECK -> PERMISSION CHECK -> SECURITY CHECK -> APPROVED REPORT

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. UNTRUSTED DATA: Todo manifiesto es hostil por defecto.
2. RECHAZO DETERMINISTA: Fallo en cualquier etapa aborta inmediatamente la carga.
3. AISLAMIENTO: Detección y bloqueo de permisos prohibidos o intentos de manipulación de seguridad.
"""

from __future__ import annotations

import re

from core.exceptions import MCPError
from core.logger import get_logger
from core.plugin_security import (
    ALLOWED_CAPABILITY_STRINGS,
)
from core.plugins_v2.ecosystem_models import (
    PLUGIN_NAME_REGEX,
    SEMVER_REGEX,
    PluginManifest2,
    PluginValidationReport,
    ValidationStageResult,
)
from core.security_architecture import SecurityLevel

logger = get_logger("jessyca.plugins_v2.validator")

# Permisos explícitamente prohibidos para plugins de terceros
FORBIDDEN_PERMISSIONS: set[str] = {
    "security.override",
    "kernel.bypass",
    "system.unrestricted",
    "admin.grant",
    "emergency_stop.bypass",
    "risk_engine.modify",
    "permission_manager.override",
    "*",
}

# Palabras clave sospechosas de manipulación de seguridad en metadatos
SECURITY_TAMPERING_KEYWORDS: set[str] = {
    "__proto__",
    "constructor",
    "emergencystopmanager",
    "securitypipeline",
    "riskengine",
    "permissionmanager",
    "confirmationmanager",
}


class PluginEcosystemValidationError(MCPError):
    """Error emitido durante la validación del ecosistema de plugins."""

    pass


class PluginEcosystemValidator:
    """Validador central de 5 etapas para manifiestos del Ecosistema de Plugins 2.0."""

    @classmethod
    def validate_manifest(
        cls,
        manifest: PluginManifest2,
        available_plugins: dict[str, str] | None = None,
    ) -> PluginValidationReport:
        """Ejecuta las 5 etapas de validación sobre el manifiesto y retorna el informe consolidado."""
        stages: list[ValidationStageResult] = []
        installed = available_plugins or {}

        # ── ETAPA 1: SCHEMA VALIDATION ──
        s1_passed, s1_msg = cls._validate_schema(manifest)
        stages.append(ValidationStageResult(stage_name="SCHEMA_VALIDATION", passed=s1_passed, message=s1_msg))
        if not s1_passed:
            return PluginValidationReport(
                plugin_name=manifest.name,
                is_valid=False,
                stages=tuple(stages),
                overall_error=f"Fallo en SCHEMA_VALIDATION: {s1_msg}",
            )

        # ── ETAPA 2: DEPENDENCY CHECK ──
        s2_passed, s2_msg = cls._validate_dependencies(manifest, installed)
        stages.append(ValidationStageResult(stage_name="DEPENDENCY_CHECK", passed=s2_passed, message=s2_msg))
        if not s2_passed:
            return PluginValidationReport(
                plugin_name=manifest.name,
                is_valid=False,
                stages=tuple(stages),
                overall_error=f"Fallo en DEPENDENCY_CHECK: {s2_msg}",
            )

        # ── ETAPA 3: PERMISSION CHECK ──
        s3_passed, s3_msg = cls._validate_permissions(manifest)
        stages.append(ValidationStageResult(stage_name="PERMISSION_CHECK", passed=s3_passed, message=s3_msg))
        if not s3_passed:
            return PluginValidationReport(
                plugin_name=manifest.name,
                is_valid=False,
                stages=tuple(stages),
                overall_error=f"Fallo en PERMISSION_CHECK: {s3_msg}",
            )

        # ── ETAPA 4: SECURITY CHECK ──
        s4_passed, s4_msg = cls._validate_security(manifest)
        stages.append(ValidationStageResult(stage_name="SECURITY_CHECK", passed=s4_passed, message=s4_msg))
        if not s4_passed:
            return PluginValidationReport(
                plugin_name=manifest.name,
                is_valid=False,
                stages=tuple(stages),
                overall_error=f"Fallo en SECURITY_CHECK: {s4_msg}",
            )

        # ── ETAPA 5: CONSOLIDACIÓN DE APROBACIÓN ──
        stages.append(ValidationStageResult(stage_name="LOAD_APPROVAL", passed=True, message="Manifiesto validado y aprobado para carga."))
        return PluginValidationReport(
            plugin_name=manifest.name,
            is_valid=True,
            stages=tuple(stages),
            overall_error=None,
        )

    # ── MÉTODOS DE ETAPAS ──

    @classmethod
    def _validate_schema(cls, manifest: PluginManifest2) -> tuple[bool, str]:
        # 1. Nombre
        if not manifest.name or not PLUGIN_NAME_REGEX.match(manifest.name):
            return False, f"Nombre de plugin inválido '{manifest.name}'. Debe ser alfanumérico (3-64 caracteres) con guiones."

        # 2. Versión SemVer
        if not manifest.version or not SEMVER_REGEX.match(manifest.version):
            return False, f"Versión '{manifest.version}' no cumple el formato SemVer (ej: 1.0.0)."

        # 3. Entrypoint seguro (prevenir path traversal y rutas absolutas)
        ep = manifest.entrypoint.strip()
        if not ep or ep.startswith("/") or ep.startswith("\\") or ":" in ep or ".." in ep or "\x00" in ep:
            return False, f"Entrypoint inseguro o con path traversal detectado: '{manifest.entrypoint}'."

        # 4. Capacidades
        if not manifest.capabilities:
            return False, "El plugin debe declarar al menos una capacidad válida en 'capabilities'."

        seen_caps = set()
        for cap in manifest.capabilities:
            if cap in seen_caps:
                return False, f"Capacidad duplicada detectada: '{cap}'."
            if cap not in ALLOWED_CAPABILITY_STRINGS:
                return False, f"Capacidad no permitida o no reconocida por el sistema: '{cap}'."
            seen_caps.add(cap)

        return True, "Esquema y metadatos válidos."

    @classmethod
    def _validate_dependencies(cls, manifest: PluginManifest2, installed: dict[str, str]) -> tuple[bool, str]:
        for dep_name, min_ver in manifest.dependencies.items():
            if dep_name not in installed:
                return False, f"Dependencia faltante: El plugin requiere '{dep_name}' (>= {min_ver}) pero no está instalado."

            inst_ver = installed[dep_name]
            if not cls._is_version_compatible(inst_ver, min_ver):
                return False, f"Versión incompatible de dependencia '{dep_name}': Instalada '{inst_ver}' < Requerida '{min_ver}'."

        return True, "Todas las dependencias están satisfechas."

    @classmethod
    def _validate_permissions(cls, manifest: PluginManifest2) -> tuple[bool, str]:
        for perm in manifest.permissions:
            p_clean = perm.strip().lower()
            if p_clean in FORBIDDEN_PERMISSIONS:
                return False, f"Permiso prohibido solicitado: '{perm}'. Violación de seguridad inmutable."

            # Verificar que el permiso corresponda a una capacidad declarada
            perm_prefix = p_clean.split(".")[0] if "." in p_clean else p_clean
            has_matching_cap = any(cap.startswith(perm_prefix) for cap in manifest.capabilities)
            if not has_matching_cap:
                return False, f"Permiso '{perm}' no está respaldado por ninguna capacidad declarada en el manifiesto."

        return True, "Permisos validados y conformes."

    @classmethod
    def _validate_security(cls, manifest: PluginManifest2) -> tuple[bool, str]:
        # 1. Detección de cadenas de manipulación de seguridad en metadatos
        combined_text = f"{manifest.name} {manifest.description} {manifest.author} {manifest.entrypoint}".lower()
        for kw in SECURITY_TAMPERING_KEYWORDS:
            if kw in combined_text:
                return False, f"Intento malicioso de manipulación de seguridad detectado con palabra clave '{kw}'."

        # 2. Validación de herramientas declaradas
        for tool in manifest.tools:
            if not tool.name or not tool.operation:
                return False, "Herramienta con declaración inválida (falta name u operation)."

            # Herramienta debe declarar una capacidad presente en manifest.capabilities
            if tool.required_capability and tool.required_capability not in manifest.capabilities:
                return False, f"Herramienta '{tool.name}' exige capacidad no declarada: '{tool.required_capability}'."

            # No autoelevar o falsear nivel de riesgo
            if "delete" in tool.name.lower() or "delete" in tool.operation.lower():
                if tool.declared_risk_level == SecurityLevel.SAFE:
                    return False, f"Intento de degradación de riesgo en herramienta destructiva '{tool.name}' (declarada como SAFE)."

        return True, "Verificación de seguridad y capacidades superada."

    @staticmethod
    def _is_version_compatible(installed_version: str, required_version: str) -> bool:
        """Compara versiones SemVer simples (major.minor.patch)."""
        try:
            inst_parts = [int(p) for p in re.split(r"[-.]", installed_version)[:3] if p.isdigit()]
            req_parts = [int(p) for p in re.split(r"[-.]", required_version)[:3] if p.isdigit()]
            return inst_parts >= req_parts
        except Exception:
            return installed_version == required_version
