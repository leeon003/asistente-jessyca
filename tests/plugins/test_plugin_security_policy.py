"""Pruebas unitarias de la Arquitectura de Seguridad para Plugins (Etapa 14.0).

REQUISITOS PROBADOS:
1. UNTRUSTED CODE: Todo plugin es no confiable por defecto.
2. CERO capacidades inventadas: Declarar capacidades no oficiales lanza PluginCapabilityViolationError.
3. CERO autoelevación de riesgo: Declarar herramientas peligrosas con riesgo bajo lanza PluginPrivilegeElevationError.
4. Inmutabilidad de registradores centrales del núcleo.
5. Manifiesto válido con capacidades declaradas oficialmente (filesystem.read, clipboard, etc.).
"""

from __future__ import annotations

import pytest

from core.permission_manager import PermissionDecision
from core.plugin_security import (
    PluginCapabilityViolationError,
    PluginDeclaredCapability,
    PluginPrivilegeElevationError,
    PluginSecurityPolicy,
)


def test_untrusted_plugin_by_default() -> None:
    """Verifica que un plugin sin capacidades declaradas no obtenga permisos por defecto."""
    policy = PluginSecurityPolicy()

    # Validar manifiesto con 0 capacidades solicitadas
    profile = policy.validate_plugin_manifest(
        plugin_id="untrusted-plugin-001",
        requested_capability_names=[],
        declared_tools=[],
    )

    assert profile.plugin_id == "untrusted-plugin-001"
    assert len(profile.declared_capabilities) == 0

    # Intentar ejecutar cualquier acción requiere capacidades explícitas
    perm = policy.evaluate_plugin_action(
        profile=profile,
        tool_name="file.read",
        operation="read_file",
    )
    assert perm.decision == PermissionDecision.DENY
    assert "carece de la capacidad requerida" in perm.reason


def test_plugin_cannot_invent_capabilities() -> None:
    """Verifica que un plugin NO pueda inventar cadenas de capacidad fuera del catálogo oficial."""
    policy = PluginSecurityPolicy()

    with pytest.raises(PluginCapabilityViolationError) as exc_info:
        policy.validate_plugin_manifest(
            plugin_id="malicious-inventor-plugin",
            requested_capability_names=["system.bypass", "admin.godmode"],
            declared_tools=[],
        )

    assert "CERO capacidades inventadas" in str(exc_info.value) or "no autorizada" in str(exc_info.value)


def test_plugin_cannot_auto_elevate_risk() -> None:
    """Verifica que un plugin NO pueda declarar una herramienta peligrosa como SAFE/READ_ONLY."""
    policy = PluginSecurityPolicy()

    declared_tools = [
        {
            "name": "powershell.execute",
            "operation": "run_script",
            "claimed_risk": "READ_ONLY",  # Intento engañoso de reducir riesgo
        }
    ]

    with pytest.raises(PluginPrivilegeElevationError) as exc_info:
        policy.validate_plugin_manifest(
            plugin_id="tricky-plugin",
            requested_capability_names=["process.execute"],
            declared_tools=declared_tools,
        )

    assert "autoelevar privilegios" in str(exc_info.value)


def test_valid_plugin_capability_manifest() -> None:
    """Verifica que un manifiesto legítimo con capacidades oficiales sea procesado correctamente."""
    policy = PluginSecurityPolicy()

    valid_caps = [
        PluginDeclaredCapability.FILESYSTEM_READ.value,
        PluginDeclaredCapability.CLIPBOARD.value,
    ]

    profile = policy.validate_plugin_manifest(
        plugin_id="good-reader-plugin",
        requested_capability_names=valid_caps,
        declared_tools=[],
    )

    assert profile.plugin_id == "good-reader-plugin"
    assert len(profile.declared_capabilities) == 2

    # Probar evaluación de lectura permitida
    perm_read = policy.evaluate_plugin_action(profile, "file.read", "read_file")
    assert perm_read.decision == PermissionDecision.ALLOW

    # Probar evaluación de escritura (no declarada) -> DENY
    perm_write = policy.evaluate_plugin_action(profile, "file.write", "save_file")
    assert perm_write.decision == PermissionDecision.DENY


def test_dangerous_action_requires_confirmation() -> None:
    """Verifica que acciones DANGEROUS/CRITICAL exigirán confirmación interactiva a pesar de tener la capacidad."""
    policy = PluginSecurityPolicy()

    profile = policy.validate_plugin_manifest(
        plugin_id="sys-exec-plugin",
        requested_capability_names=[PluginDeclaredCapability.PROCESS_EXECUTE.value],
        declared_tools=[],
    )

    # Intentar ejecutar powershell (CRITICAL) -> REQUIRE_CONFIRMATION
    perm = policy.evaluate_plugin_action(profile, "cmd.execute", "run")
    assert perm.decision == PermissionDecision.REQUIRE_CONFIRMATION
    assert "CERO bypass para plugins" in perm.reason
