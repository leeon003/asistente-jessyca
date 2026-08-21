"""Motor de consenso Multi-LLM (consensus_engine.py - Fase 10: Multi-LLM Consensus Engine).

Permite recolectar análisis independientes de múltiples modelos (Qwen, Gemma, Llama) y consolidar
una conclusión unificada sin contaminación de contexto entre ellos.

INVARIANTES DE SEGURIDAD ABSOLUTAS:
1. Los modelos NO pueden votar sobre seguridad ni alterar políticas.
2. CONSENSUS NO ES AUTORIZACIÓN: Todo resultado con efectos colaterales debe pasar por el Security Pipeline.
3. Aislamiento estricto: Las inferencias de cada modelo son completamente independientes y aisladas.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any, ClassVar

from core.llm.consensus_policy import ConsensusPolicy
from core.llm.consensus_result import ConsensusResult, ModelVote
from core.llm.inference import LLMProvider, OllamaProvider
from core.llm.model_manager import ModelManager, get_model_manager
from core.logger import get_logger

logger = get_logger("jessyca.llm.consensus")

DEFAULT_CONSENSUS_ENSEMBLE: tuple[str, ...] = (
    "qwen3:8b",
    "gemma4:e4b",
    "llama3.1:latest",
)


class ConsensusEngine:
    """Motor de orquestación y resolución de consenso Multi-LLM."""

    _instance: ClassVar[ConsensusEngine | None] = None
    _class_lock: ClassVar[threading.RLock] = threading.RLock()

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        model_manager: ModelManager | None = None,
        default_ensemble: tuple[str, ...] | None = None,
    ) -> None:
        self.llm_provider = llm_provider or OllamaProvider()
        self.model_manager = model_manager or get_model_manager()
        self.default_ensemble = default_ensemble or DEFAULT_CONSENSUS_ENSEMBLE

    @classmethod
    def get_instance(cls) -> ConsensusEngine:
        """Obtiene la instancia global singleton del ConsensusEngine."""
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = ConsensusEngine()
            return cls._instance

    def evaluate_votes(
        self,
        votes: list[ModelVote],
        task: str,
        policy: ConsensusPolicy | None = None,
    ) -> ConsensusResult:
        """Evalúa un conjunto de votos ya recolectados mediante la política configurada."""
        active_policy = policy or ConsensusPolicy()
        return active_policy.evaluate_votes(votes=votes, task=task)

    def run_consensus(
        self,
        task: str,
        prompt: str,
        models: list[str] | tuple[str, ...] | None = None,
        policy: ConsensusPolicy | None = None,
        timeout_per_model: float = 30.0,
        custom_runners: Mapping[str, Callable[[str], ModelVote | dict[str, Any]]] | None = None,
    ) -> ConsensusResult:
        """Ejecuta inferencias independientes sobre el conjunto de modelos y obtiene el consenso final.

        Garantiza que ningún modelo vea la respuesta de los demás (cero contaminación de contexto).
        """
        target_models = tuple(models or self.default_ensemble)
        active_policy = policy or ConsensusPolicy()
        votes: list[ModelVote] = []

        logger.info(
            f"[CONSENSUS START] Iniciando consenso Multi-LLM para tarea: '{task}' con {len(target_models)} modelos: {target_models}"
        )

        for model_id in target_models:
            start_t = time.monotonic()
            try:
                # 1. Si existe un custom runner mockeado o especializado para pruebas/plugins
                if custom_runners and model_id in custom_runners:
                    runner_fn = custom_runners[model_id]
                    res = runner_fn(prompt)
                    latency = time.monotonic() - start_t
                    if isinstance(res, ModelVote):
                        votes.append(res)
                    elif isinstance(res, dict):
                        votes.append(
                            ModelVote(
                                model_id=model_id,
                                decision=res.get("decision", "UNKNOWN"),
                                answer=res.get("answer", ""),
                                confidence=float(res.get("confidence", 1.0)),
                                reasoning=res.get("reasoning", ""),
                                latency_seconds=latency,
                                is_valid=res.get("is_valid", True),
                                error=res.get("error"),
                            )
                        )
                    continue

                # 2. Inferencia estándar independiente mediante LLMProvider
                structured_prompt = (
                    f"{prompt}\n\n"
                    f"Responde estrictamente en formato JSON válido con la siguiente estructura:\n"
                    f'{{"decision": "<palabra_clave_decision>", "confidence": 0.0_a_1.0, "reasoning": "<breve_explicacion>", "answer": "<respuesta_completa>"}}'
                )

                output_text = self.llm_provider.generate_text(
                    prompt=structured_prompt,
                    model_name=model_id,
                    system_prompt="Eres un modelo analítico imparcial que evalúa tareas de forma estructurada e independiente.",
                )
                latency = time.monotonic() - start_t

                # 3. Parseo estructurado del voto del modelo
                vote = self._parse_model_output(model_id=model_id, raw_output=output_text, latency=latency)
                votes.append(vote)

            except Exception as e:
                latency = time.monotonic() - start_t
                logger.warning(f"[CONSENSUS MODEL FAILURE] Modelo '{model_id}' falló durante consenso: {e}")
                votes.append(
                    ModelVote(
                        model_id=model_id,
                        decision="ERROR",
                        answer="",
                        confidence=0.0,
                        reasoning="",
                        latency_seconds=latency,
                        is_valid=False,
                        error=str(e),
                        raw_output="",
                    )
                )

        # 4. Consolidación de votos bajo la política de consenso
        consensus = active_policy.evaluate_votes(votes=votes, task=task)
        logger.info(
            f"[CONSENSUS RESULT] Tarea: '{task}' -> Estado: {consensus.status}, "
            f"Decisión: '{consensus.final_decision}', Ratio: {consensus.agreement_ratio:.2f}"
        )
        return consensus

    @staticmethod
    def _parse_model_output(model_id: str, raw_output: str, latency: float) -> ModelVote:
        """Extrae de forma robusta la decisión y respuesta estructurada del output del modelo."""
        try:
            # Buscar bloque JSON
            json_match = re.search(r"\{.*\}", raw_output, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                decision = str(data.get("decision", "UNKNOWN")).strip()
                answer = str(data.get("answer", raw_output)).strip()
                confidence = float(data.get("confidence", 1.0))
                reasoning = str(data.get("reasoning", "")).strip()

                return ModelVote(
                    model_id=model_id,
                    decision=decision,
                    answer=answer,
                    confidence=max(0.0, min(1.0, confidence)),
                    reasoning=reasoning,
                    latency_seconds=latency,
                    is_valid=True,
                    raw_output=raw_output,
                )
        except Exception:
            pass

        # Fallback a texto libre si el JSON no se pudo deserializar
        cleaned = raw_output.strip()
        first_line = cleaned.splitlines()[0] if cleaned else "UNKNOWN"
        return ModelVote(
            model_id=model_id,
            decision=first_line[:50],
            answer=cleaned,
            confidence=0.7,
            reasoning=cleaned,
            latency_seconds=latency,
            is_valid=True,
            raw_output=raw_output,
        )


def get_consensus_engine() -> ConsensusEngine:
    """Acceso helper al singleton global de ConsensusEngine."""
    return ConsensusEngine.get_instance()
