"""Motor Determinista de Detección de Patrones de Experiencia (patterns.py - Fase 58).

Identifica patrones recurrentes en el historial de experiencias:
1. Fallos repetidos (Repeated Failure)
2. Éxitos consistentes (Repeated Success)
3. Baja confianza STT (Low STT Confidence)
4. Variantes léxicas/fonéticas STT (STT Recognition Variants)
5. Baja confianza de intención / ambigüedad (Low Intent Confidence)
6. Fallos de verificación post-ejecución en OS (Verification Failure)
7. Aclaraciones reiteradas (Repeated Clarification)
8. Correcciones de usuario (User Correction Pattern)
9. Degradación de latencia (Latency Degradation)
10. Acciones repetidas (Repeated Action Pattern)
11. Fallos de herramientas y skills (Tool / Skill Failure Pattern)
"""

from __future__ import annotations

import difflib
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from core.experience.analysis_models import (
    CorrectionPattern,
    FailurePattern,
    IntentPattern,
    LatencyPattern,
    Pattern,
    PatternSeverity,
    PatternType,
    STTPattern,
    SuccessPattern,
)
from core.experience.metrics import _calculate_percentile
from core.experience.models import (
    ExecutionStatus,
    Experience,
    ExperienceCategory,
    VerificationStatus,
)


def _string_similarity(a: str, b: str) -> float:
    """Calcula la similitud de secuencia entre dos cadenas normalizadas."""
    return difflib.SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def detect_repeated_failures(
    experiences: Sequence[Experience],
    min_occurrences: int = 2,
) -> list[FailurePattern]:
    """Detecta operaciones o intenciones que fallan repetidamente."""
    ops: dict[str, list[Experience]] = defaultdict(list)
    for exp in experiences:
        op = exp.intent.name if exp.intent else (exp.target.value if exp.target else "unknown")
        ops[op].append(exp)

    patterns: list[FailurePattern] = []
    for op, exps in ops.items():
        fails = [
            e for e in exps
            if (e.execution and e.execution.status in (ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT))
            or e.category in (ExperienceCategory.ACTION_FAILED, ExperienceCategory.TIMEOUT)
        ]
        if len(fails) >= min_occurrences:
            failure_rate = round(len(fails) / len(exps), 4)
            err_types = list({e.error.error_type for e in fails if e.error and e.error.error_type})
            severity = PatternSeverity.CRITICAL if failure_rate >= 0.75 else (
                PatternSeverity.HIGH if failure_rate >= 0.50 else PatternSeverity.MEDIUM
            )

            evidence = [
                {
                    "experience_id": e.experience_id,
                    "timestamp": e.timestamp.isoformat(),
                    "input": e.input.raw_text,
                    "error": e.error.message if e.error else None,
                }
                for e in fails
            ]

            patterns.append(
                FailurePattern(
                    type=PatternType.REPEATED_FAILURE,
                    description=f"Fallo repetido en la operación '{op}' con {len(fails)} fallos de {len(exps)} intentos ({failure_rate * 100:.1f}%).",
                    frequency=len(fails),
                    confidence=round(min(1.0, 0.6 + (len(fails) * 0.1)), 2),
                    evidence=evidence,
                    first_seen=min(e.timestamp for e in fails),
                    last_seen=max(e.timestamp for e in fails),
                    affected_operations=[op],
                    severity=severity,
                    failure_rate=failure_rate,
                    error_types=err_types,
                )
            )

    return patterns


def detect_repeated_successes(
    experiences: Sequence[Experience],
    min_occurrences: int = 3,
) -> list[SuccessPattern]:
    """Detecta operaciones que se ejecutan con consistencia y éxito constante."""
    ops: dict[str, list[Experience]] = defaultdict(list)
    for exp in experiences:
        op = exp.intent.name if exp.intent else (exp.target.value if exp.target else "unknown")
        ops[op].append(exp)

    patterns: list[SuccessPattern] = []
    for op, exps in ops.items():
        successes = [
            e for e in exps
            if (e.execution and e.execution.status == ExecutionStatus.SUCCESS)
            or e.category == ExperienceCategory.ACTION_SUCCESS
        ]
        if len(successes) >= min_occurrences:
            success_rate = round(len(successes) / len(exps), 4)
            if success_rate >= 0.80:
                evidence = [
                    {
                        "experience_id": e.experience_id,
                        "timestamp": e.timestamp.isoformat(),
                        "input": e.input.raw_text,
                    }
                    for e in successes[:5]
                ]

                patterns.append(
                    SuccessPattern(
                        type=PatternType.REPEATED_SUCCESS,
                        description=f"Éxito consistente en la operación '{op}' con {len(successes)} ejecuciones exitosas ({success_rate * 100:.1f}%).",
                        frequency=len(successes),
                        confidence=round(success_rate, 2),
                        evidence=evidence,
                        first_seen=min(e.timestamp for e in successes),
                        last_seen=max(e.timestamp for e in successes),
                        affected_operations=[op],
                        severity=PatternSeverity.INFO,
                        success_rate=success_rate,
                    )
                )

    return patterns


def detect_low_stt_confidence(
    experiences: Sequence[Experience],
    threshold: float = 0.70,
) -> list[STTPattern]:
    """Detecta episodios recurrentes de baja confianza en reconocimiento de voz."""
    low_stt = [
        e for e in experiences
        if (e.stt and (e.stt.confidence < threshold or e.stt.is_low_confidence))
        or e.category == ExperienceCategory.LOW_STT_CONFIDENCE
    ]

    if not low_stt:
        return []

    confs = [e.stt.confidence for e in low_stt if e.stt and e.stt.confidence is not None]
    avg_conf = round(sum(confs) / len(confs), 4) if confs else 0.50

    evidence = [
        {
            "experience_id": e.experience_id,
            "timestamp": e.timestamp.isoformat(),
            "raw_text": e.input.raw_text,
            "confidence": e.stt.confidence if e.stt else None,
        }
        for e in low_stt
    ]

    return [
        STTPattern(
            type=PatternType.LOW_STT_CONFIDENCE,
            description=f"Se detectaron {len(low_stt)} transcripciones de voz con baja confianza (promedio: {avg_conf:.2f}).",
            frequency=len(low_stt),
            confidence=round(1.0 - avg_conf, 2),
            evidence=evidence,
            first_seen=min(e.timestamp for e in low_stt),
            last_seen=max(e.timestamp for e in low_stt),
            affected_operations=list({e.intent.name for e in low_stt if e.intent}),
            severity=PatternSeverity.MEDIUM if len(low_stt) >= 3 else PatternSeverity.LOW,
            avg_stt_confidence=avg_conf,
        )
    ]


def detect_stt_variants(
    experiences: Sequence[Experience],
    similarity_threshold: float = 0.75,
) -> list[STTPattern]:
    """Detecta variaciones fonéticas/léxicas sobre un mismo target (ej. 'bloc de notas', 'blog de notas', 'blot de notas')."""
    # Extraer términos candidatos de targets e inputs
    candidates: list[tuple[str, Experience]] = []
    for exp in experiences:
        if exp.target and exp.target.value:
            candidates.append((exp.target.value.strip().lower(), exp))
        elif exp.input and exp.input.raw_text:
            text = exp.input.raw_text.strip().lower()
            # Si contiene frases clave como 'abre ...'
            for prefix in ("abre el ", "abre la ", "abre ", "cerrar ", "busca "):
                if text.startswith(prefix):
                    cand = text[len(prefix):].strip()
                    if cand:
                        candidates.append((cand, exp))
                    break

    if not candidates:
        return []

    # Agrupar cadenas similares
    clusters: list[list[tuple[str, Experience]]] = []
    for text, exp in candidates:
        matched = False
        for cluster in clusters:
            rep_text, _ = cluster[0]
            if _string_similarity(rep_text, text) >= similarity_threshold:
                cluster.append((text, exp))
                matched = True
                break
        if not matched:
            clusters.append([(text, exp)])

    patterns: list[STTPattern] = []
    for cluster in clusters:
        distinct_texts = list({t for t, _ in cluster})
        if len(distinct_texts) > 1 and len(cluster) >= 2:
            # Determinar el target canónico (el más frecuente)
            counts: dict[str, int] = defaultdict(int)
            for t, _ in cluster:
                counts[t] += 1
            canonical = max(counts.keys(), key=lambda k: counts[k])
            variants = [t for t in distinct_texts if t != canonical]

            evidence = [
                {
                    "experience_id": exp.experience_id,
                    "term": text,
                    "timestamp": exp.timestamp.isoformat(),
                }
                for text, exp in cluster
            ]

            patterns.append(
                STTPattern(
                    type=PatternType.STT_RECOGNITION,
                    description=f"Variaciones léxicas/fonéticas detectadas para '{canonical}': {', '.join(variants)} ({len(cluster)} ocurrencias).",
                    frequency=len(cluster),
                    confidence=round(min(1.0, 0.70 + (len(cluster) * 0.05)), 2),
                    evidence=evidence,
                    first_seen=min(exp.timestamp for _, exp in cluster),
                    last_seen=max(exp.timestamp for _, exp in cluster),
                    affected_operations=[canonical],
                    severity=PatternSeverity.LOW if len(cluster) < 5 else PatternSeverity.MEDIUM,
                    canonical_target=canonical,
                    variants=variants,
                )
            )

    return patterns


def detect_low_intent_confidence(
    experiences: Sequence[Experience],
    threshold: float = 0.70,
) -> list[IntentPattern]:
    """Detecta intenciones con baja confianza o clasificadas como ambiguas."""
    ambig_exps = [
        e for e in experiences
        if (e.intent and (e.intent.confidence < threshold or e.intent.is_ambiguous))
        or e.category == ExperienceCategory.AMBIGUOUS_INTENT
    ]

    if not ambig_exps:
        return []

    ops: dict[str, list[Experience]] = defaultdict(list)
    for e in ambig_exps:
        intent_name = e.intent.name if e.intent else "unknown"
        ops[intent_name].append(e)

    patterns: list[IntentPattern] = []
    for intent_name, exps in ops.items():
        evidence = [
            {
                "experience_id": e.experience_id,
                "input": e.input.raw_text,
                "confidence": e.intent.confidence if e.intent else None,
            }
            for e in exps
        ]
        patterns.append(
            IntentPattern(
                type=PatternType.LOW_INTENT_CONFIDENCE,
                description=f"Ambigüedad o baja confianza en intención '{intent_name}' ({len(exps)} veces).",
                frequency=len(exps),
                confidence=round(min(1.0, 0.5 + (len(exps) * 0.1)), 2),
                evidence=evidence,
                first_seen=min(e.timestamp for e in exps),
                last_seen=max(e.timestamp for e in exps),
                affected_operations=[intent_name],
                severity=PatternSeverity.MEDIUM if len(exps) >= 3 else PatternSeverity.LOW,
                intent_name=intent_name,
                ambiguity_rate=1.0,
            )
        )

    return patterns


def detect_verification_failures(
    experiences: Sequence[Experience],
) -> list[FailurePattern]:
    """Detecta fallos en la verificación post-ejecución del sistema operativo."""
    verif_fails = [
        e for e in experiences
        if (e.verification and (e.verification.status == VerificationStatus.FAILED or not e.verification.is_verified))
        or e.category == ExperienceCategory.VERIFICATION_FAILED
    ]

    if not verif_fails:
        return []

    targets: dict[str, list[Experience]] = defaultdict(list)
    for e in verif_fails:
        target_name = e.target.value if e.target and e.target.value else (e.intent.name if e.intent else "general")
        targets[target_name].append(e)

    patterns: list[FailurePattern] = []
    for target_name, exps in targets.items():
        evidence = [
            {
                "experience_id": e.experience_id,
                "timestamp": e.timestamp.isoformat(),
                "action": e.execution.action if e.execution else None,
                "verification_type": e.verification.verification_type if e.verification else None,
            }
            for e in exps
        ]
        patterns.append(
            FailurePattern(
                type=PatternType.VERIFICATION_FAILURE,
                description=f"Fallo de verificación en el sistema operativo para el objetivo '{target_name}' ({len(exps)} incidentes).",
                frequency=len(exps),
                confidence=0.95,
                evidence=evidence,
                first_seen=min(e.timestamp for e in exps),
                last_seen=max(e.timestamp for e in exps),
                affected_operations=[target_name],
                severity=PatternSeverity.HIGH,
                failure_rate=1.0,
                error_types=["VerificationMismatch"],
            )
        )

    return patterns


def detect_repeated_clarifications(
    experiences: Sequence[Experience],
    min_occurrences: int = 2,
) -> list[Pattern]:
    """Detecta solicitudes repetidas de aclaración por falta de parámetros."""
    clarifs = [
        e for e in experiences
        if e.category == ExperienceCategory.CLARIFICATION_REQUESTED
    ]

    if len(clarifs) < min_occurrences:
        return []

    evidence = [
        {
            "experience_id": e.experience_id,
            "input": e.input.raw_text,
            "response": e.response.text if e.response else None,
        }
        for e in clarifs
    ]

    return [
        Pattern(
            type=PatternType.REPEATED_CLARIFICATION,
            description=f"Solicitud recurrente de aclaración al usuario ({len(clarifs)} veces registradas).",
            frequency=len(clarifs),
            confidence=0.85,
            evidence=evidence,
            first_seen=min(e.timestamp for e in clarifs),
            last_seen=max(e.timestamp for e in clarifs),
            affected_operations=list({e.intent.name for e in clarifs if e.intent}),
            severity=PatternSeverity.LOW,
        )
    ]


def detect_user_corrections(
    experiences: Sequence[Experience],
) -> list[CorrectionPattern]:
    """Detecta patrones en las correcciones realizadas por el usuario."""
    corrections = [
        e for e in experiences
        if e.category == ExperienceCategory.USER_CORRECTION
        or (e.correction and e.correction.is_correction)
    ]

    if not corrections:
        return []

    orig_vals = [e.correction.original_target for e in corrections if e.correction and e.correction.original_target]
    corr_vals = [e.correction.corrected_target for e in corrections if e.correction and e.correction.corrected_target]

    evidence = [
        {
            "experience_id": e.experience_id,
            "input": e.input.raw_text,
            "corrected_target": e.correction.corrected_target if e.correction else None,
        }
        for e in corrections
    ]

    return [
        CorrectionPattern(
            type=PatternType.USER_CORRECTION,
            description=f"Correcciones explícitas del usuario detectadas ({len(corrections)} eventos).",
            frequency=len(corrections),
            confidence=0.90,
            evidence=evidence,
            first_seen=min(e.timestamp for e in corrections),
            last_seen=max(e.timestamp for e in corrections),
            affected_operations=list({e.intent.name for e in corrections if e.intent}),
            severity=PatternSeverity.MEDIUM,
            original_values=orig_vals,
            corrected_values=corr_vals,
        )
    ]


def detect_latency_degradations(
    experiences: Sequence[Experience],
    latency_threshold_ms: float = 500.0,
) -> list[LatencyPattern]:
    """Detecta operaciones con degradación de latencia o tiempos excesivos."""
    ops: dict[str, list[float]] = defaultdict(list)
    exp_map: dict[str, list[Experience]] = defaultdict(list)

    for exp in experiences:
        if exp.latency and exp.latency.total_ms > 0:
            op = exp.intent.name if exp.intent else "general"
            ops[op].append(exp.latency.total_ms)
            exp_map[op].append(exp)

    patterns: list[LatencyPattern] = []
    for op, lat_list in ops.items():
        sorted_lats = sorted(lat_list)
        avg_lat = round(sum(sorted_lats) / len(sorted_lats), 2)
        p50 = round(_calculate_percentile(sorted_lats, 0.50), 2)
        p95 = round(_calculate_percentile(sorted_lats, 0.95), 2)

        if avg_lat >= latency_threshold_ms or p95 >= latency_threshold_ms * 1.5:
            exps = exp_map[op]
            evidence = [
                {
                    "experience_id": e.experience_id,
                    "total_ms": e.latency.total_ms,
                    "execution_ms": e.latency.execution_ms,
                }
                for e in exps[:5]
            ]

            patterns.append(
                LatencyPattern(
                    type=PatternType.LATENCY_DEGRADATION,
                    description=f"Latencia elevada en la operación '{op}': promedio {avg_lat}ms, p95 {p95}ms.",
                    frequency=len(lat_list),
                    confidence=0.85,
                    evidence=evidence,
                    first_seen=min(e.timestamp for e in exps),
                    last_seen=max(e.timestamp for e in exps),
                    affected_operations=[op],
                    severity=PatternSeverity.HIGH if avg_lat >= 1000.0 else PatternSeverity.MEDIUM,
                    avg_latency_ms=avg_lat,
                    p50_latency_ms=p50,
                    p95_latency_ms=p95,
                )
            )

    return patterns


def detect_repeated_actions(
    experiences: Sequence[Experience],
    min_occurrences: int = 3,
) -> list[Pattern]:
    """Detecta secuencias o comandos ejecutados con alta frecuencia."""
    actions: dict[str, list[Experience]] = defaultdict(list)
    for exp in experiences:
        key = exp.input.raw_text.strip().lower()
        if key:
            actions[key].append(exp)

    patterns: list[Pattern] = []
    for action_text, exps in actions.items():
        if len(exps) >= min_occurrences:
            evidence = [
                {
                    "experience_id": e.experience_id,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in exps[:5]
            ]
            patterns.append(
                Pattern(
                    type=PatternType.REPEATED_ACTION,
                    description=f"Acción frecuente repetida '{action_text}' ({len(exps)} ejecuciones).",
                    frequency=len(exps),
                    confidence=0.95,
                    evidence=evidence,
                    first_seen=min(e.timestamp for e in exps),
                    last_seen=max(e.timestamp for e in exps),
                    affected_operations=[action_text],
                    severity=PatternSeverity.INFO,
                )
            )

    return patterns


def detect_tool_skill_failures(
    experiences: Sequence[Experience],
    min_failures: int = 2,
) -> list[FailurePattern]:
    """Detecta herramientas técnicas o skills específicas con alta tasa de error."""
    tools: dict[str, list[Experience]] = defaultdict(list)
    for exp in experiences:
        tool = exp.execution.tool_name if exp.execution and exp.execution.tool_name else (
            exp.metadata.skill_used if exp.metadata and exp.metadata.skill_used else None
        )
        if tool:
            tools[tool].append(exp)

    patterns: list[FailurePattern] = []
    for tool, exps in tools.items():
        fails = [
            e for e in exps
            if (e.execution and e.execution.status == ExecutionStatus.FAILED)
            or e.category == ExperienceCategory.ACTION_FAILED
        ]
        if len(fails) >= min_failures:
            fail_rate = round(len(fails) / len(exps), 4)
            evidence = [
                {
                    "experience_id": e.experience_id,
                    "error": e.error.message if e.error else None,
                }
                for e in fails
            ]
            patterns.append(
                FailurePattern(
                    type=PatternType.TOOL_SKILL_FAILURE,
                    description=f"La herramienta o skill '{tool}' presentó {len(fails)} fallos de {len(exps)} usos ({fail_rate * 100:.1f}%).",
                    frequency=len(fails),
                    confidence=round(fail_rate, 2),
                    evidence=evidence,
                    first_seen=min(e.timestamp for e in fails),
                    last_seen=max(e.timestamp for e in fails),
                    affected_operations=[tool],
                    severity=PatternSeverity.HIGH if fail_rate >= 0.50 else PatternSeverity.MEDIUM,
                    failure_rate=fail_rate,
                )
            )

    return patterns


def detect_all_patterns(
    experiences: Sequence[Experience],
    config: dict[str, Any] | None = None,
) -> list[Pattern]:
    """Ejecuta todos los detectores de patrones y consolida los resultados ordenados por severidad."""
    if not experiences:
        return []

    cfg = config or {}
    all_patterns: list[Pattern] = []

    # 1. Fallos y éxitos repetidos
    all_patterns.extend(detect_repeated_failures(experiences, min_occurrences=cfg.get("min_failure_occurrences", 2)))
    all_patterns.extend(detect_repeated_successes(experiences, min_occurrences=cfg.get("min_success_occurrences", 3)))

    # 2. STT y variantes
    all_patterns.extend(detect_low_stt_confidence(experiences, threshold=cfg.get("stt_confidence_threshold", 0.70)))
    all_patterns.extend(detect_stt_variants(experiences, similarity_threshold=cfg.get("stt_similarity_threshold", 0.75)))

    # 3. Intenciones y ambigüedad
    all_patterns.extend(detect_low_intent_confidence(experiences, threshold=cfg.get("intent_confidence_threshold", 0.70)))
    all_patterns.extend(detect_repeated_clarifications(experiences, min_occurrences=cfg.get("min_clarification_occurrences", 2)))

    # 4. Verificación OS
    all_patterns.extend(detect_verification_failures(experiences))

    # 5. Correcciones de usuario
    all_patterns.extend(detect_user_corrections(experiences))

    # 6. Latencia
    all_patterns.extend(detect_latency_degradations(experiences, latency_threshold_ms=cfg.get("latency_threshold_ms", 500.0)))

    # 7. Acciones repetidas y herramientas
    all_patterns.extend(detect_repeated_actions(experiences, min_occurrences=cfg.get("min_action_occurrences", 3)))
    all_patterns.extend(detect_tool_skill_failures(experiences, min_failures=cfg.get("min_tool_failures", 2)))

    # Ordenar por severidad decreciente y luego por frecuencia
    severity_order = {
        PatternSeverity.CRITICAL: 5,
        PatternSeverity.HIGH: 4,
        PatternSeverity.MEDIUM: 3,
        PatternSeverity.LOW: 2,
        PatternSeverity.INFO: 1,
    }
    return sorted(
        all_patterns,
        key=lambda p: (severity_order.get(p.severity, 0), p.frequency),
        reverse=True,
    )
