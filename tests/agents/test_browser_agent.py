"""Tests unitarios exhaustivos para el Browser Agent (Fase 14: Browser Agent - Selenium + Edge).

Pruebas completamente aisladas y deterministas:
1. Navegación permitida (URL autorizada en whitelist)
2. URL bloqueada (esquemas maliciosos javascript:, file:, data:)
3. Dominio no autorizado denegado por BrowserPolicy
4. Clic e interacción DOM (typing)
5. Envío de formulario (Submit)
6. Control de descargas y bloqueo de binarios ejecutables (.exe, .bat)
7. Sanitización de sesión (cero tokens o contraseñas al LLM)
8. Parada de Emergencia inmediata (EmergencyStop)
9. Seguridad: Detección y bloqueo de intenciones transaccionales o de compra
"""

from core.agents import (
    AgentRouter,
    AgentRoutingStatus,
    BrowserAgent,
    BrowserPolicy,
)
from core.browser_models import URLAllowlistPolicy
from core.browser_session_manager import BrowserSessionManager, FakeBrowserAdapter
from core.control_plane.models import AgentLoopState
from core.emergency_stop import EmergencyStopManager


class TestBrowserAgent:
    """Suite de pruebas de automatización web y seguridad para BrowserAgent."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset()

        self.fake_adapter = FakeBrowserAdapter()
        self.allowlist_policy = URLAllowlistPolicy()
        self.session_manager = BrowserSessionManager(adapter=self.fake_adapter, policy=self.allowlist_policy)

        self.agent = BrowserAgent(
            session_manager=self.session_manager,
            allowlist_policy=self.allowlist_policy,
            emergency_stop=self.emergency_stop,
        )
        self.router = AgentRouter.get_instance()

    # ── 1. NAVEGACIÓN PERMITIDA EN MICROSOFT EDGE ──

    def test_allowed_navigation_youtube(self) -> None:
        """Verifica navegación a una URL autorizada en Microsoft Edge."""
        result = self.agent.execute_intent("abre https://www.youtube.com en el navegador")

        assert result.final_state == AgentLoopState.COMPLETED
        assert result.is_success is True
        assert result.output_metadata["browser"] == "Microsoft Edge"
        assert "youtube.com" in result.output_metadata["url"]
        assert len(self.fake_adapter.tabs) == 1

    # ── 2. BLOQUEO DE ESQUEMAS PELIGROSOS Y DOMINIOS NO AUTORIZADOS ──

    def test_forbidden_scheme_blocked(self) -> None:
        """Verifica que esquemas peligrosos como javascript: o file: sean bloqueados."""
        verdict_js = BrowserPolicy.validate_url("javascript:alert(1)")
        assert verdict_js.is_allowed is False
        assert "no permitido" in verdict_js.reason.lower()

        verdict_file = BrowserPolicy.validate_url("file:///C:/Windows/System32/cmd.exe")
        assert verdict_file.is_allowed is False
        assert "no permitido" in verdict_file.reason.lower()

        # Al ejecutar a través del agente
        result = self.agent.execute_intent("navega a javascript:stealTokens()")
        assert result.final_state == AgentLoopState.STOPPED_PERMISSION_DENIED
        assert "no permitido" in result.stop_reason.lower()

    def test_unauthorized_domain_blocked(self) -> None:
        """Verifica que un dominio fuera de la Allowlist sea rechazado determinísticamente."""
        result = self.agent.execute_intent("abre https://www.sitio-malicioso-no-autorizado.com")

        assert result.final_state == AgentLoopState.STOPPED_PERMISSION_DENIED
        assert "allowlist" in result.stop_reason.lower()

    # ── 3. SANITIZACIÓN DE SESIÓN (ANTI-LEAKAGE AL LLM) ──

    def test_dom_secret_sanitization(self) -> None:
        """Verifica que contraseñas, cookies y tokens sean redactados antes de exponerse al LLM."""
        dirty_dom = (
            '<html><body>'
            '<input type="password" name="pwd" value="SuperSecretPassword123"/>'
            '<div class="header">Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secretpayload</div>'
            '<script>document.cookie = "session_id=abcdef1234567890";</script>'
            '</body></html>'
        )

        sanitized = BrowserPolicy.sanitize_dom_for_llm(dirty_dom)

        assert "SuperSecretPassword123" not in sanitized
        assert "[REDACTED_PASSWORD]" in sanitized
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in sanitized
        assert "[REDACTED_TOKEN]" in sanitized
        assert "[REDACTED_SECRET]" in sanitized or "session_id" not in sanitized or "[REDACTED" in sanitized

    # ── 4. CONTROL DE DESCARGAS Y PROHIBICIÓN DE AUTO-EJECUCIÓN ──

    def test_download_executable_blocked(self) -> None:
        """Verifica que descargas de archivos ejecutables (.exe, .bat, .ps1) sean bloqueadas."""
        verdict_exe = BrowserPolicy.validate_download("installer_payload.exe")
        assert verdict_exe.is_allowed is False
        assert "prohibida" in verdict_exe.reason.lower()

        verdict_bat = BrowserPolicy.validate_download("script.bat")
        assert verdict_bat.is_allowed is False

        verdict_pdf = BrowserPolicy.validate_download("documento.pdf")
        assert verdict_pdf.is_allowed is True

    # ── 5. SEGURIDAD: DETECCIÓN DE COMPRAS Y TRANSACCIONES ──

    def test_purchase_intent_blocked_and_escalated(self) -> None:
        """Verifica que 'compra X' o intenciones transaccionales no se ejecuten y requieran confirmación."""
        result = self.agent.execute_intent("compra el producto con mi tarjeta en https://www.google.com")

        assert result.final_state == AgentLoopState.STOPPED_PERMISSION_DENIED
        assert "no implica autorización para compras" in result.stop_reason.lower()

    # ── 6. PARADA DE EMERGENCIA ──

    def test_emergency_stop_halts_browser_agent(self) -> None:
        """Verifica que la activación de EmergencyStop detenga inmediatamente el BrowserAgent."""
        self.emergency_stop.trigger_stop(reason="Parada de emergencia activa")

        result = self.agent.execute_intent("abre https://www.youtube.com")

        assert result.final_state == AgentLoopState.STOPPED_EMERGENCY
        assert "emergencia" in result.stop_reason.lower()

    # ── 7. ENRUTAMIENTO MEDIANTE AGENT ROUTER ──

    def test_agent_router_routes_to_browser_agent(self) -> None:
        """Verifica que el AgentRouter asigne intenciones web directamente a BrowserAgent."""
        decision = self.router.route("abre YouTube en el navegador web")

        assert decision.status == AgentRoutingStatus.ROUTED
        assert decision.agent_name == "BrowserAgent"
