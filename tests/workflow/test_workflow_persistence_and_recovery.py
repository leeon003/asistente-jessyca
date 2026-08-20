"""Tests unitarios e integración para Persistencia y Recuperación de Workflows (Etapa 18.2).

Verifica:
1. WorkflowStateSnapshot (almacenamiento mínimo de estado, timestamps, metadatos).
2. Redacción de secretos antes de persistencia (Zero-Leakage en snapshots).
3. SQLiteWorkflowStore & InMemoryWorkflowStore (operaciones CRUD persistentes).
4. Invariante Crítico de Reinicio (Crash / Restart Recovery):
   - Workflows DANGEROUS/CRITICAL pasan a PAUSED_REQUIRES_REVIEW y NUNCA se auto-reanudan.
   - Workflows READ_ONLY/LOW_RISK pueden reanudarse de forma segura.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from core.autonomy.autonomy_level import TaskActionRisk
from core.workflow import (
    InMemoryWorkflowStore,
    SQLiteWorkflowStore,
    WorkflowRecoveryManager,
    WorkflowState,
    WorkflowStateSnapshot,
)


class TestWorkflowSnapshotAndSecretRedaction:
    """Pruebas de modelos de snapshot y sanitización de secretos."""

    def test_snapshot_roundtrip(self) -> None:
        snap = WorkflowStateSnapshot(
            workflow_id="wf_snap_01",
            name="Backup DB",
            status=WorkflowState.RUNNING,
            risk_level=TaskActionRisk.LOW_RISK,
            current_step_id="step_compress",
            completed_steps=("step_dump",),
            step_results_summary={"step_dump": {"duration_ms": 120.0}},
            failure_reason=None,
            requires_user_review=False,
            auto_resume_allowed=True,
        )

        d = snap.to_dict()
        assert d["workflow_id"] == "wf_snap_01"
        assert d["status"] == "RUNNING"

        restored = WorkflowStateSnapshot.from_dict(d)
        assert restored.workflow_id == snap.workflow_id
        assert restored.status == snap.status
        assert restored.completed_steps == ("step_dump",)

    def test_secrets_redacted_when_saving_snapshot(self) -> None:
        """Verifica que contraseñas y tokens no se almacenen en los snapshots persistidos."""
        store = InMemoryWorkflowStore()

        raw_snapshot = WorkflowStateSnapshot(
            workflow_id="wf_leak_test",
            name="Login Workflow",
            status=WorkflowState.FAILED,
            risk_level=TaskActionRisk.LOW_RISK,
            step_results_summary={
                "step_auth": {
                    "password": "ClearTextPassword123",
                    "api_key": "sk-mysecretkey12345",
                    "normal_info": "ok",
                }
            },
            failure_reason="Fallo con token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.xyz y pwd=MySecretPassword",
        )

        store.save_snapshot(raw_snapshot)
        saved = store.get_snapshot("wf_leak_test")
        assert saved is not None

        # Verificación en resumen de pasos
        assert "ClearTextPassword123" not in str(saved.step_results_summary)
        assert saved.step_results_summary["step_auth"]["password"] == "[REDACTED_SENSITIVE_VALUE]"
        assert saved.step_results_summary["step_auth"]["api_key"] == "[REDACTED_SENSITIVE_VALUE]"
        assert saved.step_results_summary["step_auth"]["normal_info"] == "ok"

        # Verificación en failure_reason
        assert "MySecretPassword" not in str(saved.failure_reason)
        assert "[REDACTED" in str(saved.failure_reason)


class TestSQLiteWorkflowStore:
    """Pruebas para SQLiteWorkflowStore."""

    def test_sqlite_crud_operations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "workflows_test.db"
            store = SQLiteWorkflowStore(db_path)

            snap1 = WorkflowStateSnapshot(
                workflow_id="wf_sqlite_1",
                name="Workflow 1",
                status=WorkflowState.RUNNING,
                risk_level=TaskActionRisk.LOW_RISK,
                completed_steps=("s1", "s2"),
            )
            snap2 = WorkflowStateSnapshot(
                workflow_id="wf_sqlite_2",
                name="Workflow 2",
                status=WorkflowState.COMPLETED,
                risk_level=TaskActionRisk.READ_ONLY,
                completed_steps=("s1",),
            )

            store.save_snapshot(snap1)
            store.save_snapshot(snap2)

            # Recuperar
            recovered1 = store.get_snapshot("wf_sqlite_1")
            assert recovered1 is not None
            assert recovered1.name == "Workflow 1"
            assert recovered1.completed_steps == ("s1", "s2")

            # Listar activos (snap1 es RUNNING, snap2 es COMPLETED)
            active = store.list_active_snapshots()
            assert len(active) == 1
            assert active[0].workflow_id == "wf_sqlite_1"

            # Eliminar
            assert store.delete_snapshot("wf_sqlite_1") is True
            assert store.get_snapshot("wf_sqlite_1") is None


class TestCrashRestartRecovery:
    """Pruebas para la recuperación tras reinicio del sistema (Crash / Restart Recovery)."""

    def test_dangerous_workflow_blocked_on_restart(self) -> None:
        """INVARIANTE CRÍTICO: Workflows DANGEROUS interrumpidos pasan a PAUSED_REQUIRES_REVIEW.

        NO deben continuar automáticamente bajo ninguna circunstancia.
        """
        store = InMemoryWorkflowStore()

        # Simular workflow peligroso que estaba en RUNNING cuando el sistema se cayó/reinició
        interrupted_dangerous = WorkflowStateSnapshot(
            workflow_id="wf_dangerous_01",
            name="Eliminación de recursos del sistema",
            status=WorkflowState.RUNNING,
            risk_level=TaskActionRisk.DANGEROUS,
            current_step_id="step_delete_temp_cluster",
            completed_steps=("step_prep",),
        )
        store.save_snapshot(interrupted_dangerous)

        # Sistema se reinicia -> RecoveryManager procesa los flujos
        recovered_list = WorkflowRecoveryManager.handle_system_restart(store)
        assert len(recovered_list) == 1

        recovered = store.get_snapshot("wf_dangerous_01")
        assert recovered is not None
        assert recovered.status == WorkflowState.PAUSED_REQUIRES_REVIEW
        assert recovered.requires_user_review is True
        assert recovered.auto_resume_allowed is False
        assert "requiere revisión humana obligatoria" in str(recovered.failure_reason)

    def test_critical_workflow_blocked_on_restart(self) -> None:
        """INVARIANTE CRÍTICO: Workflows CRITICAL interrumpidos pasan a PAUSED_REQUIRES_REVIEW."""
        store = InMemoryWorkflowStore()

        interrupted_critical = WorkflowStateSnapshot(
            workflow_id="wf_critical_01",
            name="Instalación de paquetes de sistema",
            status=WorkflowState.WAITING,
            risk_level=TaskActionRisk.CRITICAL,
            current_step_id="step_winget_install",
        )
        store.save_snapshot(interrupted_critical)

        WorkflowRecoveryManager.handle_system_restart(store)

        recovered = store.get_snapshot("wf_critical_01")
        assert recovered is not None
        assert recovered.status == WorkflowState.PAUSED_REQUIRES_REVIEW
        assert recovered.requires_user_review is True
        assert recovered.auto_resume_allowed is False

    def test_low_risk_workflow_can_be_safely_resumed_on_restart(self) -> None:
        """Workflows LOW_RISK o READ_ONLY pueden marcarse para reanudación segura."""
        store = InMemoryWorkflowStore()

        interrupted_low_risk = WorkflowStateSnapshot(
            workflow_id="wf_low_risk_01",
            name="Generar reporte PDF",
            status=WorkflowState.RUNNING,
            risk_level=TaskActionRisk.LOW_RISK,
            current_step_id="step_format_pdf",
            completed_steps=("step_query_data",),
        )
        store.save_snapshot(interrupted_low_risk)

        WorkflowRecoveryManager.handle_system_restart(store)

        recovered = store.get_snapshot("wf_low_risk_01")
        assert recovered is not None
        assert recovered.status == WorkflowState.PAUSED
        assert recovered.requires_user_review is False
        assert recovered.auto_resume_allowed is True
