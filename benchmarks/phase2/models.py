"""Definiciones de modelos y tipos de datos para la Fase 2 del Benchmark Real JESSYCA PC."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class BenchmarkCategory(StrEnum):
    CAT1_NORMAL_COMMANDS = "cat1_normal_commands"
    CAT2_AMBIGUOUS_COMMANDS = "cat2_ambiguous_commands"
    CAT3_FALSE_SUCCESS = "cat3_false_success"
    CAT4_ERROR_RECOVERY = "cat4_error_recovery"
    CAT5_MULTISTEP_PLANNING = "cat5_multistep_planning"
    CAT6_PROJECT_ANALYSIS = "cat6_project_analysis"
    CAT7_DEBUGGING = "cat7_debugging"
    CAT8_MODEL_ROUTING_DECISION = "cat8_model_routing_decision"
    CAT9_CONTRADICTIONS = "cat9_contradictions"
    CAT10_CONVERSATIONAL_CONTEXT = "cat10_conversational_context"


@dataclass(frozen=True)
class Phase2TestCase:
    """Caso de prueba de benchmark de Fase 2."""

    test_id: str
    category: BenchmarkCategory
    title: str
    prompt: str
    system_prompt: str | None = None
    expected_intent: str | None = None
    expected_tool: str | None = None
    expected_arguments: dict[str, Any] = field(default_factory=dict)
    tool_simulation_result: dict[str, Any] = field(default_factory=dict)
    verification_simulation_result: dict[str, Any] = field(default_factory=dict)
    requires_verification: bool = False
    is_ambiguous: bool = False
    is_contradiction: bool = False
    has_prior_context: bool = False
    prior_context_messages: tuple[dict[str, str], ...] = ()
    expected_keywords: tuple[str, ...] = ()
    forbidden_keywords: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionTrace:
    """Trazabilidad completa de una ejecución individual."""

    test_id: str
    iteration: int
    category: str
    title: str
    model: str
    provider: str
    prompt: str
    response: str
    selected_tool: str | None
    arguments: dict[str, Any]
    tool_result: dict[str, Any]
    verification_result: dict[str, Any]
    final_decision: str
    latency_ms: float
    ttft_ms: float
    tokens_used: int | None
    error: str | None
    false_success: bool
    hallucination: bool
    intent_accurate: bool
    tool_accurate: bool
    argument_accurate: bool
    plan_correct: bool
    verification_correct: bool
    error_recognized: bool
    recovery_quality: float
    context_resolved: bool
    score: float


@dataclass
class AggregatedMetrics:
    """Métricas agregadas para un modelo a lo largo de todas las ejecuciones."""

    model_name: str
    provider: str
    total_runs: int = 0
    passed_runs: int = 0
    failed_runs: int = 0
    
    # 10 Métricas independientes requeridas
    intent_accuracy: float = 0.0
    tool_selection_accuracy: float = 0.0
    argument_accuracy: float = 0.0
    plan_correctness: float = 0.0
    verification_correctness: float = 0.0
    false_success_rate: float = 0.0
    error_recognition_rate: float = 0.0
    recovery_quality_avg: float = 0.0
    hallucination_rate: float = 0.0
    context_resolution_rate: float = 0.0

    # Latencia
    avg_latency_ms: float = 0.0
    min_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    avg_ttft_ms: float = 0.0

    # Desglose por categoría
    category_scores: dict[str, float] = field(default_factory=dict)
    category_latencies: dict[str, float] = field(default_factory=dict)

    # Trazas detalladas
    traces: list[ExecutionTrace] = field(default_factory=list)
