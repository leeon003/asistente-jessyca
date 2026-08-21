"""Tests unitarios e integrales para el Asistente Proactivo Seguro (Fase 27).

Verifica:
1. Notificaciones proactivas de finalización y fallos de tareas
2. Detección y contención de acciones peligrosas (REQUEST_CONFIRMATION para riesgo MEDIO/ALTO/CRÍTICO)
3. Ejecución controlada de acciones seguras (SAFE_EXECUTE)
4. Bloqueo de acciones no autorizadas (PermissionManager DENY)
5. Cancelación cooperativa vía CancellationToken
6. Parada de Emergencia prevalente e inmediata (EmergencyStopManager)
7. Robustez multihilo y blindaje contra condiciones de carrera
8. Validación estructural y rechazo de eventos corruptos o con inyecciones
"""

import threading
from typing import Any

from core.cancellation import CancellationToken
from core.emergency_stop import EmergencyStopManager
from core.permission_manager import PermissionManager
from core.proactive import (
    ProactiveActionType,
    ProactiveAssistant,
    ProactiveEvent,
    ProactiveEventType,
    ProactiveExecutionResult,
    ProactivePolicyEngine,
)
from core.risk_engine import RiskEngine


class TestProactiveAssistant:
    """Suite de pruebas exhaustiva para el Asistente Proactivo Seguro."""

    def setup_method(self) -> None:
        self.emergency_stop = EmergencyStopManager.get_instance()
        self.emergency_stop.reset("test_proactive_setup")
        self.risk_engine = RiskEngine()
        self.permission_manager = PermissionManager()
        self.policy_engine = ProactivePolicyEngine(
            risk_engine=self.risk_engine,
            permission_manager=self.permission_manager,
        )
        self.assistant = ProactiveAssistant(
            policy_engine=self.policy_engine,
            emergency_stop=self.emergency_stop,
        )
        self.assistant.reset()

    # ── 1. NOTIFICACIONES PROACTIVAS DE TAREAS Y EVENTOS INFORMATIVOS ──

    def test_notify_task_completed_event(self) -> None:
        """Verifica que la finalización de tarea emita una notificación directa y segura."""
        res = self.assistant.notify_task_completed(
            task_id="backup-daily-01",
            summary="Copia de seguridad completada con éxito.",
        )

        assert res.success is True
        assert res.action_taken == ProactiveActionType.NOTIFY_USER
        assert "backup-daily-01" in res.user_message
        assert "completada" in res.user_message

    def test_notify_task_failed_event(self) -> None:
        """Verifica que el fallo de tarea emita una notificación directa."""
        res = self.assistant.notify_task_failed(
            task_id="sync-files-02",
            error="Tiempo de espera agotado al conectar con el destino.",
        )

        assert res.success is True
        assert res.action_taken == ProactiveActionType.NOTIFY_USER
        assert "sync-files-02" in res.user_message
        assert "falló" in res.user_message

    # ── 2. ACCIONES PELIGROSAS: REQUIEREN CONFIRMACIÓN HUMANA ──

    def test_dangerous_action_requires_human_confirmation(self) -> None:
        """Verifica que una acción sensible o de riesgo medio/alto NUNCA se ejecute desatendida."""
        # Proponer eliminar archivo en directorio de trabajo (riesgo DANGEROUS)
        res = self.assistant.propose_system_action(
            event_type=ProactiveEventType.SYSTEM_EVENT,
            summary="Espacio en disco bajo. Se propone limpiar archivo temporal de compilación.",
            tool_name="filesystem.delete_file",
            tool_parameters={"path": "D:\\Projects\\build_cache.tmp"},
        )

        assert res.success is True
        assert res.action_taken == ProactiveActionType.REQUEST_CONFIRMATION
        assert "confirmación" in res.user_message.lower()
        assert res.execution_data.get("confirmation_required") is True

    # ── 3. ACCIONES SEGURAS: EJECUCIÓN CONTROLADA ──

    def test_safe_proactive_action_execution(self) -> None:
        """Verifica que acciones clasificadas como SAFE con permisos se ejecuten controladamente."""
        executed_calls: list[tuple[str, dict[str, Any]]] = []

        def mock_executor(tool_name: str, params: dict[str, Any]) -> str:
            executed_calls.append((tool_name, params))
            return "OK: Listado completado"

        res = self.assistant.propose_system_action(
            event_type=ProactiveEventType.SYSTEM_EVENT,
            summary="Inspección de diagnóstico rutinario.",
            tool_name="filesystem.list_directory",
            tool_parameters={"path": "C:\\Data"},
            tool_executor=mock_executor,
        )

        assert res.success is True
        assert res.action_taken == ProactiveActionType.SAFE_EXECUTE
        assert len(executed_calls) == 1
        assert executed_calls[0][0] == "filesystem.list_directory"
        assert res.execution_data.get("output") == "OK: Listado completado"

    # ── 4. BLOQUEO DE ACCIONES CRÍTICAS DENEGADAS POR PERMISOS ──

    def test_denied_permission_suppresses_action(self) -> None:
        """Verifica que si una acción atenta contra rutas críticas de sistema, sea denegada (DENY/SUPPRESS)."""
        res = self.assistant.propose_system_action(
            event_type=ProactiveEventType.SYSTEM_EVENT,
            summary="Intento de borrado en directorio crítico del sistema operativo.",
            tool_name="filesystem.delete_file",
            tool_parameters={"path": "C:\\Windows\\System32\\critical.dll"},
        )

        assert res.success is False
        assert res.action_taken == ProactiveActionType.SUPPRESS
        assert "bloqueada" in res.user_message.lower()

    # ── 5. CANCELACIÓN COOPERATIVA ──

    def test_cancellation_token_aborts_proactive_event(self) -> None:
        """Verifica que un CancellationToken cancelado aborte el evento proactivo."""
        token = CancellationToken()
        token.cancel(reason="Operador canceló la tarea proactiva")

        event = ProactiveEvent(
            event_type=ProactiveEventType.NOTIFICATION,
            summary="Notificación que no debe procesarse.",
        )
        res = self.assistant.process_event(event, cancellation_token=token)

        assert res.success is False
        assert res.action_taken == ProactiveActionType.SUPPRESS
        assert "cancelado" in res.user_message.lower()

    # ── 6. PARADA DE EMERGENCIA PREVALENTE ──

    def test_emergency_stop_aborts_proactive_processing(self) -> None:
        """Verifica que la Parada de Emergencia prevalezca y aborte cualquier evento proactivo."""
        self.emergency_stop.trigger_stop(
            reason="Parada de emergencia por seguridad",
            source="test_proactive",
        )

        res = self.assistant.notify_task_completed("task-99", "Tarea finalizada")
        assert res.success is False
        assert res.action_taken == ProactiveActionType.SUPPRESS
        assert "Parada de Emergencia" in res.user_message

    # ── 7. VALIDACIÓN ESTRUCTURAL Y RECHAZO DE EVENTOS INVÁLIDOS ──

    def test_invalid_event_structure_rejection(self) -> None:
        """Verifica el rechazo de eventos con identificadores vacíos o caracteres nulos."""
        # Evento con caracteres nulos
        bad_event = ProactiveEvent(
            event_id="evt-bad",
            source="evil\x00source",
            summary="Inyección nula",
        )
        res = self.assistant.process_event(bad_event)
        assert res.success is False
        assert res.action_taken == ProactiveActionType.SUPPRESS
        assert "inválido" in res.user_message.lower()

    # ── 8. CONCURRENCIA Y RACE CONDITIONS ──

    def test_concurrent_proactive_events(self) -> None:
        """Verifica que múltiples hilos puedan emitir y procesar eventos proactivamente sin condiciones de carrera."""
        received_results: list[ProactiveExecutionResult] = []
        errors: list[Exception] = []

        def listener(r: ProactiveExecutionResult) -> None:
            received_results.append(r)

        self.assistant.register_listener(listener)

        def worker(worker_id: int) -> None:
            try:
                for i in range(15):
                    self.assistant.notify_task_completed(
                        task_id=f"worker-{worker_id}-task-{i}",
                        summary=f"Paso {i} finalizado",
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(w,)) for w in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(received_results) == 60  # 4 hilos * 15 eventos
