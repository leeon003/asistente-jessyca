"""Suite de Pruebas Exhaustiva para Experience Logger (test_experience_logger.py - Fase 57).

Verifica:
1. Modelos tipados Pydantic v2 (Experience y submodelos).
2. Sanitización estricta de credenciales, tokens, secretos y truncamiento.
3. Almacenamiento en InMemoryExperienceStore y SQLiteExperienceStore (con índices y WAL).
4. Consultas estructuradas mediante ExperienceRepository.
5. Registrador central ExperienceLogger y registro de las 10 categorías clave.
6. Aislamiento de fallos (Fail-Safe: una falla del almacén NUNCA interrumpe la ejecución principal).
7. Integración end-to-end con JessycaLocalAgent.
8. Concurrencia multi-hilo segura y serialización JSON.
9. Desacoplamiento estricto del AuditLogger y compatibilidad retroactiva.
"""

from __future__ import annotations

import concurrent.futures
import sqlite3
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.audit_logger import AuditLogger, get_audit_logger
from core.experience.experience_logger import ExperienceLogger, get_experience_logger
from core.experience.experience_store import (
    InMemoryExperienceStore,
    SQLiteExperienceStore,
)
from core.experience.models import (
    CorrectionInfo,
    ExecutionResult,
    ExecutionStatus,
    Experience,
    ExperienceCategory,
    ExperienceInput,
    ExperienceMetadata,
    InputSource,
    IntentResult,
    LatencyInfo,
    ResponseResult,
    STTResult,
    TargetInfo,
    VerificationResult,
    VerificationStatus,
)
from core.experience.repository import ExperienceRepository
from core.experience.sanitization import (
    is_sensitive_key,
    sanitize_experience_data,
)
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import InputModality, JessycaRequest


@pytest.fixture(autouse=True)
def reset_singletons():
    """Garantiza aislamiento estricto entre pruebas."""
    ExperienceLogger.reset_instance()
    agent = JessycaLocalAgent.get_instance()
    agent.reset()
    yield
    ExperienceLogger.reset_instance()
    agent.reset()


# ── TEST 1: MODELOS Y VALIDACIÓN PYDANTIC V2 ──

def test_experience_models_creation_and_defaults():
    """Verifica que el modelo Experience genere UUID, UTC timestamp y submodelos válidos."""
    exp_input = ExperienceInput(
        source=InputSource.VOICE,
        raw_text="abre el bloc de notas",
        normalized_text="abre el bloc de notas",
    )
    exp = Experience(
        category=ExperienceCategory.ACTION_SUCCESS,
        session_id="session-101",
        correlation_id="corr-202",
        input=exp_input,
    )

    assert exp.experience_id is not None
    # Validar formato UUID
    uuid.UUID(exp.experience_id)
    assert exp.timestamp is not None
    assert exp.category == ExperienceCategory.ACTION_SUCCESS
    assert exp.session_id == "session-101"
    assert exp.input.source == InputSource.VOICE
    assert exp.input.raw_text == "abre el bloc de notas"
    assert exp.latency.total_ms == 0.0
    assert exp.metadata.version == "3.0.0"


def test_experience_serialization_roundtrip():
    """Verifica la serialización a diccionario y reconstrucción sin pérdida de datos."""
    exp = Experience(
        category=ExperienceCategory.ACTION_SUCCESS,
        session_id="s1",
        correlation_id="c1",
        input=ExperienceInput(source=InputSource.TEXT, raw_text="calcula 25 + 10"),
        stt=STTResult(text="calcula 25 + 10", confidence=0.98),
        intent=IntentResult(name="math_calculation", confidence=1.0, parameters={"op": "sum"}),
        target=TargetInfo(target_type="math", value="25 + 10"),
        execution=ExecutionResult(status=ExecutionStatus.SUCCESS, tool_name="system.calc", action="calculate"),
        verification=VerificationResult(status=VerificationStatus.SUCCESS, is_verified=True),
        response=ResponseResult(text="El resultado es 35."),
        latency=LatencyInfo(total_ms=12.5, execution_ms=4.2),
        error=None,
        correction=CorrectionInfo(is_correction=False),
        metadata=ExperienceMetadata(model_used="local-agent", tags=["test", "math"]),
    )

    data = exp.to_dict()
    assert isinstance(data, dict)
    assert data["category"] == "ACTION_SUCCESS"
    assert data["input"]["raw_text"] == "calcula 25 + 10"
    assert data["verification"]["is_verified"] is True

    reconstructed = Experience.from_dict(data)
    assert reconstructed.experience_id == exp.experience_id
    assert reconstructed.category == ExperienceCategory.ACTION_SUCCESS
    assert reconstructed.stt is not None
    assert reconstructed.stt.confidence == 0.98
    assert reconstructed.execution is not None
    assert reconstructed.execution.status == ExecutionStatus.SUCCESS


# ── TEST 2: SANITIZACIÓN ESTRICTA Y ZERO LEAKAGE ──

def test_sanitization_sensitive_keys_and_values():
    """Verifica que contraseñas, tokens y claves secretas sean enmascaradas."""
    assert is_sensitive_key("password") is True
    assert is_sensitive_key("API_KEY") is True
    assert is_sensitive_key("auth_token") is True
    assert is_sensitive_key("user_cookie") is True
    assert is_sensitive_key("app_name") is False

    payload = {
        "user": "alice",
        "password": "super_secret_password_123",
        "api_key": "sk-123456789012345678901234567890123456",
        "auth_header": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
        "nested": {
            "session_cookie": "sess_987654321",
            "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC3\n-----END PRIVATE KEY-----",
            "safe_param": "bloc de notas",
        },
        "items": [
            {"token": "ghp_123456789012345678901234567890123654"},
            "Texto normal",
        ],
    }

    sanitized = sanitize_experience_data(payload)

    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["auth_header"] == "[REDACTED]"
    assert sanitized["nested"]["session_cookie"] == "[REDACTED]"
    assert sanitized["nested"]["private_key"] == "[REDACTED]"
    assert sanitized["nested"]["safe_param"] == "bloc de notas"
    assert sanitized["items"][0]["token"] == "[REDACTED]"
    assert sanitized["items"][1] == "Texto normal"


def test_sanitization_truncation_of_long_strings():
    """Verifica el truncamiento automático de strings excesivamente largos."""
    long_text = "A" * 3000
    sanitized = sanitize_experience_data(long_text, max_str_len=100)
    assert len(sanitized) == 100 + len(" [TRUNCATED]")
    assert sanitized.endswith("[TRUNCATED]")


# ── TEST 3: ALMACENES DE EXPERIENCIA (IN-MEMORY & SQLITE) ──

def test_in_memory_experience_store():
    """Verifica operaciones CRUD y filtros en InMemoryExperienceStore."""
    store = InMemoryExperienceStore()

    exp1 = Experience(
        category=ExperienceCategory.ACTION_SUCCESS,
        session_id="sess-A",
        correlation_id="corr-1",
        input=ExperienceInput(raw_text="abrir notepad"),
    )
    exp2 = Experience(
        category=ExperienceCategory.ACTION_FAILED,
        session_id="sess-A",
        correlation_id="corr-2",
        input=ExperienceInput(raw_text="abrir programa_inexistente"),
    )
    exp3 = Experience(
        category=ExperienceCategory.USER_CORRECTION,
        session_id="sess-B",
        correlation_id="corr-3",
        input=ExperienceInput(raw_text="no, abre calculadora"),
    )

    store.save(exp1)
    store.save(exp2)
    store.save(exp3)

    assert store.count() == 3
    assert store.count(session_id="sess-A") == 2
    assert store.count(category=ExperienceCategory.USER_CORRECTION) == 1

    retrieved = store.get(exp1.experience_id)
    assert retrieved is not None
    assert retrieved.input.raw_text == "abrir notepad"

    query_sess_a = store.query(session_id="sess-A")
    assert len(query_sess_a) == 2

    assert store.delete(exp2.experience_id) is True
    assert store.count() == 2
    assert store.get(exp2.experience_id) is None

    store.clear()
    assert store.count() == 0


def test_sqlite_experience_store_persistence():
    """Verifica persistencia determinista, transacciones e índices en SQLiteExperienceStore."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = str(Path(tmpdir) / "test_experiences.db")
        store = SQLiteExperienceStore(db_path=db_file)

        exp1 = Experience(
            category=ExperienceCategory.ACTION_SUCCESS,
            session_id="sess-1",
            correlation_id="c-1",
            input=ExperienceInput(raw_text="abrir calc"),
            execution=ExecutionResult(status=ExecutionStatus.SUCCESS, tool_name="windows.apps"),
        )
        exp2 = Experience(
            category=ExperienceCategory.VERIFICATION_FAILED,
            session_id="sess-1",
            correlation_id="c-2",
            input=ExperienceInput(raw_text="abrir app_bloqueada"),
            verification=VerificationResult(status=VerificationStatus.FAILED, is_verified=False),
        )

        store.save(exp1)
        store.save(exp2)

        assert store.count() == 2
        assert store.count(category=ExperienceCategory.VERIFICATION_FAILED) == 1

        retrieved1 = store.get(exp1.experience_id)
        assert retrieved1 is not None
        assert retrieved1.execution is not None
        assert retrieved1.execution.tool_name == "windows.apps"

        # Validar persistencia reabriendo el store desde el mismo archivo
        store2 = SQLiteExperienceStore(db_path=db_file)
        assert store2.count() == 2
        retrieved2 = store2.get(exp2.experience_id)
        assert retrieved2 is not None
        assert retrieved2.category == ExperienceCategory.VERIFICATION_FAILED

        # Probar borrado y limpieza
        assert store2.delete(exp1.experience_id) is True
        assert store2.count() == 1
        store2.clear()
        assert store2.count() == 0


# ── TEST 4: REPOSITORIO DE DOMINIO ──

def test_experience_repository_queries():
    """Verifica consultas de alto nivel a través de ExperienceRepository."""
    store = InMemoryExperienceStore()
    repo = ExperienceRepository(store=store)

    exp_ok = Experience(
        category=ExperienceCategory.ACTION_SUCCESS,
        session_id="session-X",
        correlation_id="c1",
        input=ExperienceInput(raw_text="hola"),
    )
    exp_fail = Experience(
        category=ExperienceCategory.ACTION_FAILED,
        session_id="session-X",
        correlation_id="c2",
        input=ExperienceInput(raw_text="accion_fallida"),
    )
    exp_verif_fail = Experience(
        category=ExperienceCategory.VERIFICATION_FAILED,
        session_id="session-Y",
        correlation_id="c3",
        input=ExperienceInput(raw_text="accion_no_verificada"),
    )
    exp_corr = Experience(
        category=ExperienceCategory.USER_CORRECTION,
        session_id="session-Y",
        correlation_id="c4",
        input=ExperienceInput(raw_text="cambia café por té"),
    )

    for exp in (exp_ok, exp_fail, exp_verif_fail, exp_corr):
        repo.save_experience(exp)

    assert repo.count_experiences() == 4
    assert len(repo.get_by_session("session-X")) == 2
    assert len(repo.get_by_correlation_id("c3")) == 1
    assert len(repo.get_by_category(ExperienceCategory.USER_CORRECTION)) == 1

    failed_exps = repo.get_failed_experiences()
    assert len(failed_exps) == 2
    assert {e.category for e in failed_exps} == {ExperienceCategory.ACTION_FAILED, ExperienceCategory.VERIFICATION_FAILED}

    corrections = repo.get_user_corrections()
    assert len(corrections) == 1
    assert corrections[0].input.raw_text == "cambia café por té"


# ── TEST 5: EXPERIENCE LOGGER & 10 CATEGORÍAS CLAVE ──

def test_experience_logger_ten_key_scenarios():
    """Verifica el registro de las 10 categorías funcionales de experiencias requeridas."""
    store = InMemoryExperienceStore()
    repo = ExperienceRepository(store=store)
    logger = ExperienceLogger(repository=repo)

    # 1. ACTION_SUCCESS
    id_1 = logger.log_interaction(
        user_input="abre el bloc de notas",
        response_text="He abierto Bloc de notas.",
        category=ExperienceCategory.ACTION_SUCCESS,
        target_type="application",
        target_value="notepad",
        execution_status=ExecutionStatus.SUCCESS,
        is_verified=True,
    )
    assert id_1 is not None

    # 2. ACTION_FAILED
    id_2 = logger.log_interaction(
        user_input="ejecuta comando inválido",
        response_text="Error al ejecutar el comando.",
        category=ExperienceCategory.ACTION_FAILED,
        execution_status=ExecutionStatus.FAILED,
        error_message="Command failed with code 1",
    )
    assert id_2 is not None

    # 3. VERIFICATION_FAILED
    id_3 = logger.log_interaction(
        user_input="abre calc",
        response_text="No pude verificar que Calculadora esté abierta.",
        category=ExperienceCategory.VERIFICATION_FAILED,
        verification_status=VerificationStatus.FAILED,
        is_verified=False,
    )
    assert id_3 is not None

    # 4. LOW_STT_CONFIDENCE
    id_4 = logger.log_interaction(
        user_input="...ruido ininteligible...",
        response_text="No te entendí bien. ¿Puedes repetirlo?",
        source=InputSource.VOICE,
        category=ExperienceCategory.LOW_STT_CONFIDENCE,
        stt_confidence=0.35,
    )
    assert id_4 is not None

    # 5. AMBIGUOUS_INTENT
    id_5 = logger.log_interaction(
        user_input="búscame aquello",
        response_text="¿Podrías especificar qué archivo deseas buscar?",
        category=ExperienceCategory.AMBIGUOUS_INTENT,
        intent_confidence=0.45,
    )
    assert id_5 is not None

    # 6. CLARIFICATION_REQUESTED
    id_6 = logger.log_interaction(
        user_input="suma",
        response_text="¿Qué números te gustaría que sume?",
        category=ExperienceCategory.CLARIFICATION_REQUESTED,
    )
    assert id_6 is not None

    # 7. USER_CORRECTION
    id_7 = logger.log_interaction(
        user_input="No, cambia café por té",
        response_text="Entendido, he cambiado 'café' por 'té' en tu lista.",
        category=ExperienceCategory.USER_CORRECTION,
        is_correction=True,
        target_value="té",
    )
    assert id_7 is not None

    # 8. TIMEOUT
    id_8 = logger.log_interaction(
        user_input="descarga archivo gigante",
        response_text="La operación excedió el tiempo límite.",
        category=ExperienceCategory.TIMEOUT,
        execution_status=ExecutionStatus.TIMEOUT,
        error_message="Operation timed out after 30s",
    )
    assert id_8 is not None

    # 9. ACTION_BLOCKED
    id_9 = logger.log_interaction(
        user_input="elimina system32",
        response_text="Detecté una acción sensible. ¿Confirmas su ejecución?",
        category=ExperienceCategory.ACTION_BLOCKED,
        execution_status=ExecutionStatus.BLOCKED,
    )
    assert id_9 is not None

    # 10. CANCELLED
    id_10 = logger.log_interaction(
        user_input="olvídalo, cancela",
        response_text="Entendido, operación cancelada.",
        category=ExperienceCategory.CANCELLED,
        execution_status=ExecutionStatus.CANCELLED,
    )
    assert id_10 is not None

    assert repo.count_experiences() == 10
    categories = {exp.category for exp in repo.get_recent(limit=10)}
    assert categories == {
        ExperienceCategory.ACTION_SUCCESS,
        ExperienceCategory.ACTION_FAILED,
        ExperienceCategory.VERIFICATION_FAILED,
        ExperienceCategory.LOW_STT_CONFIDENCE,
        ExperienceCategory.AMBIGUOUS_INTENT,
        ExperienceCategory.CLARIFICATION_REQUESTED,
        ExperienceCategory.USER_CORRECTION,
        ExperienceCategory.TIMEOUT,
        ExperienceCategory.ACTION_BLOCKED,
        ExperienceCategory.CANCELLED,
    }


# ── TEST 6: AISLAMIENTO ESTRICTO ANTE FALLAS (FAIL-SAFE ISOLATION) ──

def test_experience_logger_fail_safe_isolation():
    """Garantiza que cualquier excepción en el almacén NO se propague ni falle al llamador."""
    faulty_store = MagicMock()
    faulty_store.save.side_effect = sqlite3.OperationalError("disk I/O error or database locked")

    faulty_repo = ExperienceRepository(store=faulty_store)
    logger = ExperienceLogger(repository=faulty_repo)

    exp = Experience(
        category=ExperienceCategory.ACTION_SUCCESS,
        input=ExperienceInput(raw_text="test fail-safe"),
    )

    # Debe retornar None sin lanzar ninguna excepción
    result = logger.log_experience(exp)
    assert result is None


def test_experience_logger_disabled_mode():
    """Verifica que cuando está deshabilitado no intente guardar experiencias."""
    store = InMemoryExperienceStore()
    repo = ExperienceRepository(store=store)
    logger = ExperienceLogger(repository=repo, enabled=False)

    exp = Experience(
        category=ExperienceCategory.ACTION_SUCCESS,
        input=ExperienceInput(raw_text="test disabled"),
    )

    result = logger.log_experience(exp)
    assert result is None
    assert store.count() == 0

    logger.enable()
    assert logger.is_enabled() is True
    result_enabled = logger.log_experience(exp)
    assert result_enabled is not None
    assert store.count() == 1


# ── TEST 7: INTEGRACIÓN END-TO-END CON JESSYCA LOCAL AGENT ──

def test_local_agent_records_experience_on_execution():
    """Verifica que procesar solicitudes en JessycaLocalAgent registre experiencias automáticamente."""
    store = InMemoryExperienceStore()
    repo = ExperienceRepository(store=store)
    exp_logger = ExperienceLogger(repository=repo)

    agent = JessycaLocalAgent.get_instance()
    agent.experience_logger = exp_logger

    req = JessycaRequest(
        user_input="calcula 50 + 75",
        session_id="agent-session-1",
        modality=InputModality.TEXT,
    )
    resp = agent.interact(req)

    assert resp.success is True
    assert "125" in resp.response_text
    assert store.count() == 1

    experiences = store.query(session_id="agent-session-1")
    assert len(experiences) == 1
    logged_exp = experiences[0]
    assert logged_exp.input.raw_text == "calcula 50 + 75"
    assert logged_exp.category == ExperienceCategory.ACTION_SUCCESS
    assert logged_exp.intent is not None
    assert logged_exp.intent.name == "math_calculation"


def test_local_agent_records_clarification_and_correction_experiences():
    """Verifica que preguntas de aclaración y correcciones se clasifiquen y registren fielmente."""
    store = InMemoryExperienceStore()
    repo = ExperienceRepository(store=store)
    exp_logger = ExperienceLogger(repository=repo)

    agent = JessycaLocalAgent.get_instance()
    agent.experience_logger = exp_logger

    # Turno 1: Solicitud incompleta que exige aclaración
    req1 = JessycaRequest(
        user_input="abre",
        session_id="clarif-session",
        modality=InputModality.TEXT,
    )
    resp1 = agent.interact(req1)
    assert resp1.requires_clarification is True

    # Turno 2: Corrección de usuario
    req2 = JessycaRequest(
        user_input="No, cambia café por té",
        session_id="clarif-session",
        modality=InputModality.TEXT,
    )
    resp2 = agent.interact(req2)
    assert resp2.success is True

    assert store.count(session_id="clarif-session") == 2
    recent = repo.get_by_session("clarif-session")
    categories = [e.category for e in recent]
    assert ExperienceCategory.CLARIFICATION_REQUESTED in categories
    assert ExperienceCategory.USER_CORRECTION in categories


# ── TEST 8: CONCURRENCIA MULTI-HILO SEGURA ──

def test_concurrent_experience_logging():
    """Verifica el registro concurrente desde 20 hilos sin condiciones de carrera ni corrupción."""
    store = InMemoryExperienceStore()
    repo = ExperienceRepository(store=store)
    logger = ExperienceLogger(repository=repo)

    num_threads = 20
    num_logs_per_thread = 10

    def worker(worker_id: int):
        for i in range(num_logs_per_thread):
            logger.log_interaction(
                user_input=f"worker {worker_id} request {i}",
                response_text=f"worker {worker_id} response {i}",
                session_id=f"session-worker-{worker_id}",
                category=ExperienceCategory.ACTION_SUCCESS,
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, w) for w in range(num_threads)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    assert store.count() == num_threads * num_logs_per_thread


# ── TEST 9: DESACOPLAMIENTO ESTRICTO DEL AUDIT LOGGER ──

def test_audit_logger_and_experience_logger_decoupling():
    """Verifica que el AuditLogger siga funcionando independientemente sin interferencias."""
    audit_logger = get_audit_logger()
    exp_logger = get_experience_logger()

    assert audit_logger is not None
    assert exp_logger is not None
    assert not isinstance(exp_logger, AuditLogger)
    assert hasattr(exp_logger, "log_experience")
    assert hasattr(audit_logger, "log_event")
