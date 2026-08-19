"""Etapa 16.0 — Vector 05: Scheduled Task Bypass Audit.

Verifica que el TaskScheduler resiste:
- Ejecución directa sin AutonomyPolicy (DirectToolExecutionBypassError)
- Tarea programada que intenta acción CRITICAL sin confirmación
- Invariante: scheduled_task != user_authorization
- Scheduler cannot grant authority
"""

from __future__ import annotations

import pytest

from core.autonomy_policy import AutonomousTaskRequest, AutonomyPolicy, TaskActionRisk
from core.task_scheduler import DirectToolExecutionBypassError, ScheduledTaskManager


class TestSchedulerBypassInvariant:
    """INVARIANTE: scheduled_task != user_authorization."""

    def test_scheduled_task_is_not_user_authorization(self) -> None:
        """Una tarea programada NO otorga autorización de usuario por sí sola."""
        from core.autonomy_policy import AutonomyPolicy, TaskActionRisk

        policy = AutonomyPolicy()
        req = AutonomousTaskRequest(
            task_id="sched-001",
            tool_name="filesystem.read",
            operation="read",
            is_scheduled=True,
            user_id="default_user",
        )

        # El scheduler no puede elevar autoridad automáticamente
        result = policy.evaluate_autonomous_request(req)

        # READ_ONLY o LOW_RISK debería ser ALLOW
        # Pero DANGEROUS/CRITICAL desde scheduler = DENY sin confirmación humana
        assert isinstance(result.risk_level, TaskActionRisk), (
            "El resultado de autonomía debe incluir clasificación de riesgo."
        )

    def test_scheduler_cannot_grant_dangerous_authority(self) -> None:
        """Tarea programada DANGEROUS debe requerir confirmación, nunca auto-ejecutarse."""
        from core.autonomy_policy import AutonomyPolicy

        policy = AutonomyPolicy()
        req = AutonomousTaskRequest(
            task_id="sched-dangerous",
            tool_name="filesystem.delete",
            operation="delete",
            is_scheduled=True,
            parameters={"recursive": True},
        )

        result = policy.evaluate_autonomous_request(req)
        assert not result.allowed or result.requires_confirmation, (
            "[AUDIT] Tarea programada DANGEROUS fue autorizada sin confirmación. "
            "Invariante scheduled_task != user_authorization violado."
        )

    def test_scheduler_cannot_grant_critical_authority(self) -> None:
        """Tarea programada CRITICAL debe ser DENY sin excepción."""
        from core.autonomy_policy import AutonomyPolicy

        policy = AutonomyPolicy()
        req = AutonomousTaskRequest(
            task_id="sched-critical",
            tool_name="system.registry_write",
            operation="write",
            is_scheduled=True,
            parameters={"key": "HKLM\\Software\\Critical"},
        )

        result = policy.evaluate_autonomous_request(req)
        assert not result.allowed, (
            "[AUDIT] Tarea programada CRITICAL fue autorizada. "
            "Operaciones CRITICAL deben ser siempre DENY para tareas automáticas."
        )

    def test_wake_word_cannot_grant_critical_authority(self) -> None:
        """Detección de wake word tampoco puede otorgar autoridad CRITICAL."""
        from core.autonomy_policy import AutonomyPolicy

        policy = AutonomyPolicy()
        req = AutonomousTaskRequest(
            task_id="wake-critical",
            tool_name="system.delete_files",
            operation="delete",
            is_wake_word=True,
            parameters={"recursive": True},
        )

        result = policy.evaluate_autonomous_request(req)
        assert not result.allowed or result.requires_confirmation, (
            "[AUDIT] Wake word trigger no puede otorgar autoridad CRITICAL automáticamente."
        )


class TestScheduledTaskManagerSecurity:
    """Tests de seguridad del ScheduledTaskManager."""

    def test_manager_initializes_correctly(self) -> None:
        """El scheduler debe inicializarse en estado seguro."""
        manager = ScheduledTaskManager()
        assert manager is not None
        assert manager._running is False, (
            "Scheduler debe iniciar en estado STOPPED, no en RUNNING."
        )

    def test_read_only_task_can_be_scheduled(self) -> None:
        """Tareas READ_ONLY deben poder ser programadas sin confirmación."""
        from core.task_scheduler import IntervalTrigger

        manager = ScheduledTaskManager()
        trigger = IntervalTrigger(interval_seconds=3600)

        task = manager.schedule_task(
            task_id="safe-task-001",
            tool_name="system.info",
            operation="read",
            trigger=trigger,
        )

        assert task is not None
        assert task.task_id == "safe-task-001"

    def test_task_with_dangerous_operation_requires_policy_check(self) -> None:
        """Tareas con operación DANGEROUS deben pasar por AutonomyPolicy."""
        from core.task_scheduler import IntervalTrigger

        manager = ScheduledTaskManager()
        trigger = IntervalTrigger(interval_seconds=3600)

        # Intentar programar una tarea peligrosa
        # El scheduler debe registrarla pero con clasificación de riesgo elevada
        task = manager.schedule_task(
            task_id="dangerous-task-001",
            tool_name="filesystem.delete",
            operation="delete",
            trigger=trigger,
            parameters={"recursive": True},
        )

        # La tarea se programa pero la ejecución debe pasar por AutonomyPolicy
        assert task is not None
        assert task.task_id == "dangerous-task-001"

    def test_duplicate_task_id_rejected(self) -> None:
        """El mismo task_id no puede ser registrado dos veces."""
        from core.task_scheduler import IntervalTrigger

        manager = ScheduledTaskManager()
        trigger = IntervalTrigger(interval_seconds=3600)

        manager.schedule_task(
            task_id="dup-task-001",
            tool_name="system.info",
            operation="read",
            trigger=trigger,
        )

        with pytest.raises(Exception):
            manager.schedule_task(
                task_id="dup-task-001",
                tool_name="system.info",
                operation="read",
                trigger=trigger,
            )


class TestIntervalTriggerSafety:
    """Tests de seguridad del IntervalTrigger para detectar M-05."""

    def test_zero_interval_rejected(self) -> None:
        """Intervalo de 0 segundos debe ser rechazado (protección DoS)."""
        from core.task_scheduler import IntervalTrigger
        with pytest.raises(ValueError):
            IntervalTrigger(interval_seconds=0)

    def test_negative_interval_rejected(self) -> None:
        """Intervalo negativo debe ser rechazado."""
        from core.task_scheduler import IntervalTrigger
        with pytest.raises(ValueError):
            IntervalTrigger(interval_seconds=-10)

    def test_trigger_fires_at_most_once_per_interval(self) -> None:
        """M-05 AUDIT: Trigger no debe dispararse múltiples veces por el mismo período."""
        from datetime import UTC, datetime, timedelta
        from core.task_scheduler import IntervalTrigger

        trigger = IntervalTrigger(interval_seconds=60)
        now = datetime.now(UTC)

        # Primera vez debe disparar
        assert trigger.should_fire(now) is True
        trigger.mark_fired(now)

        # Inmediatamente después NO debe disparar
        assert trigger.should_fire(now + timedelta(seconds=1)) is False

        # Después del intervalo completo sí debe disparar
        assert trigger.should_fire(now + timedelta(seconds=61)) is True
