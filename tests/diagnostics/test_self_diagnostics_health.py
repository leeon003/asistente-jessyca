"""Suite de pruebas exhaustivas para el Sistema de Autodiagnóstico y Salud (Fase 29).

Simula y valida:
1. Ollama caído / down
2. Modelo ausente / missing model
3. GPU no disponible / CPU fallback
4. VRAM insuficiente / threshold exceeded
5. Browser no disponible
6. MCP caído / tools unavailable
7. Memoria inaccesible / DB locked
8. Plugin / Skill defectuoso
9. Informe integral HealthReport (14 componentes)
10. Invariante de seguridad: El diagnóstico solo observa y no altera configuraciones.
"""

from core.diagnostics import (
    ComponentStatus,
    ComponentUnavailableError,
    HealthCheck,
    HealthMonitor,
    HealthReport,
    HealthStatus,
    probe_browser_health,
    probe_gpu_health,
    probe_mcp_health,
    probe_memory_health,
    probe_models_health,
    probe_ollama_health,
    probe_plugins_health,
    probe_security_health,
    probe_vram_health,
)
from core.emergency_stop import EmergencyStopManager


class TestSelfDiagnosticsHealth:
    """Suite integral para el subsistema de diagnóstico y salud de JESSYCA 3.0."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_diagnostics_setup")
        self.monitor = HealthMonitor.get_instance()
        self.monitor.reset_failures()

    # ══════════════════════════════════════════════════════════════════
    # 1. SIMULACIÓN: OLLAMA CAÍDO
    # ══════════════════════════════════════════════════════════════════

    def test_probe_ollama_down_simulation(self) -> None:
        """Verifica que si Ollama está caído devuelva UNAVAILABLE con mensaje claro."""
        def mock_ollama_down() -> HealthStatus:
            return HealthStatus.UNAVAILABLE

        check = probe_ollama_health(custom_checker=mock_ollama_down)
        assert check.status == HealthStatus.UNAVAILABLE
        assert check.component == "ollama"
        assert check.is_available is False

    # ══════════════════════════════════════════════════════════════════
    # 2. SIMULACIÓN: MODELO AUSENTE
    # ══════════════════════════════════════════════════════════════════

    def test_probe_missing_model_simulation(self) -> None:
        """Verifica que la ausencia de modelos requeridos degrade o inhabilite el estado."""
        def mock_models_partial() -> HealthStatus:
            return HealthStatus.DEGRADED

        check = probe_models_health(custom_checker=mock_models_partial)
        assert check.status == HealthStatus.DEGRADED
        assert check.component == "models"

    # ══════════════════════════════════════════════════════════════════
    # 3. SIMULACIÓN: GPU NO DISPONIBLE
    # ══════════════════════════════════════════════════════════════════

    def test_probe_gpu_unavailable_cpu_fallback(self) -> None:
        """Verifica que sin GPU CUDA el sistema opere en estado DEGRADED / CPU fallback."""
        def mock_no_cuda() -> HealthStatus:
            return HealthStatus.DEGRADED

        check = probe_gpu_health(custom_checker=mock_no_cuda)
        assert check.status == HealthStatus.DEGRADED
        assert check.component == "gpu"

    # ══════════════════════════════════════════════════════════════════
    # 4. SIMULACIÓN: VRAM INSUFICIENTE
    # ══════════════════════════════════════════════════════════════════

    def test_probe_vram_insufficient_simulation(self) -> None:
        """Verifica que ante VRAM insuficiente el probe marque UNAVAILABLE o DEGRADED."""
        def mock_low_vram() -> HealthStatus:
            return HealthStatus.UNAVAILABLE

        check = probe_vram_health(custom_checker=mock_low_vram)
        assert check.status == HealthStatus.UNAVAILABLE
        assert check.component == "vram"

    # ══════════════════════════════════════════════════════════════════
    # 5. SIMULACIÓN: BROWSER NO DISPONIBLE
    # ══════════════════════════════════════════════════════════════════

    def test_probe_browser_unavailable_simulation(self) -> None:
        """Verifica la detección de navegador no disponible."""
        def mock_no_browser() -> HealthStatus:
            return HealthStatus.UNAVAILABLE

        check = probe_browser_health(custom_checker=mock_no_browser)
        assert check.status == HealthStatus.UNAVAILABLE
        assert check.component == "browser"

    # ══════════════════════════════════════════════════════════════════
    # 6. SIMULACIÓN: MCP CAÍDO
    # ══════════════════════════════════════════════════════════════════

    def test_probe_mcp_down_simulation(self) -> None:
        """Verifica la detección de fallo en el servidor MCP."""
        def mock_mcp_error() -> HealthStatus:
            return HealthStatus.ERROR

        check = probe_mcp_health(custom_checker=mock_mcp_error)
        assert check.status == HealthStatus.ERROR
        assert check.component == "mcp"

    # ══════════════════════════════════════════════════════════════════
    # 7. SIMULACIÓN: MEMORIA INACCESIBLE
    # ══════════════════════════════════════════════════════════════════

    def test_probe_memory_inaccessible_simulation(self) -> None:
        """Verifica la detección de error en el almacenamiento de memoria SQLite."""
        def mock_memory_locked() -> None:
            raise RuntimeError("Database is locked")

        check = probe_memory_health(custom_checker=mock_memory_locked)
        assert check.status == HealthStatus.ERROR
        assert check.component == "memory"
        assert "Database is locked" in str(check.details)

    # ══════════════════════════════════════════════════════════════════
    # 8. SIMULACIÓN: PLUGIN DEFECTUOSO
    # ══════════════════════════════════════════════════════════════════

    def test_probe_broken_plugin_simulation(self) -> None:
        """Verifica que un fallo en plugins/skills sea reportado como ERROR."""
        def mock_plugin_crash() -> None:
            raise ValueError("Corrupted plugin manifest")

        check = probe_plugins_health(custom_checker=mock_plugin_crash)
        assert check.status == HealthStatus.ERROR
        assert check.component == "plugins"

    # ══════════════════════════════════════════════════════════════════
    # 9. INFORME INTEGRAL (HEALTH REPORT CON 14 COMPONENTES)
    # ══════════════════════════════════════════════════════════════════

    def test_full_health_report_generation(self) -> None:
        """Verifica que el informe integral contenga los 14 componentes requeridos."""
        report: HealthReport = self.monitor.run_all_checks()

        expected_components = {
            "system",
            "gpu",
            "vram",
            "ollama",
            "models",
            "model_manager",
            "memory",
            "browser",
            "desktop",
            "voice",
            "scheduler",
            "mcp",
            "security",
            "plugins",
        }

        # Comprobar que todos los 14 componentes están presentes
        for comp in expected_components:
            assert comp in report.checks, f"Componente '{comp}' faltante en HealthReport."
            status: ComponentStatus = report.get_component_status(comp)
            assert status in (
                HealthStatus.HEALTHY,
                HealthStatus.DEGRADED,
                HealthStatus.UNAVAILABLE,
                HealthStatus.ERROR,
            )

        assert report.overall_status in (
            HealthStatus.HEALTHY,
            HealthStatus.DEGRADED,
            HealthStatus.UNAVAILABLE,
            HealthStatus.ERROR,
        )
        assert "Overall Status" in report.to_summary()

    # ══════════════════════════════════════════════════════════════════
    # 10. ASSERT AVAILABLE Y MANEJO DE EXCEPCIONES
    # ══════════════════════════════════════════════════════════════════

    def test_assert_available_raises_on_unavailable_component(self) -> None:
        """Verifica que assert_available lance ComponentUnavailableError sin bucles."""
        self.monitor.register_probe(
            "browser",
            lambda: HealthCheck(
                name="browser",
                component="browser",
                status=HealthStatus.UNAVAILABLE,
                message="Browser control unavailable",
            ),
        )

        try:
            self.monitor.assert_available("browser")
            raise AssertionError("Debió lanzar ComponentUnavailableError")
        except ComponentUnavailableError as exc:
            assert "Browser control unavailable" in str(exc)

    # ══════════════════════════════════════════════════════════════════
    # 11. INVARIANTE DE SEGURIDAD (SOLO OBSERVACIÓN)
    # ══════════════════════════════════════════════════════════════════

    def test_diagnostics_does_not_modify_security_state(self) -> None:
        """Verifica que ejecutar diagnósticos no altere el estado de EmergencyStop ni políticas."""
        assert self.emergency_stop.is_stopped() is False

        # Ejecutar sondeo de seguridad y reporte completo
        _check = probe_security_health()
        _report = self.monitor.run_all_checks()

        # El estado de parada de emergencia no debe haber cambiado
        assert self.emergency_stop.is_stopped() is False
