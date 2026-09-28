"""Modo Shadow para JESSYCA Decision Engine (JDE) - Fase 2.

Permite observar el tráfico real de producción de JESSYCA sin intervenir en el flujo operativo.
Compara:
    CURRENT SYSTEM (resultado y mensaje real emitido por JessycaLocalAgent)
    vs
    JDE PREDICTED DECISION (lo que JDE habría decidido con política y verificación)

REGLAS ABSOLUTAS:
1. "Shadow Mode es OBSERVACIÓN, no duplicación de ejecución."
2. NUNCA ejecuta una acción física adicional.
3. NUNCA bloquea la respuesta al usuario ni modifica el resultado productivo.
4. NUNCA activa fallback real en producción durante esta fase.
5. Redacta secretos, tokens y credenciales de los logs de persistencia.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.jde.models import DecisionRequest, VerificationRequirement
from core.jde.policy import JDEPolicyGate
from core.jde.receipts import ActionReceipt, JDEEvidence
from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType
from core.logger import get_logger

logger = get_logger("jessyca.jde.shadow")

# Directorio y archivo de persistencia de Shadow Mode
SHADOW_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "logs", "jde")
SHADOW_LOG_FILE = os.path.join(SHADOW_LOG_DIR, "shadow.jsonl")

# Patrones para redacción de secretos
_SENSITIVE_KEY_PATTERNS = re.compile(
    r"(pass|pwd|secret|token|api_?key|auth|bearer|credential|pin|private_?key)",
    re.IGNORECASE,
)


def redact_sensitive_data(data: Any) -> Any:
    """Elimina o anonimiza recursivamente credenciales, tokens y secretos."""
    if isinstance(data, Mapping):
        redacted_dict: dict[str, Any] = {}
        for k, v in data.items():
            k_str = str(k)
            if _SENSITIVE_KEY_PATTERNS.search(k_str):
                redacted_dict[k_str] = "***REDACTED_SECRET***"
            else:
                redacted_dict[k_str] = redact_sensitive_data(v)
        return redacted_dict
    elif isinstance(data, (list, tuple, set)):
        return [redact_sensitive_data(item) for item in data]
    elif isinstance(data, str):
        # Ocultar posibles Bearer tokens o hashes largos tipo API key
        if "bearer " in data.lower():
            return re.sub(r"(bearer\s+)[a-zA-Z0-9_\-\.]{8,}", r"\1***REDACTED***", data, flags=re.IGNORECASE)
        return data
    return data


class ShadowClassification(StrEnum):
    """Clasificación formal de concordancia o divergencia entre el Sistema Actual y JDE."""

    CONCORDANT_SUCCESS = "CONCORDANT_SUCCESS"
    CONCORDANT_FAILURE = "CONCORDANT_FAILURE"
    CONCORDANT_UNKNOWN = "CONCORDANT_UNKNOWN"
    FALSE_SUCCESS = "FALSE_SUCCESS"
    FALSE_FAILURE = "FALSE_FAILURE"
    POLICY_DIVERGENCE = "POLICY_DIVERGENCE"
    VERIFICATION_DIVERGENCE = "VERIFICATION_DIVERGENCE"
    DECISION_DIVERGENCE = "DECISION_DIVERGENCE"


class DivergenceSeverity(StrEnum):
    """Nivel de severidad de una divergencia detectada."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ShadowEvaluation(BaseModel):
    """Evaluación comparativa generada por JDE en Modo Shadow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    user_request: str
    intent: str
    selected_tool: str
    proposed_action: str
    risk_level: str
    confidence: float
    current_system_success: bool
    current_system_verified: bool
    current_system_message: str
    jde_predicted_state: DecisionState
    jde_would_allow: bool
    jde_requires_confirmation: bool
    jde_has_verification_contract: bool
    classification: ShadowClassification
    severity: DivergenceSeverity
    is_divergent: bool
    divergence_reason: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    execution_status: str = "UNKNOWN"
    verification_status: str = "UNKNOWN"
    receipt_id: str | None = None
    latency_overhead_ms: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_log_dict(self) -> dict[str, Any]:
        """Serializa la evaluación para el archivo jsonl con secretos redactados."""
        data = self.model_dump()
        data["parameters"] = redact_sensitive_data(self.parameters)
        data["user_request"] = redact_sensitive_data(self.user_request)
        data["timestamp"] = self.timestamp.isoformat()
        return data


class JDEShadowMetrics:
    """Contador y agregador de métricas para el Shadow Mode."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.total_observations: int = 0
        self.concordant_success: int = 0
        self.concordant_failure: int = 0
        self.concordant_unknown: int = 0
        self.false_success: int = 0
        self.false_failure: int = 0
        self.policy_divergence: int = 0
        self.verification_divergence: int = 0
        self.decision_divergence: int = 0
        self.critical_divergence: int = 0
        self.unknown_results: int = 0
        self.latencies_ms: list[float] = []

    def record(self, eval_result: ShadowEvaluation) -> None:
        with self.lock:
            self.total_observations += 1
            self.latencies_ms.append(eval_result.latency_overhead_ms)

            if eval_result.classification == ShadowClassification.CONCORDANT_SUCCESS:
                self.concordant_success += 1
            elif eval_result.classification == ShadowClassification.CONCORDANT_FAILURE:
                self.concordant_failure += 1
            elif eval_result.classification == ShadowClassification.CONCORDANT_UNKNOWN:
                self.concordant_unknown += 1
            elif eval_result.classification == ShadowClassification.FALSE_SUCCESS:
                self.false_success += 1
            elif eval_result.classification == ShadowClassification.FALSE_FAILURE:
                self.false_failure += 1
            elif eval_result.classification == ShadowClassification.POLICY_DIVERGENCE:
                self.policy_divergence += 1
            elif eval_result.classification == ShadowClassification.VERIFICATION_DIVERGENCE:
                self.verification_divergence += 1
            elif eval_result.classification == ShadowClassification.DECISION_DIVERGENCE:
                self.decision_divergence += 1

            if eval_result.severity == DivergenceSeverity.CRITICAL:
                self.critical_divergence += 1

            if eval_result.jde_predicted_state == DecisionState.UNKNOWN:
                self.unknown_results += 1

    def compute_latency_stats(self) -> tuple[float, float, float]:
        """Calcula (average_ms, p95_ms, max_ms)."""
        with self.lock:
            if not self.latencies_ms:
                return 0.0, 0.0, 0.0
            sorted_lat = sorted(self.latencies_ms)
            avg = sum(sorted_lat) / len(sorted_lat)
            p95_idx = int(len(sorted_lat) * 0.95)
            p95 = sorted_lat[min(p95_idx, len(sorted_lat) - 1)]
            maximum = sorted_lat[-1]
            return round(avg, 2), round(p95, 2), round(maximum, 2)

    def format_report(self) -> str:
        """Genera el reporte consolidado formal."""
        avg_lat, p95_lat, max_lat = self.compute_latency_stats()
        return (
            "===================================================\n"
            "               JDE SHADOW REPORT                   \n"
            "===================================================\n"
            f"Observations: {self.total_observations}\n\n"
            f"Concordant success:       {self.concordant_success}\n"
            f"Concordant failure:       {self.concordant_failure}\n"
            f"Concordant unknown:       {self.concordant_unknown}\n\n"
            f"False success:            {self.false_success}\n"
            f"False failure:            {self.false_failure}\n\n"
            f"Policy divergence:        {self.policy_divergence}\n"
            f"Verification divergence:  {self.verification_divergence}\n"
            f"Decision divergence:      {self.decision_divergence}\n\n"
            f"Critical divergences:     {self.critical_divergence}\n"
            f"Unknown results:          {self.unknown_results}\n\n"
            "Shadow overhead:\n"
            f"  average: {avg_lat} ms\n"
            f"  p95:     {p95_lat} ms\n"
            f"  maximum: {max_lat} ms\n"
            "==================================================="
        )


class JDEShadowMode:
    """Motor de observación y evaluación no invasiva (Shadow Mode)."""

    def __init__(
        self,
        policy_gate: JDEPolicyGate | None = None,
        persist_to_file: bool = True,
        log_file_path: str | None = None,
    ) -> None:
        self.policy_gate = policy_gate or JDEPolicyGate()
        self._history: list[ShadowEvaluation] = []
        self._is_enabled: bool = True
        self._persist_to_file = persist_to_file
        self._log_file_path = log_file_path or SHADOW_LOG_FILE
        self.metrics = JDEShadowMetrics()
        self._receipts: dict[str, ActionReceipt] = {}
        self._lock = threading.RLock()

        if self._persist_to_file:
            try:
                os.makedirs(os.path.dirname(self._log_file_path), exist_ok=True)
            except Exception as e:
                logger.warning(f"[JDE SHADOW] No se pudo crear directorio de logs {self._log_file_path}: {e}")

    def is_enabled(self) -> bool:
        return self._is_enabled

    def set_enabled(self, enabled: bool) -> None:
        self._is_enabled = enabled

    def get_receipt(self, request_id: str) -> ActionReceipt | None:
        """Recupera el recibo formal e inmutable de una acción observada en Shadow Mode."""
        with self._lock:
            return self._receipts.get(request_id)

    def evaluate_shadow(
        self,
        request: DecisionRequest,
        current_system_success: bool,
        current_system_message: str,
        current_system_verified: bool = False,
        execution_status: str = "OK",
        verification_status: str = "UNKNOWN",
        raw_evidence: Any = None,
    ) -> ShadowEvaluation:
        """Observa una interacción completada y compara las decisiones sin alterar nada."""
        t_start = time.perf_counter()
        if not self._is_enabled:
            logger.debug("[JDE SHADOW] Modo Shadow desactivado.")

        # 1. Evaluar política en JDE
        pol_dec = self.policy_gate.evaluate(
            tool=request.tool,
            action=request.proposed_action,
            parameters=request.parameters,
            user_confirmed=request.policy_requirements.requires_human_confirmation,
            declared_risk=request.risk_level,
        )

        has_verification = len(request.verification_requirements) > 0
        predicted_state: DecisionState

        # Regla de oro Anti-False Success
        if not pol_dec.is_allowed:
            predicted_state = DecisionState.BLOCKED
        elif pol_dec.requires_confirmation:
            predicted_state = DecisionState.BLOCKED
        elif current_system_success and current_system_verified:
            predicted_state = DecisionState.SUCCESS
        elif current_system_success and not current_system_verified:
            # Caso crítico: El sistema declara éxito pero el SO no lo confirmó
            predicted_state = DecisionState.UNKNOWN
        elif not current_system_success and current_system_verified:
            # Falso fallo: el sistema cree que falló, pero el SO confirmó presencia
            predicted_state = DecisionState.SUCCESS
        elif execution_status == "OK" and (verification_status in ("UNVERIFIABLE", "UNKNOWN") or not current_system_verified):
            predicted_state = DecisionState.UNKNOWN
        else:
            predicted_state = DecisionState.FAILED

        # 2. Clasificar el resultado según la taxonomía formal
        classification: ShadowClassification
        severity: DivergenceSeverity
        is_divergent: bool = False
        divergence_reason: str | None = None

        tool_clean = request.tool.lower()
        is_critical_surface = any(c in tool_clean for c in ("youtube", "browser", "apps", "mcp", "computer_use", "files", "whatsapp", "cmd"))

        if (pol_dec.requires_confirmation or not pol_dec.is_allowed) and not request.policy_requirements.requires_human_confirmation:
            classification = ShadowClassification.POLICY_DIVERGENCE
            severity = DivergenceSeverity.CRITICAL if "delete" in request.proposed_action or "kill" in request.proposed_action else DivergenceSeverity.HIGH
            is_divergent = True
            divergence_reason = (
                f"SECURITY_DIVERGENCE: El sistema actual ejecutó una acción sensible ('{request.proposed_action}') que "
                f"JDE habría bloqueado o exigido confirmación previa (rule: {pol_dec.rule_matched})."
            )
        elif current_system_success and not current_system_verified:
            classification = ShadowClassification.FALSE_SUCCESS
            severity = DivergenceSeverity.CRITICAL if is_critical_surface else DivergenceSeverity.HIGH
            is_divergent = True
            divergence_reason = (
                f"CRITICAL_FALSE_SUCCESS: El sistema actual declaró éxito en '{request.proposed_action}' "
                f"sin evidencia observable verificada (current_verified=False). JDE predice UNKNOWN (Prevención de Falso Éxito)."
            )
        elif not current_system_success and current_system_verified:
            classification = ShadowClassification.FALSE_FAILURE
            severity = DivergenceSeverity.HIGH if is_critical_surface else DivergenceSeverity.MEDIUM
            is_divergent = True
            divergence_reason = (
                f"FALSE_FAILURE: El sistema actual declaró fallo en '{request.proposed_action}' "
                f"pero se comprobó evidencia positiva en el sistema operativo."
            )
        elif current_system_success and current_system_verified:
            classification = ShadowClassification.CONCORDANT_SUCCESS
            severity = DivergenceSeverity.INFO
            is_divergent = False
            divergence_reason = None
        elif not current_system_success and not current_system_verified:
            if predicted_state == DecisionState.UNKNOWN:
                classification = ShadowClassification.CONCORDANT_UNKNOWN
            else:
                classification = ShadowClassification.CONCORDANT_FAILURE
            severity = DivergenceSeverity.INFO
            is_divergent = False
            divergence_reason = None
        else:
            classification = ShadowClassification.DECISION_DIVERGENCE
            severity = DivergenceSeverity.MEDIUM
            is_divergent = True
            divergence_reason = f"DECISION_DIVERGENCE: Discordancia general en '{request.proposed_action}'."

        # Generar ActionReceipt inmutable con trazabilidad criptográfica
        receipt_id: str | None = None
        try:
            ev_list: list[JDEEvidence] = []
            if raw_evidence:
                if isinstance(raw_evidence, list):
                    for item in raw_evidence:
                        if isinstance(item, JDEEvidence):
                            ev_list.append(item)
                        elif isinstance(item, dict):
                            ev_list.append(JDEEvidence(
                                verification_type=item.get("verification_type", "state_check"),
                                target=str(item.get("target", request.proposed_action)),
                                is_verified=bool(item.get("is_verified", current_system_verified)),
                                observed_state=item.get("observed_state", {}),
                                details=item.get("details", item),
                            ))
                elif isinstance(raw_evidence, dict):
                    ev_list.append(JDEEvidence(
                        verification_type=raw_evidence.get("verification_type", "state_check"),
                        target=str(raw_evidence.get("target", request.proposed_action)),
                        is_verified=bool(raw_evidence.get("is_verified", current_system_verified)),
                        observed_state=raw_evidence.get("observed_state", {}),
                        details=raw_evidence.get("details", raw_evidence),
                    ))

            exec_st = ExecutionStatusType.OK if execution_status == "OK" else ExecutionStatusType.ERROR
            verif_st = (
                VerificationStatusType.VERIFIED_TRUE if current_system_verified
                else (VerificationStatusType.UNVERIFIABLE if verification_status in ("UNVERIFIABLE", "UNKNOWN")
                      else VerificationStatusType.VERIFIED_FALSE)
            )

            policy_verdict = "ALLOW" if pol_dec.is_allowed else ("CONFIRM" if pol_dec.requires_confirmation else "BLOCK")
            receipt = ActionReceipt.create(
                request_id=request.request_id,
                user_request=request.user_request,
                action=request.proposed_action,
                tool=request.tool,
                parameters=request.parameters,
                executor="legacy_runtime",
                verifier="legacy_verifier",
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                execution_status=exec_st,
                verification_status=verif_st,
                verified=current_system_verified,
                final_status=predicted_state,
                evidence=ev_list,
                policy_verdict=policy_verdict,
            )
            receipt_id = receipt.receipt_id
            with self._lock:
                self._receipts[request.request_id] = receipt
        except Exception as receipt_err:
            logger.debug(f"[JDE SHADOW RECEIPT] No se pudo generar ActionReceipt: {receipt_err}")

        latency_overhead_ms = (time.perf_counter() - t_start) * 1000

        evaluation = ShadowEvaluation(
            request_id=request.request_id,
            user_request=request.user_request,
            intent=request.intent,
            selected_tool=request.tool,
            proposed_action=request.proposed_action,
            risk_level=pol_dec.risk_level,
            confidence=request.confidence,
            current_system_success=current_system_success,
            current_system_verified=current_system_verified,
            current_system_message=current_system_message,
            jde_predicted_state=predicted_state,
            jde_would_allow=pol_dec.is_allowed,
            jde_requires_confirmation=pol_dec.requires_confirmation,
            jde_has_verification_contract=has_verification,
            classification=classification,
            severity=severity,
            is_divergent=is_divergent,
            divergence_reason=divergence_reason,
            parameters=request.parameters,
            execution_status=execution_status,
            verification_status=verification_status,
            receipt_id=receipt_id,
            latency_overhead_ms=round(latency_overhead_ms, 3),
        )

        with self._lock:
            self._history.append(evaluation)
            self.metrics.record(evaluation)

        # 3. Persistir registro a archivo JSONL si está habilitado
        if self._persist_to_file and self._log_file_path:
            try:
                line = json.dumps(evaluation.to_log_dict(), ensure_ascii=False)
                with open(self._log_file_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception as ex:
                logger.debug(f"[JDE SHADOW PERSISTENCE] Error al escribir log shadow: {ex}")

        if is_divergent:
            logger.warning(
                f"[JDE SHADOW DIVERGENCE] [{severity.value}] {classification.value} | "
                f"req={request.request_id} tool={request.tool} | {divergence_reason}"
            )
        else:
            logger.debug(f"[JDE SHADOW CONCORDANT] req={request.request_id} -> {classification.value}")

        return evaluation

    def get_evaluations(self) -> list[ShadowEvaluation]:
        with self._lock:
            return list(self._history)

    def get_divergences(self) -> list[ShadowEvaluation]:
        with self._lock:
            return [e for e in self._history if e.is_divergent]

    def get_critical_divergences(self) -> list[ShadowEvaluation]:
        with self._lock:
            return [e for e in self._history if e.severity == DivergenceSeverity.CRITICAL]

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()
            self.metrics = JDEShadowMetrics()


_GLOBAL_JDE_SHADOW: JDEShadowMode | None = None
_SHADOW_LOCK = threading.Lock()


def get_jde_shadow_mode() -> JDEShadowMode:
    """Retorna la instancia global singleton de JDEShadowMode."""
    global _GLOBAL_JDE_SHADOW
    with _SHADOW_LOCK:
        if _GLOBAL_JDE_SHADOW is None:
            _GLOBAL_JDE_SHADOW = JDEShadowMode()
        return _GLOBAL_JDE_SHADOW
