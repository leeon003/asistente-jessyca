"""Comparador y Evaluador de Candidatas a Herramientas (Etapa 19.1).

Garantiza:
1. Comparación determinista entre herramientas descubiertas.
2. Identificación de herramientas no disponibles o no autorizadas y descarte transparente.
3. Propuesta de ALTERNATIVAS SEGURAS (Safe Alternatives) cuando la herramienta primaria no puede ejecutarse.
4. Ponderación por evidencia de memoria (preferencias y fallos históricos).
"""

from __future__ import annotations

from core.autonomy.autonomy_level import TaskActionRisk
from core.logger import get_logger
from core.tool_planner.models import MemoryEvidence, ToolCandidate

logger = get_logger("jessyca.planner.comparator")


class ToolCandidateComparator:
    """Compara, pondera y ordena candidatas a herramientas basándose en capacidades y evidencia de memoria."""

    @classmethod
    def evaluate_and_rank(
        cls,
        candidates: list[ToolCandidate],
        evidence_list: list[MemoryEvidence],
    ) -> tuple[ToolCandidate | None, list[ToolCandidate]]:
        """Evalúa las herramientas candidatas, aplica evidencia de memoria y selecciona la mejor opción autorizada o alternativa segura.

        Returns:
            tuple[ToolCandidate | None, list[ToolCandidate]]: (Mejor candidata seleccionada, Lista de candidatas descartadas)
        """
        if not candidates:
            return None, []

        authorized_candidates: list[ToolCandidate] = []
        discarded_candidates: list[ToolCandidate] = []

        # 1. Separar herramientas no disponibles o no autorizadas
        for cand in candidates:
            if not cand.is_available:
                discarded_candidates.append(cand)
                continue
            if not cand.is_authorized:
                discarded_candidates.append(cand)
                continue

            current_score = cand.score
            adjusted_reasons = [cand.match_reason]

            # 2. Aplicar evidencia de memoria
            for ev in evidence_list:
                ev_text = ev.fact_or_preference.lower()
                t_name = cand.tool_name.lower()
                t_full = f"{cand.tool_name}.{cand.operation}".lower()

                if t_name in ev_text or t_full in ev_text:
                    avoid_patterns = [
                        f"en lugar de {t_name}",
                        f"en vez de {t_name}",
                        f"evitar {t_name}",
                        f"no usar {t_name}",
                        f"fallo {t_name}",
                        f"deprecated {t_name}",
                    ]
                    prefer_patterns = [
                        f"preferir {t_name}",
                        f"prefer {t_name}",
                        f"usar {t_name}",
                        f"frecuente {t_name}",
                        f"default {t_name}",
                        f"mejor {t_name}",
                    ]

                    is_avoided = any(p in ev_text for p in avoid_patterns)
                    is_preferred = any(p in ev_text for p in prefer_patterns)

                    if is_avoided:
                        penalty = 6.0 * ev.confidence
                        current_score -= penalty
                        adjusted_reasons.append(f"Evidencia de sustitución/descarte (-{penalty:.1f}): '{ev.fact_or_preference}'")
                    elif is_preferred:
                        boost = 6.0 * ev.confidence
                        current_score += boost
                        adjusted_reasons.append(f"Evidencia de preferencia (+{boost:.1f}): '{ev.fact_or_preference}'")
                    elif "prefer" in ev_text or "usar" in ev_text:
                        boost = 2.0 * ev.confidence
                        current_score += boost
                        adjusted_reasons.append(f"Evidencia contextual (+{boost:.1f}): '{ev.fact_or_preference}'")

            updated_cand = ToolCandidate(
                tool_name=cand.tool_name,
                operation=cand.operation,
                capability=cand.capability,
                score=current_score,
                match_reason="; ".join(adjusted_reasons),
                minimum_autonomy_level=cand.minimum_autonomy_level,
                declared_risk=cand.declared_risk,
                reversibility=cand.reversibility,
                requires_confirmation=cand.requires_confirmation,
                audit_requirement=cand.audit_requirement,
                limitations=cand.limitations,
                is_available=cand.is_available,
                is_authorized=cand.is_authorized,
                is_safe_alternative=cand.is_safe_alternative,
                discard_reason=cand.discard_reason,
            )
            authorized_candidates.append(updated_cand)

        # 3. Si no hay herramientas autorizadas directas, pero hubo candidatas descartadas por riesgo/permiso:
        # Buscar una alternativa segura entre las candidatas que sean READ_ONLY o de menor riesgo
        if not authorized_candidates and discarded_candidates:
            # Buscar alternativas seguras entre los candidatos disponibles pero de menor riesgo
            safe_alts = [
                c for c in candidates
                if c.is_available and c.declared_risk in (TaskActionRisk.READ_ONLY, TaskActionRisk.LOW_RISK)
            ]
            if safe_alts:
                safe_alts.sort(key=lambda c: c.score, reverse=True)
                best_safe = safe_alts[0]
                primary_discarded = discarded_candidates[0]
                selected_alt = ToolCandidate(
                    tool_name=best_safe.tool_name,
                    operation=best_safe.operation,
                    capability=best_safe.capability,
                    score=best_safe.score,
                    match_reason=f"Alternativa segura propuesta para sustituir '{primary_discarded.capability}' ({primary_discarded.discard_reason})",
                    minimum_autonomy_level=best_safe.minimum_autonomy_level,
                    declared_risk=best_safe.declared_risk,
                    reversibility=best_safe.reversibility,
                    requires_confirmation=best_safe.requires_confirmation,
                    audit_requirement=best_safe.audit_requirement,
                    limitations=best_safe.limitations,
                    is_available=True,
                    is_authorized=True,
                    is_safe_alternative=True,
                )
                return selected_alt, discarded_candidates

            return None, discarded_candidates

        if not authorized_candidates:
            return None, discarded_candidates

        # 4. Ordenar candidatos autorizados por score descendente
        authorized_candidates.sort(key=lambda c: c.score, reverse=True)
        selected_best = authorized_candidates[0]

        # Las demás pasan como alternativas descartadas
        for alt in authorized_candidates[1:]:
            discarded_cand = ToolCandidate(
                tool_name=alt.tool_name,
                operation=alt.operation,
                capability=alt.capability,
                score=alt.score,
                match_reason=alt.match_reason,
                minimum_autonomy_level=alt.minimum_autonomy_level,
                declared_risk=alt.declared_risk,
                reversibility=alt.reversibility,
                requires_confirmation=alt.requires_confirmation,
                audit_requirement=alt.audit_requirement,
                limitations=alt.limitations,
                is_available=True,
                is_authorized=True,
                is_safe_alternative=False,
                discard_reason=f"Alternativa descartada por score inferior ({alt.score:.2f} vs {selected_best.score:.2f} de '{selected_best.capability}')",
            )
            discarded_candidates.append(discarded_cand)

        return selected_best, discarded_candidates
