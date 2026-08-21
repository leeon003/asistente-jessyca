"""Tests unitarios exhaustivos para el AgentRouter (Fase 8: Agent Router)."""

from core.agents import (
    AgentRouter,
    AgentRoutingStatus,
    AgentType,
    DesktopAgent,
    FileAgent,
    SystemAgent,
    get_agent_router,
)


class TestAgentRouter:
    """Pruebas de selección determinista y políticas de fallback del AgentRouter."""

    def setup_method(self) -> None:
        self.router = AgentRouter()

    def test_route_to_desktop_agent(self) -> None:
        """Verifica que intenciones visuales y de interfaz enruten hacia DesktopAgent."""
        examples = [
            "mira mi pantalla",
            "haz una captura de pantalla y revisa la ventana activa",
            "haz click en el botón Guardar",
            "lee el texto con OCR en la pantalla",
            "escribe en el bloc de notas",
        ]
        for query in examples:
            decision = self.router.route(query)
            assert decision.status == AgentRoutingStatus.ROUTED, f"Fallo en: {query}"
            assert decision.agent_type == AgentType.DESKTOP
            assert decision.agent_name == "DesktopAgent"
            assert decision.confidence >= 0.7

    def test_route_to_system_agent(self) -> None:
        """Verifica que intenciones de telemetría y diagnóstico enruten hacia SystemAgent."""
        examples = [
            "revisa memoria RAM",
            "¿cuántos procesos hay activos en el sistema?",
            "dame las métricas de rendimiento y uso de CPU",
            "ejecuta un diagnóstico del estado del sistema",
        ]
        for query in examples:
            decision = self.router.route(query)
            assert decision.status == AgentRoutingStatus.ROUTED, f"Fallo en: {query}"
            assert decision.agent_type == AgentType.SYSTEM
            assert decision.agent_name == "SystemAgent"
            assert decision.confidence >= 0.7

    def test_route_to_file_agent(self) -> None:
        """Verifica que intenciones de manipulación de archivos enruten hacia FileAgent."""
        examples = [
            "crea un archivo de texto en el sandbox",
            "lee el archivo reporte.json",
            "guarda los datos en notas.txt",
            "busca archivos en el directorio",
        ]
        for query in examples:
            decision = self.router.route(query)
            assert decision.status == AgentRoutingStatus.ROUTED, f"Fallo en: {query}"
            assert decision.agent_type == AgentType.FILE
            assert decision.agent_name == "FileAgent"
            assert decision.confidence >= 0.7

    def test_route_ambiguous_or_empty_needs_clarification(self) -> None:
        """Verifica que entradas vacías o fuera de alcance retornen NEEDS_CLARIFICATION."""
        decision_empty = self.router.route("")
        assert decision_empty.status == AgentRoutingStatus.NEEDS_CLARIFICATION
        assert decision_empty.clarification_prompt is not None

        decision_unrelated = self.router.route("cocina una pizza napolitana con queso")
        assert decision_unrelated.status == AgentRoutingStatus.NEEDS_CLARIFICATION
        assert decision_unrelated.agent_type is None

    def test_get_agent_for_intent_resolution(self) -> None:
        """Verifica la resolución directa de instancia y decisión estructurada."""
        agent, decision = self.router.get_agent_for_intent("mira mi pantalla")
        assert isinstance(agent, DesktopAgent)
        assert decision.status == AgentRoutingStatus.ROUTED
        assert decision.agent_type == AgentType.DESKTOP

        agent_sys, decision_sys = self.router.get_agent_for_intent("revisa la memoria RAM")
        assert isinstance(agent_sys, SystemAgent)
        assert decision_sys.status == AgentRoutingStatus.ROUTED

        agent_file, decision_file = self.router.get_agent_for_intent("crea un archivo de log")
        assert isinstance(agent_file, FileAgent)
        assert decision_file.status == AgentRoutingStatus.ROUTED

        # Caso no resuelto
        agent_none, decision_none = self.router.get_agent_for_intent("haz algo desconocido")
        assert agent_none is None
        assert decision_none.status == AgentRoutingStatus.NEEDS_CLARIFICATION

    def test_singleton_accessor(self) -> None:
        """Verifica el helper global get_agent_router()."""
        r1 = get_agent_router()
        r2 = AgentRouter.get_instance()
        assert r1 is r2

    def test_security_rule_no_privilege_escalation(self) -> None:
        """Invariante: AgentRouter no modifica ni amplía los permisos de los agentes asignados."""
        agent, _ = self.router.get_agent_for_intent("revisa la memoria RAM")
        assert isinstance(agent, SystemAgent)

        # El SystemAgent retornado sigue siendo estrictamente READ ONLY
        is_ok, reason = agent.validate_tool_call("system", "kill_process", {"pid": 1234})
        assert is_ok is False
        assert "read only" in reason.lower() or "no pertenece" in reason.lower()
