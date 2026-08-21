"""Tests unitarios e integrales para el Ecosistema de Plugins 2.0 (Fase 28).

Verifica:
1. Validación y registro exitoso de plugin válido (5 etapas superadas)
2. Rechazo de plugin inválido por esquema o metadatos malformados
3. Rechazo por versión incompatible (SemVer inválido o versión de dependencia menor)
4. Rechazo por dependencia faltante
5. Rechazo por herramienta no declarada o capacidad no coincidente
6. Rechazo por permisos prohibidos o insuficientes (ej. security.override, admin.grant)
7. Rechazo por plugin malicioso o intento de degradación de riesgo
8. Aislamiento estricto: imposibilidad de alterar el Bloque de Seguridad Inmutable
"""

from core.emergency_stop import EmergencyStopManager
from core.permission_manager import PermissionManager
from core.plugins_v2 import (
    PluginEcosystemManager,
    PluginEcosystemValidator,
    PluginManifest2,
    PluginStatus,
    PluginToolDeclaration,
)
from core.risk_engine import RiskEngine
from core.security_architecture import SecurityLevel


class TestPluginEcosystem2:
    """Suite de pruebas exhaustiva para el Ecosistema de Plugins 2.0."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_plugin_ecosystem_setup")
        self.validator = PluginEcosystemValidator()
        self.manager = PluginEcosystemManager(validator=self.validator)
        self.manager.reset()
        self.risk_engine = RiskEngine()
        self.permission_manager = PermissionManager()

    # ── 1. PLUGIN VÁLIDO (CARGA EXITOSA EN 5 ETAPAS) ──

    def test_valid_plugin_installation_and_activation(self) -> None:
        """Verifica que un plugin válido supere las 5 etapas de validación y pueda activarse."""
        manifest = PluginManifest2(
            name="file-archiver-plugin",
            version="1.0.0",
            capabilities=("filesystem.read", "filesystem.write"),
            tools=(
                PluginToolDeclaration(
                    name="file_archiver.compress_zip",
                    description="Comprime archivos en formato ZIP.",
                    operation="write",
                    required_capability="filesystem.write",
                    declared_risk_level=SecurityLevel.LOW,
                ),
            ),
            permissions=("filesystem.read", "filesystem.write"),
            description="Plugin para compresión y archivo de ficheros locales.",
            author="Jessyca Team",
            entrypoint="archiver.py",
        )

        report = self.manager.install_plugin(manifest)
        assert report.is_valid is True
        assert len(report.stages) == 5
        assert report.overall_error is None

        # Activar
        activated = self.manager.activate_plugin("file-archiver-plugin")
        assert activated is True
        assert self.manager.get_status("file-archiver-plugin") == PluginStatus.ACTIVE

    # ── 2. PLUGIN INVÁLIDO POR ESQUEMA O METADATOS ──

    def test_invalid_plugin_name_and_entrypoint_rejection(self) -> None:
        """Verifica el rechazo de plugins con nombres ilegales o entrypoints con path traversal."""
        # Nombre ilegal
        bad_name_manifest = PluginManifest2(
            name="INVALID NAME WITH SPACES AND CAPS",
            version="1.0.0",
            capabilities=("filesystem.read",),
            description="Bad name",
            author="Dev",
        )
        rep1 = self.manager.install_plugin(bad_name_manifest)
        assert rep1.is_valid is False
        assert "Nombre de plugin inválido" in str(rep1.overall_error)

        # Path traversal en entrypoint
        bad_ep_manifest = PluginManifest2(
            name="evil-traversal-plugin",
            version="1.0.0",
            capabilities=("filesystem.read",),
            description="Traversal",
            author="Hacker",
            entrypoint="../../system32/cmd.exe",
        )
        rep2 = self.manager.install_plugin(bad_ep_manifest)
        assert rep2.is_valid is False
        assert "path traversal" in str(rep2.overall_error).lower()

    # ── 3. VERSIÓN INCOMPATIBLE (SEMVER INVÁLIDO) ──

    def test_invalid_semver_version_rejection(self) -> None:
        """Verifica que versiones que no cumplan SemVer sean rechazadas."""
        manifest = PluginManifest2(
            name="bad-version-plugin",
            version="version_1_final_beta",  # No es SemVer
            capabilities=("filesystem.read",),
            description="Bad version",
            author="Dev",
        )
        report = self.manager.install_plugin(manifest)
        assert report.is_valid is False
        assert "SemVer" in str(report.overall_error)

    # ── 4. DEPENDENCIA FALTANTE ──

    def test_missing_dependency_rejection(self) -> None:
        """Verifica que si un plugin declara una dependencia no instalada, sea rechazado."""
        manifest = PluginManifest2(
            name="advanced-ocr-plugin",
            version="2.0.0",
            capabilities=("filesystem.read",),
            dependencies={"core-vision-plugin": "1.5.0"},  # No está instalado
            description="Requiere core vision",
            author="Dev",
        )
        report = self.manager.install_plugin(manifest)
        assert report.is_valid is False
        assert "Dependencia faltante" in str(report.overall_error)

    def test_incompatible_dependency_version_rejection(self) -> None:
        """Verifica que si la versión instalada es inferior a la requerida, sea rechazado."""
        # 1. Instalar dependencia base v1.0.0
        base_manifest = PluginManifest2(
            name="base-math-plugin",
            version="1.0.0",
            capabilities=("system.info",),
            description="Base math",
            author="Dev",
        )
        self.manager.install_plugin(base_manifest)

        # 2. Intentar instalar plugin que exige v2.0.0
        consumer_manifest = PluginManifest2(
            name="advanced-stats-plugin",
            version="1.0.0",
            capabilities=("system.info",),
            dependencies={"base-math-plugin": "2.0.0"},  # Exige v2.0.0 pero está v1.0.0
            description="Consumer stats",
            author="Dev",
        )
        report = self.manager.install_plugin(consumer_manifest)
        assert report.is_valid is False
        assert "Versión incompatible de dependencia" in str(report.overall_error)

    # ── 5. HERRAMIENTA NO DECLARADA O CAPACIDAD NO COINCIDENTE ──

    def test_tool_with_undeclared_capability_rejection(self) -> None:
        """Verifica que una herramienta que exija una capacidad no declarada en el manifiesto sea rechazada."""
        manifest = PluginManifest2(
            name="network-scraper-plugin",
            version="1.0.0",
            capabilities=("filesystem.read",),  # Solo declara filesystem
            tools=(
                PluginToolDeclaration(
                    name="scraper.fetch_url",
                    operation="network_call",
                    required_capability="network",  # No está en capabilities
                ),
            ),
            description="Scraper",
            author="Dev",
        )
        report = self.manager.install_plugin(manifest)
        assert report.is_valid is False
        assert "capacidad no declarada" in str(report.overall_error).lower()

    # ── 6. PERMISOS PROHIBIDOS O INSUFICIENTES ──

    def test_forbidden_permission_rejection(self) -> None:
        """Verifica que cualquier intento de solicitar permisos prohibidos sea rechazado."""
        manifest = PluginManifest2(
            name="bypass-security-plugin",
            version="1.0.0",
            capabilities=("filesystem.read",),
            permissions=("security.override",),  # Permiso prohibido
            description="Intento de bypass",
            author="Malicious",
        )
        report = self.manager.install_plugin(manifest)
        assert report.is_valid is False
        assert "Permiso prohibido" in str(report.overall_error)

    # ── 7. PLUGIN MALICIOSO Y DEGRADACIÓN DE RIESGO ──

    def test_destructive_tool_risk_degradation_rejection(self) -> None:
        """Verifica que declarar una herramienta destructiva (delete) como SAFE sea rechazado."""
        manifest = PluginManifest2(
            name="stealth-cleaner-plugin",
            version="1.0.0",
            capabilities=("filesystem.write",),
            tools=(
                PluginToolDeclaration(
                    name="cleaner.delete_all_logs",
                    operation="delete",
                    required_capability="filesystem.write",
                    declared_risk_level=SecurityLevel.SAFE,  # Intento ilegal de declarar SAFE para delete
                ),
            ),
            description="Stealth cleaner",
            author="Malicious",
        )
        report = self.manager.install_plugin(manifest)
        assert report.is_valid is False
        assert "degradación de riesgo" in str(report.overall_error).lower()

    # ── 8. AISLAMIENTO E IMPOSIBILIDAD DE ALTERAR SEGURIDAD ──

    def test_plugin_cannot_tamper_with_immutable_security_block(self) -> None:
        """Verifica que un plugin que intente nombrar o apuntar a clases de seguridad sea bloqueado."""
        manifest = PluginManifest2(
            name="tamper-plugin",
            version="1.0.0",
            capabilities=("system.info",),
            description="Intentando inyectar payload en EmergencyStopManager y SecurityPipeline",
            author="Hacker",
        )
        report = self.manager.install_plugin(manifest)
        assert report.is_valid is False
        assert "Intento malicioso de manipulación de seguridad" in str(report.overall_error)

        # Comprobar que los singletons inmutables siguen 100% operativos e intactos
        assert self.emergency_stop.is_stopped() is False
        assert self.permission_manager is not None
        assert self.risk_engine is not None
