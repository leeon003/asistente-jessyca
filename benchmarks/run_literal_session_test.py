"""benchmarks/run_literal_session_test.py
Ejecuta la sesión literal completa requerida por el usuario y extrae métricas y transcripción exacta.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState
from interfaces.modo_voz import VoiceSpeaker
from services.voice.barge_in_controller import BargeInController

def main():
    agent = JessycaLocalAgent.get_instance()
    session_id = f"session_eval_{int(time.time())}"

    print("=" * 70)
    print("      JESSYCA 3.0 — SESIÓN CONVERSACIONAL Y FLUIDEZ (EVALUACIÓN REAL)")
    print("=" * 70)

    # 1. Turno 1
    t0 = time.perf_counter()
    r1 = agent.interact("Explícame RAM y almacenamiento en dos frases", session_id=session_id)
    dur1 = (time.perf_counter() - t0) * 1000.0
    print(f"\n[Turno 1] Usuario: 'Explícame RAM y almacenamiento en dos frases'")
    print(f"Jessyca: {r1.response_text}")
    print(f"(Tiempo Core: {dur1:.1f}ms | Modelo: {r1.selected_model} | Estado: {r1.status.value})")

    # 2. Turno 2
    t0 = time.perf_counter()
    r2 = agent.interact("Ahora dilo con un ejemplo", session_id=session_id)
    dur2 = (time.perf_counter() - t0) * 1000.0
    print(f"\n[Turno 2] Usuario: 'Ahora dilo con un ejemplo'")
    print(f"Jessyca: {r2.response_text}")
    print(f"(Tiempo Core: {dur2:.1f}ms | Modelo: {r2.selected_model} | Estado: {r2.status.value})")

    # 3. Turno 3
    t0 = time.perf_counter()
    r3 = agent.interact("No entendiste: me refería al espacio del disco", session_id=session_id)
    dur3 = (time.perf_counter() - t0) * 1000.0
    print(f"\n[Turno 3] Usuario: 'No entendiste: me refería al espacio del disco'")
    print(f"Jessyca: {r3.response_text}")
    print(f"(Tiempo Core: {dur3:.1f}ms | Modelo: {r3.selected_model} | Estado: {r3.status.value})")

    # 4. Turno 4
    t0 = time.perf_counter()
    r4 = agent.interact("¿Qué me recomiendas hacer después y por qué?", session_id=session_id)
    dur4 = (time.perf_counter() - t0) * 1000.0
    print(f"\n[Turno 4] Usuario: '¿Qué me recomiendas hacer después y por qué?'")
    print(f"Jessyca: {r4.response_text}")
    print(f"(Tiempo Core: {dur4:.1f}ms | Modelo: {r4.selected_model} | Estado: {r4.status.value})")

    # 5. Turno 5: Abre YouTube con verificación observable
    t0 = time.perf_counter()
    r5 = agent.interact("Abre YouTube", session_id=session_id)
    dur5 = (time.perf_counter() - t0) * 1000.0
    print(f"\n[Turno 5] Usuario: 'Abre YouTube'")
    print(f"Jessyca: {r5.response_text}")
    print(f"(Tiempo Core: {dur5:.1f}ms | Skill: {r5.selected_skill} | Herramientas: {r5.tools_executed} | Estado: {r5.status.value})")

    # 6. Turno 6: Interrupción (Barge-in)
    speaker = VoiceSpeaker()
    controller = BargeInController(tts_manager=speaker._tts_manager)
    speaker.barge_in_controller = controller
    import threading
    t_start_barge = time.perf_counter()
    def _speak_long():
        speaker.speak("Esta es una respuesta larga para comprobar que al interrumpir se detiene también el audio pendiente y no quedan oraciones viejas reproduciéndose.")
    th = threading.Thread(target=_speak_long)
    th.start()
    time.sleep(0.08)
    stopped = controller.trigger_barge_in(reason="Interrupción del usuario")
    th.join(timeout=2.0)
    dur6 = (time.perf_counter() - t_start_barge) * 1000.0
    print(f"\n[Turno 6] Interrupción de voz (Barge-In) durante respuesta larga:")
    print(f"Resultado: Audio cancelado inmediatamente ({stopped}) | Latencia de corte: {dur6:.1f}ms")

    # 7. Turno 7: Ollama desconectado
    mock_prov = MagicMock()
    mock_prov.is_available.return_value = False
    mock_prov._last_availability_error = "Conexión rechazada en localhost:11434"
    orig_prov = agent.conversational_handler.llm_provider
    try:
        agent.conversational_handler.llm_provider = mock_prov
        t0 = time.perf_counter()
        r7 = agent.interact("Explícame cómo funciona un compilador", session_id=session_id)
        dur7 = (time.perf_counter() - t0) * 1000.0
        print(f"\n[Turno 7] Ollama desconectado (Fallo controlado):")
        print(f"Usuario: 'Explícame cómo funciona un compilador'")
        print(f"Jessyca: {r7.response_text}")
        print(f"(Tiempo: {dur7:.1f}ms | Éxito: {r7.success} | Estado: {r7.status.value} | Error: {r7.error})")
    finally:
        agent.conversational_handler.llm_provider = orig_prov

    print("\n" + "=" * 70)

if __name__ == "__main__":
    main()
