"""Tests unitarios exhaustivos para Colaboración Multi-Agente (Fase 9: Multi-Agent Collaboration)."""

from core.agents import (
    AgentCoordinator,
    DelegationPolicy,
    DesktopAgent,
    FileAgent,
    SystemAgent,
    TaskGraph,
    TaskNode,
)
from core.autonomy.autonomy_governor import get_autonomy_governor
from core.control_plane.models import AgentBudget, AgentLoopState
from core.emergency_stop import EmergencyStopManager


class TestMultiAgentCollaboration:
    """Pruebas de delegación autorizada, prevención de ciclos, DAGs y seguridad multi-agente."""

    def setup_method(self) -> None:
        self.governor = get_autonomy_governor()
        self.governor.reset_to_default()
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset()

        self.desktop_agent = DesktopAgent(emergency_stop=self.emergency_stop)
        self.system_agent = SystemAgent(emergency_stop=self.emergency_stop)
        self.file_agent = FileAgent(emergency_stop=self.emergency_stop)

        self.coordinator = AgentCoordinator(
            desktop_agent=self.desktop_agent,
            system_agent=self.system_agent,
            file_agent=self.file_agent,
            emergency_stop=self.emergency_stop,
        )

    # ── 1. DELEGACIÓN VÁLIDA ──

    def test_valid_delegation_system_to_desktop(self) -> None:
        """Verifica una delegación autorizada: SystemAgent -> DesktopAgent (visual_verification)."""
        verdict = DelegationPolicy.validate_delegation(
            sender_agent_id="agent_system",
            recipient_agent_id="agent_desktop",
            scope="visual_verification",
        )
        assert verdict.is_allowed is True
        assert verdict.authorized_scope == "visual_verification"

        # Ejecutar delegación a través del coordinador con intent visual
        result = self.coordinator.execute_delegation(
            sender=self.system_agent,
            target_agent_id="agent_desktop",
            intent="Capturar screenshot de la ventana activa",
            scope="visual_verification",
        )
        assert result.final_state == AgentLoopState.COMPLETED
        assert result.is_success is True

    # ── 2. DELEGACIÓN INVÁLIDA (NO AUTORIZADA) ──

    def test_invalid_delegation_denied(self) -> None:
        """Verifica que delegaciones no autorizadas en la matriz sean rechazadas deterministamente."""
        # FileAgent NO tiene autorización para delegar hacia SystemAgent
        verdict = DelegationPolicy.validate_delegation(
            sender_agent_id="agent_file",
            recipient_agent_id="agent_system",
            scope="diagnostics",
        )
        assert verdict.is_allowed is False
        assert "no tiene permiso" in verdict.reason.lower()

        # Intentar ejecutar con el coordinador
        result = self.coordinator.execute_delegation(
            sender=self.file_agent,
            target_agent_id="agent_system",
            intent="Consultar CPU",
            scope="diagnostics",
        )
        assert result.final_state == AgentLoopState.STOPPED_PERMISSION_DENIED
        assert "no tiene permiso" in result.stop_reason.lower()

    # ── 3. PREVENCIÓN DE CICLOS Y RECURSIÓN ──

    def test_cycle_and_recursion_detection(self) -> None:
        """Verifica que una cadena que intente re-delegar al emisor (A -> B -> A) sea bloqueada."""
        # Cadena previa: agent_system -> agent_desktop
        # Intento de re-delegar de nuevo hacia agent_system
        verdict = DelegationPolicy.validate_delegation(
            sender_agent_id="agent_desktop",
            recipient_agent_id="agent_system",
            scope="diagnostics",
            delegation_chain=("agent_system",),
        )
        assert verdict.is_allowed is False
        assert "ciclo" in verdict.reason.lower() or "no tiene permiso" in verdict.reason.lower()

    def test_max_delegation_depth_limit(self) -> None:
        """Verifica que superar la profundidad máxima de delegación (MAX_DELEGATION_DEPTH=2) sea bloqueado."""
        # Cadena de profundidad 2: agent_system -> agent_desktop
        verdict = DelegationPolicy.validate_delegation(
            sender_agent_id="agent_desktop",
            recipient_agent_id="agent_file",
            scope="save_screenshot",
            delegation_chain=("agent_external", "agent_system"),
        )
        assert verdict.is_allowed is False
        assert "profundidad máxima" in verdict.reason.lower()

    # ── 4. TASK GRAPH DAG & EJECUCIÓN COLABORATIVA ──

    def test_task_graph_cycle_detection(self) -> None:
        """Verifica que TaskGraph detecte ciclos de dependencias antes de ejecutar."""
        graph = TaskGraph()
        n1 = TaskNode(node_id="node_1", agent_id="agent_system", intent="Diagnóstico")
        n2 = TaskNode(node_id="node_2", agent_id="agent_desktop", intent="Verificación")

        graph.add_node(n1)
        graph.add_node(n2)
        graph.add_dependency("node_2", "node_1")  # n2 depende de n1
        graph.add_dependency("node_1", "node_2")  # ciclo: n1 depende de n2

        assert graph.detect_cycles() is True

        exec_report = self.coordinator.execute_task_graph(graph)
        assert exec_report["success"] is False
        assert "ciclo" in exec_report["error"].lower()

    def test_task_graph_collaborative_workflow_success(self) -> None:
        """Verifica el flujo colaborativo completo: SystemAgent -> DesktopAgent -> FileAgent."""
        graph = TaskGraph()

        node_sys = TaskNode(
            node_id="step_sys",
            agent_id="agent_system",
            intent="Consultar métricas del sistema",
        )
        node_desk = TaskNode(
            node_id="step_desk",
            agent_id="agent_desktop",
            intent="Capturar screenshot de la ventana",
            dependencies=["step_sys"],
        )
        node_file = TaskNode(
            node_id="step_file",
            agent_id="agent_file",
            intent="Escribir archivo en sandbox/reporte.txt",
            dependencies=["step_desk"],
        )

        graph.add_node(node_sys)
        graph.add_node(node_desk)
        graph.add_node(node_file)
        graph.add_dependency("step_desk", "step_sys")
        graph.add_dependency("step_file", "step_desk")

        assert graph.detect_cycles() is False

        exec_report = self.coordinator.execute_task_graph(graph)
        assert exec_report["success"] is True
        assert exec_report["executed_nodes"] == 3
        assert exec_report["nodes_results"]["step_sys"]["status"] == "COMPLETED"
        assert exec_report["nodes_results"]["step_desk"]["status"] == "COMPLETED"
        assert exec_report["nodes_results"]["step_file"]["status"] == "COMPLETED"

    def test_task_graph_global_timeout(self) -> None:
        """Verifica que el timeout global en TaskGraph detenga la ejecución del grafo."""
        graph = TaskGraph()
        n1 = TaskNode(node_id="n1", agent_id="agent_system", intent="Tarea 1")
        n2 = TaskNode(node_id="n2", agent_id="agent_desktop", intent="Tarea 2", dependencies=["n1"])
        graph.add_node(n1)
        graph.add_node(n2)
        graph.add_dependency("n2", "n1")

        # Configurar timeout global minúsculo (0.001s)
        budget = AgentBudget.create(max_time=0.001)
        report = self.coordinator.execute_task_graph(graph, global_budget=budget)

        assert report["success"] is False
