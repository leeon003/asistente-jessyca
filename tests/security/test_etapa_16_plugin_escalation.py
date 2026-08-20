"""Etapa 16.0 — Vector 06: Plugin Capability Escalation Audit.

Verifica que el Plugin Framework resiste:
- Inventar capabilities fuera del catálogo oficial
- Autoelevar el nivel de riesgo de herramientas
- Declarar capacidades sin permisos correspondientes
- M-02: Mapeo frágil de tool→capability por subcadena
"""

from __future__ import annotations

import pytest

from core.plugin_security import (
    ALLOWED_CAPABILITY_STRINGS,
    PluginCapabilityViolationError,
    PluginDeclaredCapability,
    PluginPrivilegeElevationError,
    PluginSecurityPolicy,
)


class TestPluginCapabilityInvention:
    """Ningún plugin puede inventar capabilities fuera del catálogo oficial."""

    def setup_method(self) -> None:
        self.policy = PluginSecurityPolicy()

    def test_official_capabilities_catalog_is_fixed(self) -> None:
        """El catálogo de capabilities es fijo e inmutable."""
        official_caps = {cap.value for cap in PluginDeclaredCapability}
        assert official_caps == ALLOWED_CAPABILITY_STRINGS
        # Las capabilities oficiales deben ser exactamente estas 12
        assert len(official_caps) == 12, (
            f"[AUDIT] El catálogo tiene {len(official_caps)} capabilities, se esperan 12."
        )

    def test_invented_capability_rejected(self) -> None:
        """Plugin que intenta declarar capability inventada debe ser rechazado."""
        with pytest.raises(PluginCapabilityViolationError, match="[Ss]eguridad|[Vv]iolation"):
            self.policy.validate_plugin_manifest(
                plugin_id="evil-plugin",
                requested_capability_names=["system.kernel_access"],  # No existe
                declared_tools=[],
            )

    def test_empty_string_capability_rejected(self) -> None:
        """Capability vacía no debe ser permitida."""
        with pytest.raises(PluginCapabilityViolationError):
            self.policy.validate_plugin_manifest(
                plugin_id="empty-cap-plugin",
                requested_capability_names=[""],
                declared_tools=[],
            )

    def test_wildcard_capability_rejected(self) -> None:
        """Wildcard '*' no debe ser una capability válida."""
        with pytest.raises(PluginCapabilityViolationError):
            self.policy.validate_plugin_manifest(
                plugin_id="wildcard-plugin",
                requested_capability_names=["*"],
                declared_tools=[],
            )

    def test_sql_injection_in_capability_name_rejected(self) -> None:
        """Inyección SQL en nombre de capability debe ser rechazada."""
        with pytest.raises(PluginCapabilityViolationError):
            self.policy.validate_plugin_manifest(
                plugin_id="sql-plugin",
                requested_capability_names=["filesystem.read'; DROP TABLE--"],
                declared_tools=[],
            )

    def test_valid_capabilities_accepted(self) -> None:
        """Plugin con capabilities oficiales válidas debe ser aceptado."""
        profile = self.policy.validate_plugin_manifest(
            plugin_id="valid-plugin",
            requested_capability_names=[
                PluginDeclaredCapability.FILESYSTEM_READ.value,
                PluginDeclaredCapability.SYSTEM_INFO.value,
            ],
            declared_tools=[],
        )
        assert profile.plugin_id == "valid-plugin"
        assert len(profile.declared_capabilities) == 2


class TestPluginPrivilegeElevation:
    """Ningún plugin puede autoelevar el riesgo de sus herramientas."""

    def setup_method(self) -> None:
        self.policy = PluginSecurityPolicy()

    def test_plugin_cannot_downgrade_risk_of_dangerous_tool(self) -> None:
        """Plugin no puede declarar herramienta DANGEROUS como SAFE."""
        with pytest.raises(PluginPrivilegeElevationError, match=r"(?i)elevaci|escalat|violat"):
            self.policy.validate_plugin_manifest(
                plugin_id="escalating-plugin",
                requested_capability_names=[PluginDeclaredCapability.PROCESS_EXECUTE.value],
                declared_tools=[
                    {
                        "name": "run_powershell",
                        "operation": "execute",
                        "claimed_risk": "READ_ONLY",  # Intento de downgrade
                    }
                ],
            )

    def test_plugin_cannot_claim_lower_risk_for_registry_write(self) -> None:
        """Plugin no puede declarar registry.write como LOW_RISK."""
        with pytest.raises(PluginPrivilegeElevationError):
            self.policy.validate_plugin_manifest(
                plugin_id="registry-escalating-plugin",
                requested_capability_names=[PluginDeclaredCapability.REGISTRY_WRITE.value],
                declared_tools=[
                    {
                        "name": "registry.write",
                        "operation": "write",
                        "claimed_risk": "LOW_RISK",  # Registry write es CRITICAL
                    }
                ],
            )

    def test_plugin_action_without_required_capability_denied(self) -> None:
        """Plugin sin capability 'filesystem.write' no puede acceder a file delete."""
        # Plugin sólo tiene filesystem.read
        profile = self.policy.validate_plugin_manifest(
            plugin_id="readonly-plugin",
            requested_capability_names=[PluginDeclaredCapability.FILESYSTEM_READ.value],
            declared_tools=[],
        )

        # Intentar acción que requiere filesystem.write
        perm = self.policy.evaluate_plugin_action(
            profile=profile,
            tool_name="file.delete",
            operation="delete",
        )

        from core.permission_manager import PermissionDecision
        assert perm.decision == PermissionDecision.DENY, (
            "[AUDIT] Plugin sin 'filesystem.write' pudo acceder a file.delete."
        )

    def test_dangerous_plugin_action_requires_confirmation(self) -> None:
        """Acciones DANGEROUS de plugins deben requerir confirmación."""
        # Plugin con filesystem.write
        profile = self.policy.validate_plugin_manifest(
            plugin_id="write-plugin",
            requested_capability_names=[PluginDeclaredCapability.FILESYSTEM_WRITE.value],
            declared_tools=[],
        )

        perm = self.policy.evaluate_plugin_action(
            profile=profile,
            tool_name="filesystem",
            operation="delete",
        )

        from core.permission_manager import PermissionDecision
        assert perm.decision in (
            PermissionDecision.REQUIRE_CONFIRMATION,
            PermissionDecision.DENY,
        ), (
            "[AUDIT] Acción DANGEROUS de plugin no requirió confirmación."
        )


class TestPluginCapabilityMappingM02:
    """AUDIT M-02: Mapeo frágil tool→capability por subcadena."""

    def setup_method(self) -> None:
        self.policy = PluginSecurityPolicy()

    def test_network_in_name_maps_to_network_capability(self) -> None:
        """M-02 AUDIT: Tool con 'network' en nombre se mapea a capability NETWORK."""
        profile = self.policy.validate_plugin_manifest(
            plugin_id="net-plugin",
            requested_capability_names=[PluginDeclaredCapability.NETWORK.value],
            declared_tools=[],
        )
        perm = self.policy.evaluate_plugin_action(
            profile=profile,
            tool_name="my_network_diagnostic",  # 'network' en nombre
            operation="read",
        )
        # Debe funcionar porque tiene capability NETWORK
        from core.permission_manager import PermissionDecision
        assert perm.decision in (PermissionDecision.ALLOW, PermissionDecision.REQUIRE_CONFIRMATION)

    def test_filesystem_tool_without_network_capability(self) -> None:
        """M-02 AUDIT: Tool de filesystem que incluye 'network' en nombre puede confundir el mapeo."""
        profile = self.policy.validate_plugin_manifest(
            plugin_id="fs-only-plugin",
            requested_capability_names=[PluginDeclaredCapability.FILESYSTEM_READ.value],
            declared_tools=[],
        )

        # Tool que sólo necesita filesystem.read pero tiene 'network' en el nombre
        perm = self.policy.evaluate_plugin_action(
            profile=profile,
            tool_name="network_file_cache_reader",
            operation="read",
        )

        from core.permission_manager import PermissionDecision
        # M-02: La subcadena 'network' en el nombre puede mapearlo a capability NETWORK
        # que el plugin NO tiene — resultando en DENY incorrecto para una operación legítima
        if perm.decision == PermissionDecision.DENY:
            pytest.xfail(
                "[AUDIT-M02-CONFIRMED] Tool 'network_file_cache_reader' con sólo capability "
                "filesystem.read fue DENIED porque '_map_tool_to_required_capability()' "
                "detectó 'network' en el nombre y requirió capability NETWORK. "
                "Mapeo frágil por subcadena confirmado."
            )
