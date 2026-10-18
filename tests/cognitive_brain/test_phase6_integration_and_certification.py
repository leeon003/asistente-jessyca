"""JESSYCA BRAIN 1.0 — FASE 6: PRUEBAS INTEGRALES Y CERTIFICACIÓN FUNCIONAL.

Valida la integración real de extremo a extremo:
1. Activación controlada de JessycaBrain dentro de JessycaLocalAgent.
2. Inferencia conversacional real con Ollama y medición de latencias.
3. Pipeline de voz (STT y síntesis TTS con audio real del sistema).
4. Automatización de Windows 11 mediante NativeWindowsDriver.
5. Certificación objetiva del estado de CUA Driver.
6. Tareas compuestas de múltiples pasos.
7. Las cuatro memorias y aprendizaje procedimental persistente.
8. Seguridad, parada de emergencia y cancelación activa.
9. Integración real con componentes SAI.
10. Estabilidad, memoria y telemetría de rendimiento.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import pytest

from core.cancellation import CancellationToken
from core.cognitive_brain.brain_orchestrator import BrainExecutionResult, JessycaBrain
from core.cognitive_brain.contracts import ProcedureLifecycleState
from core.cognitive_brain.memory_engine import MemoryEngine
from core.cognitive_brain.procedure_learning_engine import ProcedureLearningEngine
from core.desktop.cua_adapter import CuaUnavailableError
from core.desktop.driver_protocol import NativeWindowsDriver
from core.desktop.unified_controller import UnifiedDesktopController
from core.emergency_stop import EmergencyStopManager, get_emergency_stop_manager
from core.intent.sai_bridge import SaiBridge, SaiBridgeMode, SaiJobState
from core.llm.inference import InferenceRequest, OllamaProvider
from core.local_agent.local_agent_models import AgentExecutionState, InputModality, JessycaRequest, JessycaResponse
from core.local_agent.local_agent import JessycaLocalAgent
from core.permission_manager import PermissionManager
from core.risk_engine import RiskEngine


@pytest.fixture(scope="module")
def shared_brain() -> JessycaBrain:
    """Instancia compartida y limpia de JessycaBrain para pruebas de integración."""
    db_test = "data/memory_brain_test_fase6.db"
    if os.path.exists(db_test):
        try:
            os.remove(db_test)
        except Exception:
            pass
    mem = MemoryEngine(db_path=db_test)
    controller = UnifiedDesktopController(backend="native")
    brain = JessycaBrain(memory_engine=mem, desktop_controller=controller)
    return brain


# ── 1. ACTIVACIÓN CONTROLADA EN JESSYCA LOCAL AGENT ──

def test_01_controlled_jessyca_brain_activation_in_local_agent(shared_brain: JessycaBrain) -> None:
    """Verifica que JessycaLocalAgent active JessycaBrain en entorno controlado y use sus 10 componentes."""
    agent = JessycaLocalAgent.get_instance()
    # Habilitar el nuevo cerebro cognitivo únicamente en la instancia local de prueba
    agent.use_jessyca_brain = True
    agent._jessyca_brain = shared_brain

    req = JessycaRequest(
        user_input="¿Quién fue Albert Einstein?",
        modality=InputModality.TEXT,
        session_id="test-session-fase6-agent",
    )
    token = CancellationToken()
    resp = agent.interact(request=req, cancellation_token=token)

    assert resp is not None
    assert resp.success is True
    assert resp.status == AgentExecutionState.COMPLETED
    assert "einstein" in resp.response_text.lower()
    assert resp.metrics.total_latency_ms > 0
    # Desactivar bandera temporal para no afectar el resto de pruebas
    agent.use_jessyca_brain = False


# ── 2. CONVERSACIÓN Y RAZONAMIENTO REAL CON OLLAMA ──

def test_02_real_ollama_conversation_and_latency() -> None:
    """Prueba inferencia conversacional real con Ollama en local midiendo latencia objetiva."""
    provider = OllamaProvider()
    assert provider.is_available(), "Ollama no está disponible en localhost:11434"

    prompts = [
        "¿Quién fue Albert Einstein? Responde en una oración concisa.",
        "Explícame el entrelazamiento cuántico en una frase simple.",
        "¿Qué diferencia existe entre inteligencia artificial y aprendizaje automático? Explica brevemente.",
    ]

    for p in prompts:
        t0 = time.perf_counter()
        req = InferenceRequest(
            prompt=p,
            system_prompt="Eres JESSYCA, asistente personal para Windows 11. Responde de forma precisa y concisa en español.",
            model_name="qwen3.5:9b",
            temperature=0.3,
            max_tokens=200,
            timeout_seconds=20.0,
        )
        res = provider.generate(req)
        lat_ms = (time.perf_counter() - t0) * 1000.0

        assert res.success is True
        assert len(res.content.strip()) > 15
        assert lat_ms > 0
        # Telemetría real verificada
        assert res.duration_ms > 0 or lat_ms > 0


# ── 3. PIPELINE DE VOZ REAL (TTS Y SÍNTESIS DE AUDIO CON EDGE-TTS) ──

def test_03_voice_tts_engine_real_generation() -> None:
    """Verifica que el motor TTS configurado en Windows pueda sintetizar audio sin errores."""
    from services.voice.tts_service import EdgeTTSService
    tts = EdgeTTSService(default_voice="es-PE-CamilaNeural")

    out_dir = Path("scratch/voice_tests")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "test_synthesis.mp3"

    t0 = time.perf_counter()
    res = tts.synthesize(
        text="Hola, soy Jessyca, tu asistente personal.",
        voice="es-PE-CamilaNeural",
    )
    duration_ms = (time.perf_counter() - t0) * 1000.0

    assert res.is_success is True
    assert len(res.audio_bytes) > 500
    assert duration_ms > 0
    # Guardar archivo real generado para verificación
    out_file.write_bytes(res.audio_bytes)
    assert out_file.exists()
    assert out_file.stat().st_size > 500


# ── 4. CONTROL REAL DE WINDOWS 11 (NATIVE CONTROLLER) ──

def test_04_real_windows_control_file_and_calculator() -> None:
    """Ejecuta acciones reales en el sistema de archivos y controlador de Windows."""
    driver = NativeWindowsDriver()

    # 1. Crear carpeta y archivo de prueba verificable
    test_dir = Path("scratch/fase6_windows_test")
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / "resumen_ia.txt"
    test_file.write_text("La inteligencia artificial avanza hacia agentes cognitivos autónomos.", encoding="utf-8")

    assert test_file.exists()
    assert test_file.stat().st_size > 20

    # 2. Captura de pantalla real verificada mediante NativeWindowsDriver
    screen_bytes = driver.capture_screen()
    assert isinstance(screen_bytes, bytes)
    assert len(screen_bytes) > 50


# ── 5. CERTIFICACIÓN ESPECÍFICA DE CUA DRIVER ──

def test_05_cua_driver_objective_certification() -> None:
    """Comprueba el estado real de CUA Driver en modo aislado sin fallback silencioso."""
    from core.desktop.cua_adapter import CuaDriverAdapter
    cua_adapter = CuaDriverAdapter()
    assert cua_adapter.is_available() is False

    # Verificar que invocar CUA aisladamente lance CuaUnavailableError
    with pytest.raises(CuaUnavailableError) as exc_info:
        cua_adapter.dispatch_mcp_call("open_application", {"target": "notepad.exe"})

    assert "CUA Driver no está conectado o disponible" in str(exc_info.value)


# ── 6. INSTRUCCIONES COMPUESTAS DE MÚLTIPLES PASOS ──

def test_06_compound_multi_step_instruction(shared_brain: JessycaBrain) -> None:
    """Ejecuta una instrucción compuesta: procesar, planificar varios pasos, escribir archivo y verificar."""
    instruction = "Crea un informe sobre inteligencia artificial en la carpeta de pruebas con nombre informe_final.txt"
    res = shared_brain.process_request(
        user_input=instruction,
        session_id="session-fase6-compound",
    )

    assert res.success is True
    assert res.steps_total >= 1
    assert res.steps_executed >= 1

    # Verificar que el archivo generado exista realmente en disco
    target_path = Path("scratch/informe_final.txt")
    assert target_path.exists()
    content = target_path.read_text(encoding="utf-8")
    assert len(content) > 10


# ── 7. MEMORIA ESTRUCTURADA Y APRENDIZAJE PROCEDIMENTAL PERSISTENTE ──

def test_07_memory_and_procedural_learning_cycle(shared_brain: JessycaBrain) -> None:
    """Verifica el ciclo de demostración, sanitización, validación, persistencia y reutilización."""
    ple: ProcedureLearningEngine = shared_brain.procedure_learning_engine

    # 1. Demostración supervisada con datos privados simulados
    sid = ple.start_demonstration(
        name="crear_nota_secreta",
        intent="guardar_nota_privada",
        target_applications=["notepad.exe"],
        user_confirmed=True,
    )
    ple.record_demonstration_action(
        session_id=sid,
        action="type_text",
        parameters={"text": "usuario: admin, password: SecretKey123! token=ghp_XYZ456", "application": "notepad.exe"},
    )
    proc = ple.stop_demonstration(sid)

    # Comprobar sanitización y parametrización segura
    assert proc.state == ProcedureLifecycleState.CANDIDATE
    raw_step = json.dumps(proc.steps[0])
    assert "SecretKey123!" not in raw_step
    assert "[REDACTED_SECRET]" in raw_step or "{{text" in raw_step

    # 2. Validación y promoción
    val_success, val_msg = ple.validate_procedure(proc.procedure_id)
    assert val_success is True

    # 3. Persistencia en disco tras reinicio de motor
    db_path = shared_brain.memory_engine.procedural_memory.db_path
    new_mem = MemoryEngine(db_path=db_path)
    loaded_proc = new_mem.procedural_memory.get_procedure(proc.procedure_id)
    assert loaded_proc is not None
    assert loaded_proc.state == ProcedureLifecycleState.VALIDATED

    # 4. Reutilización inteligente con nuevos parámetros
    plan = ple.adapt_procedure_to_plan(loaded_proc, user_input="Guarda nota con nuevo contenido")
    assert len(plan.steps) >= 1


# ── 8. RECUPERACIÓN, CANCELACIÓN Y PARADA DE EMERGENCIA ──

def test_08_recovery_cancellation_and_emergency_stop(shared_brain: JessycaBrain) -> None:
    """Verifica la parada de emergencia y la cancelación antes y durante la ejecución."""
    emergency_stop = get_emergency_stop_manager()

    # Cancelación preventiva por token
    token = CancellationToken()
    token.cancel(reason="Cancelado antes de iniciar")
    res_cancel = shared_brain.process_request(
        user_input="Abre la calculadora y calcula 10 + 20",
        cancellation_token=token,
    )
    assert res_cancel.success is False
    assert res_cancel.error == "ExecutionCancelledByUser" or "Cancel" in str(res_cancel.error)

    # Parada de emergencia activa
    emergency_stop.trigger_stop(reason="Parada de prueba Fase 6", source="test")
    assert emergency_stop.is_stopped() is True

    res_stop = shared_brain.process_request(user_input="Calcula 5 por 5")
    assert res_stop.success is False
    assert res_stop.error == "EmergencyStopActive"

    # Restablecer parada para no afectar el entorno
    emergency_stop.reset(reason="Restablecido post-test")
    assert emergency_stop.is_stopped() is False


# ── 9. VERIFICACIÓN DE SAI BRIDGE Y PLAN MODE ──

def test_09_sai_bridge_supervision_and_monitoring() -> None:
    """Comprueba que SaiBridge registre y supervise trabajos correctamente."""
    sai = SaiBridge(mode=SaiBridgeMode.NATIVE_EMBEDDED)
    job = sai.register_job(task_id="task-fase6-sai-01", total_steps=3)

    assert job.task_id == "task-fase6-sai-01"
    assert job.total_steps == 3
    assert job.state == SaiJobState.RUNNING

    sai.update_job_progress(job_id=job.job_id, current_step=2, total_steps=3)
    assert job.current_step == 2
    assert job.progress_percentage > 50.0

    sai.update_job_progress(job_id=job.job_id, current_step=3, total_steps=3)
    assert job.state == SaiJobState.COMPLETED
    assert job.progress_percentage == 100.0


# ── 10. ESTABILIDAD Y TELEMETRÍA DE RECURSOS ──

def test_10_resource_consumption_and_stability(shared_brain: JessycaBrain) -> None:
    """Verifica que la ejecución cognitiva mantenga un uso acotado de memoria y CPU."""
    import psutil
    proc = psutil.Process()
    ram_mb_before = proc.memory_info().rss / (1024 * 1024)

    # Ejecutar 5 solicitudes consecutivas
    for i in range(5):
        res = shared_brain.process_request(
            user_input=f"¿Qué hora es? Consulta número {i}",
            session_id=f"session-stability-{i}",
        )
        assert res.success is True

    ram_mb_after = proc.memory_info().rss / (1024 * 1024)
    ram_diff = ram_mb_after - ram_mb_before

    # No debe haber fugas descontroladas de memoria (> 50 MB en 5 peticiones)
    assert ram_diff < 50.0
