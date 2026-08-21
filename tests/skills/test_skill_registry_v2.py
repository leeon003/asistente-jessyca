"""Tests unitarios e integrales para el formal Skill Registry 2.0 (Fase 28.3).

Verifica:
1. Registro y catálogo multi-versión
2. Detección y rechazo de duplicados (no silent overwrite)
3. Lookup determinista por ID y por ID@versión
4. Coexistencia de múltiples versiones de una misma Skill
5. Discovery multidimensional (ID, capability, categoría, tool, agent, riesgo)
6. Ciclo de vida y estados: ENABLED, DISABLED, INVALID, UNLOADED
7. Desregistro específico por versión o global
8. Rechazo y contención de Skills inválidas
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
)


class MockMultiVersionSkill(BaseSkill):
    """Skill de prueba configurable para versionado."""

    def __init__(
        self,
        skill_id: str,
        version: str = "1.0.0",
        capabilities: tuple[str, ...] = ("filesystem_read",),
        required_tools: tuple[str, ...] = ("file.search",),
        required_agents: tuple[str, ...] = ("FileAgent",),
        risk_level: SecurityLevel = SecurityLevel.SAFE,
        category: str = "files",
    ) -> None:
        manifest = SkillManifest(
            id=skill_id,
            name=f"{skill_id} v{version}",
            version=version,
            description=f"Descripción de {skill_id} en versión {version}",
            author="Jessyca Team",
            capabilities=capabilities,
            required_tools=required_tools,
            required_agents=required_agents,
            risk_level=risk_level,
        )
        def_obj = SkillDefinition(
            skill_id=skill_id,
            name=f"{skill_id} v{version}",
            version=version,
            description=f"Descripción de {skill_id} en versión {version}",
            capabilities=capabilities,
            required_tools=required_tools,
            risk_level=risk_level,
            manifest=manifest,
        )
        super().__init__(nombre=skill_id, nivel_riesgo=1, definition=def_obj)

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        return {"exito": True, "mensaje": f"{self.nombre} v{self.definition.version} ejecutada."}


class TestSkillRegistryV2:
    """Suite de pruebas formal para el Skill Registry multi-versión."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_registry_v2_setup")
        self.registry = SkillRegistry()
        self.registry.reset()

    # ── 1. REGISTRO FORMAL ──

    def test_register_single_and_multiple_skills(self) -> None:
        """Verifica el registro y listado básico de skills."""
        s1 = MockMultiVersionSkill(skill_id="browser.search", version="1.0.0", capabilities=("web_search",))
        s2 = MockMultiVersionSkill(skill_id="files.organize", version="1.0.0", capabilities=("filesystem_write",))

        ok1, err1 = self.registry.register_skill(s1)
        ok2, err2 = self.registry.register_skill(s2)

        assert ok1 is True and err1 is None
        assert ok2 is True and err2 is None
        assert len(self.registry.list_skills()) == 2
        assert self.registry.get_status("browser.search") in (SkillStatus.READY, SkillStatus.ENABLED)

    # ── 2. DUPLICADOS Y CONFLICTOS SILENCIOSOS ──

    def test_duplicate_registration_is_rejected_without_silent_overwrite(self) -> None:
        """Verifica que intentar registrar la misma (id, versión) sea rechazado sin sobrescritura."""
        s1 = MockMultiVersionSkill(skill_id="browser.search", version="1.0.0")
        s1_dup = MockMultiVersionSkill(skill_id="browser.search", version="1.0.0")

        ok1, _ = self.registry.register_skill(s1)
        assert ok1 is True

        ok2, err2 = self.registry.register_skill(s1_dup)
        assert ok2 is False
        assert "Conflicto de versión" in str(err2)

    # ── 3. LOOKUP DETERMINISTA POR ID Y POR ID@VERSION ──

    def test_lookup_by_id_and_by_id_at_version(self) -> None:
        """Verifica que el lookup resuelva tanto por ID canónico como por ID@version explícito."""
        s_v1 = MockMultiVersionSkill(skill_id="documents.summarize", version="1.0.0")
        s_v2 = MockMultiVersionSkill(skill_id="documents.summarize", version="1.2.0")

        self.registry.register_skill(s_v1)
        self.registry.register_skill(s_v2)

        # Lookup exacto por versión
        lookup_v1 = self.registry.lookup("documents.summarize@1.0.0")
        assert lookup_v1 is not None
        assert lookup_v1.definition.version == "1.0.0"

        lookup_v2 = self.registry.lookup("documents.summarize@1.2.0")
        assert lookup_v2 is not None
        assert lookup_v2.definition.version == "1.2.0"

        # Lookup canónico (debe resolver la versión activa más reciente)
        lookup_active = self.registry.lookup("documents.summarize")
        assert lookup_active is not None
        assert lookup_active.definition.version == "1.2.0"

    # ── 4. COEXISTENCIA DE MÚLTIPLES VERSIONES ──

    def test_multiple_versions_coexistence(self) -> None:
        """Verifica que múltiples versiones coexistan sin colisionar en el registro."""
        s1 = MockMultiVersionSkill(skill_id="windows.apps", version="1.0.0")
        s2 = MockMultiVersionSkill(skill_id="windows.apps", version="1.1.0")
        s3 = MockMultiVersionSkill(skill_id="windows.apps", version="2.0.0")

        self.registry.register_skill(s1)
        self.registry.register_skill(s2)
        self.registry.register_skill(s3)

        all_defs = self.registry.list_all_versions()
        assert len(all_defs) == 3
        # La lista canónica solo devuelve 1 (la versión activa)
        assert len(self.registry.list_skills()) == 1

    # ── 5. DISCOVERY MULTIDIMENSIONAL ──

    def test_multidimensional_discovery(self) -> None:
        """Verifica la búsqueda por capability, categoría, tool, agent y riesgo."""
        s_browser = MockMultiVersionSkill(
            skill_id="browser.youtube",
            version="1.0.0",
            capabilities=("browser_navigation", "content_read"),
            required_tools=("browser.open", "browser.read"),
            required_agents=("BrowserAgent",),
            risk_level=SecurityLevel.SAFE,
        )
        s_files = MockMultiVersionSkill(
            skill_id="files.organize",
            version="1.0.0",
            capabilities=("filesystem_write",),
            required_tools=("file.move",),
            required_agents=("FileAgent",),
            risk_level=SecurityLevel.WARNING,
        )

        self.registry.register_skill(s_browser)
        self.registry.register_skill(s_files)

        # 1. Por capability
        disc_cap = self.registry.discover(capability="browser_navigation")
        assert len(disc_cap) == 1
        assert disc_cap[0].skill_id == "browser.youtube"

        # 2. Por categoría
        disc_cat = self.registry.discover(category="files")
        assert len(disc_cat) == 1
        assert disc_cat[0].skill_id == "files.organize"

        # 3. Por tool
        disc_tool = self.registry.discover(tool="file.move")
        assert len(disc_tool) == 1
        assert disc_tool[0].skill_id == "files.organize"

        # 4. Por agent
        disc_agent = self.registry.discover(agent="BrowserAgent")
        assert len(disc_agent) == 1
        assert disc_agent[0].skill_id == "browser.youtube"

        # 5. Por riesgo
        disc_risk = self.registry.discover(risk_level=SecurityLevel.WARNING)
        assert len(disc_risk) == 1
        assert disc_risk[0].skill_id == "files.organize"

    # ── 6. ENABLE / DISABLE ──

    def test_enable_and_disable_skill(self) -> None:
        """Verifica las transiciones de estado ENABLED / DISABLED."""
        skill = MockMultiVersionSkill(skill_id="system.diagnostics", version="1.0.0")
        self.registry.register_skill(skill)
        assert self.registry.get_status("system.diagnostics") in (SkillStatus.READY, SkillStatus.ENABLED)

        # Deshabilitar
        dis_ok = self.registry.disable_skill("system.diagnostics")
        assert dis_ok is True
        assert self.registry.get_status("system.diagnostics") == SkillStatus.DISABLED

        # Discovery con only_enabled=True no debe encontrarla
        assert len(self.registry.discover(id="system.diagnostics", only_enabled=True)) == 0

        # Habilitar
        en_ok = self.registry.enable_skill("system.diagnostics")
        assert en_ok is True
        assert self.registry.get_status("system.diagnostics") == SkillStatus.ENABLED
        assert len(self.registry.discover(id="system.diagnostics", only_enabled=True)) == 1

    # ── 7. UNREGISTER POR VERSIÓN O GLOBAL ──

    def test_unregister_specific_version_and_global(self) -> None:
        """Verifica desregistro específico por versión y global."""
        s1 = MockMultiVersionSkill(skill_id="browser.search", version="1.0.0")
        s2 = MockMultiVersionSkill(skill_id="browser.search", version="1.1.0")

        self.registry.register_skill(s1)
        self.registry.register_skill(s2)

        # Desregistrar solo v1.0.0
        unreg_v1 = self.registry.unregister_skill("browser.search@1.0.0")
        assert unreg_v1 is True
        assert self.registry.lookup("browser.search@1.0.0") is None
        assert self.registry.lookup("browser.search@1.1.0") is not None

        # Desregistrar globalmente browser.search
        unreg_all = self.registry.unregister_skill("browser.search")
        assert unreg_all is True
        assert self.registry.lookup("browser.search") is None

    # ── 8. SKILL INVÁLIDA RECHAZADA ──

    def test_invalid_skill_rejected_and_marked_invalid(self) -> None:
        """Verifica que una skill con esquema o permisos inválidos sea rechazada y no quede activa."""
        class DummyInvalidSkill(BaseSkill):
            def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
                return {"exito": False}

        bad_def = SkillDefinition(
            skill_id="invalid.skill",
            name="Invalid Skill",
            version="not_a_semver",  # SemVer inválido
        )
        bad_skill = DummyInvalidSkill(nombre="invalid.skill", definition=bad_def)

        ok, err = self.registry.register_skill(bad_skill)
        assert ok is False
        assert "SemVer" in str(err)
        assert self.registry.get_status("invalid.skill@not_a_semver") == SkillStatus.INVALID
        assert self.registry.lookup("invalid.skill") is None
