"""Generador y Modelo del Reporte Diario de Aprendizaje (daily_report.py - Fase 63).

Estructura y exporta el informe formal del ciclo diario:
- Métricas cuantitativas de experiencias procesadas.
- Patrones y anomalías descubiertos.
- Propuestas formuladas, aprobadas y rechazadas.
- Casos de regresión añadidos y ejecutados.
- Despliegues y rollbacks efectuados.
- Formateo amigable en Markdown y exportación JSON persistente.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.logger import get_logger

logger = get_logger("jessyca.learning.daily_report")


class DailyLearningReport(BaseModel):
    """Informe consolidado de resultados del ciclo de aprendizaje diario."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    date: str
    run_id: str
    total_experiences: int = 0
    successful_experiences: int = 0
    failed_experiences: int = 0
    verification_failures: int = 0
    clarifications: int = 0
    corrections: int = 0
    patterns_detected: list[str] = Field(default_factory=list)
    proposals_generated: int = 0
    proposals_approved: int = 0
    proposals_rejected: int = 0
    regression_tests_added: int = 0
    regression_tests_failed: int = 0
    improvements_deployed: int = 0
    rollbacks: int = 0
    performance_delta: dict[str, float] = Field(default_factory=dict)
    security_events: int = 0
    duration_ms: float = 0.0
    status: str = "COMPLETED"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serializa el reporte en un diccionario."""
        return self.model_dump(mode="json")

    def to_markdown(self) -> str:
        """Genera una representación formateada en Markdown del reporte."""
        patterns_str = "\n".join(f"- {p}" for p in self.patterns_detected) if self.patterns_detected else "- Ninguno detectado."

        return f"""# JESSYCA LEARNING REPORT

**Fecha:** {self.date}
**Run ID:** `{self.run_id}`
**Estado:** `{self.status}` ({self.duration_ms:.1f}ms)

---

## 1. Métricas de Interacción Diaria
- **Total Experiencias:** {self.total_experiences}
- **Exitosas:** {self.successful_experiences}
- **Fallidas:** {self.failed_experiences}
- **Fallos de Verificación OS:** {self.verification_failures}
- **Aclaraciones Requeridas:** {self.clarifications}
- **Correcciones del Usuario:** {self.corrections}

## 2. Patrones Detectados
{patterns_str}

## 3. Propuestas y Mejoras
- **Propuestas Generadas:** {self.proposals_generated}
- **Propuestas Aprobadas:** {self.proposals_approved}
- **Propuestas Rechazadas:** {self.proposals_rejected}
- **Mejoras Desplegadas:** {self.improvements_deployed}
- **Rollbacks Efectuados:** {self.rollbacks}

## 4. Inmunidad y Regresiones
- **Tests de Regresión Añadidos:** +{self.regression_tests_added}
- **Tests de Regresión Fallidos:** {self.regression_tests_failed}
- **Eventos de Seguridad:** {self.security_events}

---
*Generado automáticamente por JESSYCA Experience & Learning Engine@3.0*
"""

    def save(self, storage_dir: str | Path | None = None) -> Path:
        """Persiste el informe en formato JSON y Markdown en el disco."""
        from config.settings import AppSettings
        settings = AppSettings()

        raw_dir = storage_dir or getattr(settings, "DAILY_REPORT_STORAGE_PATH", "data/learning_reports/")
        base_dir = Path(str(raw_dir))
        base_dir.mkdir(parents=True, exist_ok=True)

        json_file = base_dir / f"report_{self.date}_{self.run_id[:8]}.json"
        md_file = base_dir / f"report_{self.date}_{self.run_id[:8]}.md"

        json_file.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        md_file.write_text(self.to_markdown(), encoding="utf-8")

        logger.info(f"[DAILY REPORT] Guardado reporte de aprendizaje en {json_file}.")
        return json_file
