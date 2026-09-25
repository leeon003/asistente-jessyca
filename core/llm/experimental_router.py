"""Router Inteligente Experimental de Modelos LLM para JESSYCA PC (experimental_router.py - Fase 3).

Permite clasificar contextualmente tareas y seleccionar dinámicamente entre Gemma 4 e4b, Qwen3 8B y Nemotron 3 Ultra
operando bajo tres modos estrictos:
1. STATIC (por defecto): Inalterado, ejecuta siempre con el modelo actual configurado.
2. SHADOW: Analiza y registra la recomendación en logs estructurados sin modificar el modelo de ejecución real.
3. EXPERIMENTAL: Activa la selección real del modelo únicamente cuando se especifica por configuración/benchmark.

INVARIANTES CRÍTICAS:
- El router selecciona el modelo; NO ejecuta herramientas de Windows, NO declara éxito y NO sustituye la verificación.
- Si NEMOTRON_ENABLED=false o el sistema está offline, Nemotron queda estrictamente excluido.
- Las órdenes de voz rápidas priorizan latencia y se enrutan a Gemma 4 local.
- Cadena de fallback determinista: Nemotron -> Qwen3 -> Gemma4.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable

from core.llm.exceptions import (
    InferenceError,
    ProviderConnectionError,
    ProviderError,
    ProviderTimeoutError,
)
from core.llm.model_registry import ModelRegistry
from core.llm.vram_governor import VRAMGovernor
from core.logger import get_logger

logger = get_logger("jessyca.llm.router.experimental")


class RouterMode(StrEnum):
    """Modos de operación del Router Inteligente Experimental."""

    STATIC = "static"            # Modo por defecto de producción: No altera nada
    SHADOW = "shadow"            # Evalúa y registra en logs sin cambiar el modelo de ejecución
    EXPERIMENTAL = "experimental"# Enrutamiento real controlado por flag / benchmark
    CONTROLLED = "controlled"    # Enrutamiento controlado Fase 5 (activo solo si MODEL_ROUTER_ENABLED=True)


class TaskCategory(StrEnum):
    """Categorías funcionales para el enrutador inteligente."""

    FAST_INTERACTION = "fast_interaction"      # Diálogo rápido, comandos simples de voz, apertura/cierre directo
    TECHNICAL = "technical"                    # Análisis de código, debugging, trazas de error, terminal
    COMPLEX_REASONING = "complex_reasoning"    # Razonamiento deductivo, contradicciones, trade-offs de arquitectura
    AGENT_PLANNING = "agent_planning"          # Planes multi-step, pipelines atómicos de verificación
    OFFLINE = "offline"                        # Operación local sin acceso a redes externas
    AMBIGUOUS = "ambiguous"                    # Solicitudes incompletas o ambiguas que requieren aclaración
    CONVERSATION = "conversation"              # Diálogo social, saludos, agradecimientos, consultas informales
    OTHER = "other"                            # Solicitudes que no encajan claramente en otras categorías


def sanitize_sensitive_text(text: str) -> str:
    """Sanitiza credenciales, tokens, contraseñas y claves API de textos antes de registrarlos."""
    if not text:
        return ""
    # Patrones de API keys y tokens (OpenAI, GitHub, Bearer, etc.)
    sanitized = re.sub(r"\b(sk-[a-zA-Z0-9_\-]{20,})\b", "[REDACTED_API_KEY]", text)
    sanitized = re.sub(r"\b(ghp_[a-zA-Z0-9]{30,})\b", "[REDACTED_API_KEY]", sanitized)
    sanitized = re.sub(r"\b(Bearer\s+)[a-zA-Z0-9_\-\.]{15,}\b", r"\1[REDACTED_TOKEN]", sanitized, flags=re.IGNORECASE)
    # Patrones de contraseñas y credenciales explícitas (password=..., clave: ..., secret=...)
    sanitized = re.sub(r"(password|pass|contrase[ñn]a|clave|secret|token)\s*[:=]\s*([^\s,;]+)", r"\1=[REDACTED_SECRET]", sanitized, flags=re.IGNORECASE)
    # Hashes hexadecimales largos (32+ caracteres)
    sanitized = re.sub(r"\b[a-f0-9]{32,64}\b", "[REDACTED_HASH]", sanitized, flags=re.IGNORECASE)
    return sanitized


@dataclass(frozen=True)
class RouterDecision:
    """Decisión estructurada y explicable emitida por el Router Experimental."""

    recommended_model: str
    confidence: float
    reason: str
    task_type: TaskCategory
    estimated_complexity: str  # "low", "medium", "high"
    fallback_chain: tuple[str, ...]
    is_voice_command: bool
    nemotron_available: bool
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommended_model": self.recommended_model,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "task_type": str(self.task_type.value),
            "estimated_complexity": self.estimated_complexity,
            "fallback_chain": list(self.fallback_chain),
            "is_voice_command": self.is_voice_command,
            "nemotron_available": self.nemotron_available,
            "created_at": self.created_at,
        }


class ShadowLogger:
    """Registrador thread-safe para auditoría de decisiones en modo shadow y experimental."""

    _lock = threading.Lock()

    def __init__(self, log_path: Path | str | None = None) -> None:
        raw_path = log_path or os.getenv("ROUTER_SHADOW_LOG_FILE", "logs/router_shadow.jsonl")
        self.log_path = Path(raw_path)
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"[SHADOW LOGGER] No se pudo crear directorio para logs shadow: {e}")

    def log_decision(
        self,
        request_id: str,
        user_text: str,
        current_model: str,
        decision: RouterDecision,
        execution_model: str,
        router_mode: RouterMode,
        latency_ms: float = 0.0,
        router_decision_latency_ms: float | None = None,
        execution_latency_ms: float = 0.0,
        total_latency_ms: float = 0.0,
        tool_selected: str | None = None,
        tool_result: str | None = None,
        verification_result: str = "PENDING",
        fallback_used: bool = False,
        error: str | None = None,
        evaluation: str | None = None,
        evaluation_notes: str | None = None,
        input_type: str = "text",
        intent: str | None = None,
        vram_state: dict[str, Any] | None = None,
        policy: str = "RoutingPolicyV5",
    ) -> None:
        """Registra un evento estructurado en formato JSONL garantizando privacidad y sanitización."""
        clean_text = sanitize_sensitive_text(user_text)[:180]
        routing_lat = router_decision_latency_ms if router_decision_latency_ms is not None else latency_ms
        tot_lat = total_latency_ms if total_latency_ms > 0 else (routing_lat + execution_latency_ms)

        entry = {
            "timestamp": time.time(),
            "iso_time": datetime.now(UTC).isoformat(),
            "request_id": request_id,
            "input_type": input_type,
            "intent": intent or str(decision.task_type.value),
            "current_model": current_model,
            "recommended_model": decision.recommended_model,
            "selected_model": execution_model,
            "routing_reason": decision.reason,
            "policy": policy,
            "vram_state": vram_state or {},
            "router_mode": str(router_mode.value),
            "user_text": clean_text,
            "confidence": round(decision.confidence, 4),
            "task_type": str(decision.task_type.value),
            "complexity": decision.estimated_complexity,
            "reason": decision.reason,
            "nemotron_available": decision.nemotron_available,
            "execution_model": execution_model,
            "latency_ms": round(latency_ms, 2),
            "router_decision_latency_ms": round(routing_lat, 2),
            "execution_latency_ms": round(execution_latency_ms, 2),
            "total_latency_ms": round(tot_lat, 2),
            "tool_selected": tool_selected,
            "tool_result": tool_result,
            "verification_result": verification_result,
            "verification": verification_result,
            "success": (error is None) and (tool_result != "failed") and (verification_result != "FAILED"),
            "fallback": fallback_used,
            "fallback_used": fallback_used,
            "error": error,
            "evaluation": evaluation,
            "evaluation_notes": evaluation_notes,
        }

        with self._lock:
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.warning(f"[SHADOW LOGGER] No se pudo escribir log shadow: {e}")

    def update_execution_metrics(
        self,
        request_id: str,
        tool_selected: str | None = None,
        tool_result: str | None = None,
        verification_result: str = "COMPLETED",
        execution_latency_ms: float = 0.0,
        total_latency_ms: float = 0.0,
        error: str | None = None,
    ) -> bool:
        """Actualiza los campos de ejecución del registro correspondiente al request_id."""
        with self._lock:
            try:
                if not self.log_path.exists():
                    return False
                lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
                updated = False
                new_lines = []
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        if record.get("request_id") == request_id:
                            if tool_selected is not None:
                                record["tool_selected"] = tool_selected
                            if tool_result is not None:
                                record["tool_result"] = tool_result
                            if verification_result:
                                record["verification_result"] = verification_result
                            if execution_latency_ms > 0:
                                record["execution_latency_ms"] = round(execution_latency_ms, 2)
                            if total_latency_ms > 0:
                                record["total_latency_ms"] = round(total_latency_ms, 2)
                            if error is not None:
                                record["error"] = error
                            # Recalcular success consistentemente tras actualizar campos de ejecución
                            rec_tool = record.get("tool_result")
                            rec_verif = record.get("verification_result", "PENDING")
                            rec_error = record.get("error")
                            record["success"] = (
                                rec_error is None
                                and rec_tool != "failed"
                                and rec_verif not in ("FAILED", "PENDING")
                            )
                            updated = True
                        new_lines.append(json.dumps(record, ensure_ascii=False))
                    except Exception:
                        new_lines.append(line)

                if updated:
                    self.log_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                return updated
            except Exception as e:
                logger.warning(f"[SHADOW LOGGER] Error actualizando métricas de ejecución: {e}")
                return False

    def update_evaluation(
        self,
        request_id: str,
        evaluation: str,
        notes: str = "",
    ) -> bool:
        """Marca una recomendación como appropriate, questionable o inappropriate."""
        if evaluation not in ("appropriate", "questionable", "inappropriate"):
            raise ValueError(f"Evaluación inválida '{evaluation}'. Debe ser: appropriate, questionable o inappropriate.")

        with self._lock:
            try:
                if not self.log_path.exists():
                    return False
                lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
                updated = False
                new_lines = []
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        if record.get("request_id") == request_id:
                            record["evaluation"] = evaluation
                            if notes:
                                record["evaluation_notes"] = notes
                            updated = True
                        new_lines.append(json.dumps(record, ensure_ascii=False))
                    except Exception:
                        new_lines.append(line)

                if updated:
                    self.log_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
                return updated
            except Exception as e:
                logger.warning(f"[SHADOW LOGGER] Error actualizando evaluación: {e}")
                return False

    def get_recent_entries(self, limit: int = 20) -> list[dict[str, Any]]:
        """Recupera los últimos N registros del archivo shadow en orden cronológico inverso."""
        with self._lock:
            try:
                if not self.log_path.exists():
                    return []
                lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
                entries = []
                for line in reversed(lines):
                    if not line.strip():
                        continue
                    try:
                        entries.append(json.loads(line))
                        if len(entries) >= limit:
                            break
                    except Exception:
                        pass
                return entries
            except Exception as e:
                logger.warning(f"[SHADOW LOGGER] Error leyendo entradas recientes: {e}")
                return []



class Phase6Logger:
    """Registrador estructurado y detector de anomalías para la Fase 6 de Operación Controlada."""

    _lock = threading.Lock()

    def __init__(self, log_path: Path | str | None = None) -> None:
        raw_path = log_path or os.getenv("ROUTER_PHASE6_LOG_FILE", "logs/router_phase6.jsonl")
        self.log_path = Path(raw_path)
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.warning(f"[PHASE 6 LOGGER] No se pudo crear directorio para logs: {e}")

    def detect_alerts(
        self,
        recommended_model: str,
        selected_model: str,
        execution_model: str,
        fallback: bool,
        fallback_reason: str | None,
        inference_latency_ms: float,
        timeout_threshold_ms: float,
        vram_after_mb: float,
        vram_budget_mb: float,
        tool_executed: bool,
        verification: str,
        total_latency_ms: float,
        success: bool = True,
        latency_outlier_threshold_ms: float = 15000.0,
    ) -> list[str]:
        """Detecta automáticamente anomalías y genera alertas de la Sección 21."""
        alerts: list[str] = []

        # 1. Routing incorrecto: Modelo ejecutado diferente del seleccionado sin fallback registrado
        if execution_model != selected_model and not fallback:
            alerts.append("routing_incorrecto")

        # 2. Fallback inesperado: Fallback sin error/motivo documentado
        if fallback and not fallback_reason:
            alerts.append("fallback_inesperado")

        # 3. Timeout: Inferencia >= timeout configurado
        if inference_latency_ms >= timeout_threshold_ms and timeout_threshold_ms > 0:
            alerts.append("timeout")

        # 4. VRAM: Uso superior al presupuesto de seguridad
        if vram_after_mb > vram_budget_mb and vram_budget_mb > 0:
            alerts.append("vram_exceeded")

        # 5. False-success: Herramienta ejecutada reportada como éxito sin verificación real.
        #    CONDICIÓN ESTRICTA: solo se dispara si la herramienta se ejecutó (tool_executed=True),
        #    el resultado declarado es éxito (success=True) pero la verificación falló o no existe.
        #    NO aplica cuando success=False — en ese caso el sistema ya previno correctamente el false-success.
        if tool_executed and success and verification not in ("VERIFIED", "COMPLETED"):
            alerts.append("false_success")

        # 6. Latencia: Detectar outliers
        if total_latency_ms > latency_outlier_threshold_ms:
            alerts.append("latency_outlier")

        return alerts

    def log_interaction(
        self,
        request_id: str,
        router_enabled: bool,
        intent: str,
        recommended_model: str,
        selected_model: str,
        execution_model: str,
        routing_latency_ms: float = 0.0,
        inference_latency_ms: float = 0.0,
        tool_latency_ms: float = 0.0,
        verification_latency_ms: float = 0.0,
        total_latency_ms: float = 0.0,
        vram_before_mb: float = 0.0,
        vram_after_mb: float = 0.0,
        vram_budget_mb: float = 10752.0,
        fallback: bool = False,
        fallback_reason: str | None = None,
        success: bool = True,
        verification: str = "VERIFIED",
        tool_executed: bool = False,
        timeout_threshold_ms: float = 15000.0,
        phase: str = "phase6",
    ) -> dict[str, Any]:
        """Registra una interacción estructurada de Fase 6 y evalúa alertas."""
        tot_lat = total_latency_ms if total_latency_ms > 0 else (
            routing_latency_ms + inference_latency_ms + tool_latency_ms + verification_latency_ms
        )
        alerts = self.detect_alerts(
            recommended_model=recommended_model,
            selected_model=selected_model,
            execution_model=execution_model,
            fallback=fallback,
            fallback_reason=fallback_reason,
            inference_latency_ms=inference_latency_ms,
            timeout_threshold_ms=timeout_threshold_ms,
            vram_after_mb=vram_after_mb,
            vram_budget_mb=vram_budget_mb,
            tool_executed=tool_executed,
            verification=verification,
            total_latency_ms=tot_lat,
            success=success,
        )

        entry = {
            "timestamp": time.time(),
            "request_id": request_id,
            "phase": phase,
            "router_enabled": router_enabled,
            "intent": intent,
            "recommended_model": recommended_model,
            "selected_model": selected_model,
            "execution_model": execution_model,
            "routing_latency_ms": round(routing_latency_ms, 2),
            "inference_latency_ms": round(inference_latency_ms, 2),
            "tool_latency_ms": round(tool_latency_ms, 2),
            "verification_latency_ms": round(verification_latency_ms, 2),
            "total_latency_ms": round(tot_lat, 2),
            "vram_before_mb": round(vram_before_mb, 2),
            "vram_after_mb": round(vram_after_mb, 2),
            "fallback": fallback,
            "fallback_reason": fallback_reason,
            "success": success,
            "verification": verification,
            "alerts": alerts,
        }

        with self._lock:
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception as e:
                logger.warning(f"[PHASE 6 LOGGER] Error al escribir en log: {e}")

        if alerts:
            logger.warning(f"[PHASE 6 ALERTA] Detectadas anomalías en request {request_id}: {alerts}")

        return entry

    def get_recent_entries(self, limit: int = 50) -> list[dict[str, Any]]:
        """Recupera los últimos N registros en orden cronológico."""
        with self._lock:
            try:
                if not self.log_path.exists():
                    return []
                lines = self.log_path.read_text(encoding="utf-8").strip().splitlines()
                entries = []
                for line in lines:
                    if not line.strip():
                        continue
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
                return entries[-limit:]
            except Exception as e:
                logger.warning(f"[PHASE 6 LOGGER] Error leyendo entradas recientes: {e}")
                return []


class ExperimentalRouter:
    """Enrutador de modelos multi-dimensional con soporte para static, shadow y experimental."""

    DEFAULT_FALLBACK_CHAIN = (
        "nvidia/nemotron-3-ultra-550b-a55b",
        "qwen3:8b",
        "gemma4:e4b",
    )

    def __init__(
        self,
        mode: RouterMode | str | None = None,
        confidence_threshold: float | None = None,
        shadow_logger: ShadowLogger | None = None,
        phase6_logger: Phase6Logger | None = None,
        registry: ModelRegistry | None = None,
        vram_governor: VRAMGovernor | None = None,
        enabled: bool | None = None,
    ) -> None:
        raw_mode = mode or os.getenv("MODEL_ROUTER_MODE", "shadow")
        try:
            self.mode = RouterMode(str(raw_mode).lower().strip())
        except ValueError:
            self.mode = RouterMode.SHADOW

        if enabled is not None:
            self.enabled = bool(enabled)
        elif "MODEL_ROUTER_ENABLED" in os.environ:
            self.enabled = os.environ["MODEL_ROUTER_ENABLED"].strip().lower() in ("true", "1", "yes", "on")
        else:
            self.enabled = (self.mode == RouterMode.EXPERIMENTAL)

        raw_thresh = confidence_threshold or os.getenv("ROUTER_CONFIDENCE_THRESHOLD", "0.80")
        try:
            self.confidence_threshold = float(raw_thresh)
        except ValueError:
            self.confidence_threshold = 0.80

        self.shadow_logger = shadow_logger or ShadowLogger()
        self.phase6_logger = phase6_logger or Phase6Logger()
        self.registry = registry or ModelRegistry.get_instance()
        self.vram_governor = vram_governor or VRAMGovernor.get_instance()

    def is_enabled(self) -> bool:
        """Determina si el enrutamiento activo de modelos está habilitado."""
        return self.enabled

    def is_model_available(self, model_name: str) -> bool:
        """Determina si un modelo está habilitado y disponible en el catálogo."""
        if not model_name:
            return False
        clean = model_name.strip()
        if "nemotron" in clean.lower():
            return self.is_nemotron_enabled()
        try:
            prof = self.registry.get(clean)
            return bool(prof.enabled)
        except Exception:
            return False

    def check_vram_capacity(self, model_name: str) -> tuple[bool, str, dict[str, Any]]:
        """Verifica con el VRAMGovernor si el modelo cabe en el presupuesto utilizable."""
        if not self.vram_governor:
            return True, "VRAMGovernor no activo", {}

        report = self.vram_governor.get_budget_report()
        report_dict = {
            "total_vram_mb": report.total_vram_mb,
            "usable_budget_mb": report.usable_budget_mb,
            "allocated_mb": report.currently_allocated_mb,
            "remaining_mb": report.remaining_budget_mb,
            "loaded_models_count": report.loaded_models_count,
        }

        if "nemotron" in model_name.lower():
            return True, "Modelo remoto (0 VRAM local)", report_dict

        try:
            prof = self.registry.get(model_name)
        except Exception:
            prof = None

        if prof is not None and prof.vram_estimate_mb > 0:
            if not self.vram_governor.can_fit(prof):
                return (
                    False,
                    f"VRAM insuficiente: '{model_name}' requiere {prof.vram_estimate_mb}MB y restante es {report.remaining_budget_mb}MB",
                    report_dict,
                )
        return True, "VRAM suficiente", report_dict

    def is_nemotron_enabled(self) -> bool:
        """Determina si Nemotron está habilitado tanto por feature flag como en el catálogo."""
        env_flag = os.getenv("NEMOTRON_ENABLED", "false").strip().lower() in ("true", "1", "yes", "on")
        if not env_flag:
            return False
        try:
            prof = self.registry.get("nvidia/nemotron-3-ultra-550b-a55b")
            return bool(prof.enabled or env_flag)
        except Exception:
            return False

    def classify_task(
        self,
        user_text: str,
        is_voice: bool = False,
        is_offline: bool = False,
        context: dict[str, Any] | None = None,
    ) -> tuple[TaskCategory, str, float, str]:
        """Clasifica el texto del usuario según su naturaleza técnica, complejidad y restricciones operativas.

        Retorna: (TaskCategory, recommended_model, confidence, reason)
        """
        text_clean = user_text.strip().lower()
        nemotron_ready = self.is_nemotron_enabled() and not is_offline

        # ── 1. CONDICIÓN OFFLINE / LOCAL ONLY ────────────────────────────────
        if is_offline or not os.getenv("INTERNET_AVAILABLE", "true").lower() in ("true", "1", "yes"):
            # En modo offline, Nemotron queda estrictamente prohibido
            if any(k in text_clean for k in ("error", "código", "python", "traceback", "analiza", "plan")):
                return (
                    TaskCategory.OFFLINE,
                    "qwen3:8b",
                    0.92,
                    "Offline mode: Tarea técnica asignada a Qwen3 local sin dependencias de red.",
                )
            return (
                TaskCategory.OFFLINE,
                "gemma4:e4b",
                0.95,
                "Offline mode: Comando directo asignado a Gemma 4 local.",
            )

        # ── 1.5 DETECCIÓN DE ÓRDENES AMBIGUAS O DEÍCTICAS ──────────────────────
        clean_nopunct = re.sub(r"[^\w\s]", "", text_clean).strip()
        ambiguous_exact = (
            "cierra eso", "abre el navegador", "ponme google", "hazlo", "hazlo ahora", "mira eso",
            "no se", "algo", "abre", "cancelar"
        )
        if any(ak in clean_nopunct for ak in ("cierra eso", "ponme google", "hazlo ahora", "mira eso", "abre el navegador")) or clean_nopunct in ambiguous_exact or clean_nopunct.startswith("quiero hablar con alguien"):
            # Asegurar que no sea comando explícito con navegador especificado (ej. "abre el navegador chrome")
            if not any(spec in clean_nopunct for spec in ("chrome", "edge", "firefox", "brave", "opera")):
                return (
                    TaskCategory.AMBIGUOUS,
                    "gemma4:e4b",
                    0.84,
                    "Orden ambigua: Requiere resolución de intención o pregunta de aclaración rápida.",
                )

        # ── 2. REGLA ESPECIAL DE VOZ / LATENCIA CRÍTICA ─────────────────────
        # Si es una orden de voz y la tarea es simple, Gemma 4 tiene prioridad absoluta (<400ms)
        is_simple_voice = is_voice or any(
            text_clean.startswith(prefix)
            for prefix in ("jessica", "jessyca", "oye jessica", "hola jessica")
        )

        voice_action_keywords = (
            "abre", "cierra", "sube", "baja", "pausa", "reproduce",
            "qué hora", "cómo estás", "buenos días", "silencia", "busca en google"
        )
        if is_simple_voice and any(text_clean.startswith(k) or k in text_clean for k in voice_action_keywords):
            # Comprobar que no sea un plan multi-step complejo camuflado
            if not any(multi in text_clean for multi in ("después", "luego", "y dime qué encontraste", "cinco pasos", "analiza y propón")):
                return (
                    TaskCategory.FAST_INTERACTION,
                    "gemma4:e4b",
                    0.95,
                    "Voz interactiva: Prioridad de baja latencia asignada a Gemma 4 local (<400ms).",
                )

        # ── 3. DETECCIÓN DE AGENT PLANNING / MULTI-STEP ──────────────────────
        is_planning = any(
            pk in text_clean
            for pk in (
                "cinco pasos", "paso a paso", "valida cada etapa", "investiga el problema",
                "planifica cómo", "organiza los archivos", "y dime qué encontraste",
                "toma una captura", "fallo parcial", "multi-step", "rollback",
            )
        ) or (
            "primero" in text_clean and ("después" in text_clean or "luego" in text_clean)
        ) or (
            "crea una carpeta" in text_clean and "mueve" in text_clean
        ) or (
            ("copia" in text_clean or "cópialo" in text_clean) and "verifica" in text_clean
        )

        if is_planning:
            if nemotron_ready:
                return (
                    TaskCategory.AGENT_PLANNING,
                    "nvidia/nemotron-3-ultra-550b-a55b",
                    0.91,
                    "Planificación multi-step y separación formal REASONING->PLAN asignada a Nemotron 3 Ultra.",
                )
            else:
                return (
                    TaskCategory.AGENT_PLANNING,
                    "qwen3:8b",
                    0.86,
                    "Planificación multi-step asignada a Qwen3 local (Nemotron remoto no disponible).",
                )

        # ── 4. DETECCIÓN DE RAZONAMIENTO COMPLEJO Y CONTRADICCIONES ─────────
        reasoning_keywords = (
            "analiza por qué", "contradicción", "contradiccion", "contradicciones", "contradicci",
            "paradoja", "cuello de botella",
            "trade-off", "teorema de bayes", "falsos positivos", "solución arquitectónica",
            "decisiones contradictorias", "varias causas posibles", "propón una estrategia",
            "diseña un plan para solucionar este problema", "inconsistencia entre módulos",
            "dependencias cruzadas", "falso éxito", "probes de verificación",
            "analiza cómo resolver", "analiza las contradicciones"
        )
        if any(rk in text_clean for rk in reasoning_keywords):
            if nemotron_ready:
                return (
                    TaskCategory.COMPLEX_REASONING,
                    "nvidia/nemotron-3-ultra-550b-a55b",
                    0.89,
                    "Razonamiento profundo y análisis de contradicciones asignado a Nemotron 3 Ultra.",
                )
            else:
                return (
                    TaskCategory.COMPLEX_REASONING,
                    "qwen3:8b",
                    0.87,
                    "Razonamiento complejo asignado a Qwen3 local (Nemotron remoto desactivado).",
                )

        # ── 5. DETECCIÓN TÉCNICA / DEBUGGING / CÓDIGO ────────────────────────
        technical_keywords = (
            "python", "traceback", "debug", "error de python", "revisa este código",
            "race condition", r"(?<!b)lock", "vram", "oom", "permissionerror",
            "providerconnectionerror", "jsondecodeerror", "singleton", "memory leak",
            "código", "codigo", "algoritmo", "script", "sql", "depura", "depurar",
            "refactoriza", "función", "funcion", "indexerror", "decorador", "dijkstra",
            "quicksort", "fibonacci", "expresión regular", "expresion regular"
        )
        if any(re.search(tk, text_clean) for tk in technical_keywords):
            # Qwen3 8B es el modelo técnico local especializado por excelencia
            return (
                TaskCategory.TECHNICAL,
                "qwen3:8b",
                0.93,
                "Análisis de código y debugging técnico asignado a Qwen3 8B local.",
            )


        # ── 6.5 DETECCIÓN CONVERSACIONAL PURA ────────────────────────────────
        conversational_phrases = (
            "cómo te llamas", "quién eres", "cuéntame un chiste", "gracias jessyca",
            "muchas gracias", "de nada", "qué puedes hacer", "buen trabajo"
        )
        if any(cp in text_clean for cp in conversational_phrases):
            return (
                TaskCategory.CONVERSATION,
                "gemma4:e4b",
                0.93,
                "Interacción conversacional o social directa asignada a Gemma 4 local.",
            )

        # ── 6.8 DETECCIÓN DE OTRAS ENTRADAS NO ESTRUCTURADAS ──────────────────
        if not text_clean or len(text_clean.strip()) < 2 or re.match(r"^[\W_]+$", text_clean):
            return (
                TaskCategory.OTHER,
                "gemma4:e4b",
                0.70,
                "Entrada no estructurada o de baja inteligibilidad asignada a categoría 'other'.",
            )

        # ── 7. FAST INTERACTION GENERAL (DEFAULT SEGURO) ─────────────────────
        return (
            TaskCategory.FAST_INTERACTION,
            "gemma4:e4b",
            0.92,
            "Interacción estándar de diálogo directo asignada a Gemma 4 local.",
        )

    def route_decision(
        self,
        user_text: str,
        is_voice: bool = False,
        is_offline: bool = False,
        context: dict[str, Any] | None = None,
    ) -> RouterDecision:
        """Calcula la recomendación del router aplicando umbrales de confianza, disponibilidad y VRAM."""
        nemotron_ready = self.is_nemotron_enabled() and not is_offline
        category, target_model, confidence, reason = self.classify_task(
            user_text=user_text,
            is_voice=is_voice,
            is_offline=is_offline,
            context=context,
        )

        # Seguridad de Umbral de Confianza: Si confianza < threshold, revertir a modelo local seguro
        if confidence < self.confidence_threshold:
            logger.warning(
                f"[ROUTER] Confianza {confidence:.2f} inferior al umbral {self.confidence_threshold:.2f}. "
                f"Revertiendo a modelo local seguro: 'gemma4:e4b'"
            )
            target_model = "gemma4:e4b"
            reason += f" (Umbral no alcanzado {confidence:.2f} < {self.confidence_threshold:.2f}; fallback seguro local)."

        # Validar disponibilidad real del modelo recomendado en el catálogo/entorno
        if not self.is_model_available(target_model):
            avail_found = False
            for fb in ("qwen3:8b", "gemma4:e4b"):
                if self.is_model_available(fb):
                    reason += f" (Modelo '{target_model}' no disponible; asignado fallback '{fb}')."
                    target_model = fb
                    avail_found = True
                    break
            if not avail_found:
                target_model = "gemma4:e4b"

        # Validar presupuesto de memoria de video (VRAMGovernor)
        vram_ok, vram_msg, _ = self.check_vram_capacity(target_model)
        if not vram_ok:
            reason += f" (VRAM insuficiente para '{target_model}': {vram_msg}; degradando a 'gemma4:e4b')."
            target_model = "gemma4:e4b"

        # Construir cadena de fallback específica según el modelo recomendado
        if "nemotron" in target_model.lower():
            fallback_chain = ("qwen3:8b", "gemma4:e4b")
            complexity = "high"
        elif "qwen" in target_model.lower():
            fallback_chain = ("gemma4:e4b",)
            complexity = "medium"
        else:
            fallback_chain = ("qwen3:8b",)
            complexity = "low"

        return RouterDecision(
            recommended_model=target_model,
            confidence=confidence,
            reason=reason,
            task_type=category,
            estimated_complexity=complexity,
            fallback_chain=fallback_chain,
            is_voice_command=is_voice,
            nemotron_available=nemotron_ready,
        )

    def route_execution(
        self,
        user_text: str,
        current_model: str = "gemma4:e4b",
        is_voice: bool = False,
        is_offline: bool = False,
        request_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> tuple[str, RouterDecision]:
        """Aplica la política de enrutamiento gobernada por MODEL_ROUTER_ENABLED y RouterMode.

        Retorna: (modelo_que_debe_ejecutarse, decision_del_router)
        """
        req_id = request_id or f"req_{uuid.uuid4().hex[:8]}"
        start_t = time.perf_counter()

        try:
            decision = self.route_decision(
                user_text=user_text,
                is_voice=is_voice,
                is_offline=is_offline,
                context=context,
            )
        except Exception as e:
            logger.warning(f"[ROUTER ERROR] Fallo calculando decisión de enrutamiento: {e}. Revertiendo a default.")
            decision = RouterDecision(
                recommended_model=current_model,
                confidence=0.50,
                reason=f"Excepción en router: {e}",
                task_type=TaskCategory.OTHER,
                estimated_complexity="low",
                fallback_chain=("qwen3:8b",),
                is_voice_command=is_voice,
                nemotron_available=False,
            )

        routing_lat_ms = (time.perf_counter() - start_t) * 1000.0
        _, _, vram_state = self.check_vram_capacity(decision.recommended_model)
        is_voice_inp = is_voice or decision.is_voice_command
        input_type_str = "voice" if is_voice_inp else "text"

        # ── FASE 5: CONTROL POR FEATURE FLAG MODEL_ROUTER_ENABLED ──
        if not self.enabled:
            # Comportamiento anterior estricto (STATIC / SHADOW):
            # Jamás modifica el modelo de producción
            execution_model = current_model
            if self.mode == RouterMode.SHADOW:
                try:
                    self.shadow_logger.log_decision(
                        request_id=req_id,
                        user_text=user_text,
                        current_model=current_model,
                        decision=decision,
                        execution_model=execution_model,
                        router_mode=self.mode,
                        latency_ms=routing_lat_ms,
                        router_decision_latency_ms=routing_lat_ms,
                        verification_result="SHADOW_RECORDED",
                        input_type=input_type_str,
                        vram_state=vram_state,
                    )
                except Exception as e:
                    logger.warning(f"[ROUTER SHADOW] Error no crítico al invocar shadow_logger: {e}")
                logger.info(
                    f"[ROUTER SHADOW] Recomienda: '{decision.recommended_model}' (Confianza: {decision.confidence:.2f}) | "
                    f"Ejecución fija: '{execution_model}' | Tarea: {decision.task_type.value}"
                )
            return execution_model, decision

        # ── MODEL_ROUTER_ENABLED=True: ACTIVACIÓN CONTROLADA ──
        if self.mode in (RouterMode.EXPERIMENTAL, RouterMode.CONTROLLED):
            candidate = decision.recommended_model

            # Validar disponibilidad real en runtime
            if not self.is_model_available(candidate):
                logger.warning(f"[ROUTER CONTROLLED] Modelo candidato '{candidate}' no disponible. Revertiendo a fallback.")
                candidate = "gemma4:e4b"
                for fb in decision.fallback_chain:
                    if self.is_model_available(fb):
                        candidate = fb
                        break

            # Validar VRAM con VRAMGovernor
            vram_ok_cand, vram_msg_cand, vram_state_cand = self.check_vram_capacity(candidate)
            if not vram_ok_cand:
                logger.warning(f"[ROUTER CONTROLLED] {vram_msg_cand}. Revertiendo a modelo base seguro 'gemma4:e4b'")
                candidate = "gemma4:e4b"
                vram_state = vram_state_cand
            else:
                vram_state = vram_state_cand

            execution_model = candidate
            try:
                self.shadow_logger.log_decision(
                    request_id=req_id,
                    user_text=user_text,
                    current_model=current_model,
                    decision=decision,
                    execution_model=execution_model,
                    router_mode=self.mode,
                    latency_ms=routing_lat_ms,
                    router_decision_latency_ms=routing_lat_ms,
                    verification_result="CONTROLLED_ROUTED",
                    input_type=input_type_str,
                    vram_state=vram_state,
                )
            except Exception as e:
                logger.warning(f"[ROUTER CONTROLLED] Error no crítico al invocar shadow_logger: {e}")
            logger.info(
                f"[ROUTER CONTROLLED] Enrutado a: '{execution_model}' | Razón: {decision.reason}"
            )
        elif self.mode == RouterMode.SHADOW:
            execution_model = current_model
            try:
                self.shadow_logger.log_decision(
                    request_id=req_id,
                    user_text=user_text,
                    current_model=current_model,
                    decision=decision,
                    execution_model=execution_model,
                    router_mode=self.mode,
                    latency_ms=routing_lat_ms,
                    router_decision_latency_ms=routing_lat_ms,
                    verification_result="SHADOW_RECORDED",
                    input_type=input_type_str,
                    vram_state=vram_state,
                )
            except Exception as e:
                logger.warning(f"[ROUTER SHADOW] Error no crítico al invocar shadow_logger: {e}")
        else:
            execution_model = current_model

        return execution_model, decision

    def execute_with_fallback(
        self,
        primary_model: str,
        decision: RouterDecision,
        execute_fn: Callable[[str], Any],
        timeout_seconds: float = 15.0,
    ) -> tuple[Any, str, list[str]]:
        """Ejecuta una función de inferencia con la cadena de fallback determinista (Nemotron -> Qwen -> Gemma).

        Retorna: (resultado, modelo_que_tuvo_exito, lista_de_modelos_intentados)
        """
        attempted_chain = [primary_model] + [m for m in decision.fallback_chain if m != primary_model]
        attempts_log: list[str] = []
        last_exception: Exception | None = None

        for model in attempted_chain:
            attempts_log.append(model)
            try:
                logger.debug(f"[ROUTER FALLBACK] Intentando ejecución con modelo: '{model}'")
                result = execute_fn(model)
                logger.info(f"[ROUTER FALLBACK] Éxito alcanzado con modelo: '{model}' (Intentos: {attempts_log})")
                return result, model, attempts_log
            except (ProviderTimeoutError, ProviderConnectionError, ProviderError, InferenceError) as e:
                last_exception = e
                logger.warning(
                    f"[ROUTER FALLBACK] Modelo '{model}' falló con {type(e).__name__} ({e}). "
                    f"Cascada a siguiente modelo en cadena..."
                )
            except Exception as e:
                last_exception = e
                logger.error(f"[ROUTER FALLBACK] Excepción inesperada con '{model}': {e}. Cascada al siguiente...")

        # Si todos fallaron, levantar la última excepción sin declarar éxito falso
        raise InferenceError(
            f"Todos los modelos de la cadena de fallback fallaron {attempts_log}. Último error: {last_exception}"
        ) from last_exception


_global_experimental_router: ExperimentalRouter | None = None
_global_router_lock = threading.Lock()


def get_experimental_router(
    mode: RouterMode | str | None = None,
    enabled: bool | None = None,
) -> ExperimentalRouter:
    """Retorna la instancia global del ExperimentalRouter."""
    global _global_experimental_router
    with _global_router_lock:
        if _global_experimental_router is None:
            _global_experimental_router = ExperimentalRouter(mode=mode, enabled=enabled)
        else:
            if mode is not None:
                try:
                    raw_mode = mode if isinstance(mode, RouterMode) else RouterMode(str(mode).lower().strip())
                    _global_experimental_router.mode = raw_mode
                except ValueError:
                    pass
            if enabled is not None:
                _global_experimental_router.enabled = bool(enabled)
        return _global_experimental_router

