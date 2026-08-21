"""Tests unitarios e integrales para Skill Manifest & Capability Declaration (Fase 28.1).

Verifica:
1. Validación y registro exitoso de SkillManifest válido
2. Rechazo de manifest incompleto (campos requeridos faltantes)
3. Rechazo de capability desconocida o no permitida
4. Rechazo de herramientas requeridas con formato o caracteres inválidos
5. Rechazo de degradación de riesgo en operaciones destructivas
6. Rechazo de versión SemVer inválida
7. Rechazo por dependencia inexistente o versión incompatible
8. Rechazo de entrypoints con path traversal o rutas absolutas
9. Rechazo de intentos de escalada de privilegios y permisos prohibidos
"""

from typing import Any

from core.emergency_stop import EmergencyStopManager
from core.security_architecture import SecurityLevel
from skills import (
    BaseSkill,
    SkillDefinition,
    SkillManifest,
    SkillRegistry,
    SkillStatus,
    SkillValidator,
)


class DummyManifestSkill(BaseSkill):
    """Skill de prueba con SkillManifest formal."""

    def __init__(self, manifest: SkillManifest) -> None:
        def_obj = SkillDefinition(
            skill_id=manifest.id,
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            capabilities=manifest.capabilities,
            required_tools=manifest.required_tools,
            required_permissions=manifest.permissions,
            risk_level=manifest.risk_level,
            author=manifest.author,
            manifest=manifest,
        )
        super().__init__(nombre=manifest.id, nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        return {"exito": True, "mensaje": f"Skill {self.nombre} ejecutada."}


class TestSkillManifest:
    """Suite de pruebas para Skill Manifest & Capability Declaration."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_skill_manifest_setup")
        self.registry = SkillRegistry()
        self.registry.reset()

    # ── 1. MANIFEST VÁLIDO ──

    def test_valid_manifest_passes_and_reaches_ready(self) -> None:
        """Verifica que un SkillManifest formal válido pase validación y alcance estado READY."""
        manifest = SkillManifest(
            id="browser.search",
            name="Browser Search Skill",
            version="1.2.0",
            description="Permite realizar búsquedas web y extraer contenido.",
            author="Jessyca Team",
            capabilities=("browser_navigation", "web_search", "content_read"),
            required_tools=("browser.open", "browser.navigate", "browser.read"),
            required_agents=("BrowserAgent",),
            required_models=("llama3.2:latest",),
            permissions=("browser.open", "browser.navigate"),
            risk_level=SecurityLevel.SAFE,
            entrypoint="browser_skill.py",
        )

        is_valid, error = SkillValidator.validate_manifest(manifest)
        assert is_valid is True
        assert error is None

        # Registro en el SkillRegistry
        skill = DummyManifestSkill(manifest)
        reg_ok, reg_err = self.registry.register_skill(skill)
        assert reg_ok is True
        assert reg_err is None
        assert self.registry.get_status("browser.search") == SkillStatus.READY

    # ── 2. MANIFEST INCOMPLETO ──

    def test_incomplete_manifest_rejection(self) -> None:
        """Verifica el rechazo de manifests sin nombre, descripción o capacidades."""
        # Sin nombre
        m_no_name = SkillManifest(
            id="test.incomplete",
            name="",
            description="Some description",
            author="Dev",
            capabilities=("filesystem_read",),
        )
        val1, err1 = SkillValidator.validate_manifest(m_no_name)
        assert val1 is False
        assert "nombre válido" in str(err1).lower()

        # Sin capacidades
        m_no_caps = SkillManifest(
            id="test.incomplete2",
            name="No Caps Skill",
            description="Some description",
            author="Dev",
            capabilities=(),
        )
        val2, err2 = SkillValidator.validate_manifest(m_no_caps)
        assert val2 is False
        assert "al menos una capacidad" in str(err2).lower()

    # ── 3. CAPABILITY DESCONOCIDA ──

    def test_unknown_capability_rejection(self) -> None:
        """Verifica el rechazo de capacidades inventadas o no reconocidas."""
        manifest = SkillManifest(
            id="test.unknown.cap",
            name="Unknown Cap Skill",
            description="Uses invented capability",
            author="Dev",
            capabilities=("unrecognized_alien_capability",),
        )
        is_valid, error = SkillValidator.validate_manifest(manifest)
        assert is_valid is False
        assert "Capacidad desconocida" in str(error)

    # ── 4. TOOL REQUERIDA INVÁLIDA ──

    def test_invalid_tool_format_rejection(self) -> None:
        """Verifica el rechazo de herramientas con nombres ilegales."""
        manifest = SkillManifest(
            id="test.invalid.tool",
            name="Invalid Tool Skill",
            description="Uses bad tool name",
            author="Dev",
            capabilities=("filesystem_read",),
            required_tools=("tool with spaces and &%^",),
        )
        is_valid, error = SkillValidator.validate_manifest(manifest)
        assert is_valid is False
        assert "Herramienta requerida inválida" in str(error)

    # ── 5. RIESGO INVÁLIDO Y DEGRADACIÓN DE RIESGO ──

    def test_risk_degradation_rejection(self) -> None:
        """Verifica que una skill destructiva que declare SAFE sea rechazada."""
        manifest = SkillManifest(
            id="files.purge",
            name="Purge Files",
            description="Borrado masivo y delete total de ficheros de usuario",
            author="Dev",
            capabilities=("filesystem_write",),
            risk_level=SecurityLevel.SAFE,  # Intento ilegal de declarar SAFE
        )
        is_valid, error = SkillValidator.validate_manifest(manifest)
        assert is_valid is False
        assert "Degradación de riesgo inválida" in str(error)

    # ── 6. VERSIÓN SEMVER INVÁLIDA ──

    def test_invalid_semver_rejection(self) -> None:
        """Verifica que versiones que no sigan SemVer sean rechazadas."""
        manifest = SkillManifest(
            id="test.bad.version",
            name="Bad Version Skill",
            version="v1_final",
            description="Non semver",
            author="Dev",
            capabilities=("system_info",),
        )
        is_valid, error = SkillValidator.validate_manifest(manifest)
        assert is_valid is False
        assert "SemVer" in str(error)

    # ── 7. DEPENDENCIAS FALTANTES O INCOMPATIBLES ──

    def test_missing_dependency_rejection(self) -> None:
        """Verifica el rechazo si una dependencia requerida no está instalada."""
        manifest = SkillManifest(
            id="advanced.analysis",
            name="Advanced Analysis",
            description="Requires core parser",
            author="Dev",
            capabilities=("system_info",),
            dependencies={"core.parser": "2.0.0"},  # No instalada
        )
        is_valid, error = SkillValidator.validate_manifest(manifest, installed_skills={})
        assert is_valid is False
        assert "Dependencia faltante" in str(error)

    def test_incompatible_dependency_version_rejection(self) -> None:
        """Verifica el rechazo si la versión instalada es inferior a la requerida."""
        manifest = SkillManifest(
            id="advanced.analysis",
            name="Advanced Analysis",
            description="Requires core parser v2",
            author="Dev",
            capabilities=("system_info",),
            dependencies={"core.parser": "2.0.0"},
        )
        is_valid, error = SkillValidator.validate_manifest(
            manifest,
            installed_skills={"core.parser": "1.0.0"},  # 1.0.0 < 2.0.0
        )
        assert is_valid is False
        assert "Versión incompatible de dependencia" in str(error)

    # ── 8. ENTRYPOINT INVÁLIDO O CON PATH TRAVERSAL ──

    def test_entrypoint_path_traversal_rejection(self) -> None:
        """Verifica el rechazo de entrypoints con path traversal o rutas absolutas."""
        manifest = SkillManifest(
            id="evil.entrypoint",
            name="Evil Entrypoint",
            description="Traversal attempt",
            author="Hacker",
            capabilities=("filesystem_read",),
            entrypoint="../../system32/calc.exe",
        )
        is_valid, error = SkillValidator.validate_manifest(manifest)
        assert is_valid is False
        assert "Entrypoint inseguro" in str(error)

    # ── 9. INTENTO DE PRIVILEGE ESCALATION Y MANIPULACIÓN ──

    def test_privilege_escalation_and_tampering_rejection(self) -> None:
        """Verifica el bloqueo de permisos prohibidos y de inyección en metadatos."""
        # Permiso prohibido
        m_forbidden_perm = SkillManifest(
            id="escalation.skill",
            name="Escalation Skill",
            description="Bypass attempt",
            author="Hacker",
            capabilities=("filesystem_read",),
            permissions=("security.override",),
        )
        val1, err1 = SkillValidator.validate_manifest(m_forbidden_perm)
        assert val1 is False
        assert "Intento de escalada de privilegios" in str(err1)

        # Manipulación en metadatos
        m_tampering = SkillManifest(
            id="tamper.skill",
            name="Tamper Skill",
            description="Intentando inyectar en EmergencyStopManager y SecurityPipeline",
            author="Hacker",
            capabilities=("system_info",),
        )
        val2, err2 = SkillValidator.validate_manifest(m_tampering)
        assert val2 is False
        assert "Intento malicioso de manipulación de seguridad" in str(err2)
