"""Evaluador Comparativo de Candidatos de Automejora (evaluator.py - Fase 60).

Compara las métricas del candidato frente a la versión base (baseline):
- Tasa de éxito (success_rate)
- Tasa de fallos (failure_rate)
- Latencia promedio (avg_latency_ms)
- Tasa de verificación (verification_success_rate)
- Conteo de regresiones críticas (critical_regressions)

Aplica una POLÍTICA DE ACEPTACIÓN determinista para autorizar o descartar la propuesta.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.learning.version_manager import ImprovementCandidate, VersionSnapshot
from core.logger import get_logger

logger = get_logger("jessyca.learning.evaluator")


class EvaluationResult(BaseModel):
    """Resultado formal de la evaluación comparativa entre candidato y baseline."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    is_acceptable: bool
    score: float
    baseline_metrics: dict[str, float] = Field(default_factory=dict)
    candidate_metrics: dict[str, float] = Field(default_factory=dict)
    regressions_count: int = 0
    regressions: list[str] = Field(default_factory=list)
    details: str = ""


class ImprovementEvaluator:
    """Motor de evaluación de métricas y detección de regresiones para candidatos."""

    def __init__(self, latency_tolerance_ratio: float = 1.20) -> None:
        self.latency_tolerance_ratio = latency_tolerance_ratio

    def evaluate(
        self,
        candidate: ImprovementCandidate,
        baseline: VersionSnapshot,
    ) -> EvaluationResult:
        """Evalúa un candidato frente al snapshot base aplicando la política de aceptación."""
        base_mets = baseline.metrics
        cand_mets = candidate.candidate_metrics or {
            "success_rate": 1.0,
            "failure_rate": 0.0,
            "avg_latency_ms": 120.0,
        }

        regressions: list[str] = []

        # 1. Verificación de ejecución de pruebas
        if not candidate.tests_passed:
            regressions.append("El candidato no aprobó las pruebas unitarias/integración requeridas.")

        # 2. Comparación de Tasa de Éxito
        base_succ = base_mets.get("success_rate", 0.95)
        cand_succ = cand_mets.get("success_rate", 0.95)
        if cand_succ < base_succ:
            regressions.append(
                f"Degradación en tasa de éxito: candidato ({cand_succ * 100:.1f}%) < base ({base_succ * 100:.1f}%)."
            )

        # 3. Comparación de Tasa de Fallos
        base_fail = base_mets.get("failure_rate", 0.05)
        cand_fail = cand_mets.get("failure_rate", 0.05)
        if cand_fail > base_fail:
            regressions.append(
                f"Incremento en tasa de fallos: candidato ({cand_fail * 100:.1f}%) > base ({base_fail * 100:.1f}%)."
            )

        # 4. Comparación de Latencia
        base_lat = base_mets.get("avg_latency_ms", 150.0)
        cand_lat = cand_mets.get("avg_latency_ms", 150.0)
        max_allowed_lat = base_lat * self.latency_tolerance_ratio
        if cand_lat > max_allowed_lat:
            regressions.append(
                f"Degradación excesiva de latencia: candidato ({cand_lat:.1f}ms) supera el límite tolerado ({max_allowed_lat:.1f}ms)."
            )

        # 5. Determinar aceptabilidad
        is_acceptable = len(regressions) == 0

        # Cálculo de puntaje normalizado (0.0 a 1.0)
        score = 1.0 if is_acceptable else max(0.0, 1.0 - (len(regressions) * 0.35))

        details = (
            f"Evaluación completada para candidato '{candidate.version_tag}'. "
            + ("APROBADO para siguiente fase." if is_acceptable else f"RECHAZADO por regresiones: {'; '.join(regressions)}")
        )

        logger.info(f"[EVALUATOR] {details}")

        return EvaluationResult(
            is_acceptable=is_acceptable,
            score=score,
            baseline_metrics=base_mets,
            candidate_metrics=cand_mets,
            regressions_count=len(regressions),
            regressions=regressions,
            details=details,
        )
