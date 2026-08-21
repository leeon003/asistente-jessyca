"""Tests unitarios exhaustivos para el Multi-LLM Consensus Engine (Fase 10: Multi-LLM Consensus Engine)."""

from core.llm import (
    ConsensusEngine,
    ConsensusPolicy,
    ConsensusStatus,
    ConsensusStrategy,
    ModelVote,
    get_consensus_engine,
)


class TestMultiLLMConsensusEngine:
    """Pruebas de consenso unánime, mayoría, desacuerdos, timeouts, caídas y seguridad."""

    def setup_method(self) -> None:
        self.engine = ConsensusEngine()

    # ── 1. CONSENSO UNÁNIME Y POR MAYORÍA ──

    def test_unanimous_consensus(self) -> None:
        """Verifica el consenso cuando todos los modelos coinciden en la misma decisión."""
        votes = [
            ModelVote(model_id="qwen3:8b", decision="ALLOW", answer="Acción segura.", confidence=0.95),
            ModelVote(model_id="gemma4:e4b", decision="ALLOW", answer="Acción segura verificada.", confidence=0.90),
            ModelVote(model_id="llama3.1:latest", decision="ALLOW", answer="Permitido.", confidence=0.92),
        ]

        result = self.engine.evaluate_votes(votes=votes, task="Validar operación de solo lectura")

        assert result.status == ConsensusStatus.UNANIMOUS
        assert result.is_consensus_reached is True
        assert result.final_decision == "ALLOW"
        assert result.agreement_ratio == 1.0
        assert result.confidence_score > 0.90
        assert result.divergence_notes is None

    def test_majority_consensus(self) -> None:
        """Verifica el consenso cuando 2 de 3 modelos coinciden en la decisión."""
        votes = [
            ModelVote(model_id="qwen3:8b", decision="RETRY", answer="Reintentar con backoff.", confidence=0.90),
            ModelVote(model_id="gemma4:e4b", decision="RETRY", answer="Reintentar.", confidence=0.85),
            ModelVote(model_id="llama3.1:latest", decision="ABORT", answer="Abortar operación.", confidence=0.80),
        ]

        result = self.engine.evaluate_votes(votes=votes, task="Evaluar fallo de red")

        assert result.status == ConsensusStatus.MAJORITY
        assert result.is_consensus_reached is True
        assert result.final_decision == "RETRY"
        assert round(result.agreement_ratio, 2) == 0.67
        assert "Mayoría alcanzada" in (result.divergence_notes or "")

    # ── 2. DESACUERDO Y RESULTADO AMBIGUO ──

    def test_disagreement_all_different(self) -> None:
        """Verifica el estado DISAGREEMENT cuando cada modelo emite una decisión distinta."""
        votes = [
            ModelVote(model_id="qwen3:8b", decision="OPTION_A", answer="A", confidence=0.8),
            ModelVote(model_id="gemma4:e4b", decision="OPTION_B", answer="B", confidence=0.8),
            ModelVote(model_id="llama3.1:latest", decision="OPTION_C", answer="C", confidence=0.8),
        ]

        result = self.engine.evaluate_votes(votes=votes, task="Selección de estrategia")

        assert result.status == ConsensusStatus.DISAGREEMENT
        assert result.is_consensus_reached is False
        assert result.final_decision is None
        assert result.divergence_notes is not None

    def test_strict_unanimous_disagreement(self) -> None:
        """Verifica que bajo UNANIMOUS_REQUIRED una sola disidencia genere DISAGREEMENT."""
        policy = ConsensusPolicy(strategy=ConsensusStrategy.UNANIMOUS_REQUIRED)
        votes = [
            ModelVote(model_id="qwen3:8b", decision="PROCEED", answer="OK", confidence=0.95),
            ModelVote(model_id="gemma4:e4b", decision="PROCEED", answer="OK", confidence=0.95),
            ModelVote(model_id="llama3.1:latest", decision="WAIT", answer="Esperar", confidence=0.70),
        ]

        result = self.engine.evaluate_votes(votes=votes, task="Verificación estricta", policy=policy)

        assert result.status == ConsensusStatus.DISAGREEMENT
        assert result.is_consensus_reached is False
        assert "Divergencia" in (result.divergence_notes or "")

    # ── 3. TOLERANCIA A FALLOS: TIMEOUT Y MODELO CAÍDO ──

    def test_fault_tolerance_one_model_down(self) -> None:
        """Verifica que si 1 modelo se cae o sufre timeout, los 2 restantes aún logren consenso."""
        votes = [
            ModelVote(model_id="qwen3:8b", decision="SUCCESS", answer="OK", confidence=0.9),
            ModelVote(model_id="gemma4:e4b", decision="SUCCESS", answer="OK", confidence=0.85),
            ModelVote(
                model_id="llama3.1:latest",
                decision="ERROR",
                answer="",
                confidence=0.0,
                is_valid=False,
                error="ConnectionTimeout: Ollama endpoint unreachable",
            ),
        ]

        result = self.engine.evaluate_votes(votes=votes, task="Tarea tolerante a fallos")

        assert result.status == ConsensusStatus.UNANIMOUS
        assert result.is_consensus_reached is True
        assert result.final_decision == "SUCCESS"
        assert result.agreement_ratio == 1.0

    def test_insufficient_responses_when_multiple_fail(self) -> None:
        """Verifica INSUFFICIENT_RESPONSES si menos del quórum mínimo (2) logran responder."""
        votes = [
            ModelVote(model_id="qwen3:8b", decision="SUCCESS", answer="OK", confidence=0.9),
            ModelVote(model_id="gemma4:e4b", decision="ERROR", answer="", is_valid=False, error="OOM Error"),
            ModelVote(model_id="llama3.1:latest", decision="ERROR", answer="", is_valid=False, error="Timeout"),
        ]

        result = self.engine.evaluate_votes(votes=votes, task="Tarea con falla masiva")

        assert result.status == ConsensusStatus.INSUFFICIENT_RESPONSES
        assert result.is_consensus_reached is False
        assert result.final_decision is None

    # ── 4. ESTRATEGIA PONDERADA (WEIGHTED CONFIDENCE) ──

    def test_weighted_confidence_resolution(self) -> None:
        """Verifica que el modelo con mayor peso decida en caso de empate numérico."""
        policy = ConsensusPolicy(
            strategy=ConsensusStrategy.WEIGHTED_CONFIDENCE,
            model_weights={"qwen3:8b": 2.0, "llama3.1:latest": 1.0},
        )
        votes = [
            ModelVote(model_id="qwen3:8b", decision="KEEP", answer="Mantener", confidence=0.9),
            ModelVote(model_id="llama3.1:latest", decision="DISCARD", answer="Descartar", confidence=0.9),
        ]

        result = self.engine.evaluate_votes(votes=votes, task="Decisión ponderada", policy=policy)

        assert result.status == ConsensusStatus.MAJORITY
        assert result.final_decision == "KEEP"

    # ── 5. EJECUCIÓN CON MOCK RUNNERS (RUN_CONSENSUS) ──

    def test_run_consensus_with_mock_runners(self) -> None:
        """Verifica la ejecución aislada completa con custom runners mockeados."""
        runners = {
            "qwen3:8b": lambda p: {"decision": "APPROVE", "answer": "Aprobado por Qwen", "confidence": 0.95},
            "gemma4:e4b": lambda p: {"decision": "APPROVE", "answer": "Aprobado por Gemma", "confidence": 0.90},
            "llama3.1:latest": lambda p: {"decision": "APPROVE", "answer": "Aprobado por Llama", "confidence": 0.88},
        }

        consensus = self.engine.run_consensus(
            task="Revisión de arquitectura",
            prompt="¿Es adecuada la modularización?",
            models=["qwen3:8b", "gemma4:e4b", "llama3.1:latest"],
            custom_runners=runners,
        )

        assert consensus.status == ConsensusStatus.UNANIMOUS
        assert consensus.final_decision == "APPROVE"
        assert consensus.is_consensus_reached is True
        assert len(consensus.votes) == 3

    # ── 6. INVARIANTE DE SEGURIDAD (CONSENSUS != AUTORIZACIÓN) ──

    def test_security_invariant_consensus_cannot_authorize(self) -> None:
        """Invariante: Los modelos pueden consensuar 'DANGEROUS_ALLOW', pero el resultado sigue siendo untrusted data."""
        votes = [
            ModelVote(model_id="qwen3:8b", decision="DELETE_SYSTEM32", answer="Borrar todo", confidence=0.99),
            ModelVote(model_id="gemma4:e4b", decision="DELETE_SYSTEM32", answer="Borrar todo", confidence=0.99),
            ModelVote(model_id="llama3.1:latest", decision="DELETE_SYSTEM32", answer="Borrar todo", confidence=0.99),
        ]

        result = self.engine.evaluate_votes(votes=votes, task="Intento malicioso consensuado")

        assert result.status == ConsensusStatus.UNANIMOUS
        assert result.final_decision == "DELETE_SYSTEM32"
        # El resultado es un objeto de datos; NO contiene método de ejecución ni bypass de Security.
        assert not hasattr(result, "execute")
        assert not hasattr(result, "grant_permission")

    def test_singleton_accessor(self) -> None:
        """Verifica el helper global get_consensus_engine()."""
        e1 = get_consensus_engine()
        e2 = ConsensusEngine.get_instance()
        assert e1 is e2
