"""Pruebas Exhaustivas de Aprendizaje Procedimental para JESSYCA BRAIN 1.0 — FASE 5 (tests/cognitive_brain/test_procedure_learning_engine.py).

Implementa las 10 pruebas funcionales mandatorias (Pruebas A - J):
- Prueba A: Aprendizaje básico a partir de experiencia exitosa (CANDIDATE).
- Prueba B: Validación independiente y promoción a VALIDATED.
- Prueba C: Reutilización inteligente con sustitución de parámetros (Smart Parameter Adaptation).
- Prueba D: Persistencia tras reinicio en base de datos SQLite (data/memory_brain.db).
- Prueba E: Manejo y aprendizaje de errores sin alterar código fuente.
- Prueba F: Aprendizaje por demostración supervisada con sanitización de credenciales.
- Prueba G: Seguridad estricta: bloqueo de ejecución de procedimientos CANDIDATE o fuera de permisos.
- Prueba H: Recuperación tras interrupción (Checkpointing) sin duplicación de pasos.
- Prueba I: Integración con SAI Bridge (Plan Mode, supervisión y registro de trabajo).
- Prueba J: Integración E2E completa ("JESSYCA, utiliza el procedimiento que te enseñé...").
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
import pytest

from core.cancellation import CancellationToken
from core.cognitive_brain.brain_orchestrator import JessycaBrain
from core.cognitive_brain.contracts import (
    CanonicalPlan,
    CanonicalPlanStep,
    LearnedProcedure,
    PlanStepExecutionState,
    ProcedureLifecycleState,
)
from core.cognitive_brain.memory_engine import MemoryEngine, ProceduralMemory
from core.cognitive_brain.procedure_learning_engine import ProcedureLearningEngine
from core.emergency_stop import EmergencyStopManager


@pytest.fixture(autouse=True)
def clean_state():
    """Limpia el estado de parada de emergencia y puntos de control temporales."""
    esm = EmergencyStopManager.get_instance()
    esm.reset()
    yield
    esm.reset()


# =========================================================================
# PRUEBA A — APRENDIZAJE BÁSICO (EXPERIENCIA -> CANDIDATE)
# =========================================================================

def test_prueba_a_basic_experience_learning(tmp_path):
    """Enseñar a JESSYCA a abrir Bloc de notas y escribir texto de prueba a partir de una experiencia exitosa."""
    db_file = tmp_path / "proc_mem_a.db"
    mem_engine = MemoryEngine(db_path=str(db_file))
    learning_engine = ProcedureLearningEngine(memory_engine=mem_engine)

    # Simular un episodio exitoso de ejecución de bloc de notas
    episode = {
        "episode_id": "ep-test-notepad-01",
        "task_id": "task-notepad-01",
        "user_instruction": "Abre el bloc de notas y escribe notas de prueba",
        "intent": "desktop_edit",
        "actions_executed": [
            {"action_name": "open_application", "tool_name": "desktop.app", "parameters": {"app_name": "notepad"}},
            {"action_name": "type_text", "tool_name": "desktop.keyboard", "parameters": {"text": "notas de prueba"}},
            {"action_name": "close_application", "tool_name": "desktop.app", "parameters": {"app_name": "notepad.exe"}},
        ],
        "success": True,
        "verified_evidence": {"is_verified": True},
    }

    candidate = learning_engine.learn_from_experience(episode)
    assert candidate is not None
    assert candidate.state == ProcedureLifecycleState.CANDIDATE
    assert candidate.approval_status == "PROPOSED"
    assert candidate.version == 1
    assert len(candidate.steps) == 3
    # Comprobar que el texto fue parametrizado como plantilla dinámica
    assert any("text" in str(s.get("parameters", {})) for s in candidate.steps)

    # Comprobar que se guardó en ProceduralMemory
    saved = mem_engine.procedural_memory.get_procedure(candidate.procedure_id)
    assert saved is not None
    assert saved.name == candidate.name


# =========================================================================
# PRUEBA B — VALIDACIÓN INDEPENDIENTE (CANDIDATE -> TESTING -> VALIDATED)
# =========================================================================

def test_prueba_b_independent_validation_promotion(tmp_path):
    """Ejecutar el procedimiento en entorno de prueba y verificar que se promueva a VALIDATED."""
    db_file = tmp_path / "proc_mem_b.db"
    mem_engine = MemoryEngine(db_path=str(db_file))
    learning_engine = ProcedureLearningEngine(memory_engine=mem_engine)

    # 1. Crear procedimiento candidato
    proc = LearnedProcedure(
        procedure_id="proc-notepad-validate",
        name="desktop_edit:notepad_notes",
        associated_intent="desktop_edit",
        required_applications=["notepad"],
        authorized_tools=["desktop.app", "desktop.keyboard"],
        steps=[
            {"action_name": "open_application", "parameters": {"app_name": "notepad"}},
            {"action_name": "type_text", "parameters": {"text": "contenido validado"}},
            {"action_name": "close_application", "parameters": {"app_name": "notepad.exe"}},
        ],
        state=ProcedureLifecycleState.CANDIDATE,
    )
    mem_engine.procedural_memory.save_procedure(proc)

    # 2. Ejecutar validación independiente con executor controlado
    executed_actions = []

    def test_exec(action, tool, params):
        executed_actions.append((action, params))
        return True, {"verified": True}, None

    success, msg = learning_engine.validate_procedure(proc.procedure_id, test_executor=test_exec)
    assert success is True
    assert "validado" in msg.lower()
    assert len(executed_actions) == 3

    # 3. Comprobar que fue promovido a VALIDATED
    updated_proc = mem_engine.procedural_memory.get_procedure(proc.procedure_id)
    assert updated_proc.state == ProcedureLifecycleState.VALIDATED
    assert updated_proc.approval_status == "APPROVED"
    assert updated_proc.last_validated_at is not None
    assert len(updated_proc.validation_evidence) >= 1


# =========================================================================
# PRUEBA C — REUTILIZACIÓN INTELIGENTE (SMART PARAMETER SUBSTITUTION)
# =========================================================================

def test_prueba_c_smart_reuse_parameter_substitution(tmp_path):
    """Solicitar el mismo procedimiento con un texto diferente y verificar la sustitución dinámica."""
    db_file = tmp_path / "proc_mem_c.db"
    mem_engine = MemoryEngine(db_path=str(db_file))
    learning_engine = ProcedureLearningEngine(memory_engine=mem_engine)

    # Procedimiento validado con marcadores {{text}}
    proc = LearnedProcedure(
        procedure_id="proc-notepad-reuse",
        name="desktop_edit:notepad_write",
        associated_intent="desktop_edit",
        authorized_tools=["desktop.app", "desktop.keyboard"],
        steps=[
            {"action_name": "open_application", "parameters": {"app_name": "notepad"}},
            {"action_name": "type_text", "parameters": {"text": "{{text}}"}},
            {"action_name": "close_application", "parameters": {"app_name": "notepad.exe"}},
        ],
        state=ProcedureLifecycleState.VALIDATED,
    )
    mem_engine.procedural_memory.save_procedure(proc)

    # Solicitud de usuario con texto completamente nuevo
    user_req = 'Abre el bloc de notas y escribe "Información confidencial del informe anual"'
    plan = learning_engine.adapt_procedure_to_plan(
        procedure=proc,
        user_input=user_req,
        extracted_parameters={"text": "Información confidencial del informe anual"},
    )

    assert plan is not None
    assert len(plan.steps) == 3
    # El segundo paso debe tener el texto adaptado
    step_type = plan.steps[1]
    assert step_type.parameters["text"] == "Información confidencial del informe anual"
    assert "{{text}}" not in step_type.parameters["text"]


# =========================================================================
# PRUEBA D — PERSISTENCIA TRAS REINICIO
# =========================================================================

def test_prueba_d_persistence_across_restart(tmp_path):
    """Reiniciar la instancia de memoria y comprobar que conserva versión, parámetros, estado y evidencias."""
    db_file = tmp_path / "proc_mem_persist.db"

    # Sesión 1: Crear, validar y guardar
    mem_1 = MemoryEngine(db_path=str(db_file))
    learn_1 = ProcedureLearningEngine(memory_engine=mem_1)
    proc = LearnedProcedure(
        procedure_id="proc-persist-01",
        name="report_gen:quantum",
        associated_intent="generate_report",
        input_parameters={"topic": "string", "filename": "string"},
        steps=[{"action_name": "write_document", "parameters": {"filename": "{{filename}}"}}],
        state=ProcedureLifecycleState.VALIDATED,
        version=2,
        success_count=5,
    )
    mem_1.procedural_memory.save_procedure(proc)

    # Sesión 2: Reinicio completo (nueva instancia conectada a la misma BD)
    mem_2 = MemoryEngine(db_path=str(db_file))
    recovered = mem_2.procedural_memory.get_procedure("proc-persist-01")

    assert recovered is not None
    assert recovered.procedure_id == "proc-persist-01"
    assert recovered.name == "report_gen:quantum"
    assert recovered.version == 2
    assert recovered.state == ProcedureLifecycleState.VALIDATED
    assert recovered.success_count == 5
    assert "filename" in recovered.input_parameters


# =========================================================================
# PRUEBA E — MANEJO Y APRENDIZAJE DE ERRORES (FAILURE ADAPTATION)
# =========================================================================

def test_prueba_e_error_handling_and_adaptation(tmp_path):
    """Modificar condición de prueba para que falle, verificar que aprenda y evite falsos éxitos sin alterar código."""
    db_file = tmp_path / "proc_mem_err.db"
    mem_engine = MemoryEngine(db_path=str(db_file))
    learning_engine = ProcedureLearningEngine(memory_engine=mem_engine)

    proc = LearnedProcedure(
        procedure_id="proc-err-test",
        name="calc:multiply",
        associated_intent="calculator",
        steps=[{"step_id": "step-1", "action_name": "click_element", "parameters": {"element_id": "btn_multiply"}}],
        state=ProcedureLifecycleState.VALIDATED,
        version=1,
    )
    mem_engine.procedural_memory.save_procedure(proc)

    # Simular fallo en step-1
    adapted = learning_engine.learn_from_failure(
        procedure_id="proc-err-test",
        failed_step={"step_id": "step-1", "action_name": "click_element"},
        error_evidence={"error": "ElementNotFound: btn_multiply timeout after 10s"},
    )

    assert adapted is not None
    assert adapted.version == 2
    assert adapted.failure_count == 1
    assert len(adapted.modification_history) >= 1
    assert "failure_adaptation" in adapted.modification_history[-1]["event"]
    # Comprobar que el paso ahora incluye estrategia de fallback
    s1 = adapted.steps[0]
    assert s1.get("fallback_strategy") == "reobserve_window_bounds"
    assert s1.get("retry_limit", 1) >= 2


# =========================================================================
# PRUEBA F — APRENDIZAJE SUPERVISADO POR DEMOSTRACIÓN (CON PRIVACIDAD)
# =========================================================================

def test_prueba_f_supervised_demonstration_privacy(tmp_path):
    """Demostrar un procedimiento asegurando que no registre contraseñas o datos sensibles."""
    db_file = tmp_path / "proc_mem_demo.db"
    mem_engine = MemoryEngine(db_path=str(db_file))
    learning_engine = ProcedureLearningEngine(memory_engine=mem_engine)

    # Iniciar demostración
    sid = learning_engine.start_demonstration(
        name="login_flow_demo",
        intent="app_login",
        target_applications=["notepad.exe"],
        user_confirmed=True,
    )

    # Registrar acciones, incluyendo una con contraseña
    learning_engine.record_demonstration_action(
        session_id=sid,
        action="open_application",
        parameters={"app_name": "notepad"},
    )
    learning_engine.record_demonstration_action(
        session_id=sid,
        action="type_text",
        parameters={"text": "Usuario: admin, Password: SecretPassword123!"},
        element_info={"automation_id": "txt_input"},
    )

    # Pausa y reanudación
    assert learning_engine.pause_demonstration(sid) is True
    assert learning_engine.resume_demonstration(sid) is True

    # Finalizar demostración
    learned_demo = learning_engine.stop_demonstration(sid)
    assert learned_demo is not None
    assert learned_demo.state == ProcedureLifecycleState.CANDIDATE
    assert len(learned_demo.steps) == 2

    # VERIFICACIÓN DE PRIVACIDAD CRÍTICA: La contraseña no debe estar en texto plano
    step_type = learned_demo.steps[1]
    raw_step_content = json.dumps(step_type)
    assert "SecretPassword123!" not in raw_step_content
    assert "[REDACTED_SECRET]" in raw_step_content or "{{text" in raw_step_content


# =========================================================================
# PRUEBA G — SEGURIDAD: BLOQUEO DE PROCEDIMIENTOS CANDIDATE O SIN PERMISOS
# =========================================================================

def test_prueba_g_security_blocks_unvalidated_execution(tmp_path):
    """Intentar reutilizar un procedimiento no validado (CANDIDATE) y comprobar bloqueo de ejecución."""
    db_file = tmp_path / "proc_mem_sec.db"
    mem_engine = MemoryEngine(db_path=str(db_file))
    learning_engine = ProcedureLearningEngine(memory_engine=mem_engine)

    proc_candidate = LearnedProcedure(
        procedure_id="proc-unvalidated",
        name="dangerous:wipe",
        steps=[{"action_name": "delete_all", "parameters": {}}],
        state=ProcedureLifecycleState.CANDIDATE,  # NO validado
    )
    mem_engine.procedural_memory.save_procedure(proc_candidate)

    # Intentar generar plan para ejecutarlo
    with pytest.raises(PermissionError) as exc_info:
        learning_engine.adapt_procedure_to_plan(
            procedure=proc_candidate,
            user_input="Ejecuta el borrado",
        )
    assert "Solo procedimientos VALIDATED pueden ejecutarse" in str(exc_info.value)


# =========================================================================
# PRUEBA H — RECUPERACIÓN TRAS INTERRUPCIÓN (CHECKPOINTING CONTINUO)
# =========================================================================

def test_prueba_h_task_recovery_without_duplication(tmp_path):
    """Interrumpir un procedimiento de varios pasos, recuperar el checkpoint y continuar sin duplicar."""
    db_file = tmp_path / "proc_mem_recov.db"
    ckpt_dir = tmp_path / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    mem_engine = MemoryEngine(db_path=str(db_file))
    brain = JessycaBrain(
        memory_engine=mem_engine,
        checkpoint_dir=str(ckpt_dir),
    )

    # Simular ejecución donde el paso 1 tiene éxito y luego se simula caída
    token = CancellationToken()
    executed_log = []

    def failing_executor(action, tool, params):
        executed_log.append(action)
        if len(executed_log) == 1:
            return True, {"out": 1}, None
        return False, None, "SimulatedCrashMidTask"

    res_fail = brain.process_request(
        "Investiga sobre física cuántica y escribe el resumen en scratch/cuantica.txt",
        session_id="recov_session",
        cancellation_token=token,
        tool_executor=failing_executor,
    )
    assert res_fail.success is False
    assert res_fail.steps_executed == 1

    # Recuperar la tarea interrumpida usando el checkpoint persistente
    res_recovered = brain.recover_interrupted_task(
        task_id=res_fail.task_id,
        tool_executor=lambda a, t, p: (True, {"recovered_step": a}, None),
    )
    assert res_recovered.success is True
    assert res_recovered.steps_executed == res_recovered.steps_total


# =========================================================================
# PRUEBA I — INTEGRACIÓN CON SAI BRIDGE
# =========================================================================

def test_prueba_i_sai_bridge_monitoring_and_jobs(tmp_path):
    """Comprobar que SAI Bridge registra jobs, actualiza progreso y supervisa la ejecución."""
    db_file = tmp_path / "proc_mem_sai.db"
    mem_engine = MemoryEngine(db_path=str(db_file))
    brain = JessycaBrain(memory_engine=mem_engine)

    res = brain.process_request(
        "Investiga sobre agentes autónomos y genera un reporte en resumen.txt",
        session_id="sai_session",
        tool_executor=lambda a, t, p: (True, {"executed": a}, None),
    )

    assert res.success is True
    assert res.sai_job_id is not None
    # Verificar que el job fue registrado en el SAI Bridge
    assert res.sai_job_id in brain.sai_bridge._jobs_store
    job = brain.sai_bridge._jobs_store[res.sai_job_id]
    assert job.state.value in ("COMPLETED", "RUNNING", "INITIALIZED")


# =========================================================================
# PRUEBA J — INTEGRACIÓN COMPLETA E2E ("UTILIZA EL PROCEDIMIENTO...")
# =========================================================================

def test_prueba_j_full_end_to_end_procedure_reuse(tmp_path):
    """Ejecutar: 'JESSYCA, utiliza el procedimiento que te enseñé para crear un informe nuevo...'"""
    db_file = tmp_path / "proc_mem_j.db"
    mem_engine = MemoryEngine(db_path=str(db_file))
    learning_engine = ProcedureLearningEngine(memory_engine=mem_engine)
    brain = JessycaBrain(
        memory_engine=mem_engine,
        procedure_learning_engine=learning_engine,
    )

    # 1. Enseñar y validar un procedimiento de creación de informes
    proc = LearnedProcedure(
        procedure_id="proc-informe-reporte",
        name="informe_ia:generar_reporte",
        associated_intent="generate_report",
        required_applications=["filesystem_writer"],
        authorized_tools=["academic_search", "notepad_writer"],
        input_parameters={"topic": "string", "filename": "string"},
        steps=[
            {"step_id": "step-1", "action_name": "research_topic", "tool_name": "academic_search", "parameters": {"topic": "{{topic}}"}},
            {"step_id": "step-2", "action_name": "write_document", "tool_name": "notepad_writer", "parameters": {"filename": "{{filename}}"}},
        ],
        state=ProcedureLifecycleState.VALIDATED,
        approval_status="APPROVED",
    )
    mem_engine.procedural_memory.save_procedure(proc)

    # 2. Solicitud natural del usuario
    user_prompt = "JESSYCA, utiliza el procedimiento que te enseñé para crear un informe nuevo sobre inteligencia artificial en informe_ia.txt"
    res = brain.process_request(
        user_input=user_prompt,
        session_id="test_session_j",
        tool_executor=lambda a, t, p: (True, {"action": a, "params": p}, None),
    )

    assert res.success is True
    assert res.requires_action is True
    assert res.steps_executed == 2

    # Comprobar que ProceduralMemory registró el resultado de ejecución
    updated = mem_engine.procedural_memory.get_procedure(proc.procedure_id)
    assert updated.success_count >= 1
