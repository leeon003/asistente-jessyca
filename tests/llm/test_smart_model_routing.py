"""Tests unitarios e integrales para Smart Model Routing 2.0 (Fase 25: Multi-Factor Model Routing).

Verifica:
1. Enrutamiento multi-factor por TaskType y Complejidad
2. Requisito estricto de capacidad (Capability Non-Negotiability: Vision exige modelo con visión)
3. Fallback determinista y cadena de respaldo ante fallos/exclusión
4. Restricción de VRAM (anti-OOM y selección de modelos ligeros)
5. Rendimiento histórico (ModelPerformanceTracker)
6. Confianza y desglose explicable de puntuaciones (candidate_scores)
7. Imposibilidad de auto-elección unilateral por el modelo
8. Integración con Consenso Multi-LLM
9. Invariante: MODEL ROUTER != AUTHORIZATION
"""

from core.llm.consensus_policy import ConsensusPolicy, ConsensusStrategy
from core.llm.model_registry import ModelRegistry
from core.llm.model_router import ModelRouter
from core.llm.routing_policy import (
    RoutingContext,
    RoutingPolicy,
    TaskComplexity,
    TaskType,
)
from core.llm.smart_routing_models import ModelPerformanceTracker
from core.permission_manager import PermissionDecision, PermissionManager
from core.risk_engine import RiskEngine
from core.security_architecture import (
    SecurityContext,
    SecurityLevel,
    SecurityRequest,
    ToolSecurityMetadata,
)


class TestSmartModelRouting2:
    """Suite de pruebas exhaustiva para Smart Model Routing 2.0."""

    def setup_method(self) -> None:
        self.registry = ModelRegistry.get_instance()
        self.tracker = ModelPerformanceTracker()
        self.tracker.reset()
        self.policy = RoutingPolicy(registry=self.registry, tracker=self.tracker)
        self.router = ModelRouter(registry=self.registry, policy=self.policy, tracker=self.tracker)
        self.risk_engine = RiskEngine()
        self.permission_manager = PermissionManager()

    # ── 1. ENRUTAMIENTO MULTI-FACTOR POR TIPO DE TAREA ──

    def test_routing_by_task_type(self) -> None:
        """Verifica que cada tipo de tarea resuelva al modelo óptimo de su categoría."""
        # Visión -> qwen3-vl:4b
        p_vision = self.router.select_model_for_task(TaskType.VISION)
        assert p_vision.name == "qwen3-vl:4b"

        # Razonamiento complejo -> qwen3:8b
        p_reason = self.router.select_model_for_task(TaskType.REASONING, complexity=TaskComplexity.HIGH)
        assert p_reason.name == "qwen3:8b"

        # Clasificación rápida -> llama3.2
        p_class = self.router.select_model_for_task(TaskType.CLASSIFICATION, complexity=TaskComplexity.LOW)
        assert p_class.name == "llama3.2"

        # Conversación general -> llama3.1
        p_conv = self.router.select_model_for_task(TaskType.CONVERSATION)
        assert p_conv.name in ("llama3.1", "llama3.2")

    # ── 2. REQUISITO ESTRICTO DE CAPACIDAD (CAPABILITY NON-NEGOTIABILITY) ──

    def test_capability_non_negotiability_for_vision(self) -> None:
        """Verifica que una tarea de visión JAMÁS seleccione un modelo sin visión, incluso con mejor historial."""
        # Darle rendimiento perfecto a llama3.2
        self.router.record_inference_result(
            model_name="llama3.2",
            task_type=TaskType.VISION,
            latency_ms=10.0,
            success=True,
        )

        context = RoutingContext(task_type=TaskType.VISION, requires_vision=True)
        decision = self.router.route_smart(context)

        # Debe seleccionar obligatoriamente qwen3-vl:4b porque es el único con visión
        assert decision.selected_model.name == "qwen3-vl:4b"
        assert decision.selected_model.supports_vision is True

    # ── 3. FALLBACK DETERMINISTA ANTE MODELO NO DISPONIBLE ──

    def test_deterministic_fallback_chain(self) -> None:
        """Verifica que si el modelo primario está excluido o falla, el enrutador use el fallback determinista."""
        context = RoutingContext(
            task_type=TaskType.REASONING,
            complexity=TaskComplexity.HIGH,
            excluded_model_ids=("qwen3:8b",),  # Excluir el primario
        )

        decision = self.router.route_smart(context)
        # El fallback debe ser el siguiente compatible en razonamiento (gemma4:e4b o llama3.1)
        assert decision.selected_model.name in ("gemma4:e4b", "llama3.1")
        assert decision.selected_model.name != "qwen3:8b"

    def test_get_fallback_model_convenience_method(self) -> None:
        """Verifica que get_fallback_model() asigne automáticamente un reemplazo válido."""
        fallback = self.router.get_fallback_model(attempted_model="llama3.2")
        assert fallback is not None
        assert fallback.name != "llama3.2"

    # ── 4. RESTRICCIÓN DE VRAM Y PREVENCIÓN DE OOM ──

    def test_vram_pressure_filters_heavy_models(self) -> None:
        """Verifica que ante presupuesto acotado de VRAM (ej. 3000 MB), se descarte qwen3:8b (5700 MB)."""
        context = RoutingContext(
            task_type=TaskType.REASONING,
            max_available_vram_mb=3000,  # Límite estricto que solo permite modelos livianos
        )

        decision = self.router.route_smart(context)
        assert decision.selected_model.vram_estimate_mb is not None
        assert decision.selected_model.vram_estimate_mb <= 3000
        assert decision.selected_model.name != "qwen3:8b"

    # ── 5. SEGUIMIENTO DE RENDIMIENTO HISTÓRICO ──

    def test_historical_performance_tracking_influences_scoring(self) -> None:
        """Verifica que el historial de éxito influya en las decisiones de enrutamiento."""
        # Registrar 10 fallos consecutivos para llama3.1 en CLASSIFICATION
        for _ in range(10):
            self.router.record_inference_result(
                model_name="llama3.1",
                task_type=TaskType.CLASSIFICATION,
                latency_ms=120.0,
                success=False,
            )

        # Registrar 10 éxitos para gemma4:e4b
        for _ in range(10):
            self.router.record_inference_result(
                model_name="gemma4:e4b",
                task_type=TaskType.CLASSIFICATION,
                latency_ms=30.0,
                success=True,
            )

        context = RoutingContext(
            task_type=TaskType.CLASSIFICATION,
            excluded_model_ids=("llama3.2",),  # Forzar competencia entre gemma4 y llama3.1
        )
        decision = self.router.route_smart(context)
        assert decision.selected_model.name == "gemma4:e4b"

    # ── 6. CONFIANZA Y DESGLOSE EXPLICABLE (CANDIDATE SCORES) ──

    def test_decision_includes_confidence_and_scores_breakdown(self) -> None:
        """Verifica que la decisión contenga confianza acotada y desglose de candidatos."""
        context = RoutingContext(task_type=TaskType.PLANNING, complexity=TaskComplexity.MEDIUM)
        decision = self.router.route_smart(context)

        assert 0.50 <= decision.confidence <= 1.0
        assert len(decision.candidate_scores) > 0
        assert decision.selected_model.name in decision.candidate_scores
        assert decision.reason != ""
        assert isinstance(decision.fallback_chain, tuple)

    # ── 7. CONSENSO MULTI-LLM ──

    def test_consensus_policy_compatibility(self) -> None:
        """Verifica la compatibilidad con las políticas de consenso Multi-LLM."""
        consensus_pol = ConsensusPolicy(
            min_participating_models=2,
            min_agreement_threshold=0.51,
            strategy=ConsensusStrategy.MAJORITY_VOTE,
        )
        assert consensus_pol.min_participating_models == 2
        assert "qwen3:8b" in consensus_pol.model_weights

    # ── 8. INVARIANTE: MODEL ROUTER != AUTHORIZATION ──

    def test_model_router_has_zero_security_authority(self) -> None:
        """Verifica que ModelRouter no participe en decisiones de seguridad ni bypass de SecurityPipeline."""
        assert not hasattr(self.router, "authorize_action")
        assert not hasattr(self.router, "execute_tool")

        # Comprobación de que una acción crítica sigue siendo denegada por SecurityPipeline
        req = SecurityRequest(
            context=SecurityContext(user="router_model", tool_name="system.format_disk", parameters={}),
            metadata=ToolSecurityMetadata(tool_name="system.format_disk", category="system", risk_level=SecurityLevel.CRITICAL),
        )
        assessment = self.risk_engine.evaluate_risk(req)
        assert assessment.risk_level == SecurityLevel.CRITICAL

        decision = self.permission_manager.check_permission(
            tool_name="system.format_disk",
            risk_level=SecurityLevel.CRITICAL,
        )
        assert decision == PermissionDecision.DENY
