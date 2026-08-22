"""Motor de Generación y Gestión de Propuestas de Aprendizaje (proposal_engine.py - Fase 59).

Transforma los patrones y anomalías detectados por el Experience Analyzer en
propuestas de mejora estructuradas, gobernadas por ciclo de vida formal y
estrictamente protegidas contra modificaciones no autorizadas o componentes de seguridad.
"""

from __future__ import annotations

import threading

from core.experience.analysis_models import (
    ExperienceAnalysis,
    Pattern,
    PatternType,
)
from core.learning.proposal_models import (
    LearningProposal,
    ProposalCategory,
    ProposalRiskLevel,
    ProposalStatus,
)
from core.learning.proposal_store import IProposalStore, SQLiteProposalStore
from core.learning.proposal_validator import ProposalValidator
from core.logger import get_logger

logger = get_logger("jessyca.learning.engine")


class LearningProposalEngine:
    """Motor central para la generación, validación y ciclo de vida de propuestas de aprendizaje."""

    def __init__(self, store: IProposalStore | None = None) -> None:
        self._store = store or SQLiteProposalStore()
        self._lock = threading.RLock()

    @property
    def store(self) -> IProposalStore:
        return self._store

    def generate_proposal_from_pattern(
        self,
        pattern: Pattern,
        analysis_id: str | None = None,
    ) -> LearningProposal | None:
        """Convierte un patrón detectado en una propuesta de aprendizaje estructurada."""
        analysis_ids = [analysis_id] if analysis_id else []
        pattern_ids = [pattern.pattern_id]

        # 1. Patrón STT / Variantes de reconocimiento
        if pattern.type in (PatternType.STT_RECOGNITION, PatternType.LOW_STT_CONFIDENCE):
            canonical = getattr(pattern, "canonical_target", None) or (pattern.affected_operations[0] if pattern.affected_operations else "desconocido")
            variants = getattr(pattern, "variants", [])
            var_str = f" con variantes {variants}" if variants else ""

            return LearningProposal(
                source_analysis_ids=analysis_ids,
                source_pattern_ids=pattern_ids,
                category=ProposalCategory.STT,
                problem=f"El reconocedor STT presenta ambigüedad en el objetivo '{canonical}'{var_str}.",
                evidence=pattern.evidence,
                occurrences=pattern.frequency,
                current_behavior=f"Se registraron {pattern.frequency} ocurrencias con discrepancias fonéticas/léxicas.",
                suggested_improvement=f"Incorporar pistas de vocabulario contextual en el reconocedor STT para '{canonical}'.",
                expected_benefit="Incrementar la exactitud de transcripción y eliminar desambiguaciones reiteradas.",
                risk=ProposalRiskLevel.LOW,
                confidence=pattern.confidence,
                affected_components=["voice.stt_contextual_vocabulary"],
                required_tests=[
                    "test_existing_voice_commands",
                    "test_unrelated_applications",
                    "test_ambiguous_application_names",
                ],
                potential_breakage=["Riesgo mínimo de sobreajuste fonético en palabras similares."],
                status=ProposalStatus.DRAFT,
            )

        # 2. Patrón de Fallos Repetidos o de Tools
        if pattern.type in (PatternType.REPEATED_FAILURE, PatternType.TOOL_SKILL_FAILURE, PatternType.VERIFICATION_FAILURE):
            target_op = pattern.affected_operations[0] if pattern.affected_operations else "general_operation"
            cat = ProposalCategory.TOOL if "tool" in target_op or "skill" in target_op else ProposalCategory.UX

            return LearningProposal(
                source_analysis_ids=analysis_ids,
                source_pattern_ids=pattern_ids,
                category=cat,
                problem=f"Fallo recurrente detectado en la operación o herramienta '{target_op}'.",
                evidence=pattern.evidence,
                occurrences=pattern.frequency,
                current_behavior=pattern.description,
                suggested_improvement=f"Implementar validación de precondiciones y reintento determinista para '{target_op}'.",
                expected_benefit="Reducir la tasa de error y aumentar la fiabilidad de ejecución.",
                risk=ProposalRiskLevel.MEDIUM,
                confidence=pattern.confidence,
                affected_components=[f"skills.{target_op}"],
                required_tests=[
                    "test_fault_recovery",
                    "test_execution_preconditions",
                ],
                potential_breakage=["Tiempo de respuesta ligeramente mayor ante validaciones previas."],
                status=ProposalStatus.DRAFT,
            )

        # 3. Patrón de Degradación de Latencia
        if pattern.type == PatternType.LATENCY_DEGRADATION:
            target_op = pattern.affected_operations[0] if pattern.affected_operations else "general_pipeline"
            avg_lat = getattr(pattern, "avg_latency_ms", 0.0)

            return LearningProposal(
                source_analysis_ids=analysis_ids,
                source_pattern_ids=pattern_ids,
                category=ProposalCategory.PERFORMANCE,
                problem=f"Degradación de latencia observada en '{target_op}' (Promedio: {avg_lat}ms).",
                evidence=pattern.evidence,
                occurrences=pattern.frequency,
                current_behavior=pattern.description,
                suggested_improvement=f"Optimizar pipeline de enrutamiento y cachear resolución de entidades para '{target_op}'.",
                expected_benefit="Reducción de latencia en turnos interactivos.",
                risk=ProposalRiskLevel.LOW,
                confidence=pattern.confidence,
                affected_components=["core.pipeline_optimizer"],
                required_tests=[
                    "test_latency_benchmark",
                    "test_cache_invalidation",
                ],
                potential_breakage=["Consumo menor de memoria adicional por cache."],
                status=ProposalStatus.DRAFT,
            )

        # 4. Patrón de Corrección de Usuario
        if pattern.type == PatternType.USER_CORRECTION:
            corr_targets = getattr(pattern, "corrected_values", [])
            target_str = ", ".join(corr_targets[:3]) if corr_targets else "parámetros de diálogo"

            return LearningProposal(
                source_analysis_ids=analysis_ids,
                source_pattern_ids=pattern_ids,
                category=ProposalCategory.UX,
                problem=f"Correcciones recurrentes del usuario sobre: {target_str}.",
                evidence=pattern.evidence,
                occurrences=pattern.frequency,
                current_behavior=pattern.description,
                suggested_improvement="Ajustar la resolución contextual de entidades y orden de prioridad en el extractor de slots.",
                expected_benefit="Mayor asertividad conversacional y menor fricción con el usuario.",
                risk=ProposalRiskLevel.LOW,
                confidence=pattern.confidence,
                affected_components=["core.conversation_context"],
                required_tests=[
                    "test_slot_resolution_priority",
                    "test_context_continuity",
                ],
                potential_breakage=["Posible cambio de prioridad en desambiguación contextual."],
                status=ProposalStatus.DRAFT,
            )

        # 5. Patrón de Intención Ambigua / Aclaraciones
        if pattern.type in (PatternType.LOW_INTENT_CONFIDENCE, PatternType.REPEATED_CLARIFICATION):
            intent_name = getattr(pattern, "intent_name", None) or (pattern.affected_operations[0] if pattern.affected_operations else "intención general")

            return LearningProposal(
                source_analysis_ids=analysis_ids,
                source_pattern_ids=pattern_ids,
                category=ProposalCategory.INTENT,
                problem=f"Ambigüedad o baja confianza reiterada en la intención '{intent_name}'.",
                evidence=pattern.evidence,
                occurrences=pattern.frequency,
                current_behavior=pattern.description,
                suggested_improvement=f"Refinar plantillas de coincidencia y ejemplos de slots para '{intent_name}'.",
                expected_benefit="Disminuir preguntas redundantes de aclaración.",
                risk=ProposalRiskLevel.LOW,
                confidence=pattern.confidence,
                affected_components=["core.intent_resolver"],
                required_tests=[
                    "test_intent_classification",
                    "test_ambiguity_clarification",
                ],
                potential_breakage=["Ligero ajuste en umbrales de confianza semántica."],
                status=ProposalStatus.DRAFT,
            )

        return None

    def generate_proposals_from_analysis(
        self,
        analysis: ExperienceAnalysis,
    ) -> list[LearningProposal]:
        """Genera un conjunto de propuestas validadas a partir de un informe de análisis de experiencias."""
        proposals: list[LearningProposal] = []
        seen_problems: set[str] = set()

        for pattern in analysis.patterns:
            # Omitir patrones puramente informativos de éxito si no ameritan propuesta
            if pattern.type in (PatternType.REPEATED_SUCCESS, PatternType.GENERAL):
                continue

            prop = self.generate_proposal_from_pattern(pattern, analysis_id=analysis.analysis_id)
            if prop and prop.problem not in seen_problems:
                seen_problems.add(prop.problem)
                proposals.append(prop)

        logger.info(f"[PROPOSAL ENGINE] Generadas {len(proposals)} propuestas a partir del análisis {analysis.analysis_id}.")
        return proposals

    def submit_proposal(self, proposal: LearningProposal) -> LearningProposal:
        """Valida formalmente y persiste una propuesta en el almacén."""
        with self._lock:
            # Validar integridad y seguridad
            is_valid, errors = ProposalValidator.validate_proposal(proposal)
            if not is_valid:
                raise ValueError(f"Propuesta rechazada por validación: {'; '.join(errors)}")

            # Avanzar a estado VALIDATED
            validated_prop = ProposalValidator.transition_proposal(proposal, ProposalStatus.VALIDATED)
            self._store.save(validated_prop)
            logger.info(f"[PROPOSAL SUBMITTED] Propuesta {validated_prop.proposal_id} validada y almacenada.")
            return validated_prop

    def advance_proposal(
        self,
        proposal_id: str,
        target_status: ProposalStatus,
        reason: str | None = None,
    ) -> LearningProposal:
        """Avanza el estado de una propuesta registrada siguiendo las reglas de la máquina de estados."""
        with self._lock:
            current = self._store.get(proposal_id)
            if not current:
                raise ValueError(f"No se encontró la propuesta con ID '{proposal_id}'.")

            updated = ProposalValidator.transition_proposal(current, target_status, reason=reason)
            self._store.save(updated)
            logger.info(f"[PROPOSAL TRANSITION] Propuesta {proposal_id} avanzada de {current.status.value} a {target_status.value}.")
            return updated

    # ── MÉTODOS DE CONSULTA FILTRADA ──

    def get_pending_proposals(self) -> list[LearningProposal]:
        """Obtiene propuestas que se encuentran en trámite o pendientes de evaluación."""
        results: list[LearningProposal] = []
        for st in (ProposalStatus.DRAFT, ProposalStatus.VALIDATED, ProposalStatus.SIMULATION_PENDING, ProposalStatus.READY_FOR_EVALUATION):
            results.extend(self._store.query(status=st))
        return results

    def get_approved_proposals(self) -> list[LearningProposal]:
        """Obtiene propuestas aprobadas formalmente."""
        return self._store.query(status=ProposalStatus.APPROVED)

    def get_rejected_proposals(self) -> list[LearningProposal]:
        """Obtiene propuestas que fueron rechazadas con su motivo."""
        return self._store.query(status=ProposalStatus.REJECTED)

    def get_deployed_proposals(self) -> list[LearningProposal]:
        """Obtiene propuestas que alcanzaron el estado de despliegue."""
        return self._store.query(status=ProposalStatus.DEPLOYED)

    def get_rolled_back_proposals(self) -> list[LearningProposal]:
        """Obtiene propuestas que sufrieron reversión técnica."""
        return self._store.query(status=ProposalStatus.ROLLED_BACK)
