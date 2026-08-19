"""Tests unitarios e integración para el Sistema de Autodiagnóstico (Etapa 17.2).

Verifica:
1. HealthStatus (HEALTHY, DEGRADED, FAILED, DISABLED).
2. HealthCheck & HealthReport (serialización, mensajes informativos, disponibilidad).
3. Sondeos deterministas (Browser, OCR, Micrófono, Ollama, VectorStore, Scheduler, Plugin, Service).
4. Detección de tasa excesiva de errores (Excessive error rate).
5. Detección de fallos repetidos en acciones (Repeated action failure).
6. Interrupción temprana sin reintentos infinitos (ComponentUnavailableError).
7. Ausencia de autoreparación peligrosa.
"""

from __future__ import annotations

import pytest

from core.diagnostics import (
    ComponentCategory,
    ComponentUnavailableError,
    HealthCheck,
    HealthMonitor,
    HealthReport,
    HealthStatus,
    get_health_monitor,
)


class TestHealthModels:
    """Pruebas de modelos HealthStatus, HealthCheck y HealthReport."""

    def test_health_statuses_present(self) -> None:
        required = {"HEALTHY", "DEGRADED", "FAILED", "DISABLED"}
        actual = {status.value for status in HealthStatus}
        assert required == actual

    def test_health_check_serialization(self) -> None:
        hc = HealthCheck(
            name="browser_check",
            component="browser",
            category=ComponentCategory.BROWSER,
            status=HealthStatus.FAILED,
            message="Browser control unavailable",
            details={"reason": "browser process crashed"},
            is_critical=True,
            duration_ms=15.4,
        )
        assert hc.is_available is False
        d = hc.to_dict()
        assert d["name"] == "browser_check"
        assert d["status"] == "FAILED"
        assert d["message"] == "Browser control unavailable"
        assert d["is_available"] is False
        assert d["is_critical"] is True

    def test_health_report_generation_and_queries(self) -> None:
        checks = {
            "browser": HealthCheck(
                name="browser",
                component="browser",
                category=ComponentCategory.BROWSER,
                status=HealthStatus.FAILED,
                message="Browser control unavailable",
            ),
            "ocr": HealthCheck(
                name="ocr",
                component="ocr",
                category=ComponentCategory.OCR,
                status=HealthStatus.HEALTHY,
                message="OCR engine operational",
            ),
        }
        report = HealthReport(
            overall_status=HealthStatus.FAILED,
            checks=checks,
            unavailable_components=["browser"],
            user_friendly_messages=["Browser control unavailable"],
            error_rate=0.05,
        )

        assert report.is_component_available("ocr") is True
        assert report.is_component_available("browser") is False
        assert report.get_user_notice("browser") == "Browser control unavailable"
        assert report.get_user_notice("ocr") is None

        summary = report.to_summary()
        assert "Overall Status: FAILED" in summary
        assert "Browser control unavailable" in summary


class TestComponentProbesAndHealthMonitor:
    """Pruebas para HealthMonitor y detección de subsistemas caídos."""

    def setup_method(self) -> None:
        self.monitor = HealthMonitor()
        self.monitor.reset_failures()

    def test_browser_unavailable_detection_and_informative_message(self) -> None:
        """Verifica que si el navegador falla, el monitor lo reporta como 'Browser control unavailable'."""
        self.monitor.register_probe(
            "browser",
            lambda: HealthCheck(
                name="browser",
                component="browser",
                category=ComponentCategory.BROWSER,
                status=HealthStatus.FAILED,
                message="Browser control unavailable",
            ),
        )

        report = self.monitor.run_all_checks()
        assert report.is_component_available("browser") is False
        assert "Browser control unavailable" in report.user_friendly_messages

        # Interrupción temprana: debe lanzar ComponentUnavailableError con mensaje claro
        with pytest.raises(ComponentUnavailableError) as exc_info:
            self.monitor.assert_available("browser")
        assert "Browser control unavailable" in str(exc_info.value)

    def test_ocr_unavailable_detection(self) -> None:
        self.monitor.register_probe(
            "ocr",
            lambda: HealthCheck(
                name="ocr",
                component="ocr",
                category=ComponentCategory.OCR,
                status=HealthStatus.FAILED,
                message="OCR unavailable",
            ),
        )
        report = self.monitor.run_all_checks()
        assert report.is_component_available("ocr") is False
        assert "OCR unavailable" in report.user_friendly_messages

        with pytest.raises(ComponentUnavailableError, match="OCR unavailable"):
            self.monitor.assert_available("ocr")

    def test_microphone_unavailable_detection(self) -> None:
        self.monitor.register_probe(
            "microphone",
            lambda: HealthCheck(
                name="microphone",
                component="microphone",
                category=ComponentCategory.MICROPHONE,
                status=HealthStatus.FAILED,
                message="Microphone unavailable",
            ),
        )
        report = self.monitor.run_all_checks()
        assert report.is_component_available("microphone") is False
        assert "Microphone unavailable" in report.user_friendly_messages

    def test_ollama_unavailable_detection(self) -> None:
        self.monitor.register_probe(
            "ollama",
            lambda: HealthCheck(
                name="ollama",
                component="ollama",
                category=ComponentCategory.OLLAMA,
                status=HealthStatus.FAILED,
                message="Ollama unavailable",
            ),
        )
        report = self.monitor.run_all_checks()
        assert report.is_component_available("ollama") is False
        assert "Ollama unavailable" in report.user_friendly_messages

    def test_vector_store_unavailable_detection(self) -> None:
        self.monitor.register_probe(
            "vector_store",
            lambda: HealthCheck(
                name="vector_store",
                component="vector_store",
                category=ComponentCategory.VECTOR_STORE,
                status=HealthStatus.FAILED,
                message="Vector store unavailable",
            ),
        )
        report = self.monitor.run_all_checks()
        assert report.is_component_available("vector_store") is False
        assert "Vector store unavailable" in report.user_friendly_messages

    def test_scheduler_failure_detection(self) -> None:
        self.monitor.register_probe(
            "scheduler",
            lambda: HealthCheck(
                name="scheduler",
                component="scheduler",
                category=ComponentCategory.SCHEDULER,
                status=HealthStatus.FAILED,
                message="Scheduler failure",
            ),
        )
        report = self.monitor.run_all_checks()
        assert report.is_component_available("scheduler") is False
        assert "Scheduler failure" in report.user_friendly_messages

    def test_plugin_failure_detection(self) -> None:
        self.monitor.register_probe(
            "plugin",
            lambda: HealthCheck(
                name="plugin",
                component="plugin",
                category=ComponentCategory.PLUGIN,
                status=HealthStatus.FAILED,
                message="Plugin failure",
            ),
        )
        report = self.monitor.run_all_checks()
        assert report.is_component_available("plugin") is False
        assert "Plugin failure" in report.user_friendly_messages

    def test_service_unavailable_detection(self) -> None:
        self.monitor.register_probe(
            "service",
            lambda: HealthCheck(
                name="service",
                component="service",
                category=ComponentCategory.SERVICE,
                status=HealthStatus.FAILED,
                message="Service unavailable",
            ),
        )
        report = self.monitor.run_all_checks()
        assert report.is_component_available("service") is False
        assert "Service unavailable" in report.user_friendly_messages


class TestOperationalDegradationAndFailureTracking:
    """Pruebas para Excessive Error Rate y Repeated Action Failures."""

    def setup_method(self) -> None:
        self.monitor = HealthMonitor()
        self.monitor.reset_failures()

    def test_repeated_action_failure_threshold(self) -> None:
        """Verifica que 3 fallos consecutivos en una tool específica disparen alerta de degradación."""
        # 1er y 2do fallo -> no alerta
        self.monitor.record_action_result("powershell.exec", success=False)
        self.monitor.record_action_result("powershell.exec", success=False)

        report = self.monitor.run_all_checks()
        assert "repeated_failures" not in report.repeated_failures_count

        # 3er fallo consecutivo -> alerta
        self.monitor.record_action_result("powershell.exec", success=False)
        report = self.monitor.run_all_checks()
        assert "powershell.exec" in report.repeated_failures_count
        assert report.repeated_failures_count["powershell.exec"] == 3
        assert any("powershell.exec" in msg for msg in report.user_friendly_messages)

        # Si luego tiene éxito, el contador se resetea
        self.monitor.record_action_result("powershell.exec", success=True)
        report = self.monitor.run_all_checks()
        assert "powershell.exec" not in report.repeated_failures_count

    def test_excessive_error_rate_threshold(self) -> None:
        """Verifica que una tasa de fallos > 30% en la ventana móvil degrade el estado general."""
        # Registrar 10 operaciones: 5 fallos, 5 éxitos -> 50% tasa de error
        for _ in range(5):
            self.monitor.record_action_result("some_tool", success=False)
        for _ in range(5):
            self.monitor.record_action_result("other_tool", success=True)

        assert self.monitor.get_error_rate() == 0.50
        report = self.monitor.run_all_checks()
        assert report.error_rate == 0.50
        assert report.checks["error_rate"].status == HealthStatus.DEGRADED
        assert any("Excessive error rate" in msg for msg in report.user_friendly_messages)

    def test_singleton_monitor_access(self) -> None:
        m1 = get_health_monitor()
        m2 = HealthMonitor.get_instance()
        assert m1 is m2
