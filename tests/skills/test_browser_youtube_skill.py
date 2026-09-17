"""Tests exhaustivos para la FASE 75.1 — YouTube Task Execution & Verification.

Prueba:
1. "Abre YouTube" -> open_browser (browser.open).
2. "Busca Playing Your Face en YouTube" -> youtube_search.
3. "Reproduce Playing Your Face en YouTube" -> youtube_play (no general_query).
4. Ejecución de reproducción exitosa -> Execution=SUCCEEDED, Verification=VERIFIED.
5. Ejecución falla (SEARCH) -> No continuar a reproducción, informar fallo.
6. Ejecución falla (PLAY) -> Informar que no se pudo iniciar reproducción.
7. No se puede verificar -> Verification=NOT_VERIFIABLE, no afirmar éxito falaz.
8. Tarea compuesta: OPEN -> SEARCH -> SELECT -> PLAY -> VERIFY.
9. Conversación multi-turno ("Abre YouTube" -> "Busca Playing Your Face" -> "Reprodúcelo").
10. Variaciones de STT ("play in your face", "la música playing your face").
11. Búsqueda web general no rota ("Busca qué es la segunda ley de Newton").
12. End-to-end con LocalAgent no produce general_query.
"""

import pytest

from core.local_agent.conversation_context import ConversationContextManager
from core.local_agent.local_agent import JessycaLocalAgent
from core.routing.fast_router import FastRouter
from skills.browser_youtube_skill import BrowserYouTubeSkill


from collections.abc import Generator

@pytest.fixture
def ctx() -> Generator[ConversationContextManager, None, None]:
    """Crea una instancia fresca de ConversationContextManager."""
    manager = ConversationContextManager()
    manager.reset_all()
    yield manager
    manager.reset_all()


# ── TEST 1: "Abre YouTube" ──
def test_intent_abre_youtube() -> None:
    router = FastRouter()
    decision = router.route("Abre YouTube")
    assert decision.intent in ("open_browser", "browser_open")
    assert decision.target_skill == "browser.open"
    assert "youtube.com" in str(decision.parameters.get("url"))


# ── TEST 2: "Busca Playing Your Face en YouTube" ──
def test_intent_busca_en_youtube() -> None:
    router = FastRouter()
    decision = router.route("Busca Playing Your Face en YouTube")
    assert decision.intent == "youtube_search"
    assert decision.target_skill == "browser.youtube"
    assert "playing your face" in decision.parameters.get("query", "").lower()


# ── TEST 3: "Reproduce Playing Your Face en YouTube" ──
def test_intent_reproduce_en_youtube() -> None:
    router = FastRouter()
    decision = router.route("Reproduce la música playing Your Face en YouTube")
    assert decision.intent == "youtube_play"
    assert decision.target_skill == "browser.youtube"
    assert decision.intent != "general_query"
    assert "playing your face" in decision.parameters.get("query", "").lower()


# ── TEST 4: Ejecución exitosa de reproducción sin auto-certificación (Fase 1) ──
def test_skill_execution_success() -> None:
    skill = BrowserYouTubeSkill()
    res = skill.execute({"operacion": "play", "query": "Playing Your Face", "video_id": "lKYQZrBm040"})  # type: ignore[arg-type]
    assert res.success is True
    result = res.output
    assert result["exito"] is True
    assert result["verification_status"] == "UNVERIFIED"
    assert result["verified"] is False
    assert result["verification_required"] is True
    assert "lKYQZrBm040" in result["url"]
    assert "reproducir" in result["mensaje"].lower()


# ── TEST 5: Fallo en SEARCH no debe continuar a PLAY ──
def test_skill_execution_search_failure() -> None:
    skill = BrowserYouTubeSkill()
    res = skill.execute({  # type: ignore[arg-type]
        "operacion": "play",
        "query": "cancion_inexistente_12345",
        "simulated_search_failure": True,
    })
    assert res.success is False
    result = res.output
    assert result["exito"] is False
    assert result["step"] == "SEARCH_YOUTUBE"
    assert result["error_code"] == "SEARCH_FAILED"
    assert result["verified"] is False
    assert "No pude encontrar" in result["mensaje"]


# ── TEST 6: Fallo en PLAY no debe afirmar reproducción ──
def test_skill_execution_play_failure() -> None:
    skill = BrowserYouTubeSkill()
    res = skill.execute({  # type: ignore[arg-type]
        "operacion": "play",
        "query": "Playing Your Face",
        "video_id": "lKYQZrBm040",
        "simulated_play_failure": True,
    })
    assert res.success is False
    result = res.output
    assert result["exito"] is False
    assert result["step"] == "PLAY_MEDIA"
    assert result["error_code"] == "PLAYBACK_FAILED"
    assert result["verified"] is False
    assert "no pude iniciar la reproducción" in result["mensaje"].lower()


# ── TEST 7: No verificable (NOT_VERIFIABLE) no debe afirmar éxito absoluto ──
def test_skill_execution_unverifiable() -> None:
    skill = BrowserYouTubeSkill()
    res = skill.execute({  # type: ignore[arg-type]
        "operacion": "play",
        "query": "Playing Your Face",
        "video_id": "lKYQZrBm040",
        "simulate_unverifiable": True,
    })
    result = res.output
    assert result["verification_status"] == "NOT_VERIFIABLE"
    assert result["verified"] is False
    assert "no fue posible verificar" in result["mensaje"]


# ── TEST 8: Tarea compuesta (OPEN -> SEARCH -> SELECT -> PLAY) sin auto-certificación ──
def test_skill_compound_task_steps() -> None:
    skill = BrowserYouTubeSkill()
    res = skill.execute({  # type: ignore[arg-type]
        "operacion": "compound_open_and_play",
        "query": "Playing Your Face",
        "video_id": "lKYQZrBm040",
    })
    assert res.success is True
    result = res.output
    assert result["exito"] is True
    steps = result.get("steps_executed", ())
    assert "OPEN_YOUTUBE" in steps
    assert "SEARCH_YOUTUBE" in steps
    assert "SELECT_RESULT" in steps
    assert "PLAY_MEDIA" in steps
    assert result["step"] == "PLAY_MEDIA"
    assert result["verification_status"] == "UNVERIFIED"
    assert result["verified"] is False


# ── TEST 9: Conversación multi-turno ("Abre YouTube" -> "Busca X" -> "Reprodúcelo") ──
def test_multiturn_conversation(ctx: ConversationContextManager) -> None:
    session_id = "test_yt_session"

    # Turno 1: "Abre YouTube"
    t1_intent, t1_params, _, _ = ctx.resolve_contextual_turn(session_id, "Abre YouTube")
    assert t1_intent in ("open_browser", "browser_open")
    assert "youtube.com" in t1_params.get("url", "")
    ctx.record_turn(session_id, "Abre YouTube", "Listo, abrí YouTube.", t1_intent)

    # Turno 2: "Busca Playing Your Face"
    t2_intent, t2_params, _, _ = ctx.resolve_contextual_turn(session_id, "Busca Playing Your Face")
    assert t2_intent == "youtube_search"
    assert "playing your face" in t2_params.get("query", "").lower()
    ctx.record_turn(session_id, "Busca Playing Your Face", "Encontré resultados.", t2_intent)

    # Turno 3: "Reprodúcelo"
    t3_intent, t3_params, _, _ = ctx.resolve_contextual_turn(session_id, "Reprodúcelo")
    assert t3_intent == "youtube_play"
    assert "playing your face" in t3_params.get("query", "").lower()


# ── TEST 10: Variaciones de STT toleradas ──
@pytest.mark.parametrize(
    "phrase,expected_query",
    [
        ("reproduce la música playing your face en youtube", "playing your face"),
        ("reproduce Playing Your Face", "playing your face"),
        ("pon la canción playing your face", "playing your face"),
        ("abre youtube y reproduce playing your face", "playing your face"),
        ("busca la música playing your face en youtube", "playing your face"),
    ],
)
def test_stt_variations(ctx: ConversationContextManager, phrase: str, expected_query: str) -> None:
    intent, params, _, _ = ctx.resolve_contextual_turn("test_stt_session", phrase)
    assert intent in ("youtube_play", "youtube_search")
    assert expected_query in params.get("query", "").lower()


# ── TEST 11: Regresión — Búsquedas web normales a Google intactas ──
def test_general_search_remains_google(ctx: ConversationContextManager) -> None:
    intent, params, _, _ = ctx.resolve_contextual_turn("test_search_session", "Busca qué es la segunda ley de Newton")
    assert intent == "browser_search"
    assert params.get("motor") == "google"
    assert "segunda ley de newton" in params.get("query", "").lower()


# ── TEST 12: End-to-end con LocalAgent no produce general_query ──
def test_local_agent_end_to_end_no_general_query() -> None:
    agent = JessycaLocalAgent()
    resp = agent.process_text(
        "Reproduce la música playing Your Face en YouTube",
        session_id="test_agent_yt",
    )
    assert resp.intent == "youtube_play"
    assert resp.intent != "general_query"
    assert any(term in resp.response_text.lower() for term in ("reproducción", "reproduciendo", "youtube"))

