"""Suite de Pruebas Exhaustiva para Personalization Engine (test_personalization_engine.py - Fase 62).

Verifica:
1. Creación de preferencias como CANDIDATE con confianza inicial baja.
2. Acumulación progresiva de evidencia hasta alcanzar estado ACTIVE (>= 0.70).
3. Confirmación explícita del usuario elevando confianza a >= 0.95.
4. Registro de contradicciones, decremento de confianza y olvido (FORGOTTEN).
5. Resolución determinista de conflictos entre valores alternativos sobre la misma clave.
6. AISLAMIENTO ABSOLUTO DE SEGURIDAD: Rechazo de secretos (passwords, tokens) y comandos de bypass.
7. Decaimiento temporal (time decay) y expiración por desuso.
8. Olvido voluntario de preferencias (forget_preference).
9. Persistencia en InMemoryPreferenceStore y SQLitePreferenceStore.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.personalization.preference_confidence import (
    ACTIVE_THRESHOLD,
    EXPLICIT_CONFIRMATION_CONFIDENCE,
    INITIAL_CANDIDATE_CONFIDENCE,
)
from core.personalization.preference_engine import PersonalizationEngine
from core.personalization.preference_models import (
    PreferenceCategory,
    PreferenceSource,
    PreferenceStatus,
    UserPreference,
)
from core.personalization.preference_store import (
    InMemoryPreferenceStore,
    SQLitePreferenceStore,
)
from core.personalization.preference_validator import (
    PreferenceValidator,
)

# ── TEST 1: CREACIÓN DE PREFERENCIA Y MODELOS ──

def test_user_preference_model_creation():
    """Verifica instanciación y serialización de UserPreference."""
    pref = UserPreference(
        category=PreferenceCategory.COMMAND_ALIAS,
        key="notas",
        value="notepad",
        confidence=0.35,
    )

    assert pref.preference_id is not None
    assert pref.status == PreferenceStatus.CANDIDATE
    assert pref.category == PreferenceCategory.COMMAND_ALIAS
    assert pref.key == "notas"
    assert pref.value == "notepad"
    assert pref.evidence_count == 1
    assert pref.contradiction_count == 0

    # Serialización y reconstrucción
    data = pref.to_dict()
    reconstructed = UserPreference.from_dict(data)
    assert reconstructed.preference_id == pref.preference_id
    assert reconstructed.key == "notas"


# ── TEST 2: APRENDIZAJE PROGRESIVO Y ACUMULACIÓN DE EVIDENCIA ──

def test_progressive_evidence_accumulation_to_active():
    """Verifica que interacciones consistentes eleven la confianza de CANDIDATE a ACTIVE."""
    store = InMemoryPreferenceStore()
    engine = PersonalizationEngine(store=store)

    # 1. Primera interacción: crea CANDIDATE (confianza inicial 0.35)
    p1 = engine.record_observation(PreferenceCategory.COMMAND_ALIAS, "notas", "notepad")
    assert p1.status == PreferenceStatus.CANDIDATE
    assert p1.confidence == INITIAL_CANDIDATE_CONFIDENCE
    assert p1.evidence_count == 1

    # 2. Segunda interacción: suma evidencia (+0.15 -> 0.50)
    p2 = engine.record_observation(PreferenceCategory.COMMAND_ALIAS, "notas", "notepad")
    assert p2.status == PreferenceStatus.CANDIDATE
    assert p2.confidence == pytest.approx(0.50)
    assert p2.evidence_count == 2

    # 3. Tercera interacción: suma evidencia (+0.15 -> 0.65)
    p3 = engine.record_observation(PreferenceCategory.COMMAND_ALIAS, "notas", "notepad")
    assert p3.status == PreferenceStatus.CANDIDATE
    assert p3.confidence == pytest.approx(0.65)

    # 4. Cuarta interacción: suma evidencia (+0.15 -> 0.80 >= 0.70) -> Se vuelve ACTIVE
    p4 = engine.record_observation(PreferenceCategory.COMMAND_ALIAS, "notas", "notepad")
    assert p4.status == PreferenceStatus.ACTIVE
    assert p4.confidence == pytest.approx(0.80)
    assert p4.evidence_count == 4

    # Verificar recuperación del valor activo
    preferred = engine.get_preferred_value(PreferenceCategory.COMMAND_ALIAS, "notas")
    assert preferred == "notepad"


# ── TEST 3: CONFIRMACIÓN EXPLÍCITA DEL USUARIO ──

def test_explicit_user_confirmation():
    """Verifica que una confirmación explícita eleve la preferencia directamente a ACTIVE con >= 0.95."""
    store = InMemoryPreferenceStore()
    engine = PersonalizationEngine(store=store)

    # 1. Registro directo como explícito
    pref_exp = engine.record_observation(
        PreferenceCategory.APPLICATION_PREFERENCE,
        "navegador",
        "msedge",
        is_explicit=True,
    )
    assert pref_exp.status == PreferenceStatus.ACTIVE
    assert pref_exp.confidence >= EXPLICIT_CONFIRMATION_CONFIDENCE
    assert pref_exp.source == PreferenceSource.USER_EXPLICIT

    # 2. Confirmación posterior de un candidato
    cand = engine.record_observation(PreferenceCategory.COMMAND_ALIAS, "calculo", "calc")
    assert cand.status == PreferenceStatus.CANDIDATE

    confirmed = engine.confirm_preference(cand.preference_id)
    assert confirmed.status == PreferenceStatus.ACTIVE
    assert confirmed.confidence >= EXPLICIT_CONFIRMATION_CONFIDENCE
    assert confirmed.last_confirmed is not None


# ── TEST 4: CONTRADICCIONES Y OLVIDO DE PREFERENCIAS ──

def test_contradictions_and_preference_degradation():
    """Verifica penalización por contradicción y eventual degradación a FORGOTTEN."""
    store = InMemoryPreferenceStore()
    engine = PersonalizationEngine(store=store)

    # Establecer preferencia activa inicial
    engine.record_observation(PreferenceCategory.COMMAND_ALIAS, "notas", "notepad", is_explicit=True)

    # Contradicción 1: el usuario corrigió (confianza cae de 0.95 a 0.70)
    c1 = engine.record_contradiction(PreferenceCategory.COMMAND_ALIAS, "notas", "notepad")
    assert c1 is not None
    assert c1.contradiction_count == 1
    assert c1.confidence == pytest.approx(0.70)

    # Contradicción 2: (cae a 0.45 < 0.70 -> regresa a CANDIDATE)
    c2 = engine.record_contradiction(PreferenceCategory.COMMAND_ALIAS, "notas", "notepad")
    assert c2 is not None
    assert c2.status == PreferenceStatus.CANDIDATE
    assert c2.confidence == pytest.approx(0.45)

    # Contradicción 3: (cae a 0.20 < 0.25 -> pasa a FORGOTTEN)
    c3 = engine.record_contradiction(PreferenceCategory.COMMAND_ALIAS, "notas", "notepad")
    assert c3 is not None
    assert c3.status == PreferenceStatus.FORGOTTEN
    assert c3.confidence == pytest.approx(0.20)

    # Ya no debe devolver valor preferido
    assert engine.get_preferred_value(PreferenceCategory.COMMAND_ALIAS, "notas") is None


# ── TEST 5: RESOLUCIÓN DETERMINISTA DE CONFLICTOS ──

def test_preference_conflict_resolution():
    """Verifica que entre múltiples alternativas para una misma clave se escoja la de mayor confianza y evidencia."""
    store = InMemoryPreferenceStore()
    engine = PersonalizationEngine(store=store)

    # El usuario dijo "notas" -> "notepad" 4 veces
    for _ in range(4):
        engine.record_observation(PreferenceCategory.COMMAND_ALIAS, "notas", "notepad")

    # El usuario dijo "notas" -> "wordpad" 1 vez
    p_wordpad = UserPreference(
        category=PreferenceCategory.COMMAND_ALIAS,
        key="notas",
        value="wordpad",
        confidence=0.35,
        evidence_count=1,
        status=PreferenceStatus.CANDIDATE,
    )
    store.save(p_wordpad)

    best = engine.resolve_conflicts(PreferenceCategory.COMMAND_ALIAS, "notas")
    assert best is not None
    assert best.value == "notepad"
    assert best.confidence >= ACTIVE_THRESHOLD


# ── TEST 6: AISLAMIENTO ABSOLUTO DE SEGURIDAD (ZERO LEAKAGE & NO BYPASS) ──

@pytest.mark.parametrize("forbidden_payload", [
    ("api_key", "sk-live-secret-123"),
    ("password", "SuperSecret123"),
    ("credential", "auth_user_pass"),
    ("bypass_security", "true"),
    ("grant_permission", "admin_all"),
    ("disable_confirmation", "always"),
])
def test_security_isolation_rejects_sensitive_and_unsafe_preferences(forbidden_payload: tuple[str, str]):
    """Garantiza que cualquier intento de registrar secretos o alterar políticas de seguridad sea rechazado."""
    key, val = forbidden_payload

    unsafe_pref = UserPreference(
        category=PreferenceCategory.COMMAND_ALIAS,
        key=key,
        value=val,
    )

    is_valid, errors = PreferenceValidator.validate_preference(unsafe_pref)
    assert is_valid is False
    assert any("CRITICAL SECURITY VIOLATION" in err for err in errors)

    store = InMemoryPreferenceStore()
    engine = PersonalizationEngine(store=store)

    with pytest.raises(ValueError, match="CRITICAL SECURITY VIOLATION"):
        engine.record_observation(PreferenceCategory.COMMAND_ALIAS, key, val)


# ── TEST 7: OLVIDO VOLUNTARIO Y DECAIMIENTO TEMPORAL ──

def test_forget_and_time_decay():
    """Verifica el olvido explícito y la degradación temporal por desuso."""
    store = InMemoryPreferenceStore()
    engine = PersonalizationEngine(store=store)

    pref = engine.record_observation(PreferenceCategory.BROWSER_PREFERENCE, "buscador", "google", is_explicit=True)
    assert pref.status == PreferenceStatus.ACTIVE

    # 1. Olvido voluntario
    forgotten = engine.forget_preference(pref.preference_id, reason="El usuario cambió de opinión")
    assert forgotten.status == PreferenceStatus.FORGOTTEN
    assert forgotten.confidence == 0.0
    assert forgotten.metadata.get("forget_reason") == "El usuario cambió de opinión"

    # 2. Decaimiento temporal
    pref2 = engine.record_observation(PreferenceCategory.APPLICATION_PREFERENCE, "editor", "vscode", is_explicit=True)
    updated_cnt = engine.cleanup_expired_preferences(decay_days=60.0)  # 60 días * 1% = 60% caída
    assert updated_cnt >= 1

    stored_pref2 = store.get(pref2.preference_id)
    assert stored_pref2 is not None
    assert stored_pref2.confidence < ACTIVE_THRESHOLD


# ── TEST 8: PERSISTENCIA EN SQLITE PREFERENCE STORE ──

def test_sqlite_preference_store_persistence():
    """Verifica persistencia determinista y consultas en SQLitePreferenceStore."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_preferences.db")
        store = SQLitePreferenceStore(db_path=db_path)

        pref = UserPreference(
            category=PreferenceCategory.COMMAND_ALIAS,
            key="musica",
            value="spotify",
            confidence=0.85,
            status=PreferenceStatus.ACTIVE,
        )
        store.save(pref)

        assert store.count() == 1
        assert store.count(category=PreferenceCategory.COMMAND_ALIAS) == 1

        # Reabrir base de datos
        store2 = SQLitePreferenceStore(db_path=db_path)
        retrieved_list = store2.get_by_key(PreferenceCategory.COMMAND_ALIAS, "musica")
        assert len(retrieved_list) == 1
        assert retrieved_list[0].value == "spotify"
        assert retrieved_list[0].confidence == 0.85

        # Limpieza
        store2.clear()
        assert store2.count() == 0
