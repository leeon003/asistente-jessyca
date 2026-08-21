"""Pruebas de verificación de aislamiento de EmergencyStopManager (Fase 20.0: Test Isolation Fix).

Verifica:
1. Un test que activa EmergencyStop no contamina los tests subsecuentes en el mismo proceso.
2. El singleton vuelve automáticamente al estado operativo RUNNING antes y después de cada test.
3. Los módulos dependientes (agentes, navegador, control plane) no heredan estado STOPPED.
"""

from core.emergency_stop import EmergencyStopManager, EmergencyStopState


class TestEmergencyStopIsolationSequence:
    """Secuencia determinista de pruebas para validar que el estado STOPPED no fuga entre tests."""

    def test_step_1_trigger_emergency_stop(self) -> None:
        """Paso 1: Activa explícitamente la parada de emergencia en el singleton global."""
        manager = EmergencyStopManager.get_instance()
        manager.trigger_stop(reason="Activación intencional de prueba para test de aislamiento", source="test_isolation")
        assert manager.is_stopped() is True
        assert manager._state in (EmergencyStopState.STOP_REQUESTED, EmergencyStopState.STOPPED)

    def test_step_2_verify_isolation_restored_clean_state(self) -> None:
        """Paso 2: Verifica que el test subsecuente recibe un singleton completamente restablecido (RUNNING)."""
        manager = EmergencyStopManager.get_instance()
        # El fixture autouse debe haber restablecido el manager a RUNNING automáticamente
        assert manager.is_stopped() is False
        assert manager._state == EmergencyStopState.RUNNING
        assert manager._reason is None
        assert manager._cancellation_event.is_set() is False

    def test_step_3_browser_and_agent_safety_not_blocked(self) -> None:
        """Paso 3: Verifica que check_cancellation no lance EmergencyStopTriggeredError."""
        manager = EmergencyStopManager.get_instance()
        # No debe lanzar excepción
        manager.check_cancellation(phase="browser_wait")
        manager.check_cancellation(phase="agent_step")
        assert manager.is_stopped() is False
