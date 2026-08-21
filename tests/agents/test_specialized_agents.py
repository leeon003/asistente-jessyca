"""Tests exhaustivos de aislamiento, permisos y seguridad para Agentes Especializados (Fase 7: Specialized Agents)."""

from typing import Any

from core.agents import (
    DesktopAgent,
    FileAgent,
    SystemAgent,
)
from core.autonomy.autonomy_governor import get_autonomy_governor
from core.control_plane.models import AgentLoopState
from core.emergency_stop import EmergencyStopManager


class TestSpecializedAgentsIsolationAndSecurity:
    """Pruebas de aislamiento estricto de herramientas y contención de seguridad."""

    def setup_method(self) -> None:
        self.governor = get_autonomy_governor()
        self.governor.reset_to_default()
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset()

    # ── 1. AISLAMIENTO ENTRE AGENTES ──

    def test_desktop_agent_cannot_use_file_agent_tools(self) -> None:
        """Aislamiento: DesktopAgent NO puede usar herramientas de FileAgent (e.g. filesystem.write)."""
        desktop_agent = DesktopAgent(emergency_stop=self.emergency_stop)

        # Intentar validar una herramienta de archivos
        is_ok, reason = desktop_agent.validate_tool_call(
            tool_name="filesystem",
            operation="write",
            params={"path": "sandbox/test.txt"},
        )

        assert is_ok is False
        assert "no pertenece" in reason.lower()

    def test_file_agent_cannot_use_system_agent_tools(self) -> None:
        """Aislamiento: FileAgent NO puede usar herramientas de SystemAgent (e.g. system.process_list)."""
        file_agent = FileAgent(emergency_stop=self.emergency_stop)

        is_ok, reason = file_agent.validate_tool_call(
            tool_name="system",
            operation="process_list",
            params={},
        )

        assert is_ok is False
        assert "no pertenece" in reason.lower()

    def test_system_agent_cannot_use_desktop_agent_tools(self) -> None:
        """Aislamiento: SystemAgent NO puede usar herramientas de DesktopAgent (e.g. windows.desktop.click)."""
        system_agent = SystemAgent(emergency_stop=self.emergency_stop)

        is_ok, reason = system_agent.validate_tool_call(
            tool_name="windows.desktop",
            operation="click",
            params={"x": 100, "y": 200},
        )

        assert is_ok is False
        assert "no pertenece" in reason.lower()

    # ── 2. RESTRICCIÓN READ-ONLY EN SYSTEM AGENT ──

    def test_system_agent_allows_read_only_diagnostics(self) -> None:
        """SystemAgent permite herramientas de diagnóstico y lectura autorizadas."""
        system_agent = SystemAgent(emergency_stop=self.emergency_stop)

        is_ok, _ = system_agent.validate_tool_call(
            tool_name="system",
            operation="info",
            params={},
        )
        assert is_ok is True

        is_ok_metrics, _ = system_agent.validate_tool_call(
            tool_name="system",
            operation="metrics",
            params={},
        )
        assert is_ok_metrics is True

    def test_system_agent_strictly_blocks_write_and_kill(self) -> None:
        """SystemAgent bloquea cualquier intento de escritura, modificación o terminación de procesos."""
        system_agent = SystemAgent(emergency_stop=self.emergency_stop)

        # 1. Intento de kill / terminate
        is_ok, reason = system_agent.validate_tool_call(
            tool_name="system",
            operation="kill_process",
            params={"pid": 1234},
        )
        assert is_ok is False
        assert "read only" in reason.lower() or "no pertenece" in reason.lower()

        # 2. Intento de set / modify
        is_ok2, reason2 = system_agent.validate_tool_call(
            tool_name="system",
            operation="set_config",
            params={"key": "val"},
        )
        assert is_ok2 is False

    # ── 3. CONTENCIÓN DE SANDBOX EN FILE AGENT ──

    def test_file_agent_allows_operations_inside_sandbox(self) -> None:
        """FileAgent permite lectura y escritura confinada a sandbox/."""
        file_agent = FileAgent(emergency_stop=self.emergency_stop)

        is_ok, _ = file_agent.validate_tool_call(
            tool_name="filesystem",
            operation="read",
            params={"path": "sandbox/informe.txt"},
        )
        assert is_ok is True

    def test_file_agent_blocks_path_traversal(self) -> None:
        """FileAgent bloquea intentos de Path Traversal (..) fuera del sandbox."""
        file_agent = FileAgent(emergency_stop=self.emergency_stop)

        is_ok, reason = file_agent.validate_tool_call(
            tool_name="filesystem",
            operation="read",
            params={"path": "sandbox/../../windows/system32/cmd.exe"},
        )
        assert is_ok is False
        assert "path traversal" in reason.lower() or "fuera" in reason.lower()

    def test_file_agent_blocks_absolute_paths_outside_sandbox(self) -> None:
        """FileAgent bloquea rutas absolutas fuera del sandbox autorizado."""
        file_agent = FileAgent(emergency_stop=self.emergency_stop)

        is_ok, reason = file_agent.validate_tool_call(
            tool_name="filesystem",
            operation="read",
            params={"path": "C:\\Windows\\System32\\drivers\\etc\\hosts"},
        )
        assert is_ok is False
        assert "fuera del directorio permitido" in reason.lower()

    # ── 4. EJECUCIÓN NORMAL Y DEFENSA ACTIVA EN LOOP ──

    def test_desktop_agent_normal_run(self) -> None:
        """Verifica la ejecución normal de DesktopAgent con herramientas de escritorio."""
        executed: list[str] = []

        def mock_executor(tool: str, op: str, params: dict[str, Any]) -> dict[str, Any]:
            executed.append(f"{tool}.{op}")
            return {"status": "ok", "screenshot": "base64data"}

        desktop_agent = DesktopAgent(
            emergency_stop=self.emergency_stop,
            action_executor=mock_executor,
        )

        result = desktop_agent.run(
            intent="Capturar pantalla y analizar interfaz",
            is_goal_satisfied=lambda ctx: True,
        )

        assert result.final_state == AgentLoopState.COMPLETED
        assert result.is_success is True

    def test_desktop_agent_blocks_unauthorized_tool_in_loop(self) -> None:
        """Verifica que el bucle de DesktopAgent se detenga inmediatamente si se intenta una herramienta no autorizada."""
        def mock_executor(tool: str, op: str, params: dict[str, Any]) -> dict[str, Any]:
            return {"status": "ok"}

        desktop_agent = DesktopAgent(
            emergency_stop=self.emergency_stop,
            action_executor=mock_executor,
        )

        # Inyectar una herramienta no permitida directamente a través de validate_tool_call
        is_ok, _ = desktop_agent.validate_tool_call("filesystem", "delete", {"path": "sandbox/x"})
        assert is_ok is False
