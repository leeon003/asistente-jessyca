"""Tests unitarios e integrales para el Centro de Control y Observabilidad en Tiempo Real (Fase 24).

Verifica:
1. Transiciones y ciclo de vida de los 8 estados formales (SystemState)
2. Notificación reactiva a suscriptores en tiempo real
3. Concurrencia y seguridad de hilos (thread-safety)
4. Control STOP con integración a EmergencyStopManager
5. Controles PAUSE y RESUME con validación de condiciones de seguridad
6. Consulta de detalles (DETAILS) y telemetría estructurada
7. Registro de herramientas ejecutadas y eventos de seguridad
8. Invariante: CONTROL CENTER != TOOL EXECUTOR y aislamiento de políticas de seguridad
"""

import threading

from core.emergency_stop import EmergencyStopManager
from core.observability.control_center import ControlCenter
from core.observability.control_center_models import (
    ControlCenterSnapshot,
    SystemState,
)
from core.permission_manager import PermissionDecision, PermissionManager
from core.risk_engine import RiskEngine
from core.security_architecture import (
    SecurityContext,
    SecurityLevel,
    SecurityRequest,
    ToolSecurityMetadata,
)


class TestControlCenter:
    """Suite de pruebas para el Centro de Control y Observabilidad."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_control_center_setup")
        self.center = ControlCenter(emergency_stop=self.emergency_stop)
        self.center.reset()
        self.risk_engine = RiskEngine()
        self.permission_manager = PermissionManager()

    # ── 1. TRANSICIONES Y ESTADOS FORMALES ──

    def test_state_lifecycle_transitions(self) -> None:
        """Verifica las transiciones a través de los 8 estados del sistema."""
        states_to_test = [
            SystemState.IDLE,
            SystemState.PLANNING,
            SystemState.RUNNING,
            SystemState.WAITING_CONFIRMATION,
            SystemState.PAUSED,
            SystemState.COMPLETED,
            SystemState.FAILED,
            SystemState.STOPPED,
        ]

        for st in states_to_test:
            snap = self.center.update_state(state=st)
            assert snap.state == st
            assert self.center.get_snapshot().state == st

    # ── 2. ACTUALIZACIÓN DE TELEMETRÍA Y SNAPSHOT ──

    def test_telemetry_update_and_snapshot(self) -> None:
        """Verifica la actualización de VRAM, tokens, latencia, modelo y agente."""
        snap = self.center.update_state(
            state=SystemState.RUNNING,
            active_model="qwen3:8b",
            active_agent="agent_desktop",
            current_task="task-desk-01",
            current_step="step_1_screenshot",
            risk_level=SecurityLevel.LOW,
            vram_mb=5700.0,
            tokens_consumed=1250,
            latency_ms=45.2,
        )

        assert snap.active_model == "qwen3:8b"
        assert snap.active_agent == "agent_desktop"
        assert snap.current_task == "task-desk-01"
        assert snap.current_step == "step_1_screenshot"
        assert snap.risk_level == SecurityLevel.LOW
        assert snap.vram_mb == 5700.0
        assert snap.tokens_consumed == 1250
        assert snap.latency_ms == 45.2

        dict_data = snap.to_dict()
        assert dict_data["active_model"] == "qwen3:8b"
        assert dict_data["state"] == "RUNNING"

    # ── 3. SUSCRIPTORES EN TIEMPO REAL ──

    def test_real_time_subscriber_notifications(self) -> None:
        """Verifica que los listeners registrados reciban notificaciones ante cada actualización."""
        received_snapshots: list[ControlCenterSnapshot] = []

        def on_update(snap: ControlCenterSnapshot) -> None:
            received_snapshots.append(snap)

        unsubscribe = self.center.subscribe(on_update)

        self.center.update_state(state=SystemState.PLANNING, current_task="task-1")
        self.center.update_state(state=SystemState.RUNNING, current_task="task-1")

        assert len(received_snapshots) == 2
        assert received_snapshots[0].state == SystemState.PLANNING
        assert received_snapshots[1].state == SystemState.RUNNING

        # Desuscribir
        unsubscribe()
        self.center.update_state(state=SystemState.COMPLETED)
        assert len(received_snapshots) == 2  # No debe recibir nuevas actualizaciones

    # ── 4. CONTROL STOP (EMERGENCY STOP INTEGRATION) ──

    def test_stop_command_triggers_emergency_stop(self) -> None:
        """Verifica que el comando STOP active la Parada de Emergencia global de forma inmediata."""
        res = self.center.stop(reason="Operador presionó botón STOP en Control Center")

        assert res.success is True
        assert res.command == "STOP"
        assert res.current_state == SystemState.STOPPED
        assert self.emergency_stop.is_stopped() is True

        # Cualquier intento posterior de cambiar estado mientras esté en parada debe mantener STOPPED
        snap_after = self.center.update_state(state=SystemState.RUNNING)
        assert snap_after.state == SystemState.STOPPED
        assert snap_after.emergency_stop_active is True

    # ── 5. CONTROLES PAUSE Y RESUME ──

    def test_pause_and_resume_controls(self) -> None:
        """Verifica el flujo seguro de pausa y reanudación."""
        self.center.update_state(state=SystemState.RUNNING)

        # 1. Pausa
        pause_res = self.center.pause(reason="Pausa de mantenimiento")
        assert pause_res.success is True
        assert pause_res.current_state == SystemState.PAUSED
        assert self.center.get_snapshot().state == SystemState.PAUSED

        # 2. Reanudar
        resume_res = self.center.resume(reason="Reanudación aprobada")
        assert resume_res.success is True
        assert resume_res.current_state == SystemState.RUNNING
        assert self.center.get_snapshot().state == SystemState.RUNNING

    def test_cannot_resume_while_emergency_stop_is_active(self) -> None:
        """Verifica que RESUME sea rechazado si la Parada de Emergencia está activa."""
        self.center.stop(reason="Parada de emergencia")

        resume_res = self.center.resume(reason="Intento inválido de reanudar")
        assert resume_res.success is False
        assert resume_res.current_state == SystemState.STOPPED
        assert "Parada de Emergencia" in resume_res.message

    # ── 6. BUFFER DE HERRAMIENTAS Y EVENTOS DE SEGURIDAD ──

    def test_record_tools_and_security_events(self) -> None:
        """Verifica el buffer de herramientas ejecutadas y el contador de eventos de seguridad."""
        self.center.record_tool_execution("filesystem.list_directory")
        self.center.record_tool_execution("desktop.screenshot")
        self.center.record_security_event("Detección de intento de escalada de permisos bloqueado")

        snap = self.center.get_snapshot()
        assert "filesystem.list_directory" in snap.tools_executed
        assert "desktop.screenshot" in snap.tools_executed
        assert snap.security_events_count == 1
        assert "escalada" in str(snap.latest_security_event).lower()

    # ── 7. DETALLES Y TELEMETRÍA COMPLETA (DETAILS) ──

    def test_get_details_command(self) -> None:
        """Verifica que el comando DETAILS retorne información diagnóstica estructurada."""
        self.center.update_state(
            state=SystemState.RUNNING,
            active_model="llama3.1",
            active_agent="agent_file",
        )
        details_res = self.center.get_details()

        assert details_res.success is True
        assert details_res.command == "DETAILS"
        assert "snapshot" in details_res.data
        assert details_res.data["snapshot"]["active_model"] == "llama3.1"

    # ── 8. CONCURRENCIA THREAD-SAFE ──

    def test_concurrent_updates_and_reads(self) -> None:
        """Verifica la robustez ante lecturas y escrituras concurrentes desde múltiples hilos."""
        errors: list[Exception] = []

        def worker_updater(worker_id: int) -> None:
            try:
                for i in range(20):
                    self.center.update_state(
                        state=SystemState.RUNNING,
                        current_task=f"task-worker-{worker_id}-{i}",
                        tokens_consumed=i * 10,
                    )
                    self.center.record_tool_execution(f"tool_{worker_id}_{i}")
            except Exception as e:
                errors.append(e)

        def worker_reader() -> None:
            try:
                for _ in range(20):
                    _ = self.center.get_snapshot()
                    _ = self.center.get_details()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker_updater, args=(1,)),
            threading.Thread(target=worker_updater, args=(2,)),
            threading.Thread(target=worker_reader),
            threading.Thread(target=worker_reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0

    # ── 9. SEGURIDAD: CONTROL CENTER NO PUEDE EJECUTAR HERRAMIENTAS DIRECTAMENTE ──

    def test_control_center_has_no_direct_tool_execution_authority(self) -> None:
        """Invariante: ControlCenter no es ejecutor de herramientas y debe respetar SecurityPipeline."""
        # El ControlCenter no expone execute_tool ni bypass
        assert not hasattr(self.center, "execute_tool")
        assert not hasattr(self.center, "bypass_security")

        # Comprobación de que una acción crítica sigue siendo denegada por SecurityPipeline
        req = SecurityRequest(
            context=SecurityContext(user="control_center_ui", tool_name="system.format_disk", parameters={}),
            metadata=ToolSecurityMetadata(tool_name="system.format_disk", category="system", risk_level=SecurityLevel.CRITICAL),
        )
        assessment = self.risk_engine.evaluate_risk(req)
        assert assessment.risk_level == SecurityLevel.CRITICAL

        decision = self.permission_manager.check_permission(
            tool_name="system.format_disk",
            risk_level=SecurityLevel.CRITICAL,
        )
        assert decision == PermissionDecision.DENY
