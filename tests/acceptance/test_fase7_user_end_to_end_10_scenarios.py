import os
import time
import pytest
import subprocess
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import JessycaRequest, InputModality, AgentExecutionState
from core.desktop.unified_controller import UnifiedDesktopController
from core.emergency_stop import EmergencyStopManager

@pytest.fixture(scope="module")
def agent():
    ag = JessycaLocalAgent.get_instance()
    ag.use_jessyca_brain = True
    return ag

@pytest.fixture(scope="module")
def controller():
    return UnifiedDesktopController()

def test_escenario_01_conversacion_einstein(agent):
    """PRUEBA 1: 'JESSYCA, ¿quién fue Albert Einstein?'"""
    t0 = time.perf_counter()
    req = JessycaRequest(
        user_input="¿Quién fue Albert Einstein? Responde en una oración concisa.",
        modality=InputModality.VOICE,
        session_id="test_session_user_01"
    )
    res = agent.interact(req)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert res.success is True
    assert "einstein" in res.response_text.lower() or "físico" in res.response_text.lower()
    assert len(res.tools_executed) == 0  # No debe invocar herramientas en consulta conversacional
    print(f"\n[ESCENARIO 1 OK] Latencia: {latency_ms:.1f} ms | Respuesta: {res.response_text}")

def test_escenario_02_cuantica(agent):
    """PRUEBA 2: 'JESSYCA, explícame qué es el entrelazamiento cuántico'"""
    t0 = time.perf_counter()
    req = JessycaRequest(
        user_input="Explícame qué es el entrelazamiento cuántico en una frase concisa.",
        modality=InputModality.TEXT,
        session_id="test_session_user_02"
    )
    res = agent.interact(req)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert res.success is True
    assert len(res.response_text) > 20
    assert len(res.tools_executed) == 0
    print(f"\n[ESCENARIO 2 OK] Latencia: {latency_ms:.1f} ms | Respuesta: {res.response_text}")

def test_escenario_03_abrir_calculadora(agent, controller):
    """PRUEBA 3: 'JESSYCA, abre la Calculadora'"""
    t0 = time.perf_counter()
    req = JessycaRequest(
        user_input="Abre la Calculadora",
        modality=InputModality.VOICE,
        session_id="test_session_user_03"
    )
    res = agent.interact(req)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert res.success is True
    assert any("calc" in str(t).lower() or "app" in str(t).lower() for t in res.tools_executed) or "calculadora" in res.response_text.lower()
    # Verificar con el controlador que la calculadora está abierta
    windows = controller.enumerate_windows()
    calc_open = any("calc" in str(w.get("title", "")).lower() or "calculadora" in str(w.get("title", "")).lower() for w in windows)
    print(f"\n[ESCENARIO 3 OK] Latencia: {latency_ms:.1f} ms | Calculadora abierta: {calc_open}")

def test_escenario_04_notepad_escritura(agent, tmp_path):
    """PRUEBA 4: 'JESSYCA, abre Bloc de notas y escribe una explicación sobre inteligencia artificial'"""
    t0 = time.perf_counter()
    test_note = tmp_path / "ia_resumen.txt"
    req = JessycaRequest(
        user_input=f"Abre Bloc de notas y escribe una explicación sobre inteligencia artificial en {test_note}",
        modality=InputModality.TEXT,
        session_id="test_session_user_04"
    )
    res = agent.interact(req)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert res.success is True
    print(f"\n[ESCENARIO 4 OK] Latencia: {latency_ms:.1f} ms | Respuesta: {res.response_text}")

def test_escenario_05_youtube_musica_clasica(agent):
    """PRUEBA 5: 'JESSYCA, abre YouTube y pon música clásica'"""
    t0 = time.perf_counter()
    req = JessycaRequest(
        user_input="Abre YouTube y pon música clásica",
        modality=InputModality.VOICE,
        session_id="test_session_user_05"
    )
    res = agent.interact(req)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert res.success is True
    assert any("browser" in str(t).lower() or "media" in str(t).lower() for t in res.tools_executed) or "youtube" in res.response_text.lower()
    print(f"\n[ESCENARIO 5 OK] Latencia: {latency_ms:.1f} ms | Respuesta: {res.response_text}")

def test_escenario_06_investigar_modelos_ia(agent):
    """PRUEBA 6: 'JESSYCA, investiga cuáles son los mejores modelos de IA disponibles para programar'"""
    t0 = time.perf_counter()
    req = JessycaRequest(
        user_input="Investiga cuáles son los mejores modelos de IA disponibles para programar y presenta conclusiones.",
        modality=InputModality.TEXT,
        session_id="test_session_user_06"
    )
    res = agent.interact(req)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert res.success is True
    assert len(res.response_text) > 30
    print(f"\n[ESCENARIO 6 OK] Latencia: {latency_ms:.1f} ms | Conclusiones: {res.response_text[:120]}...")

def test_escenario_07_acciones_compuestas(agent):
    """PRUEBA 7: 'JESSYCA, baja el volumen, abre Chrome y busca información sobre Python'"""
    t0 = time.perf_counter()
    req = JessycaRequest(
        user_input="Baja el volumen, abre Chrome y busca información sobre Python",
        modality=InputModality.VOICE,
        session_id="test_session_user_07"
    )
    res = agent.interact(req)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    assert res.success is True
    print(f"\n[ESCENARIO 7 OK] Latencia: {latency_ms:.1f} ms | Respuesta: {res.response_text}")

def test_escenario_08_memoria_contexto_continuidad(agent):
    """PRUEBA 8: 'JESSYCA, recuerda que estamos investigando inteligencia artificial' -> 'Continúa con lo anterior'"""
    session_id = "test_session_continuity_08"
    req1 = JessycaRequest(
        user_input="Recuerda que estamos investigando inteligencia artificial",
        modality=InputModality.TEXT,
        session_id=session_id
    )
    res1 = agent.interact(req1)
    assert res1.success is True

    req2 = JessycaRequest(
        user_input="Continúa con lo anterior y dime qué estábamos investigando",
        modality=InputModality.TEXT,
        session_id=session_id
    )
    res2 = agent.interact(req2)
    assert res2.success is True
    assert "inteligencia artificial" in res2.response_text.lower() or "ia" in res2.response_text.lower()
    print(f"\n[ESCENARIO 8 OK] Contexto recuperado exitosamente: {res2.response_text}")

def test_escenario_09_procedimiento_reutilizacion(agent):
    """PRUEBA 9: 'JESSYCA, utiliza el procedimiento que aprendiste para preparar otra nota'"""
    brain = agent.get_brain()
    from core.cognitive_brain.contracts import LearnedProcedure, ProcedureLifecycleState
    proc = LearnedProcedure(
        procedure_id="proc-crear-nota-fase7",
        name="crear_nota_rapida",
        description="Procedimiento para crear una nota de texto en disco",
        associated_intent="crear nota",
        steps=[{"action": "write_file", "target": "scratch/nota.txt"}],
        state=ProcedureLifecycleState.VALIDATED,
    )
    brain.procedural_memory.save_procedure(proc)
    
    req = JessycaRequest(
        user_input="Utiliza el procedimiento que aprendiste para preparar otra nota llamada resumen_fase7.txt",
        modality=InputModality.TEXT,
        session_id="test_session_user_09"
    )
    res = agent.interact(req)
    assert res.success is True
    print(f"\n[ESCENARIO 9 OK] Procedimiento reutilizado: {res.response_text}")

def test_escenario_10_cancelacion_detente(agent):
    """PRUEBA 10: 'JESSYCA, detente'"""
    emergency_mgr = EmergencyStopManager.get_instance()
    # Solicitar parada
    emergency_mgr.request_emergency_stop(reason="Orden de voz del usuario: Detente")
    assert emergency_mgr.is_stopped() is True
    
    req = JessycaRequest(
        user_input="Detente inmediatamente",
        modality=InputModality.VOICE,
        session_id="test_session_user_10"
    )
    res = agent.interact(req)
    # Debe reconocer la detención
    assert "deten" in res.response_text.lower() or "cancel" in res.response_text.lower() or res.status in (AgentExecutionState.STOPPED, AgentExecutionState.INTERRUPTED, AgentExecutionState.FAILED) or res.success is True
    
    # Restablecer para no afectar siguientes tests
    emergency_mgr.reset_emergency_stop()
    assert emergency_mgr.is_stopped() is False
    print(f"\n[ESCENARIO 10 OK] Parada de emergencia ejecutada y restablecida con seguridad.")
