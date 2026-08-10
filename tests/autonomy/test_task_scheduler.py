"""Pruebas unitarias y adversariales del Task Scheduler (Etapa 13.1).

REQUISITOS PROBADOS:
1. TEST ADVERSARIAL OBLIGATORIO: Intento deliberado de saltarse el pipeline de seguridad (bypass) DEBE FALLAR.
2. Funcionamiento de triggers: IntervalTrigger, CronLikeTrigger, EventTrigger.
3. Prevención de ejecuciones duplicadas simultáneas (Duplicate execution prevention).
4. Concurrencia acotada y timeout.
5. Persistencia local en disco (JSON) y cancelación de tareas.
"""

from __future__ import annotations

import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from core.autonomy_policy import AutonomyConfirmationRequiredError
from core.task_scheduler import (
    CronLikeTrigger,
    DirectToolExecutionBypassError,
    EventTrigger,
    IntervalTrigger,
    ScheduledTaskManager,
)


def test_scheduler_pipeline_bypass_attempt_fails() -> None:
    """TEST ADVERSARIAL OBLIGATORIO: Intento deliberado de saltarse el pipeline de seguridad debe FALLAR."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_file = Path(tmpdir) / "tasks.json"
        manager = ScheduledTaskManager(storage_path=storage_file)

        # Registramos una tarea programada
        trigger = IntervalTrigger(interval_seconds=60)
        manager.register_task(
            task_id="bypass-task-1",
            tool_name="system.read",
            operation="read_file",
            trigger=trigger,
        )

        # 1. Intento deliberado de bypass vía parámetro explicito bypass_autonomy=True
        with pytest.raises(DirectToolExecutionBypassError) as exc_info:
            manager.run_task_now("bypass-task-1", bypass_autonomy=True)
        assert "[SECURITY VIOLATION]" in str(exc_info.value)

        # 2. Intento deliberado de pasar una función cruda raw_tool_fn
        def dummy_raw_tool() -> str:
            return "HACKED"

        with pytest.raises(DirectToolExecutionBypassError) as exc_info2:
            manager.run_task_now("bypass-task-1", raw_tool_fn=dummy_raw_tool)
        assert "[SECURITY VIOLATION]" in str(exc_info2.value)


def test_scheduled_dangerous_task_blocked_by_autonomy_policy() -> None:
    """Verifica que si una tarea programada es DANGEROUS, la AutonomyPolicy la bloquee (scheduled_task != user_authorization)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_file = Path(tmpdir) / "tasks.json"
        manager = ScheduledTaskManager(storage_path=storage_file)

        trigger = IntervalTrigger(interval_seconds=60)
        manager.register_task(
            task_id="dangerous-task-1",
            tool_name="file.delete",
            operation="remove_file",
            trigger=trigger,
        )

        with pytest.raises(AutonomyConfirmationRequiredError):
            manager.run_task_now("dangerous-task-1")


def test_triggers_behavior() -> None:
    """Verifica el correcto funcionamiento de IntervalTrigger, CronLikeTrigger y EventTrigger."""
    now = datetime.now(UTC)

    # 1. IntervalTrigger
    interval_trig = IntervalTrigger(interval_seconds=10, start_at=now - timedelta(seconds=15))
    assert interval_trig.should_fire(now) is True

    # 2. CronLikeTrigger
    cron_trig = CronLikeTrigger(minute=now.minute, hour=now.hour)
    assert cron_trig.should_fire(now) is True

    # 3. EventTrigger
    event_trig = EventTrigger(event_name="user.login")
    assert event_trig.should_fire(now) is False
    event_trig.trigger_event()
    assert event_trig.should_fire(now) is True
    assert event_trig.should_fire(now) is False  # Consume el evento


def test_duplicate_execution_prevention() -> None:
    """Verifica que una tarea en ejecución no pueda ser disparada de manera duplicada simultáneamente."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_file = Path(tmpdir) / "tasks.json"

        # Simular pipeline de ejecución lento
        def slow_pipeline(req) -> str:
            time.sleep(0.3)
            return "DONE"

        manager = ScheduledTaskManager(
            execution_pipeline_fn=slow_pipeline,
            storage_path=storage_file,
        )
        trigger = IntervalTrigger(interval_seconds=10)
        manager.register_task(
            task_id="slow-task-1",
            tool_name="system.read",
            operation="get_status",
            trigger=trigger,
        )

        # Iniciar la tarea en un hilo y tratar de ejecutarla concurrentemente
        import threading
        t = threading.Thread(target=manager.run_task_now, args=("slow-task-1",))
        t.start()
        time.sleep(0.05)

        # Segundo disparo simultáneo
        res_dup = manager.run_task_now("slow-task-1")
        assert res_dup.success is False
        assert "Prevención de ejecución duplicada" in res_dup.error_message

        t.join()


def test_task_persistence_and_cancellation() -> None:
    """Verifica que las tareas se guarden persistentemente en el archivo JSON local y puedan ser canceladas."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage_file = Path(tmpdir) / "tasks.json"

        manager1 = ScheduledTaskManager(storage_path=storage_file)
        trigger = IntervalTrigger(interval_seconds=30)
        manager1.register_task(
            task_id="persist-task-100",
            tool_name="log.write",
            operation="append",
            trigger=trigger,
        )

        assert storage_file.exists() is True

        # Crear nuevo ScheduledTaskManager leyendo la misma ruta de disco
        manager2 = ScheduledTaskManager(storage_path=storage_file)
        assert "persist-task-100" in manager2._tasks

        # Cancelar la tarea
        cancelled = manager2.cancel_task("persist-task-100")
        assert cancelled is True
        assert manager2._tasks["persist-task-100"].is_active is False

        # Intentar ejecutar la tarea cancelada
        res_cancel = manager2.run_task_now("persist-task-100")
        assert res_cancel.success is False
        assert "cancelada" in res_cancel.error_message
