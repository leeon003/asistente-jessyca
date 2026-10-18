"""test_fase2_real_conversation.py
Validación Conversacional Real con Ollama (llama3.2:latest) sin mocks.
Evalúa:
1. "JESSYCA, ¿quién fue Albert Einstein?"
2. "JESSYCA, explícame el entrelazamiento cuántico".
3. "JESSYCA, ¿qué diferencia existe entre inteligencia artificial y aprendizaje automático?"
4. "JESSYCA, explícame de otra manera".
5. "JESSYCA, continúa con lo anterior".
"""
import time
import pytest
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import JessycaRequest, InputModality

def test_live_conversation_ollama():
    agent = JessycaLocalAgent.get_instance()
    session_id = f"test-fase2-real-conv-{int(time.time())}"

    prompts = [
        "JESSYCA, ¿quién fue Albert Einstein?",
        "JESSYCA, explícame el entrelazamiento cuántico.",
        "JESSYCA, ¿qué diferencia existe entre inteligencia artificial y aprendizaje automático?",
        "JESSYCA, explícame de otra manera.",
        "JESSYCA, continúa con lo anterior.",
    ]

    results = []

    for prompt in prompts:
        t0 = time.perf_counter()
        req = JessycaRequest(user_input=prompt, session_id=session_id, modality=InputModality.TEXT)
        res = agent.interact(req)
        elapsed = time.perf_counter() - t0

        print(f"\n========================================================")
        print(f"PROMPT: {prompt}")
        print(f"LATENCIA: {elapsed:.2f}s | ÉXITO: {res.success}")
        print(f"RESPUESTA:\n{res.response_text}")
        print(f"HERRAMIENTAS ACTIVADAS: {res.tools_executed}")
        print(f"========================================================")

        assert res.success is True
        assert len(res.response_text.strip()) > 20
        # No debe activar herramientas del sistema para preguntas puramente conversacionales
        assert len(res.tools_executed) == 0, f"No debió activar herramientas para '{prompt}', activó: {res.tools_executed}"
        results.append((prompt, res.response_text, elapsed))

    # Verificar que el contexto se mantuvo entre turnos 4 y 5
    p3, r3, _ = results[2]
    p4, r4, _ = results[3]
    p5, r5, _ = results[4]

    # En r4 y r5 se debe seguir hablando de IA o conceptos relacionados
    combined = (r4 + " " + r5).lower()
    assert any(w in combined for w in ["inteligencia", "aprendizaje", "automático", "modelo", "datos", "máquina", "ia", "algoritmo"]), \
        f"Contexto no mantenido en r4/r5: {combined[:200]}"
