"""Batería de Pruebas Exhaustivas para la Fase 52.1: Natural Action Dialogue & Capability Awareness.

Cubre rigurosamente:
- TEST 1: Reproducción de Baile ("Jessyca bailame")
- TEST 2: Intención ambigua ("Abre YouTube") -> Aclaración proactiva
- TEST 3: Intención incompleta ("Busca una canción") -> Aclaración de slot
- TEST 4: Búsqueda de canción ("Busca La Yerba del Rey de Morodo") -> Búsqueda + ofrecimiento
- TEST 5: Orden compuesta completa ("Busca y reproduce La Yerba del Rey de Morodo") -> Sin preguntas redundantes
- TEST 6: Continuidad contextual ("Ponla" / "Reprodúcela") -> Resolución anafórica
- TEST 7: Capacidad inexistente ("Edita profesionalmente este vídeo") -> UNSUPPORTED / NONE
- TEST 8: Capacidad parcial ("Busca un vídeo de baile y edítalo para TikTok") -> PARTIALLY_SUPPORTED
- TEST 9: Acción sensible ("Elimina el archivo temp.tmp") -> REQUIRE_CONFIRMATION
- TEST 10: Fallo de ejecución controlado -> Reporte honesto sin falso éxito
- TEST 11: Fallo de verificación -> Reporte de no confirmación
- TEST 12: Flujo multi-turno integrado end-to-end (Abre YouTube -> Busca -> Canción -> Reprodúcela)
- TEST 13: Sesión de voz continua con timeout seguro
"""

from __future__ import annotations

import tempfile
import uuid
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.local_agent.conversation_context import ConversationContextManager
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import (
    AgentExecutionState,
    InputModality,
    JessycaRequest,
)
from skills.windows_media_skill import IMediaPlayer, WindowsMediaSkill


@pytest.fixture
def temp_dance_dir() -> Generator[Path, None, None]:
    """Crea una carpeta temporal con vídeos simulados para pruebas."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        (tmp_path / "dance_clip_01.mp4").write_bytes(b"FAKE_MP4_HEADER_DATA_1")
        (tmp_path / "dance_clip_02.mkv").write_bytes(b"FAKE_MKV_HEADER_DATA_2")
        yield tmp_path


@pytest.fixture
def mock_media_player() -> MagicMock:
    """Mock de reproductor multimedia del sistema."""
    player = MagicMock(spec=IMediaPlayer)
    player.launch.return_value = (True, "PLAYBACK_LAUNCHED", 1234)
    return player


@pytest.fixture
def local_agent(temp_dance_dir: Path, mock_media_player: MagicMock) -> JessycaLocalAgent:
    """Instancia limpia de JessycaLocalAgent con contexto y media skill aislada."""
    context_mgr = ConversationContextManager(max_turns=20, conversation_timeout=300.0)
    agent = JessycaLocalAgent(context_manager=context_mgr)

    # Configurar media skill aislada
    media_skill = WindowsMediaSkill(
        authorized_directory=temp_dance_dir,
        player=mock_media_player,
    )
    agent.skill_manager.registry.register_skill(media_skill, replace=True)
    return agent


# ── TEST 1: REPRODUCCIÓN DE BAILE ─────────────────────────────────────────────

def test_01_dance_video_playback(local_agent: JessycaLocalAgent) -> None:
    """TEST 1: 'Jessyca bailame' debe evaluar FULL, emitir respuesta pre-acción y ejecutar playback verificado."""
    session_id = f"session-{uuid.uuid4().hex[:6]}"

    resp = local_agent.interact(
        JessycaRequest(user_input="Jessyca bailame", session_id=session_id)
    )

    assert resp.success is True
    assert resp.status == AgentExecutionState.COMPLETED
    assert resp.intent == "play_random_video"
    assert any(k in resp.response_text.lower() for k in ("reproduciéndose", "reproduciendo", "baile", "claro"))


# ── TEST 2: INTENCIÓN AMBIGUA (ABRIR YOUTUBE) ─────────────────────────────────

def test_02_ambiguous_youtube_clarification(local_agent: JessycaLocalAgent) -> None:
    """TEST 2: 'Abre YouTube' debe pausar y pedir aclaración sin abrir a ciegas."""
    session_id = f"session-{uuid.uuid4().hex[:6]}"

    resp = local_agent.interact(
        JessycaRequest(user_input="Jessyca abre YouTube", session_id=session_id)
    )

    assert resp.requires_clarification is True
    assert resp.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert "¿Quieres que solo abra YouTube o quieres que busque o reproduzca algo?" in resp.response_text


# ── TEST 3: INTENCIÓN INCOMPLETA (BUSCAR CANCIÓN) ──────────────────────────────

def test_03_incomplete_song_search(local_agent: JessycaLocalAgent) -> None:
    """TEST 3: 'Busca una canción' debe solicitar el nombre de la canción."""
    session_id = f"session-{uuid.uuid4().hex[:6]}"

    resp = local_agent.interact(
        JessycaRequest(user_input="Busca una canción", session_id=session_id)
    )

    assert resp.requires_clarification is True
    assert "¿Qué canción quieres que busque?" in resp.response_text


# ── TEST 4: BÚSQUEDA DIRECTA CON OFRECIMIENTO DE REPRODUCCIÓN ─────────────────

def test_04_search_song_and_offer_play(local_agent: JessycaLocalAgent) -> None:
    """TEST 4: 'Busca La Yerba del Rey de Morodo' ejecuta búsqueda y ofrece reproducir."""
    session_id = f"session-{uuid.uuid4().hex[:6]}"

    resp = local_agent.interact(
        JessycaRequest(user_input="Busca La Yerba del Rey de Morodo", session_id=session_id)
    )

    assert resp.success is True
    assert "Encontré la canción. ¿Quieres que la reproduzca?" in resp.response_text
    # Contexto actualizado
    assert local_agent.context_manager.get_recent_entity(session_id, "last_found_media") == "La Yerba del Rey de Morodo"


# ── TEST 5: ORDEN COMPUESTA COMPLETA ──────────────────────────────────────────

def test_05_compound_search_and_play(local_agent: JessycaLocalAgent) -> None:
    """TEST 5: 'Busca y reproduce La Yerba del Rey de Morodo' ejecuta sin preguntas redundantes."""
    session_id = f"session-{uuid.uuid4().hex[:6]}"

    with patch.object(local_agent.skill_manager, "execute_skill") as mock_exec:
        mock_exec.return_value = MagicMock(
            success=True,
            output={"exito": True, "mensaje": "URL abierta en Microsoft Edge."},
        )

        resp = local_agent.interact(
            JessycaRequest(user_input="Busca y reproduce La Yerba del Rey de Morodo", session_id=session_id)
        )

        assert resp.success is True
        assert resp.status == AgentExecutionState.COMPLETED
        assert resp.requires_clarification is False
        assert "reproduciéndose" in resp.response_text.lower() or "éxito" in resp.response_text.lower()


# ── TEST 6: CONTINUIDAD CONTEXTUAL (REFERENCIA IMPLÍCITA "PONLA") ─────────────

def test_06_deictic_reference_resolution(local_agent: JessycaLocalAgent) -> None:
    """TEST 6: 'Ponla' después de buscar resuelve la canción previa sin pedir nombre."""
    session_id = f"session-{uuid.uuid4().hex[:6]}"

    # Turno 1: Buscar
    local_agent.interact(
        JessycaRequest(user_input="Busca La Yerba del Rey de Morodo", session_id=session_id)
    )

    # Turno 2: "Ponla"
    with patch.object(local_agent.skill_manager, "execute_skill") as mock_exec:
        mock_exec.return_value = MagicMock(
            success=True,
            output={"exito": True, "mensaje": "URL abierta en Microsoft Edge."},
        )

        resp = local_agent.interact(
            JessycaRequest(user_input="Ponla", session_id=session_id)
        )

        assert resp.success is True
        assert resp.requires_clarification is False
        assert "reproduciéndose" in resp.response_text.lower()


# ── TEST 7: CAPACIDAD INEXISTENTE / NO SOPORTADA ──────────────────────────────

def test_07_unsupported_capability_honest_boundary(local_agent: JessycaLocalAgent) -> None:
    """TEST 7: Petición de edición profesional debe responder UNSUPPORTED sin inventar skills."""
    session_id = f"session-{uuid.uuid4().hex[:6]}"

    resp = local_agent.interact(
        JessycaRequest(user_input="Edita profesionalmente este vídeo", session_id=session_id)
    )

    assert resp.success is True
    assert resp.status == AgentExecutionState.COMPLETED
    assert "todavía no puedo hacerlo directamente" in resp.response_text.lower() or "no puedo" in resp.response_text.lower()


# ── TEST 8: CAPACIDAD PARCIALMENTE SOPORTADA ──────────────────────────────────

def test_08_partially_supported_capability(local_agent: JessycaLocalAgent) -> None:
    """TEST 8: Petición combinada (buscar baile + editar para tiktok) explica parte soportada y no soportada."""
    session_id = f"session-{uuid.uuid4().hex[:6]}"

    resp = local_agent.interact(
        JessycaRequest(user_input="Jessyca busca un vídeo de baile y edítalo para TikTok", session_id=session_id)
    )

    assert resp.success is True
    assert resp.status == AgentExecutionState.COMPLETED
    # Explica qué puede hacer y qué no
    assert "puedo" in resp.response_text.lower()
    assert "todavía no puedo" in resp.response_text.lower() or "no puedo" in resp.response_text.lower()


# ── TEST 9: ACCIÓN SENSIBLE QUE REQUIERE CONFIRMACIÓN ──────────────────────────

def test_09_action_requiring_confirmation(local_agent: JessycaLocalAgent) -> None:
    """TEST 9: 'Elimina el archivo temp.tmp' debe solicitar confirmación sin ejecutar a ciegas."""
    session_id = f"session-{uuid.uuid4().hex[:6]}"

    resp = local_agent.interact(
        JessycaRequest(user_input="Elimina el archivo temp.tmp", session_id=session_id)
    )

    assert resp.requires_confirmation is True
    assert resp.status == AgentExecutionState.AWAITING_CONFIRMATION
    assert "confirmas" in resp.response_text.lower()


# ── TEST 10: FALLO DE EJECUCIÓN CONTROLADO ─────────────────────────────────────

def test_10_controlled_execution_failure(local_agent: JessycaLocalAgent) -> None:
    """TEST 10: Error en la skill debe reportar honestamente el fallo, nunca 'Listo'."""
    session_id = f"session-{uuid.uuid4().hex[:6]}"

    with patch.object(local_agent.skill_manager, "execute_skill") as mock_exec:
        mock_exec.return_value = MagicMock(
            success=False,
            error="Error de E/S de disco.",
            output={"exito": False, "mensaje": "Error de E/S de disco."},
        )

        resp = local_agent.interact(
            JessycaRequest(user_input="Jessyca bailame", session_id=session_id)
        )

        assert resp.success is False
        assert resp.status == AgentExecutionState.FAILED
        assert "no pude" in resp.response_text.lower() or "error" in resp.response_text.lower()
        assert "listo, ya está reproduciéndose" not in resp.response_text.lower()


# ── TEST 11: FALLO DE VERIFICACIÓN ────────────────────────────────────────────

def test_11_verification_failure_honest_feedback(local_agent: JessycaLocalAgent) -> None:
    """TEST 11: Si la verificación post-ejecución no confirma el proceso, no se reporta éxito."""
    session_id = f"session-{uuid.uuid4().hex[:6]}"

    with patch.object(local_agent.skill_manager, "execute_skill") as mock_exec:
        mock_exec.return_value = MagicMock(
            success=True,
            output={
                "exito": True,
                "error_code": "VERIFICATION_FAILED",
                "evidence": {"is_verified": False, "target": "notepad", "verification_type": "process"},
                "mensaje": "Proceso no encontrado.",
            },
        )

        resp = local_agent.interact(
            JessycaRequest(user_input="Abre el Bloc de notas", session_id=session_id)
        )

        assert resp.success is False
        assert "no confirmó" in resp.response_text.lower() or "no pudo" in resp.response_text.lower()
        assert resp.response_text != "Listo, abrí el Bloc de notas."


# ── TEST 12: DIÁLOGO MULTI-TURNO INTEGRADO END-TO-END ─────────────────────────

def test_12_full_multi_turn_dialogue_flow(local_agent: JessycaLocalAgent) -> None:
    """TEST 12: Flujo multi-turno completo:
    1. Abre YouTube -> Aclaración
    2. Busca -> Petición de término
    3. La Yerba del Rey de Morodo -> Búsqueda completada + pregunta
    4. Reprodúcela -> Reproducción verificada
    """
    session_id = f"session-{uuid.uuid4().hex[:6]}"

    # Turno 1: "Jessica, abre YouTube"
    t1 = local_agent.interact(
        JessycaRequest(user_input="Jessica, abre YouTube", session_id=session_id)
    )
    assert t1.requires_clarification is True
    assert "¿Quieres que solo abra YouTube o quieres que busque o reproduzca algo?" in t1.response_text

    # Turno 2: "Busca"
    t2 = local_agent.interact(
        JessycaRequest(user_input="Busca", session_id=session_id)
    )
    assert t2.requires_clarification is True
    assert "¿qué quieres que busque?" in t2.response_text.lower()

    # Turno 3: "La Yerba del Rey de Morodo"
    t3 = local_agent.interact(
        JessycaRequest(user_input="La Yerba del Rey de Morodo", session_id=session_id)
    )
    assert t3.success is True
    assert "Encontré la canción. ¿Quieres que la reproduzca?" in t3.response_text

    # Turno 4: "Reprodúcela"
    with patch.object(local_agent.skill_manager, "execute_skill") as mock_exec:
        mock_exec.return_value = MagicMock(
            success=True,
            output={"exito": True, "mensaje": "URL abierta en Microsoft Edge."},
        )

        t4 = local_agent.interact(
            JessycaRequest(user_input="Reprodúcela", session_id=session_id)
        )
        assert t4.success is True
        assert "reproduciéndose" in t4.response_text.lower()


# ── TEST 13: SESIÓN DE VOZ CONTINUA Y TIMEOUT SEGURO ──────────────────────────

def test_13_continuous_voice_session_and_timeout(local_agent: JessycaLocalAgent) -> None:
    """TEST 13: Sesión de voz continua mantiene el estado y maneja expiración por inactividad."""
    session_id = f"session-voice-{uuid.uuid4().hex[:6]}"

    # Turno de voz 1
    v1 = local_agent.interact(
        JessycaRequest(
            user_input="Abre YouTube",
            session_id=session_id,
            modality=InputModality.VOICE,
        )
    )
    assert v1.status == AgentExecutionState.AWAITING_CLARIFICATION

    # Verificar que el contexto no ha expirado
    session = local_agent.context_manager.get_session(session_id)
    assert session is not None
    assert session.pending_intent == "youtube_clarification"

    # Simular expiración de sesión (timeout)
    session.last_activity = 0.0  # Marca antigua
    expired_session = local_agent.context_manager.get_session(session_id)
    assert expired_session is None  # Se cerró limpiamente
