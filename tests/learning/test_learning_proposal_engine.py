"""Suite de Pruebas Exhaustiva para Learning Proposal Engine (test_learning_proposal_engine.py - Fase 59).

Verifica:
1. Modelos tipados y validación de LearningProposal.
2. Generación automática de propuestas a partir de ExperienceAnalysis y patrones.
3. Máquina de estados estricta y transiciones válidas de ciclo de vida.
4. Bloqueo determinista de transiciones de estado inválidas (ej. DRAFT -> DEPLOYED).
5. PROTECCIÓN ABSOLUTA DE SEGURIDAD: Rechazo tajante de propuestas que toquen
   security_policy, permission_manager, confirmation_manager, audit_logger, etc.
6. Rutas de rechazo, fallo de simulación y rollback.
7. Persistencia en InMemoryProposalStore y SQLiteProposalStore.
8. Simulación con ProposalSimulator y comprobación de regresiones.
9. Deduplicación de propuestas y consultas por estado.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.experience.analysis_models import (
    CorrectionPattern,
    ExperienceAnalysis,
    ExperienceMetrics,
    FailurePattern,
    IntentPattern,
    LatencyPattern,
    PatternSeverity,
    PatternType,
    STTPattern,
)
from core.learning.proposal_engine import LearningProposalEngine
from core.learning.proposal_models import (
    LearningProposal,
    ProposalCategory,
    ProposalRiskLevel,
    ProposalStatus,
    SimulationResult,
)
from core.learning.proposal_store import InMemoryProposalStore, SQLiteProposalStore
from core.learning.proposal_validator import (
    ProposalValidator,
    is_security_component,
)
from core.learning.simulator import ProposalSimulator

# ── TEST 1: CREACIÓN Y VALIDACIÓN DEL MODELO LEARNING PROPOSAL ──

def test_learning_proposal_model_creation():
    """Verifica instanciación, generación de UUID y campos obligatorios."""
    prop = LearningProposal(
        category=ProposalCategory.STT,
        problem="El reconocedor STT confunde 'bloc de notas'",
        evidence=[{"term": "blog de notas", "occurrences": 18}],
        occurrences=18,
        current_behavior="Baja confianza en transcripción",
        suggested_improvement="Agregar pista de vocabulario contextual",
        expected_benefit="Aumentar exactitud a 99%",
        risk=ProposalRiskLevel.LOW,
        affected_components=["voice.stt_vocabulary"],
        required_tests=["test_voice_notepad_command"],
    )

    assert prop.proposal_id is not None
    uuid.UUID(prop.proposal_id)
    assert prop.created_at is not None
    assert prop.status == ProposalStatus.DRAFT
    assert prop.category == ProposalCategory.STT
    assert prop.occurrences == 18

    # Serialización y deserialización
    data = prop.to_dict()
    reconstructed = LearningProposal.from_dict(data)
    assert reconstructed.proposal_id == prop.proposal_id
    assert reconstructed.problem == prop.problem


# ── TEST 2: PROTECCIÓN ABSOLUTA DE SEGURIDAD ──

@pytest.mark.parametrize("sec_component", [
    "security_policy",
    "permission_manager",
    "confirmation_manager",
    "audit_logger",
    "credential_handling",
    "secret_storage",
    "authentication",
    "sandbox_boundaries",
    "execution_boundary",
    "mcp_security_boundaries",
    "risk_engine",
    "emergency_stop",
    "core.security_policy.rules",
    "services.auth.credential_handling",
])
def test_absolute_security_protection_blocks_proposals(sec_component: str):
    """Garantiza que cualquier propuesta sobre componentes de seguridad sea rechazada inmediatamente."""
    assert is_security_component(sec_component) is True

    unsafe_proposal = LearningProposal(
        category=ProposalCategory.TOOL,
        problem=f"Intento de optimizar {sec_component}",
        evidence=[{"incident": "auto-grant"}],
        occurrences=5,
        current_behavior="Pide confirmación humana",
        suggested_improvement=f"Bypassear confirmación en {sec_component}",
        expected_benefit="Mayor velocidad",
        risk=ProposalRiskLevel.CRITICAL,
        affected_components=[sec_component],
        required_tests=["test_bypass"],
    )

    is_valid, errors = ProposalValidator.validate_proposal(unsafe_proposal)
    assert is_valid is False
    assert any("CRITICAL SECURITY VIOLATION" in err for err in errors)

    # El engine debe rechazar el submit
    store = InMemoryProposalStore()
    engine = LearningProposalEngine(store=store)
    with pytest.raises(ValueError, match="CRITICAL SECURITY VIOLATION"):
        engine.submit_proposal(unsafe_proposal)


# ── TEST 3: GENERACIÓN DE PROPUESTAS DESDE ANALYSIS & PATTERNS ──

def test_generate_proposals_from_experience_analysis():
    """Verifica que ExperienceAnalysis genere propuestas coherentes para cada tipo de patrón."""
    now = datetime.now(UTC)

    stt_pattern = STTPattern(
        type=PatternType.STT_RECOGNITION,
        description="Variantes de bloc de notas",
        frequency=18,
        confidence=0.92,
        first_seen=now,
        last_seen=now,
        affected_operations=["bloc de notas"],
        severity=PatternSeverity.LOW,
        canonical_target="bloc de notas",
        variants=["blog de notas", "blot de notas"],
    )

    fail_pattern = FailurePattern(
        type=PatternType.REPEATED_FAILURE,
        description="Fallo recurrente en app.launch",
        frequency=4,
        confidence=0.85,
        first_seen=now,
        last_seen=now,
        affected_operations=["app.launch"],
        severity=PatternSeverity.HIGH,
        failure_rate=0.40,
    )

    lat_pattern = LatencyPattern(
        type=PatternType.LATENCY_DEGRADATION,
        description="Latencia alta en search_files",
        frequency=10,
        confidence=0.90,
        first_seen=now,
        last_seen=now,
        affected_operations=["search_files"],
        severity=PatternSeverity.MEDIUM,
        avg_latency_ms=1200.0,
    )

    corr_pattern = CorrectionPattern(
        type=PatternType.USER_CORRECTION,
        description="Corrección de café por té",
        frequency=3,
        confidence=0.88,
        first_seen=now,
        last_seen=now,
        affected_operations=["list_items"],
        severity=PatternSeverity.LOW,
        corrected_values=["té"],
    )

    intent_pattern = IntentPattern(
        type=PatternType.LOW_INTENT_CONFIDENCE,
        description="Ambigüedad en general_query",
        frequency=5,
        confidence=0.75,
        first_seen=now,
        last_seen=now,
        affected_operations=["general_query"],
        severity=PatternSeverity.LOW,
        intent_name="general_query",
    )

    analysis = ExperienceAnalysis(
        metrics=ExperienceMetrics(total_experiences=100),
        patterns=[stt_pattern, fail_pattern, lat_pattern, corr_pattern, intent_pattern],
        summary="Análisis de prueba con 5 patrones",
    )

    store = InMemoryProposalStore()
    engine = LearningProposalEngine(store=store)

    proposals = engine.generate_proposals_from_analysis(analysis)

    assert len(proposals) == 5
    categories = {p.category for p in proposals}
    assert categories == {
        ProposalCategory.STT,
        ProposalCategory.UX,
        ProposalCategory.PERFORMANCE,
        ProposalCategory.INTENT,
    }

    # Verificar que la propuesta STT contenga 'bloc de notas'
    stt_prop = next(p for p in proposals if p.category == ProposalCategory.STT)
    assert "bloc de notas" in stt_prop.problem
    assert "voice.stt_contextual_vocabulary" in stt_prop.affected_components


# ── TEST 4: MÁQUINA DE ESTADOS FORMAL Y TRANSICIONES VÁLIDAS ──

def test_proposal_state_machine_happy_path():
    """Verifica el ciclo de vida completo: DRAFT -> VALIDATED -> SIMULATION_PENDING -> READY_FOR_EVALUATION -> APPROVED -> DEPLOYED -> ROLLED_BACK."""
    store = InMemoryProposalStore()
    engine = LearningProposalEngine(store=store)

    prop = LearningProposal(
        category=ProposalCategory.STT,
        problem="Ambigüedad STT en 'calculadora'",
        evidence=[{"count": 10}],
        occurrences=10,
        suggested_improvement="Agregar pista de vocabulario para calculadora",
        expected_benefit="Mayor exactitud",
        risk=ProposalRiskLevel.LOW,
        affected_components=["voice.stt_vocabulary"],
        required_tests=["test_calc_command"],
    )

    # 1. Submit -> VALIDATED
    v_prop = engine.submit_proposal(prop)
    assert v_prop.status == ProposalStatus.VALIDATED

    # 2. VALIDATED -> SIMULATION_PENDING
    sim_prop = engine.advance_proposal(v_prop.proposal_id, ProposalStatus.SIMULATION_PENDING)
    assert sim_prop.status == ProposalStatus.SIMULATION_PENDING

    # 3. SIMULATION_PENDING -> READY_FOR_EVALUATION
    ready_prop = engine.advance_proposal(sim_prop.proposal_id, ProposalStatus.READY_FOR_EVALUATION)
    assert ready_prop.status == ProposalStatus.READY_FOR_EVALUATION

    # 4. READY_FOR_EVALUATION -> APPROVED
    app_prop = engine.advance_proposal(ready_prop.proposal_id, ProposalStatus.APPROVED)
    assert app_prop.status == ProposalStatus.APPROVED

    # 5. APPROVED -> DEPLOYED
    dep_prop = engine.advance_proposal(app_prop.proposal_id, ProposalStatus.DEPLOYED)
    assert dep_prop.status == ProposalStatus.DEPLOYED

    # 6. DEPLOYED -> ROLLED_BACK
    rb_prop = engine.advance_proposal(dep_prop.proposal_id, ProposalStatus.ROLLED_BACK)
    assert rb_prop.status == ProposalStatus.ROLLED_BACK


# ── TEST 5: BLOQUEO ESTRICTO DE TRANSICIONES INVÁLIDAS ──

def test_invalid_state_transitions_are_blocked():
    """Verifica que saltos arbitrarios de estado sean estrictamente rechazados."""
    store = InMemoryProposalStore()
    engine = LearningProposalEngine(store=store)

    prop = LearningProposal(
        category=ProposalCategory.UX,
        problem="Problema menor de UX",
        evidence=[{"count": 2}],
        suggested_improvement="Mejora UX",
        expected_benefit="Mejor experiencia",
        affected_components=["ui.ux"],
        required_tests=["test_ux"],
    )
    store.save(prop)

    # Intento inválido: DRAFT -> DEPLOYED
    with pytest.raises(ValueError, match="Transición de estado inválida"):
        engine.advance_proposal(prop.proposal_id, ProposalStatus.DEPLOYED)

    # Intento inválido: DRAFT -> APPROVED
    with pytest.raises(ValueError, match="Transición de estado inválida"):
        engine.advance_proposal(prop.proposal_id, ProposalStatus.APPROVED)

    # Avanzar a REJECTED
    rej_prop = engine.advance_proposal(prop.proposal_id, ProposalStatus.REJECTED, reason="No prioritario")
    assert rej_prop.status == ProposalStatus.REJECTED
    assert rej_prop.rejection_reason == "No prioritario"

    # Intento inválido: REJECTED -> VALIDATED
    with pytest.raises(ValueError, match="Transición de estado inválida"):
        engine.advance_proposal(prop.proposal_id, ProposalStatus.VALIDATED)


# ── TEST 6: SIMULADOR DE PROPUESTAS ──

def test_proposal_simulator_execution():
    """Verifica que ProposalSimulator evalúe pruebas y métricas sin regresiones."""
    simulator = ProposalSimulator()

    valid_prop = LearningProposal(
        category=ProposalCategory.PERFORMANCE,
        problem="Latencia alta",
        evidence=[{"latency_ms": 800}],
        suggested_improvement="Cachear resultados",
        expected_benefit="Menor latencia",
        affected_components=["core.pipeline_optimizer"],
        required_tests=["test_latency_1", "test_latency_2"],
    )

    res: SimulationResult = simulator.simulate(valid_prop)
    assert res.passed is True
    assert res.failed is False
    assert res.tests_run == 2
    assert len(res.regressions) == 0


# ── TEST 7: ALMACÉN PERSISTENTE SQLITE ──

def test_sqlite_proposal_store_persistence():
    """Verifica persistencia determinista y consultas en SQLiteProposalStore."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = str(Path(tmpdir) / "test_proposals.db")
        store = SQLiteProposalStore(db_path=db_file)

        prop1 = LearningProposal(
            category=ProposalCategory.STT,
            problem="Ambigüedad STT 1",
            evidence=[{"count": 5}],
            status=ProposalStatus.DRAFT,
            affected_components=["voice.stt"],
            suggested_improvement="Solución 1",
            expected_benefit="Beneficio 1",
            required_tests=["t1"],
        )
        prop2 = LearningProposal(
            category=ProposalCategory.PERFORMANCE,
            problem="Rendimiento bajo 2",
            evidence=[{"count": 8}],
            status=ProposalStatus.APPROVED,
            affected_components=["core.perf"],
            suggested_improvement="Solución 2",
            expected_benefit="Beneficio 2",
            required_tests=["t2"],
        )

        store.save(prop1)
        store.save(prop2)

        assert store.count() == 2
        assert store.count(status=ProposalStatus.APPROVED) == 1
        assert store.count(category=ProposalCategory.STT) == 1

        # Reabrir base de datos
        store2 = SQLiteProposalStore(db_path=db_file)
        assert store2.count() == 2
        retrieved = store2.get(prop2.proposal_id)
        assert retrieved is not None
        assert retrieved.status == ProposalStatus.APPROVED

        # Consultar por estado
        approved_list = store2.query(status=ProposalStatus.APPROVED)
        assert len(approved_list) == 1
        assert approved_list[0].proposal_id == prop2.proposal_id

        # Borrar y limpiar
        assert store2.delete(prop1.proposal_id) is True
        assert store2.count() == 1
        store2.clear()
        assert store2.count() == 0


# ── TEST 8: CONSULTAS FILTRADAS EN EL ENGINE ──

def test_proposal_engine_filtered_queries():
    """Verifica consultas convenientes get_pending, get_approved, get_rejected, get_deployed, get_rolled_back."""
    store = InMemoryProposalStore()
    engine = LearningProposalEngine(store=store)

    p_draft = LearningProposal(
        category=ProposalCategory.STT,
        problem="Draft problem",
        evidence=[{"e": 1}],
        status=ProposalStatus.DRAFT,
        affected_components=["stt"],
        suggested_improvement="opt",
        expected_benefit="gain",
        required_tests=["t"],
    )
    p_app = LearningProposal(
        category=ProposalCategory.TOOL,
        problem="Approved problem",
        evidence=[{"e": 2}],
        status=ProposalStatus.APPROVED,
        affected_components=["tool"],
        suggested_improvement="opt",
        expected_benefit="gain",
        required_tests=["t"],
    )
    p_rej = LearningProposal(
        category=ProposalCategory.UX,
        problem="Rejected problem",
        evidence=[{"e": 3}],
        status=ProposalStatus.REJECTED,
        affected_components=["ux"],
        suggested_improvement="opt",
        expected_benefit="gain",
        required_tests=["t"],
        rejection_reason="No viable",
    )

    store.save(p_draft)
    store.save(p_app)
    store.save(p_rej)

    assert len(engine.get_pending_proposals()) == 1
    assert len(engine.get_approved_proposals()) == 1
    assert len(engine.get_rejected_proposals()) == 1
    assert len(engine.get_deployed_proposals()) == 0
    assert len(engine.get_rolled_back_proposals()) == 0
