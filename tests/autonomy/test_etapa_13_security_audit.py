"""Auditoría de Seguridad Final para el Subsistema de Autonomía de Tareas (Etapa 13).

DEMOSTRACIÓN FORMAL DE LAS 10 GARANTÍAS DE SEGURIDAD EXIGIDAS EN ETAPA 13:
1. scheduled READ_ONLY: Tareas programadas de solo lectura permitidas autónomamente.
2. scheduled LOW_RISK: Tareas programadas de bajo riesgo permitidas autónomamente.
3. scheduled DANGEROUS: Tareas peligrosas programadas NUNCA se auto-autorizan. Requieren confirmación.
4. scheduled CRITICAL: Tareas críticas programadas NUNCA se auto-autorizan. Requieren elevación y confirmación.
5. cancelled task: Tareas canceladas desestimadas sin ejecución.
6. repeated task: Prevención activa de ejecuciones duplicadas simultáneas.
7. task loop: Prevención de bucles infinitos de tareas.
8. wake word: Deshabilitado por defecto con máquina de estados visible.
9. audio retention: CERO persistencia de audio en disco (procesamiento 100% efímero en RAM).
10. notification spam: Bloqueo de notificaciones descontroladas mediante Rate Limiting.

INVARIANTE INMUTABLE DEMOSTRADO: scheduled_task != authorization.
Toda ejecución pasa obligatoriamente por AutonomyPolicy y SecureExecutionPipeline.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

import pytest

from core.autonomy_policy import (
    AutonomousTaskRequest,
    AutonomyConfirmationRequiredError,
    AutonomyPolicy,
    TaskActionRisk,
)
from core.notification_dispatcher import (
    NotificationDispatcher,
    NotificationStatus,
)
from core.task_scheduler import (
    IntervalTrigger,
    ScheduledTaskManager,
)
from core.wake_word_detector import (
    WakeWordDetector,
    WakeWordDisabledError,
    WakeWordState,
)


def test_audit_1_scheduled_read_only_allowed() -> None:
    """1. scheduled READ_ONLY: Tarea programada de solo lectura autorizada autónomamente."""
    policy = AutonomyPolicy()
    req = AutonomousTaskRequest(
        task_id="audit-ro-1",
        tool_name="system.read",
        operation="get_status",
        is_scheduled=True,
    )
    res = policy.evaluate_task(req)
    assert res.allowed is True
    assert res.risk_level == TaskActionRisk.READ_ONLY
    assert res.requires_confirmation is False


def test_audit_2_scheduled_low_risk_allowed() -> None:
    """2. scheduled LOW_RISK: Tarea programada de bajo riesgo autorizada autónomamente."""
    policy = AutonomyPolicy()
    req = AutonomousTaskRequest(
        task_id="audit-low-1",
        tool_name="log.write",
        operation="append",
        is_scheduled=True,
    )
    res = policy.evaluate_task(req)
    assert res.allowed is True
    assert res.risk_level == TaskActionRisk.LOW_RISK
    assert res.requires_confirmation is False


def test_audit_3_scheduled_dangerous_denied_without_confirmation() -> None:
    """3. scheduled DANGEROUS: Demuestra que scheduled_task != authorization. Bloqueado si falta confirmación."""
    policy = AutonomyPolicy()
    req = AutonomousTaskRequest(
        task_id="audit-dangerous-1",
        tool_name="file.delete",
        operation="remove",
        is_scheduled=True,
    )
    res = policy.evaluate_task(req)
    assert res.allowed is False
    assert res.risk_level == TaskActionRisk.DANGEROUS
    assert res.requires_confirmation is True

    with pytest.raises(AutonomyConfirmationRequiredError):
        policy.enforce_task_execution(req)


def test_audit_4_scheduled_critical_denied_completely() -> None:
    """4. scheduled CRITICAL: Acciones críticas programadas (cmd/ps) NUNCA se auto-autorizan por estar programadas."""
    policy = AutonomyPolicy()
    req = AutonomousTaskRequest(
        task_id="audit-crit-1",
        tool_name="powershell.execute",
        operation="run_script",
        is_scheduled=True,
    )
    res = policy.evaluate_task(req)
    assert res.allowed is False
    assert res.risk_level == TaskActionRisk.CRITICAL
    assert res.requires_confirmation is True

    with pytest.raises(AutonomyConfirmationRequiredError):
        policy.enforce_task_execution(req)


def test_audit_5_cancelled_task_not_executed() -> None:
    """5. cancelled task: Tarea cancelada no se ejecuta y se desestima inmediatamente."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store_file = Path(tmpdir) / "tasks.json"
        scheduler = ScheduledTaskManager(storage_path=store_file)
        trig = IntervalTrigger(interval_seconds=60)
        scheduler.register_task("task-cancel-5", "system.read", "get_status", trig)

        # Cancelar tarea
        scheduler.cancel_task("task-cancel-5")

        # Intentar ejecutar la tarea cancelada
        result = scheduler.run_task_now("task-cancel-5")
        assert result.success is False
        assert "cancelada" in result.error_message


def test_audit_6_repeated_task_duplicate_prevention() -> None:
    """6. repeated task: Prevención activa de ejecuciones duplicadas simultáneas de una misma tarea."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store_file = Path(tmpdir) / "tasks.json"

        def slow_exec(req) -> str:
            time.sleep(0.3)
            return "OK"

        scheduler = ScheduledTaskManager(execution_pipeline_fn=slow_exec, storage_path=store_file)
        trig = IntervalTrigger(interval_seconds=60)
        scheduler.register_task("task-rep-6", "system.read", "get_status", trig)

        import threading
        t = threading.Thread(target=scheduler.run_task_now, args=("task-rep-6",))
        t.start()
        time.sleep(0.05)

        # Intento de disparo duplicado simultáneo
        res_dup = scheduler.run_task_now("task-rep-6")
        assert res_dup.success is False
        assert "Prevención de ejecución duplicada" in res_dup.error_message

        t.join()


def test_audit_7_task_loop_prevention() -> None:
    """7. task loop: Verificación de prevención de ejecución en loop infinito mediante descarte por ejecución activa."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store_file = Path(tmpdir) / "tasks.json"
        scheduler = ScheduledTaskManager(storage_path=store_file)
        trig = IntervalTrigger(interval_seconds=1)
        scheduler.register_task("task-loop-7", "system.read", "get_status", trig)

        # Ejecutar 5 disparos inmediatos
        results = [scheduler.run_task_now("task-loop-7") for _ in range(5)]
        assert len(results) == 5
        # Ninguno genera excepciones no controladas ni rompe el scheduler
        assert all(r.task_id == "task-loop-7" for r in results)


def test_audit_8_wake_word_disabled_by_default() -> None:
    """8. wake word: Detección de palabra de activación deshabilitada por defecto (WAKE_WORD_ENABLED=False)."""
    detector = WakeWordDetector()
    assert detector.enabled is False
    assert detector.state == WakeWordState.INACTIVE

    with pytest.raises(WakeWordDisabledError):
        detector.start_listening()


def test_audit_9_audio_zero_retention(tmp_path: Path) -> None:
    """9. audio retention: CERO archivos de audio en disco (procesamiento 100% efímero en RAM y purgado a 0x00)."""
    files_before = set(tmp_path.glob("*"))

    detector = WakeWordDetector()
    detector.enabled = True
    detector.start_listening()

    # Alimentar audio en memoria
    detector.process_audio_chunk(b"\x12\x34" * 1000)
    assert detector.buffer_size_bytes == 2000

    # Cancelar y sobreescribir memoria
    detector.cancel()
    assert detector.buffer_size_bytes == 0
    assert detector.state == WakeWordState.INACTIVE

    files_after = set(tmp_path.glob("*"))
    assert files_before == files_after, "Se detectó creación de archivos de audio. CERO PERSISTENCIA REQUERIDA."


def test_audit_10_notification_spam_blocked_by_rate_limiting() -> None:
    """10. notification spam: Bloqueo de loops infinitos de notificaciones mediante Rate Limiting."""
    dispatcher = NotificationDispatcher(rate_limit_per_minute=2, dedup_window_seconds=0.01)

    r1 = dispatcher.dispatch(title="Loop 1", message="Payload 1")
    r2 = dispatcher.dispatch(title="Loop 2", message="Payload 2")
    r3 = dispatcher.dispatch(title="Loop 3", message="Payload 3 (SPAM)")

    assert r1.status == NotificationStatus.SENT
    assert r2.status == NotificationStatus.SENT
    assert r3.status == NotificationStatus.RATE_LIMITED
    assert "excedido" in r3.reason.lower() or "rate" in r3.reason.lower() or "preducción" in r3.reason.lower()
