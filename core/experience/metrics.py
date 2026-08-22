"""Motor de Cálculo Estadístico y Métricas Cuantitativas (metrics.py - Fase 58).

Calcula métricas deterministas, tasas porcentuales y percentiles de latencia
a partir de colecciones de experiencias inmutables.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from core.experience.analysis_models import ExperienceMetrics
from core.experience.models import (
    ExecutionStatus,
    Experience,
    ExperienceCategory,
    VerificationStatus,
)


def _calculate_percentile(sorted_data: Sequence[float], percentile: float) -> float:
    """Calcula el percentil determinista con interpolación lineal sobre datos ordenados."""
    if not sorted_data:
        return 0.0
    if len(sorted_data) == 1:
        return float(sorted_data[0])

    k = (len(sorted_data) - 1) * percentile
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_data[int(k)])
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return float(d0 + d1)


def calculate_metrics(experiences: Sequence[Experience]) -> ExperienceMetrics:
    """Calcula las métricas cuantitativas y estadísticas sobre un conjunto de experiencias.

    Maneja de forma segura y determinista casos vacíos y datos dispersos.
    """
    total = len(experiences)
    if total == 0:
        return ExperienceMetrics()

    # Conteo de estados de ejecución
    success_count = 0
    failure_count = 0
    for exp in experiences:
        if exp.execution:
            if exp.execution.status == ExecutionStatus.SUCCESS:
                success_count += 1
            elif exp.execution.status in (ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT):
                failure_count += 1
        elif exp.category == ExperienceCategory.ACTION_SUCCESS:
            success_count += 1
        elif exp.category in (ExperienceCategory.ACTION_FAILED, ExperienceCategory.TIMEOUT):
            failure_count += 1

    success_rate = round(success_count / total, 4)
    failure_rate = round(failure_count / total, 4)

    # Verificación en sistema operativo
    verif_performed = 0
    verif_success = 0
    for exp in experiences:
        if exp.verification and exp.verification.status != VerificationStatus.NOT_PERFORMED:
            verif_performed += 1
            if exp.verification.is_verified or exp.verification.status == VerificationStatus.SUCCESS:
                verif_success += 1
        elif exp.category == ExperienceCategory.VERIFICATION_FAILED:
            verif_performed += 1

    verif_success_rate = round(verif_success / verif_performed, 4) if verif_performed > 0 else 1.0

    # Latencias (Promedio, p50, p95)
    latencies = sorted([exp.latency.total_ms for exp in experiences if exp.latency and exp.latency.total_ms > 0])
    avg_latency = round(sum(latencies) / len(latencies), 2) if latencies else 0.0
    p50_latency = round(_calculate_percentile(latencies, 0.50), 2)
    p95_latency = round(_calculate_percentile(latencies, 0.95), 2)

    # Calidad STT y Confianza
    stt_confs = [exp.stt.confidence for exp in experiences if exp.stt and exp.stt.confidence is not None]
    avg_stt_conf = round(sum(stt_confs) / len(stt_confs), 4) if stt_confs else 1.0

    # Confianza de Intención
    intent_confs = [exp.intent.confidence for exp in experiences if exp.intent and exp.intent.confidence is not None]
    avg_intent_conf = round(sum(intent_confs) / len(intent_confs), 4) if intent_confs else 1.0

    # Tasa de Aclaración
    clarif_count = sum(
        1
        for exp in experiences
        if exp.category in (ExperienceCategory.CLARIFICATION_REQUESTED, ExperienceCategory.AMBIGUOUS_INTENT, ExperienceCategory.LOW_STT_CONFIDENCE)
        or (exp.intent and exp.intent.is_ambiguous)
    )
    clarification_rate = round(clarif_count / total, 4)

    # Tasa de Corrección
    corr_count = sum(
        1
        for exp in experiences
        if exp.category == ExperienceCategory.USER_CORRECTION
        or (exp.correction and exp.correction.is_correction)
    )
    correction_rate = round(corr_count / total, 4)

    # Fallos repetidos sobre la misma operación / intención
    failed_ops: dict[str, int] = {}
    for exp in experiences:
        is_fail = (exp.execution and exp.execution.status in (ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT)) or exp.category in (ExperienceCategory.ACTION_FAILED, ExperienceCategory.TIMEOUT)
        if is_fail:
            op_key = exp.intent.name if exp.intent else (exp.target.value if exp.target else "unknown")
            failed_ops[op_key] = failed_ops.get(op_key, 0) + 1

    repeated_fails = sum(cnt for cnt in failed_ops.values() if cnt > 1)
    repeated_failure_rate = round(repeated_fails / total, 4)

    return ExperienceMetrics(
        total_experiences=total,
        success_count=success_count,
        failure_count=failure_count,
        success_rate=success_rate,
        failure_rate=failure_rate,
        verification_success_rate=verif_success_rate,
        avg_latency_ms=avg_latency,
        p50_latency_ms=p50_latency,
        p95_latency_ms=p95_latency,
        stt_confidence_avg=avg_stt_conf,
        intent_confidence_avg=avg_intent_conf,
        clarification_rate=clarification_rate,
        correction_rate=correction_rate,
        repeated_failure_rate=repeated_failure_rate,
    )
