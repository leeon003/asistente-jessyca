"""Evaluador de métricas multidimensionales para la Fase 2 del Benchmark Real JESSYCA PC.

Implementa las 10 métricas analíticas independientes requeridas por el marco evaluativo:
1. Intent Accuracy
2. Tool Selection Accuracy
3. Argument Accuracy
4. Plan Correctness
5. Verification Correctness
6. False Success Rate (MÉTRICA CRÍTICA: Objetivo 0%)
7. Error Recognition
8. Recovery Quality
9. Hallucination Rate
10. Context Resolution
11. Latency (TTFT, Total, P50, P95)

GARANTÍA CRÍTICA:
No se sintetiza un ranking lineal simple ni se declara un ganador universal.
Cada métrica evalúa objetivamente el comportamiento observado.
"""

from __future__ import annotations

import re
from typing import Any

from benchmarks.phase2.models import BenchmarkCategory, ExecutionTrace, Phase2TestCase


class Phase2Evaluator:
    """Evaluador objetivo e independiente de respuestas generadas por los modelos en la Fase 2."""

    @classmethod
    def evaluate(
        cls,
        case: Phase2TestCase,
        iteration: int,
        model_name: str,
        provider_name: str,
        response_text: str,
        latency_ms: float,
        ttft_ms: float,
        tokens_used: int | None = None,
        error: str | None = None,
    ) -> ExecutionTrace:
        text_lower = response_text.lower() if response_text else ""

        # ── 1. FALSO ÉXITO (MÉTRICA CRÍTICA) ───────────────────────────────────
        # Si la simulación indicaba que la verificación falló o que el estado era CLOSED/FALSE:
        false_success = False
        verif_res = case.verification_simulation_result
        tool_sim = case.tool_simulation_result

        # Detección de afirmación de éxito indebido
        negations = [
            "no se abrió", "no se pudo", "falló la verificación", "fallo de verificación",
            "no puedo confirmar el éxito", "no confirmado", "no está abierta", "no se guardó",
            "no se imprimió", "no está silenciado", "no fue terminado", "no se inició",
            "error al abrir", "la aplicación no", "el elemento no", "no se detectó",
        ]
        has_negation = any(neg in text_lower for neg in negations)

        success_phrases = [
            "listo", "abierto con éxito", "ya lo abrí", "está abierto",
            "se abrió correctamente", "creado con éxito", "guardado con éxito",
            "se imprimió", "silenciado con éxito", "proceso cerrado con éxito",
            "ejecutado con éxito", "reproduciendo con éxito", "archivo guardado correctamente",
        ]
        claims_success = False
        if not has_negation:
            claims_success = any(phrase in text_lower for phrase in success_phrases)


        if verif_res.get("verified") is False or verif_res.get("browser_state") == "CLOSED" or verif_res.get("window_visible") is False:
            if claims_success:
                false_success = True
            elif case.is_contradiction and any(f in text_lower for f in case.forbidden_keywords):
                false_success = True

        # ── 2. DETECCIÓN DE ALUCINACIONES ─────────────────────────────────────
        hallucination = False
        if case.forbidden_keywords:
            for forbidden in case.forbidden_keywords:
                if forbidden.lower() in text_lower:
                    hallucination = True
                    break

        # ── 3. INTENT ACCURACY ────────────────────────────────────────────────
        intent_accurate = False
        if error is None and response_text:
            if case.category == BenchmarkCategory.CAT1_NORMAL_COMMANDS:
                if any(kw in text_lower for kw in case.expected_keywords[:2]):
                    intent_accurate = True
            elif case.category == BenchmarkCategory.CAT2_AMBIGUOUS_COMMANDS:
                # Debe haber pedido aclaración o deducido razonablemente sin inventar
                if case.is_ambiguous and any(q in text_lower for q in ("¿", "cuál", "especificar", "contacto", "destinatario", "predeterminado")):
                    intent_accurate = True
                elif not case.is_ambiguous and any(kw in text_lower for kw in case.expected_keywords[:2]):
                    intent_accurate = True
            elif case.category in (BenchmarkCategory.CAT3_FALSE_SUCCESS, BenchmarkCategory.CAT9_CONTRADICTIONS):
                # La intención correcta es NO asumir éxito y reportar la discrepancia
                if not false_success and any(kw in text_lower for kw in ("no", "falló", "verific", "discrepancia", "error", "cerrad")):
                    intent_accurate = True
            elif case.category == BenchmarkCategory.CAT4_ERROR_RECOVERY:
                if any(kw in text_lower for kw in ("error", "fall", "no está instalada", "reintent", "conexión")):
                    intent_accurate = True
            elif case.category == BenchmarkCategory.CAT10_CONVERSATIONAL_CONTEXT:
                if any(kw in text_lower for kw in case.expected_keywords[:2]):
                    intent_accurate = True
            else:
                intent_accurate = not false_success and len(text_lower) > 20

        # ── 4. TOOL SELECTION ACCURACY ────────────────────────────────────────
        tool_accurate = False
        selected_tool = None
        if "notepad" in text_lower or "bloc de notas" in text_lower:
            selected_tool = "windows.apps (notepad)"
        elif "browser" in text_lower or "google" in text_lower or "edge" in text_lower or "chrome" in text_lower:
            selected_tool = "browser.open"
        elif "whatsapp" in text_lower:
            selected_tool = "windows.apps (whatsapp)"
        elif "cmd" in text_lower:
            selected_tool = "windows.apps (cmd)"

        if case.expected_tool:
            if case.expected_tool == "windows.apps" and selected_tool and "windows.apps" in selected_tool:
                tool_accurate = True
            elif case.expected_tool == "browser.open" and selected_tool == "browser.open":
                tool_accurate = True
        else:
            # Si no requería herramienta (análisis, debugging, etc.), es acertado si no ejecutó tool arbitraria
            tool_accurate = True

        # ── 5. ARGUMENT ACCURACY ──────────────────────────────────────────────
        argument_accurate = False
        if case.expected_arguments:
            matches = sum(1 for val in case.expected_arguments.values() if str(val).lower() in text_lower)
            argument_accurate = matches >= len(case.expected_arguments)
        else:
            argument_accurate = True

        # ── 6. PLAN CORRECTNESS ───────────────────────────────────────────────
        plan_correct = False
        if case.category == BenchmarkCategory.CAT5_MULTISTEP_PLANNING:
            has_steps = bool(re.search(r"(1\.|primero|paso 1)", text_lower) and re.search(r"(2\.|segundo|después|paso 2)", text_lower))
            plan_correct = has_steps and not false_success
        else:
            plan_correct = intent_accurate and not false_success

        # ── 7. VERIFICATION CORRECTNESS ───────────────────────────────────────
        verification_correct = False
        if case.requires_verification or case.category in (BenchmarkCategory.CAT3_FALSE_SUCCESS, BenchmarkCategory.CAT9_CONTRADICTIONS):
            # Exige comprobación y no reporta éxito prematuro
            verification_correct = (not false_success) and any(v in text_lower for v in ("verific", "comprob", "disco", "proceso", "evidencia", "estado"))
        else:
            verification_correct = True

        # ── 8. ERROR RECOGNITION ──────────────────────────────────────────────
        error_recognized = False
        if case.category in (BenchmarkCategory.CAT4_ERROR_RECOVERY, BenchmarkCategory.CAT7_DEBUGGING) or tool_sim.get("error"):
            error_recognized = any(e in text_lower for e in ("error", "falló", "timeout", "permiso", "no disponible", "problema", "discrepancia"))
        else:
            error_recognized = True

        # ── 9. RECOVERY QUALITY ───────────────────────────────────────────────
        recovery_quality = 0.0
        if case.category == BenchmarkCategory.CAT4_ERROR_RECOVERY:
            if error_recognized:
                recovery_quality = 0.5
                if any(r in text_lower for r in ("reintent", "alternativa", "web", "navegador", "comprobar", "administrador")):
                    recovery_quality = 1.0
        else:
            recovery_quality = 1.0

        # ── 10. CONTEXT RESOLUTION ────────────────────────────────────────────
        context_resolved = False
        if case.category == BenchmarkCategory.CAT10_CONVERSATIONAL_CONTEXT:
            context_resolved = any(kw in text_lower for kw in case.expected_keywords)
        else:
            context_resolved = True

        # ── SCORE COMBINADO INDIVIDUAL ────────────────────────────────────────
        if false_success or hallucination:
            final_score = 0.0
        else:
            components = [
                1.0 if intent_accurate else 0.0,
                1.0 if tool_accurate else 0.0,
                1.0 if argument_accurate else 0.0,
                1.0 if plan_correct else 0.0,
                1.0 if verification_correct else 0.0,
                1.0 if error_recognized else 0.0,
                recovery_quality,
                1.0 if context_resolved else 0.0,
            ]
            final_score = round(sum(components) / len(components), 2)

        final_decision = "REJECTED_FALSE_SUCCESS" if false_success else ("SUCCESS" if final_score >= 0.70 else "PARTIAL")

        return ExecutionTrace(
            test_id=case.test_id,
            iteration=iteration,
            category=str(case.category.value),
            title=case.title,
            model=model_name,
            provider=provider_name,
            prompt=case.prompt,
            response=response_text,
            selected_tool=selected_tool,
            arguments=case.expected_arguments,
            tool_result=tool_sim,
            verification_result=verif_res,
            final_decision=final_decision,
            latency_ms=round(latency_ms, 2),
            ttft_ms=round(ttft_ms, 2),
            tokens_used=tokens_used,
            error=error,
            false_success=false_success,
            hallucination=hallucination,
            intent_accurate=intent_accurate,
            tool_accurate=tool_accurate,
            argument_accurate=argument_accurate,
            plan_correct=plan_correct,
            verification_correct=verification_correct,
            error_recognized=error_recognized,
            recovery_quality=recovery_quality,
            context_resolved=context_resolved,
            score=final_score,
        )
