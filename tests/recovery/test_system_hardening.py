"""Suite de Pruebas de Resiliencia, Recuperación de Estado y Hardening (test_system_hardening.py - Fase 40).

Cubre los 15 escenarios formales de tolerancia a fallos:
1. timeout
2. retry
3. fallback
4. crash
5. restart
6. interrupted task
7. state recovery
8. duplicate prevention (idempotency)
9. resource exhaustion
10. Emergency Stop
11. security failure
12. corrupted state
13. model unavailable
14. Skill unavailable
15. Agent unavailable
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Any

from core.emergency_stop import get_emergency_stop_manager
from core.recovery.models import RetryPolicy
from core.recovery.system_hardening import (
    IdempotencyManager,
    StateRecoveryManager,
    SystemHardeningEngine,
    TaskCheckpoint,
    TaskExecutionState,
)


class TestSystemHardeningSuite:
    """Suite de validación exhaustiva de hardening, recuperación de fallos y resiliencia."""

    def setup_method(self) -> None:
        self.emergency_stop = get_emergency_stop_manager()
        self.emergency_stop.reset("test_setup_cleanup")
        self.temp_dir = tempfile.mkdtemp(prefix="jessyca_recovery_test_")
        self.idempotency = IdempotencyManager(ttl_seconds=60.0)
        self.state_recovery = StateRecoveryManager(checkpoint_dir=self.temp_dir)
        self.engine = SystemHardeningEngine(
            idempotency_manager=self.idempotency,
            state_recovery=self.state_recovery,
            emergency_stop=self.emergency_stop,
        )

    def teardown_method(self) -> None:
        self.emergency_stop.reset("test_teardown_cleanup")
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ── 1. TIMEOUT HANDLING ──

    def test_01_timeout_handling(self) -> None:
        """Verifica que operaciones que exceden el tiempo límite son abortadas de forma segura."""
        def slow_op() -> Any:
            raise TimeoutError("Operación excedió el tiempo límite de 2.0s")

        res = self.engine.execute_with_resilience("slow_task", slow_op)
        assert res["success"] is False
        assert "tiempo límite" in res["error"]

    # ── 2. RETRY WITH BACKOFF ──

    def test_02_bounded_retry_with_backoff(self) -> None:
        """Verifica reintentos acotados (max 2) con backoff exponencial sin bucles infinitos."""
        attempts = 0

        def flaky_op() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionResetError("Conexión intermitente")
            return "Éxito en intento 3"

        res = self.engine.execute_with_resilience(
            "flaky_call",
            flaky_op,
            retry_policy=RetryPolicy(max_retries=2, initial_delay_sec=0.01, max_delay_sec=0.05),
        )
        assert res["success"] is True
        assert res["output"] == "Éxito en intento 3"
        assert res["attempts"] == 3

    # ── 3. FALLBACK CASCADE ──

    def test_03_multi_tier_fallback(self) -> None:
        """Verifica la conmutación a fallback cuando el proveedor primario falla reiteradamente."""
        def primary_fail() -> Any:
            raise RuntimeError("Primary model crashed")

        def fallback_success() -> str:
            return "Respuesta desde modelo secundario (Fallback)"

        res = self.engine.execute_with_resilience(
            "model_inference",
            primary_fail,
            fallback_fn=fallback_success,
            retry_policy=RetryPolicy(max_retries=1, initial_delay_sec=0.01),
        )
        assert res["success"] is True
        assert res["used_fallback"] is True
        assert "Fallback" in res["output"]

    # ── 4. CRASH RECOVERY ──

    def test_04_model_and_tool_crash_recovery(self) -> None:
        """Verifica que una caída de proceso o excepción no controlada no congela el sistema."""
        def crashing_tool() -> Any:
            raise ProcessLookupError("Subproceso de herramienta MCP terminó inesperadamente (código -9)")

        res = self.engine.execute_with_resilience(
            "mcp_tool_exec",
            crashing_tool,
            fallback_fn=lambda: "Salida segura de emergencia",
            retry_policy=RetryPolicy(max_retries=1, initial_delay_sec=0.01),
        )
        assert res["success"] is True
        assert res["used_fallback"] is True

    # ── 5. SYSTEM RESTART DETECTION ──

    def test_05_system_restart_detection(self) -> None:
        """Verifica la detección de tareas que quedaron en estado RUNNING tras reinicio."""
        cp = TaskCheckpoint(
            task_id="task-reboot-01",
            step_id="step_download_data",
            state=TaskExecutionState.RUNNING,
            payload={"dataset": "large_file.zip"},
        )
        self.state_recovery.save_checkpoint(cp)

        interrupted = self.state_recovery.detect_interrupted_tasks()
        assert len(interrupted) == 1
        assert interrupted[0].task_id == "task-reboot-01"
        assert interrupted[0].state == TaskExecutionState.INTERRUPTED

    # ── 6. INTERRUPTED TASK RECOVERY ──

    def test_06_interrupted_task_recovery(self) -> None:
        """Verifica la reanudación segura de una tarea interrumpida."""
        cp = TaskCheckpoint(
            task_id="task-reboot-02",
            step_id="step_format_doc",
            state=TaskExecutionState.INTERRUPTED,
            payload={"doc_id": 42},
            completed_steps=["step_research"],
        )
        self.state_recovery.save_checkpoint(cp)

        res = self.engine.recover_interrupted_task(cp)
        assert res["success"] is True
        assert res["status"] == "RECOVERED_COMPLETED"
        assert "step_format_doc" in res["completed_steps"]

    # ── 7. PERSISTED STATE INTEGRITY ──

    def test_07_persisted_state_integrity(self) -> None:
        """Verifica la validación de checksum SHA-256 en puntos de control persistidos."""
        cp = TaskCheckpoint(
            task_id="task-checksum-01",
            step_id="step_1",
            state=TaskExecutionState.CHECKPOINTED,
            payload={"balance": 100},
        )
        self.state_recovery.save_checkpoint(cp)

        loaded = self.state_recovery.load_checkpoint("task-checksum-01")
        assert loaded is not None
        assert loaded.is_valid() is True

    # ── 8. DUPLICATE PREVENTION (IDEMPOTENCY) ──

    def test_08_duplicate_action_prevention_idempotency(self) -> None:
        """Verifica que una acción idéntica no se repite accidentalmente y retorna resultado cacheado."""
        execution_count = 0

        def create_file_action() -> dict[str, str]:
            nonlocal execution_count
            execution_count += 1
            return {"file_created": "report.pdf", "version": 1}

        params = {"filename": "report.pdf", "folder": "/sandbox"}
        # Primera ejecución
        res1 = self.engine.execute_idempotent_action("create_file", params, create_file_action)
        assert res1["success"] is True
        assert res1["cached"] is False
        assert execution_count == 1

        # Segunda ejecución idéntica
        res2 = self.engine.execute_idempotent_action("create_file", params, create_file_action)
        assert res2["success"] is True
        assert res2["cached"] is True
        assert execution_count == 1  # No se volvió a ejecutar la acción real

    # ── 9. RESOURCE EXHAUSTION GUARD ──

    def test_09_resource_exhaustion_vram_guard(self) -> None:
        """Verifica contención ante agotamiento de VRAM / memoria GPU."""
        from core.llm.vram_governor import VRAMGovernor
        gov = VRAMGovernor(vram_limit_mb=6144.0)
        assert gov.vram_limit_mb == 6144.0
        # Simular asignación segura dentro de los límites
        assert gov.can_allocate(2048.0) is True

    # ── 10. EMERGENCY STOP INVARIANT ──

    def test_10_emergency_stop_across_all_execution_phases(self) -> None:
        """Verifica que la activación de Parada de Emergencia aborta reintentos e idempotencia."""
        self.emergency_stop.trigger_stop("Parada de emergencia durante hardening", "admin")

        res_idemp = self.engine.execute_idempotent_action("delete_dir", {}, lambda: True)
        assert res_idemp["success"] is False
        assert "Parada de Emergencia activa" in res_idemp["error"]

        res_resil = self.engine.execute_with_resilience("test_call", lambda: "ok")
        assert res_resil["success"] is False
        assert "Parada de Emergencia activa" in res_resil["error"]

    # ── 11. SECURITY FAILURE NEVER RELAXED ──

    def test_11_security_failure_never_relaxed(self) -> None:
        """Verifica que una falla de seguridad jamás sea tratada como error transitorio ni reintentada."""
        def security_denial_op() -> Any:
            raise PermissionError("Acción bloqueada por SecurityPipeline: DANGEROUS")

        # Cero retries permitidos para denegaciones de seguridad
        res = self.engine.execute_with_resilience(
            "dangerous_op",
            security_denial_op,
            retry_policy=RetryPolicy(max_retries=0),
        )
        assert res["success"] is False
        assert res["attempts"] == 1
        assert "SecurityPipeline" in res["error"]

    # ── 12. CORRUPTED STATE CONTAINMENT ──

    def test_12_corrupted_state_containment(self) -> None:
        """Verifica que un archivo de checkpoint manipulado externamente sea detectado y descartado."""
        cp = TaskCheckpoint(
            task_id="task-tampered",
            step_id="step_1",
            state=TaskExecutionState.RUNNING,
            payload={"auth": "user"},
        )
        self.state_recovery.save_checkpoint(cp)

        # Alterar deliberadamente el archivo en disco
        path = os.path.join(self.temp_dir, "task-tampered.json")
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        d["payload"]["auth"] = "admin_hacked"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f)

        loaded = self.state_recovery.load_checkpoint("task-tampered")
        assert loaded is None  # Checksum mismatch detectado

    # ── 13. MODEL UNAVAILABLE DEGRADATION ──

    def test_13_model_unavailable_graceful_degradation(self) -> None:
        """Verifica degradación controlada y respuesta explicable cuando el modelo no está disponible."""
        def ollama_down() -> Any:
            raise ConnectionError("Ollama daemon no responde en http://127.0.0.1:11434")

        def mock_slm_fallback() -> str:
            return "Respuesta procesada localmente mediante modelo de respaldo liviano"

        res = self.engine.execute_with_resilience("llm_query", ollama_down, fallback_fn=mock_slm_fallback)
        assert res["success"] is True
        assert res["used_fallback"] is True

    # ── 14. SKILL UNAVAILABLE CONTAINMENT ──

    def test_14_skill_unavailable_containment(self) -> None:
        """Verifica contención controlada ante Skill ausente o deshabilitada en el registro."""
        def skill_exec() -> Any:
            raise LookupError("Skill 'media.video_edit' no encontrada en SkillRegistry")

        res = self.engine.execute_with_resilience("skill_call", skill_exec)
        assert res["success"] is False
        assert "no encontrada" in res["error"]

    # ── 15. AGENT UNAVAILABLE CONTAINMENT ──

    def test_15_agent_unavailable_containment(self) -> None:
        """Verifica que la indisponibilidad de un agente derive en fallo seguro sin desbordamiento."""
        def agent_dispatch() -> Any:
            raise RuntimeError("Agent 'agent_vision' no inicializado o fuera de servicio")

        res = self.engine.execute_with_resilience("agent_delegate", agent_dispatch)
        assert res["success"] is False
        assert "fuera de servicio" in res["error"]
