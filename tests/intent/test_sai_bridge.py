"""tests/intent/test_sai_bridge.py
Pruebas unitarias y de validación para SaiBridge (Fase 2).

Verifica:
1. Creación de planes estructurados en Plan Mode.
2. Consulta y aprobación formal de planes (get_plan_result, approve_plan).
3. Selección progresiva de herramientas (Progressive Tool Loading).
4. Compactación de contexto respetando límites de tokens.
5. Supervisión y ciclo de vida de trabajos (register_job, supervise_job, update_job_progress).
6. Reporte y auditoría de errores (report_error).
7. Cancelación segura de tareas y planes (cancel_task).
8. Interrupción inmediata ante Parada de Emergencia.
"""

from __future__ import annotations

import pytest

from core.emergency_stop import EmergencyStopManager
from core.intent.sai_bridge import (
    SaiBridge,
    SaiBridgeMode,
    SaiJobState,
    SaiPlanResult,
)


@pytest.fixture(autouse=True)
def reset_emergency_stop():
    """Restablece la parada de emergencia antes y después de cada prueba."""
    manager = EmergencyStopManager.get_instance()
    manager.reset("setup_sai_bridge_test")
    yield
    manager.reset("teardown_sai_bridge_test")


def test_sai_bridge_initialization_modes() -> None:
    """Verifica la inicialización de SaiBridge en los dos modos de evaluación."""
    bridge_native = SaiBridge(mode=SaiBridgeMode.NATIVE_EMBEDDED)
    assert bridge_native.mode == SaiBridgeMode.NATIVE_EMBEDDED

    bridge_ext = SaiBridge(mode=SaiBridgeMode.EXTERNAL_SUPERVISED)
    assert bridge_ext.mode == SaiBridgeMode.EXTERNAL_SUPERVISED


def test_sai_bridge_create_plan_and_retrieve() -> None:
    """Verifica que create_plan genere un plan estructurado y get_plan_result lo recupere."""
    bridge = SaiBridge()
    task = "Abre el bloc de notas y escribe notas de reunión"
    plan: SaiPlanResult = bridge.create_plan(task)

    assert plan.plan_id.startswith("plan_")
    assert len(plan.steps) >= 1
    assert plan.task_description == task
    assert plan.is_approved is False

    retrieved = bridge.get_plan_result(plan.plan_id)
    assert retrieved is not None
    assert retrieved.plan_id == plan.plan_id
    assert retrieved.title == plan.title


def test_sai_bridge_plan_approval() -> None:
    """Comprueba el flujo de aprobación formal de un plan en Plan Mode."""
    bridge = SaiBridge()
    plan = bridge.create_plan("Cierra notepad y elimina archivo temporal")

    assert plan.status in ("awaiting_approval", "ready")
    ok = bridge.approve_plan(plan.plan_id, feedback="Aprobado por el usuario")
    assert ok is True

    updated = bridge.get_plan_result(plan.plan_id)
    assert updated is not None
    assert updated.is_approved is True
    assert updated.status == "approved"
    assert updated.feedback == "Aprobado por el usuario"


def test_sai_bridge_select_tools_progressive() -> None:
    """Comprueba la selección progresiva de herramientas según el dominio de la consulta."""
    bridge = SaiBridge()

    # Consulta de archivos
    tools_files = bridge.select_tools("busca el archivo resumen.pdf en descargas")
    assert any("files" in t for t in tools_files)

    # Consulta de aplicaciones
    tools_apps = bridge.select_tools("abre la calculadora")
    assert any("apps" in t for t in tools_apps)

    # Consulta de medios/audio
    tools_media = bridge.select_tools("sube el volumen al 50%")
    assert any("audio" in t or "media" in t for t in tools_media)

    # Con lista blanca restringida
    filtered = bridge.select_tools("abre bloc de notas", available_tools=["windows.apps"])
    assert filtered == ["windows.apps"]


def test_sai_bridge_context_compaction() -> None:
    """Verifica que la compactación comprima turnos antiguos y mantenga turnos recientes."""
    bridge = SaiBridge()

    # 1. Mensajes dentro del presupuesto -> applied = False
    small_messages = [
        {"role": "system", "content": "Directiva principal"},
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "Hola, ¿en qué te ayudo?"},
    ]
    res_small = bridge.compact_context(small_messages, token_limit=1000)
    assert res_small.applied is False
    assert res_small.compacted_turns == len(small_messages)

    # 2. Mensajes extensos que superan el límite -> applied = True
    long_messages = [{"role": "system", "content": "Directiva del sistema"}]
    for i in range(20):
        long_messages.append({"role": "user", "content": f"Pregunta histórica {i} " + ("detalle " * 50)})
        long_messages.append({"role": "assistant", "content": f"Respuesta histórica {i} " + ("contenido " * 50)})

    res_long = bridge.compact_context(long_messages, token_limit=500)
    assert res_long.applied is True
    assert res_long.compacted_turns < res_long.original_turns
    assert res_long.compacted_tokens < res_long.original_tokens
    assert "RESUMEN COMPACTADO" in res_long.checkpoint_summary


def test_sai_bridge_job_supervision_lifecycle() -> None:
    """Comprueba el registro, actualización de progreso y supervisión de un trabajo."""
    bridge = SaiBridge()

    job = bridge.register_job(task_id="task_calc_01", total_steps=3)
    assert job.state == SaiJobState.RUNNING
    assert job.progress_percentage == 0.0

    bridge.update_job_progress(job.job_id, current_step=1)
    status_1 = bridge.supervise_job(job.job_id)
    assert status_1.current_step == 1
    assert abs(status_1.progress_percentage - 33.33) < 1.0

    bridge.update_job_progress(job.job_id, current_step=3)
    status_final = bridge.supervise_job(job.job_id)
    assert status_final.current_step == 3
    assert status_final.progress_percentage == 100.0
    assert status_final.state == SaiJobState.COMPLETED


def test_sai_bridge_error_reporting() -> None:
    """Verifica el registro y auditoría de errores en SaiBridge."""
    bridge = SaiBridge()
    error_data = {"module": "planner", "error": "Timeout in model inference", "code": 504}
    bridge.report_error(error_data)

    reports = bridge.get_error_reports()
    assert len(reports) == 1
    assert reports[0]["details"]["code"] == 504


def test_sai_bridge_cancel_task() -> None:
    """Verifica que cancel_task marque tanto trabajos como planes asociados como CANCELLED."""
    bridge = SaiBridge()
    job = bridge.register_job("task_to_cancel", total_steps=5)
    plan = bridge.create_plan("Escribe documento extenso")

    ok_job = bridge.cancel_task(job.job_id)
    assert ok_job is True
    assert bridge.supervise_job(job.job_id).state == SaiJobState.CANCELLED

    ok_plan = bridge.cancel_task(plan.plan_id)
    assert ok_plan is True
    assert bridge.get_plan_result(plan.plan_id).status == "cancelled"


def test_sai_bridge_emergency_stop_aborts_planning() -> None:
    """Garantiza que la parada de emergencia anule la creación de planes."""
    manager = EmergencyStopManager.get_instance()
    manager.trigger_stop(reason="Emergency Kill Switch Active", source="test")

    bridge = SaiBridge()
    plan = bridge.create_plan("Acción bajo emergencia")
    assert plan.status == "cancelled_by_emergency_stop"
    assert len(plan.steps) == 0
