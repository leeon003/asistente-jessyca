"""Analizador Central de Experiencias y Detección de Patrones (analyzer.py - Fase 58).

Componente de SOLO LECTURA que examina el historial de experiencias para:
- Extraer métricas estadísticas cuantitativas (tasas, percentiles).
- Delimitar ventanas de análisis temporal o por volumen de datos.
- Detectar patrones recurrentes, anomalías y oportunidades de mejora.
- Producir un ExperienceAnalysis inmutable y auditable para futuras propuestas.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from core.experience.analysis_models import (
    AnalysisWindow,
    ExperienceAnalysis,
    ExperienceMetrics,
    Pattern,
)
from core.experience.experience_store import IExperienceStore, SQLiteExperienceStore
from core.experience.metrics import calculate_metrics
from core.experience.models import Experience
from core.experience.patterns import detect_all_patterns
from core.experience.repository import ExperienceRepository, IExperienceRepository
from core.logger import get_logger

logger = get_logger("jessyca.experience.analyzer")


class ExperienceAnalyzer:
    """Motor de análisis de solo lectura sobre el repositorio de experiencias."""

    def __init__(
        self,
        repository: IExperienceRepository | None = None,
        store: IExperienceStore | None = None,
    ) -> None:
        if repository is not None:
            self._repository = repository
        else:
            active_store = store or SQLiteExperienceStore()
            self._repository = ExperienceRepository(store=active_store)

    @property
    def repository(self) -> IExperienceRepository:
        """Acceso de solo lectura al repositorio de experiencias."""
        return self._repository

    def _fetch_experiences(self, window: AnalysisWindow) -> list[Experience]:
        """Recupera y filtra las experiencias cumpliendo los criterios de la ventana."""
        # Determinar límite base de consulta
        query_limit = window.limit if window.limit is not None else 1000

        # Si hay filtro por intent
        if window.intent:
            raw_exps = self._repository.store.query(limit=query_limit)
        else:
            raw_exps = self._repository.get_recent(limit=query_limit)

        now = datetime.now(UTC)
        filtered: list[Experience] = []

        # Calcular límites de tiempo si están definidos
        min_time: datetime | None = window.start_time
        max_time: datetime | None = window.end_time

        if window.hours is not None:
            calc_min = now - timedelta(hours=window.hours)
            min_time = max(min_time, calc_min) if min_time else calc_min

        if window.days is not None:
            calc_min = now - timedelta(days=window.days)
            min_time = max(min_time, calc_min) if min_time else calc_min

        for exp in raw_exps:
            # Filtro temporal
            if min_time and exp.timestamp < min_time:
                continue
            if max_time and exp.timestamp > max_time:
                continue

            # Filtro por acción
            if window.action_type:
                exp_action = exp.execution.action if exp.execution else None
                if exp_action != window.action_type:
                    continue

            # Filtro por skill
            if window.skill:
                exp_skill = exp.metadata.skill_used if exp.metadata else None
                if exp_skill != window.skill:
                    continue

            # Filtro por intent
            if window.intent:
                exp_intent = exp.intent.name if exp.intent else None
                if exp_intent != window.intent:
                    continue

            filtered.append(exp)

        if window.limit is not None:
            return filtered[: window.limit]
        return filtered

    def _generate_summary(self, metrics: ExperienceMetrics, patterns: Sequence[Pattern]) -> str:
        """Genera un resumen textual determinista sobre las métricas y patrones encontrados."""
        if metrics.total_experiences == 0:
            return "No se encontraron experiencias en la ventana de análisis especificada."

        parts: list[str] = [
            f"Análisis sobre {metrics.total_experiences} experiencias.",
            f"Tasa de éxito: {metrics.success_rate * 100:.1f}%, Tasa de fallos: {metrics.failure_rate * 100:.1f}%.",
            f"Latencia promedio: {metrics.avg_latency_ms}ms (p50: {metrics.p50_latency_ms}ms, p95: {metrics.p95_latency_ms}ms).",
        ]

        if patterns:
            parts.append(f"Se detectaron {len(patterns)} patrones relevantes:")
            for p in patterns[:5]:
                parts.append(f"- [{p.type.value}] {p.description}")
        else:
            parts.append("No se detectaron patrones anómalos o de fallo recurrente.")

        return " ".join(parts)

    def analyze(
        self,
        window: AnalysisWindow | None = None,
        config: dict[str, Any] | None = None,
    ) -> ExperienceAnalysis:
        """Ejecuta el análisis completo y estructurado sobre la ventana especificada."""
        win = window or AnalysisWindow(limit=100)
        experiences = self._fetch_experiences(win)

        metrics = calculate_metrics(experiences)
        patterns = detect_all_patterns(experiences, config=config)
        summary = self._generate_summary(metrics, patterns)

        analysis = ExperienceAnalysis(
            window=win,
            metrics=metrics,
            patterns=patterns,
            summary=summary,
            metadata={"generated_by": "ExperienceAnalyzer@3.0", "experiences_analyzed": len(experiences)},
        )

        logger.info(f"[EXPERIENCE ANALYZER] Completado análisis sobre {len(experiences)} experiencias. Patrones: {len(patterns)}.")
        return analysis

    # ── MÉTODOS DE CONVENIENCIA ──

    def analyze_last_n(self, n: int = 100) -> ExperienceAnalysis:
        """Analiza las últimas N experiencias registradas."""
        return self.analyze(AnalysisWindow(limit=n))

    def analyze_recent_hours(self, hours: float = 24.0) -> ExperienceAnalysis:
        """Analiza las experiencias registradas en las últimas X horas."""
        return self.analyze(AnalysisWindow(hours=hours))

    def analyze_intent(self, intent_name: str, limit: int = 100) -> ExperienceAnalysis:
        """Analiza exclusivamente las experiencias vinculadas a una intención específica."""
        return self.analyze(AnalysisWindow(intent=intent_name, limit=limit))

    def analyze_skill(self, skill_name: str, limit: int = 100) -> ExperienceAnalysis:
        """Analiza exclusivamente las experiencias asociadas a una skill específica."""
        return self.analyze(AnalysisWindow(skill=skill_name, limit=limit))
