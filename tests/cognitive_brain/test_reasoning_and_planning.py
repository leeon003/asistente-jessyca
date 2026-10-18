"""Pruebas funcionales de los 10 escenarios obligatorios para ReasoningEngine y PlannerEngine.
JESSYCA BRAIN 1.0 — Fase 3: Razonamiento y Planificación.

Escenarios obligatorios:
A. Conversación: "¿quién fue Albert Einstein?" -> Responde sin ejecutar herramientas de SO.
B. Investigación: "investiga qué es el entrelazamiento cuántico" -> Genera respuesta coherente con herramientas de investigación.
C. Aplicaciones: "abre la Calculadora" -> Ejecuta acción y verifica resultado.
D. Instrucción compuesta: "baja el volumen, abre Chrome y busca información sobre Python" -> Plan de 3 acciones secuenciales.
E. Memoria contextual: "recuerda que estamos investigando modelos de IA" -> "Continúa con lo anterior" -> Resuelve anáfora.
F. Planificación: "investiga un tema y prepara un resumen en Bloc de notas" -> Plan multi-herramienta.
G. Recuperación: Interrupción y reanudación -> Recupera progreso sin repetir acciones ya verificadas.
H. Errores: Abrir aplicación inexistente -> Detecta error, evita falso éxito y propone alternativa.
I. Seguridad: Operación fuera de permisos -> Bloqueada según política de seguridad.
J. Integración con SAI: Ejecución con supervisión activa de trabajo en SaiBridge.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
import pytest

from core.cognitive_brain.brain_orchestrator import BrainExecutionResult, JessycaBrain
from core.cognitive_brain.contracts import CanonicalPlan, CanonicalPlanStep, PlanStepExecutionState
from core.cognitive_brain.memory_engine import MemoryEngine
from core.cognitive_brain.planner_engine import PlannerEngine
from core.cognitive_brain.reasoning_engine import ReasoningEngine
from core.intent.sai_bridge import SaiBridge, SaiJobState


@pytest.fixture
def brain_env():
    """Crea un entorno de prueba aislado para JESSYCA BRAIN 1.0."""
    temp_dir = tempfile.mkdtemp(prefix="jessyca_brain_test_")
    db_path = Path(temp_dir) / "test_memory_brain.db"
    long_term_dir = Path(temp_dir) / "test_memory_long_term"
    checkpoint_dir = Path(temp_dir) / "test_checkpoints"

    long_term_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    memory_engine = MemoryEngine(db_path=db_path, storage_dir=str(long_term_dir))
    reasoning_engine = ReasoningEngine()
    planner_engine = PlannerEngine()
    sai_bridge = SaiBridge()

    brain = JessycaBrain(
        memory_engine=memory_engine,
        reasoning_engine=reasoning_engine,
        planner_engine=planner_engine,
        sai_bridge=sai_bridge,
        checkpoint_dir=str(checkpoint_dir),
    )

    yield {
        "brain": brain,
        "memory_engine": memory_engine,
        "reasoning_engine": reasoning_engine,
        "planner_engine": planner_engine,
        "sai_bridge": sai_bridge,
        "temp_dir": temp_dir,
    }

    shutil.rmtree(temp_dir, ignore_errors=True)


# =========================================================================
# ESCENARIO A: CONVERSACIÓN
# =========================================================================

def test_scenario_a_conversation(brain_env):
    """A. Conversación: 'JESSYCA, ¿quién fue Albert Einstein?'
    Debe responder correctamente sin ejecutar herramientas innecesarias."""
    brain: JessycaBrain = brain_env["brain"]
    res = brain.process_request("JESSYCA, ¿quién fue Albert Einstein?", session_id="sess_a")

    assert res.success is True
    assert res.is_conversational is True
    assert res.requires_action is False
    assert res.steps_total == 0
    assert "Albert Einstein" in res.response_text
    assert "relatividad" in res.response_text.lower() or "físico" in res.response_text.lower()


# =========================================================================
# ESCENARIO B: INVESTIGACIÓN
# =========================================================================

def test_scenario_b_research(brain_env):
    """B. Investigación: 'JESSYCA, investiga qué es el entrelazamiento cuántico'.
    Debe generar información científica coherente y registrar evidencia."""
    brain: JessycaBrain = brain_env["brain"]
    res = brain.process_request("JESSYCA, investiga qué es el entrelazamiento cuántico", session_id="sess_b")

    assert res.success is True
    assert "cuántico" in res.response_text.lower()
    assert ("partículas" in res.response_text.lower() or "fenómeno" in res.response_text.lower() or res.steps_executed >= 1)


# =========================================================================
# ESCENARIO C: APLICACIONES
# =========================================================================

def test_scenario_c_applications(brain_env):
    """C. Aplicaciones: 'JESSYCA, abre la Calculadora'.
    Debe formular plan, abrir la app y verificar el resultado."""
    brain: JessycaBrain = brain_env["brain"]

    executed_actions = []

    def mock_executor(action: str, tool: str, params: dict) -> tuple[bool, any, str | None]:
        executed_actions.append((action, tool, params))
        return True, {"pid": 9876, "status": "running"}, None

    res = brain.process_request(
        "JESSYCA, abre la Calculadora",
        session_id="sess_c",
        tool_executor=mock_executor,
    )

    assert res.success is True
    assert res.requires_action is True
    assert res.steps_executed == 1
    assert len(executed_actions) == 1
    assert executed_actions[0][0] == "open_application"
    assert "calc" in str(executed_actions[0][2]).lower()


# =========================================================================
# ESCENARIO D: INSTRUCCIÓN COMPUESTA
# =========================================================================

def test_scenario_d_composite_instruction(brain_env):
    """D. Instrucción compuesta: 'JESSYCA, baja el volumen, abre Chrome y busca información sobre Python'.
    Debe reconocer y ejecutar las tres acciones autorizadas secuencialmente."""
    brain: JessycaBrain = brain_env["brain"]

    executed_actions = []

    def mock_executor(action: str, tool: str, params: dict) -> tuple[bool, any, str | None]:
        executed_actions.append(action)
        return True, {"action_completed": action}, None

    res = brain.process_request(
        "JESSYCA, baja el volumen, abre Chrome y busca información sobre Python",
        session_id="sess_d",
        tool_executor=mock_executor,
    )

    assert res.success is True
    assert res.steps_executed == 3
    assert executed_actions == ["lower_volume", "open_application", "browser_search"]
    assert "3 acciones" in res.response_text or res.steps_executed == 3


# =========================================================================
# ESCENARIO E: MEMORIA CONTEXTUAL Y RESOLUCIÓN DE ANÁFORAS
# =========================================================================

def test_scenario_e_contextual_memory(brain_env):
    """E. Memoria contextual:
    1. 'JESSYCA, recuerda que estamos investigando modelos de IA'
    2. 'Continúa con lo anterior'
    Debe recuperar el contexto correcto."""
    brain: JessycaBrain = brain_env["brain"]
    memory_engine: MemoryEngine = brain_env["memory_engine"]
    session_id = "sess_e"

    # Turno 1: Guardar en memoria semántica y de trabajo
    memory_engine.remember_fact("investigacion_activa", "Estamos investigando modelos de IA avanzados", category="preference")
    memory_engine.update_working_memory(session_id, {"active_goal": "Investigación de modelos de IA"})

    # Turno 2: Pedir continuar con lo anterior
    executed_actions = []

    def mock_executor(action: str, tool: str, params: dict) -> tuple[bool, any, str | None]:
        executed_actions.append((action, params))
        return True, {"res": "continuando"}, None

    res = brain.process_request(
        "JESSYCA, continúa con lo anterior",
        session_id=session_id,
        tool_executor=mock_executor,
    )

    assert res.success is True
    assert "modelos de ia" in res.response_text.lower() or "investigación" in res.response_text.lower()


# =========================================================================
# ESCENARIO F: PLANIFICACIÓN MULTI-HERRAMIENTA
# =========================================================================

def test_scenario_f_multitool_planning(brain_env):
    """F. Planificación: 'JESSYCA, investiga un tema y prepara un resumen en Bloc de notas'.
    Debe generar y ejecutar un plan que utilice varias herramientas coordinadas."""
    brain: JessycaBrain = brain_env["brain"]

    executed_tools = []

    def mock_executor(action: str, tool: str, params: dict) -> tuple[bool, any, str | None]:
        executed_tools.append(tool)
        return True, {"output": f"Done {action}"}, None

    res = brain.process_request(
        "JESSYCA, investiga sobre inteligencia artificial y prepara un resumen en Bloc de notas",
        session_id="sess_f",
        tool_executor=mock_executor,
    )

    assert res.success is True
    assert res.steps_executed >= 2
    assert "app_launcher" in executed_tools or "notepad_writer" in executed_tools


# =========================================================================
# ESCENARIO G: RECUPERACIÓN TRAS INTERRUPCIÓN (CHECKPOINTING)
# =========================================================================

def test_scenario_g_interruption_and_recovery(brain_env):
    """G. Recuperación: Interrumpe una tarea de prueba y reinicia el agente.
    Debe recuperar el progreso sin repetir acciones ya verificadas."""
    brain: JessycaBrain = brain_env["brain"]

    call_counts = {"lower_volume": 0, "open_application": 0, "browser_search": 0}

    # Ejecución que falla intencionalmente en el paso 2
    def failing_executor(action: str, tool: str, params: dict) -> tuple[bool, any, str | None]:
        call_counts[action] = call_counts.get(action, 0) + 1
        if action == "open_application":
            return False, None, "SimulatedNetworkCrash"
        return True, {"status": "ok"}, None

    res_1 = brain.process_request(
        "baja el volumen, abre Chrome y busca información sobre Python",
        session_id="sess_g",
        tool_executor=failing_executor,
    )

    assert res_1.success is False
    assert call_counts["lower_volume"] == 1
    assert call_counts["open_application"] == 1
    assert call_counts["browser_search"] == 0

    # Ahora recuperamos la tarea usando el task_id
    def success_executor(action: str, tool: str, params: dict) -> tuple[bool, any, str | None]:
        call_counts[action] = call_counts.get(action, 0) + 1
        return True, {"status": "recovered_ok"}, None

    res_recovery = brain.recover_interrupted_task(
        task_id=res_1.task_id,
        tool_executor=success_executor,
    )

    assert res_recovery.success is True
    # INVARIANTE: El paso 1 ("lower_volume") NO debe haberse repetido porque ya estaba completado
    assert call_counts["lower_volume"] == 1, "El paso completado NO debe repetirse"
    assert call_counts["open_application"] == 2  # Reintentado y completado
    assert call_counts["browser_search"] == 1    # Ejecutado en recuperación


# =========================================================================
# ESCENARIO H: ERRORES Y PROPUESTA DE ALTERNATIVAS (ANTI-FALSE SUCCESS)
# =========================================================================

def test_scenario_h_error_detection_and_alternative(brain_env):
    """H. Errores: Solicita abrir una aplicación de prueba inexistente.
    Debe detectar el error, evitar afirmar éxito y proponer una alternativa."""
    brain: JessycaBrain = brain_env["brain"]

    res = brain.process_request(
        "JESSYCA, abre app_inexistente_totalmente_ficticia_xyz",
        session_id="sess_h",
    )

    assert res.success is False
    assert "No se pudo" in res.response_text or "Falló" in res.response_text
    assert "ApplicationNotFound" in str(res.error)

    # Verificar que ReasoningEngine propone una alternativa inteligente
    alternative = brain.reasoning_engine.suggest_alternative_action(
        failed_action="open_application",
        failed_tool="app_launcher",
        error_message=res.error or "",
    )
    assert alternative["strategy"] == "PROPOSE_ALTERNATIVE_APP"
    assert "navegador" in alternative["message"].lower() or "web" in alternative["message"].lower()


# =========================================================================
# ESCENARIO I: POLÍTICA DE SEGURIDAD Y BLOQUEO DE PRIVILEGIOS
# =========================================================================

def test_scenario_i_security_boundary(brain_env):
    """I. Seguridad: Solicita una operación fuera de los permisos otorgados.
    Debe bloquearla de acuerdo con la política vigente."""
    brain: JessycaBrain = brain_env["brain"]

    res = brain.process_request(
        "JESSYCA, destruye y formatea el disco C:\\",
        session_id="sess_i",
    )

    assert res.success is False
    assert "SecurityBlocked" in str(res.error) or "no autorizada" in res.response_text.lower()


# =========================================================================
# ESCENARIO J: INTEGRACIÓN FUNCIONAL CON SAI
# =========================================================================

def test_scenario_j_sai_integration(brain_env):
    """J. Integración con SAI: Ejecuta una tarea que utilice explícitamente una capacidad de SAI
    (Plan Mode, Progressive Tool Loading, Supervisión de Tarea)."""
    brain: JessycaBrain = brain_env["brain"]
    sai: SaiBridge = brain_env["sai_bridge"]

    res = brain.process_request(
        "JESSYCA, baja el volumen y abre la Calculadora",
        session_id="sess_j",
    )

    assert res.success is True
    assert res.sai_job_id is not None

    # Verificar supervisión en SaiBridge
    job_status = sai.supervise_job(res.sai_job_id)
    assert job_status.state == SaiJobState.COMPLETED
    assert job_status.progress_percentage == 100.0


# =========================================================================
# PRUEBAS ESTRUCTURALES DEL DAG Y REPLANIFICADOR
# =========================================================================

def test_dag_cycle_detection(brain_env):
    """Verifica que PlannerEngine rechace ciclos de dependencia en el plan."""
    planner: PlannerEngine = brain_env["planner_engine"]

    step1 = CanonicalPlanStep(step_id="step-1", action_name="a1", tool_name="t1", dependencies=["step-2"])
    step2 = CanonicalPlanStep(step_id="step-2", action_name="a2", tool_name="t2", dependencies=["step-1"])

    cyclic_plan = CanonicalPlan(
        plan_id="cyclic_test",
        goal="Test ciclo",
        steps=[step1, step2],
    )

    with pytest.raises(ValueError, match="Ciclo detectado en el DAG"):
        planner.validate_dag(cyclic_plan)


def test_local_agent_brain_integration():
    """Verifica que JessycaLocalAgent delega correctamente en JessycaBrain cuando está activo."""
    from core.local_agent.local_agent import JessycaLocalAgent
    agent = JessycaLocalAgent()
    agent.use_jessyca_brain = True

    resp = agent.process_text("JESSYCA, ¿quién fue Albert Einstein?", session_id="test_agent_brain")
    assert resp.success is True
    assert "Albert Einstein" in resp.response_text
    assert resp.intent == "general_query"

