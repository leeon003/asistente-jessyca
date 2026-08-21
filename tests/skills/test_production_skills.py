"""Suite de pruebas unitarias y End-to-End para las Production Skills (Fase 28.7).

Pruebas exhaustivas para las 4 primeras Skills reales de JESSYCA:
1. windows.apps (Apertura, inspección y cierre de aplicaciones)
2. windows.screenshot (Captura de pantalla y análisis con pipeline de visión qwen3-vl)
3. files.search (Búsqueda de archivos respetando sandbox y rutas críticas)
4. browser.search (Búsquedas web y extracción de resultados en Microsoft Edge)
"""

from core.cancellation import CancellationToken
from core.emergency_stop import EmergencyStopManager
from core.security_architecture import SecurityLevel
from skills import (
    BrowserSearchSkill,
    FilesSearchSkill,
    SkillManager,
    SkillRegistry,
    SkillResult,
    SkillRouter,
    SkillRuntime,
    SkillSecuritySandbox,
    SkillStatus,
    SkillValidator,
    WindowsAppsSkill,
    WindowsScreenshotSkill,
)


class TestProductionSkills:
    """Suite integral para validar las primeras Production Skills de JESSYCA."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_production_skills_setup")
        self.registry = SkillRegistry()
        self.registry.reset()
        self.router = SkillRouter(registry=self.registry)
        self.runtime = SkillRuntime(emergency_stop=self.emergency_stop)
        self.manager = SkillManager(
            registry=self.registry,
            router=self.router,
            runtime=self.runtime,
        )
        self.sandbox = SkillSecuritySandbox(emergency_stop=self.emergency_stop)

        # Instanciar las 4 Production Skills
        self.skill_apps = WindowsAppsSkill()
        self.skill_screenshot = WindowsScreenshotSkill()
        self.skill_files = FilesSearchSkill()
        self.skill_browser = BrowserSearchSkill()

        # Registrar en catálogo
        self.manager.load_skill(self.skill_apps)
        self.manager.load_skill(self.skill_screenshot)
        self.manager.load_skill(self.skill_files)
        self.manager.load_skill(self.skill_browser)

    # ══════════════════════════════════════════════════════════════════
    # 1. MANIFEST & DECLARACIONES
    # ══════════════════════════════════════════════════════════════════

    def test_production_skills_manifests_are_valid(self) -> None:
        """Verifica que todos los manifiestos de las Production Skills sean válidos y conformes."""
        for sk in (self.skill_apps, self.skill_screenshot, self.skill_files, self.skill_browser):
            manifest = sk.definition.manifest
            assert manifest is not None
            is_valid, err = SkillValidator.validate_manifest(manifest)
            assert is_valid is True, f"Manifiesto inválido en '{sk.skill_id}': {err}"
            assert sk.definition.risk_level == SecurityLevel.SAFE
            assert len(sk.definition.capabilities) >= 1
            assert len(sk.definition.required_tools) >= 1

    # ══════════════════════════════════════════════════════════════════
    # 2. REGISTRY & DISCOVERY
    # ══════════════════════════════════════════════════════════════════

    def test_production_skills_registered_and_ready(self) -> None:
        """Verifica que las 4 skills estén registradas en el catálogo y en estado READY/ENABLED."""
        for sk_id in ("windows.apps", "windows.screenshot", "files.search", "browser.search"):
            assert self.registry.lookup(sk_id) is not None
            assert self.manager.get_skill_status(sk_id) in (SkillStatus.READY, SkillStatus.ENABLED)

    # ══════════════════════════════════════════════════════════════════
    # 3. END-TO-END INTENT ROUTING
    # ══════════════════════════════════════════════════════════════════

    def test_e2e_intent_routing_production_commands(self) -> None:
        """Verifica el enrutamiento end-to-end de los 4 comandos coloquiales solicitados."""
        # 1. "Abre Bloc de notas." -> windows.apps
        dec1 = self.router.resolve_routing("Abre Bloc de notas.")
        assert dec1.skill is not None
        assert dec1.skill.skill_id == "windows.apps"
        assert dec1.confidence >= 0.50

        # 2. "Mira mi pantalla." -> windows.screenshot
        dec2 = self.router.resolve_routing("Mira mi pantalla.")
        assert dec2.skill is not None
        assert dec2.skill.skill_id == "windows.screenshot"
        assert dec2.confidence >= 0.50

        # 3. "Busca un archivo llamado informe." -> files.search
        dec3 = self.router.resolve_routing("Busca un archivo llamado informe.")
        assert dec3.skill is not None
        assert dec3.skill.skill_id == "files.search"
        assert dec3.confidence >= 0.50

        # 4. "Busca información en Internet sobre inteligencia artificial." -> browser.search
        dec4 = self.router.resolve_routing("Busca información en Internet sobre inteligencia artificial.")
        assert dec4.skill is not None
        assert dec4.skill.skill_id == "browser.search"
        assert dec4.confidence >= 0.50

    # ══════════════════════════════════════════════════════════════════
    # 4. EJECUCIÓN NOMINAL GOBERNADA
    # ══════════════════════════════════════════════════════════════════

    def test_execute_windows_apps_skill(self) -> None:
        """Verifica la ejecución de windows.apps para inspección o lanzamiento."""
        res: SkillResult = self.manager.execute_skill(
            "windows.apps",
            parameters={"accion": "inspeccionar", "nombre_app": "notepad"},
        )
        assert res.success is True
        assert res.status == SkillStatus.COMPLETED
        assert "instancia(s)" in res.output["mensaje"]

    def test_execute_windows_screenshot_skill(self) -> None:
        """Verifica la ejecución de windows.screenshot con análisis estructurado de visión."""
        res: SkillResult = self.manager.execute_skill(
            "windows.screenshot",
            parameters={"prompt": "Describe la ventana principal visible"},
        )
        assert res.success is True
        assert res.status == SkillStatus.COMPLETED
        assert "analisis" in res.output
        assert res.output["modelo_vision"] == "qwen3-vl:4b"

    def test_execute_files_search_skill(self) -> None:
        """Verifica la ejecución segura de files.search buscando en el workspace."""
        res: SkillResult = self.manager.execute_skill(
            "files.search",
            parameters={"nombre": "pyproject", "ruta": "."},
        )
        assert res.success is True
        assert res.status == SkillStatus.COMPLETED
        assert res.output["total"] >= 1
        assert any("pyproject.toml" in match["nombre"] for match in res.output["coincidencias"])

    def test_execute_browser_search_skill(self) -> None:
        """Verifica la ejecución de browser.search generando consulta estructurada en Microsoft Edge."""
        res: SkillResult = self.manager.execute_skill(
            "browser.search",
            parameters={"query": "NVIDIA RTX 5090", "motor": "bing"},
        )
        assert res.success is True
        assert res.status == SkillStatus.COMPLETED
        assert "bing.com" in res.output["url"]
        assert res.output["navegador"] == "Microsoft Edge"
        assert len(res.output["resultados_extraidos"]) >= 1

    # ══════════════════════════════════════════════════════════════════
    # 5. SEGURIDAD Y BLOQUEO DE SANDBOX
    # ══════════════════════════════════════════════════════════════════

    def test_files_search_blocks_critical_windows_paths(self) -> None:
        """Verifica que files.search rechace búsquedas en rutas críticas de Windows."""
        res: SkillResult = self.manager.execute_skill(
            "files.search",
            parameters={"nombre": "passwords.txt", "ruta": "C:\\Windows\\System32"},
        )
        assert res.success is False
        assert res.security_decision == "DENY" or (res.output and "Acceso denegado" in str(res.output))

    def test_production_skills_sandbox_unauthorized_tool_block(self) -> None:
        """Verifica que ninguna Production Skill pueda invocar herramientas no declaradas."""
        for sk in (self.skill_apps, self.skill_screenshot, self.skill_files, self.skill_browser):
            sec_res = self.sandbox.invoke_tool(
                skill=sk,
                tool_name="unauthorized.shell_exec",
                parameters={"cmd": "whoami"},
            )
            assert sec_res.decision == "DENY"
            assert sec_res.success is False

    # ══════════════════════════════════════════════════════════════════
    # 6. CONFIABILIDAD: ARGUMENTOS INVÁLIDOS, CANCELACIÓN Y PARADA
    # ══════════════════════════════════════════════════════════════════

    def test_production_skills_invalid_arguments(self) -> None:
        """Verifica el manejo elegante ante parámetros vacíos o inválidos."""
        # windows.apps sin nombre de app
        res1 = self.manager.execute_skill("windows.apps", parameters={})
        assert res1.success is False
        assert "Debe especificar" in res1.output["mensaje"]

        # files.search sin patrón
        res2 = self.manager.execute_skill("files.search", parameters={})
        assert res2.success is False
        assert "Debe especificar" in res2.output["mensaje"]

        # browser.search sin query
        res3 = self.manager.execute_skill("browser.search", parameters={})
        assert res3.success is False
        assert "Debe especificar" in res3.output["mensaje"]

    def test_production_skills_cancellation_token(self) -> None:
        """Verifica que un token de cancelación aborte la ejecución de una Production Skill."""
        token = CancellationToken()
        token.cancel(reason="Cancelación de prueba")

        res = self.manager.execute_skill(
            "browser.search",
            parameters={"query": "OpenAI"},
            cancellation_token=token,
        )
        assert res.success is False
        assert res.status == SkillStatus.CANCELLED

    def test_production_skills_emergency_stop_halt(self) -> None:
        """Verifica que Emergency Stop bloquee de inmediato la ejecución de cualquier Production Skill."""
        self.emergency_stop.trigger_stop(reason="Emergency Test", source="qa_production_skills")

        res = self.manager.execute_skill(
            "windows.apps",
            parameters={"accion": "abrir", "nombre_app": "notepad"},
        )
        assert res.success is False
        assert res.status in (SkillStatus.CANCELLED, SkillStatus.FAILED)
        assert res.security_decision == "EMERGENCY_STOP"
