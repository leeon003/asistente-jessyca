"""Módulo de Control de Autoridad Progresiva para JESSYCA Decision Engine (JDE) - Fase 5 (CANARY).

Define la abstracción JDEAuthorityGate y los contratos formales para la transición
gradual de autoridad:
    SHADOW -> CANARY -> LIMITED -> PROGRESSIVE -> FULL

REGLAS DE FASE 5 (CANARY):
- CANARY solo se activa mediante opt-in explícito (JDE_AUTHORITY_MODE=CANARY).
- El comportamiento por defecto seguro sin configuración es estrictamente SHADOW.
- CANARY tiene autoridad real EXCLUSIVAMENTE sobre un conjunto diminuto y controlado
  de acciones verificables, locales, deterministas, reversibles y de bajo riesgo (LOW).
- Parámetros estrictamente restringidos al workspace temporal (tempfile / jde_canary_test).
- Acciones de alto riesgo, destructivas, credenciales, externas, browser/youtube/computer_use
  inciertas quedan formalmente EXCLUIDAS de CANARY (DENY / OBSERVE_ONLY).
- Anti-Escalation: CANARY nunca puede escalar automáticamente a LIMITED, PROGRESSIVE o FULL.
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.logger import get_logger

logger = get_logger("jessyca.jde.authority")

# Allowlist canónica y ultra-restringida para CANARY Authority (Fase 5)
DEFAULT_CANARY_ALLOWLIST: set[str] = {
    "windows.files:create_temp_file",
    "files:create_temp_file",
    "files.create_temp_file",
    "filesystem:create_temp_file",
    "filesystem.create_temp_file",
    "create_temp_file",
    "create_temp_test_file",
    "windows.files:create_temp_test_file",
}

# Acciones y superficies formalmente excluidas de CANARY
CANARY_FORBIDDEN_ACTIONS: set[str] = {
    "delete",
    "remove",
    "unlink",
    "kill",
    "terminate",
    "registry",
    "credentials",
    "password",
    "token",
    "payment",
    "youtube",
    "browser",
    "computer_use",
    "applicationframehost",
}

# Patrón de exclusión estricta de superficies no autorizadas en CANARY
_CANARY_EXCLUSIONS_PATTERN = re.compile(
    r"(delete|remove|rmdir|unlink|drop|truncate|wipe|destroy|format|"
    r"kill|terminate|stop_process|shutdown|reboot|restart_system|"
    r"registry|reg_|credential|password|token|payment|finance|money|"
    r"youtube|browser|computer_use|applicationframehost)",
    re.IGNORECASE,
)


def is_canary_excluded_action(action: str, tool: str = "") -> bool:
    """Verifica si una acción está estrictamente excluida de CANARY Authority."""
    target = f"{tool}:{action}".lower()
    return bool(_CANARY_EXCLUSIONS_PATTERN.search(target))


def validate_canary_scope(
    action: str,
    tool: str = "",
    parameters: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Valida que los parámetros de una acción autorizada en CANARY respeten los límites de seguridad."""
    params = parameters or {}
    target_path = (
        params.get("path")
        or params.get("file_path")
        or params.get("target")
        or params.get("destination")
    )

    if target_path:
        path_str = str(target_path).strip()
        path_norm = os.path.normpath(path_str).lower()
        temp_norm = os.path.normpath(tempfile.gettempdir()).lower()

        # Exclusiones absolutas: rutas críticas del sistema operativo
        forbidden_keywords = ("\\windows", "\\system32", "program files", "windows\\", "system32\\")
        if any(fk in path_norm for fk in forbidden_keywords):
            return False, f"Parameter out of scope: ruta crítica del sistema prohibida ('{target_path}')."

        # Debe pertenecer al directorio temporal del sistema o contener el identificador de prueba
        is_temp = (
            path_norm.startswith(temp_norm)
            or "\\temp\\" in path_norm
            or "\\tmp\\" in path_norm
            or "jde_canary" in path_norm
            or "jde_test" in path_norm
        )
        if not is_temp:
            return False, f"Parameter out of scope: la ruta ('{target_path}') no pertenece al workspace temporal permitido en CANARY."

    return True, "Parámetros dentro del scope seguro de CANARY."


class AuthorityMode(StrEnum):
    """Modos canónicos del JDE Authority Gate."""

    OFF = "OFF"
    LAB = "LAB"
    SHADOW = "SHADOW"
    ADVISORY = "ADVISORY"
    CANARY = "CANARY"
    LIMITED = "LIMITED"
    PROGRESSIVE = "PROGRESSIVE"
    CONTROLLED = "CONTROLLED"
    FULL = "FULL"

    @property
    def observes(self) -> bool:
        """Todos los modos de JDE observan la operación."""
        return True

    @property
    def decides(self) -> bool:
        """Todos los modos de JDE emiten una decisión formal de política y control."""
        return True

    @property
    def can_execute_globally(self) -> bool:
        """Indica si el modo tiene autoridad de ejecución global irrestricta."""
        return self == AuthorityMode.FULL

    @property
    def can_block_globally(self) -> bool:
        """Indica si el modo puede bloquear cualquier acción no autorizada."""
        return self in (
            AuthorityMode.LIMITED,
            AuthorityMode.PROGRESSIVE,
            AuthorityMode.FULL,
        )


class ActionRiskTier(StrEnum):
    """Clasificación canónica de riesgo para acciones del sistema."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AuthorityDecision(StrEnum):
    """Decisiones formales emitidas por el Authority Gate."""

    OBSERVE_ONLY = "OBSERVE_ONLY"
    ALLOW = "ALLOW"
    DENY = "DENY"
    REQUIRE_VERIFICATION = "REQUIRE_VERIFICATION"


# Patrones deterministas para clasificar el riesgo de acciones
_HIGH_RISK_PATTERNS = re.compile(
    r"(delete|remove|rmdir|unlink|drop|truncate|wipe|destroy|format|"
    r"kill|terminate|stop_process|shutdown|reboot|restart_system|"
    r"sudo|admin|reg_edit|system_config|modify_system|execute_arbitrary|"
    r"cmd|powershell|bash|sh|terminal|execute_command|exec_command)",
    re.IGNORECASE,
)

_MEDIUM_RISK_PATTERNS = re.compile(
    r"(write|create|update|modify|edit|save|append|touch|"
    r"open_app|launch|start|run|spawn|hotkey|click|press|type|input|"
    r"config|settings|install)",
    re.IGNORECASE,
)

_LOW_RISK_PATTERNS = re.compile(
    r"(read|inspect|check|list|view|get|query|search|find|status|info|"
    r"ping|health|echo|describe|scan|navigate|browse)",
    re.IGNORECASE,
)


def classify_action_risk(action: str, tool: str = "") -> ActionRiskTier:
    """Clasifica deterministamente una acción en su categoría de riesgo (LOW, MEDIUM, HIGH)."""
    target_str = f"{tool}:{action}".lower()

    if _HIGH_RISK_PATTERNS.search(target_str):
        return ActionRiskTier.HIGH

    if _MEDIUM_RISK_PATTERNS.search(target_str):
        return ActionRiskTier.MEDIUM

    if _LOW_RISK_PATTERNS.search(target_str):
        return ActionRiskTier.LOW

    # Por defecto, herramientas desconocidas caen en riesgo MEDIUM (principio de precaución)
    return ActionRiskTier.MEDIUM


class AuthorityGateResult(BaseModel):
    """Resultado formal inmutable de una evaluación del JDE Authority Gate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: AuthorityMode
    decision: AuthorityDecision
    can_execute: bool
    can_block: bool
    risk_tier: ActionRiskTier
    action: str
    tool: str
    capability_id: str | None = None
    promotion_status: str | None = None
    is_authorized: bool
    requires_human_confirmation: bool
    reason: str


class JDEAuthorityMetrics:
    """Métricas y telemetría de decisiones de autoridad y observabilidad."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.total_actions: int = 0
        self.verified_success: int = 0
        self.failed: int = 0
        self.unknown: int = 0
        self.not_executed: int = 0
        self.false_success: int = 0
        self.false_failure: int = 0
        self.policy_divergence: int = 0
        self.verification_divergence: int = 0
        self.decision_divergence: int = 0
        self.double_execution: int = 0

        # Métricas específicas de CANARY (Fase 5)
        self.canary_total: int = 0
        self.canary_allowed: int = 0
        self.canary_denied: int = 0
        self.canary_success: int = 0
        self.canary_failed: int = 0
        self.canary_unknown: int = 0
        self.canary_not_executed: int = 0
        self.canary_false_success: int = 0
        self.canary_double_execution: int = 0

        # Métricas específicas de LIMITED (Fase 6)
        self.limited_total: int = 0
        self.limited_allowed: int = 0
        self.limited_denied: int = 0
        self.limited_blocked: int = 0
        self.limited_success: int = 0
        self.limited_failed: int = 0
        self.limited_unknown: int = 0
        self.limited_not_executed: int = 0
        self.limited_false_success: int = 0
        self.limited_double_execution: int = 0

        # Métricas específicas de PROGRESSIVE y Promoción (Fase 7)
        self.progressive_total: int = 0
        self.progressive_allowed: int = 0
        self.progressive_denied: int = 0
        self.promotion_requests: int = 0
        self.promotion_allowed: int = 0
        self.promotion_denied: int = 0
        self.promotion_review_required: int = 0
        self.demotions: int = 0
        self.progressive_success: int = 0
        self.progressive_failed: int = 0
        self.progressive_unknown: int = 0
        self.progressive_false_success: int = 0
        self.progressive_double_execution: int = 0

        # Métricas específicas de FULL Authority (Fase 8)
        self.full_total: int = 0
        self.full_allowed: int = 0
        self.full_denied: int = 0
        self.full_success: int = 0
        self.full_failed: int = 0
        self.full_unknown: int = 0
        self.full_false_success: int = 0
        self.full_double_execution: int = 0
        self.kill_switch_events: int = 0
        self.rollbacks: int = 0

    def record_action(
        self,
        final_state: str,
        verified: bool = False,
        is_false_success: bool = False,
        is_false_failure: bool = False,
        is_policy_divergence: bool = False,
        is_verification_divergence: bool = False,
        is_decision_divergence: bool = False,
        execution_count: int = 1,
    ) -> None:
        """Registra un evento de acción con sus métricas operativas generales."""
        with self._lock:
            self.total_actions += 1
            if execution_count > 1:
                self.double_execution += 1

            state_upper = final_state.upper()
            if state_upper == "SUCCESS" and verified:
                self.verified_success += 1
            elif state_upper == "FAILED":
                self.failed += 1
            elif state_upper == "UNKNOWN":
                self.unknown += 1
            elif state_upper in ("NOT_EXECUTED", "BLOCKED"):
                self.not_executed += 1

            if is_false_success:
                self.false_success += 1
            if is_false_failure:
                self.false_failure += 1
            if is_policy_divergence:
                self.policy_divergence += 1
            if is_verification_divergence:
                self.verification_divergence += 1
            if is_decision_divergence:
                self.decision_divergence += 1

    def record_canary_action(
        self,
        decision: str,
        final_state: str,
        is_verified: bool = False,
        execution_count: int = 1,
    ) -> None:
        """Registra un evento de acción bajo autoridad CANARY."""
        with self._lock:
            self.canary_total += 1
            dec_upper = decision.upper()
            st_upper = final_state.upper()

            if dec_upper == "ALLOW":
                self.canary_allowed += 1
            elif dec_upper in ("DENY", "OBSERVE_ONLY"):
                self.canary_denied += 1

            if execution_count > 1:
                self.canary_double_execution += 1

            if st_upper == "SUCCESS":
                if is_verified:
                    self.canary_success += 1
                else:
                    self.canary_false_success += 1
            elif st_upper == "FAILED":
                self.canary_failed += 1
            elif st_upper == "UNKNOWN":
                self.canary_unknown += 1
            elif st_upper in ("NOT_EXECUTED", "BLOCKED"):
                self.canary_not_executed += 1

    def record_limited_action(
        self,
        decision: str,
        final_state: str,
        is_verified: bool = False,
        execution_count: int = 1,
    ) -> None:
        """Registra un evento de acción bajo autoridad LIMITED."""
        with self._lock:
            self.limited_total += 1
            dec_upper = decision.upper()
            st_upper = final_state.upper()

            if dec_upper == "ALLOW":
                self.limited_allowed += 1
            elif dec_upper == "DENY":
                self.limited_denied += 1
            elif dec_upper in ("BLOCKED", "REQUIRE_VERIFICATION"):
                self.limited_blocked += 1

            if execution_count > 1:
                self.limited_double_execution += 1

            if st_upper == "SUCCESS":
                if is_verified:
                    self.limited_success += 1
                else:
                    self.limited_false_success += 1
            elif st_upper == "FAILED":
                self.limited_failed += 1
            elif st_upper == "UNKNOWN":
                self.limited_unknown += 1
            elif st_upper in ("NOT_EXECUTED", "BLOCKED"):
                self.limited_not_executed += 1

    def record_progressive_action(
        self,
        decision: str,
        final_state: str,
        is_verified: bool = False,
        execution_count: int = 1,
    ) -> None:
        """Registra un evento de acción bajo autoridad PROGRESSIVE."""
        with self._lock:
            self.progressive_total += 1
            dec_upper = decision.upper()
            st_upper = final_state.upper()

            if dec_upper == "ALLOW":
                self.progressive_allowed += 1
            elif dec_upper == "DENY":
                self.progressive_denied += 1

            if execution_count > 1:
                self.progressive_double_execution += 1

            if st_upper == "SUCCESS":
                if is_verified:
                    self.progressive_success += 1
                else:
                    self.progressive_false_success += 1
            elif st_upper == "FAILED":
                self.progressive_failed += 1
            elif st_upper == "UNKNOWN":
                self.progressive_unknown += 1

    def record_promotion(self, decision: str) -> None:
        """Registra una solicitud y resultado de promoción de capacidad."""
        with self._lock:
            self.promotion_requests += 1
            dec_upper = decision.upper()
            if dec_upper == "ALLOW":
                self.promotion_allowed += 1
            elif dec_upper == "DENY":
                self.promotion_denied += 1
            elif dec_upper == "REQUIRE_REVIEW":
                self.promotion_review_required += 1

    def record_demotion(self) -> None:
        """Registra un evento de democión de capacidad."""
        with self._lock:
            self.demotions += 1

    def record_full_action(
        self,
        decision: str,
        final_state: str,
        is_verified: bool = False,
        execution_count: int = 1,
    ) -> None:
        """Registra un evento de acción bajo autoridad FULL."""
        with self._lock:
            self.full_total += 1
            dec_upper = decision.upper()
            st_upper = final_state.upper()

            if dec_upper == "ALLOW":
                self.full_allowed += 1
            elif dec_upper == "DENY":
                self.full_denied += 1

            if execution_count > 1:
                self.full_double_execution += 1

            if st_upper == "SUCCESS":
                if is_verified:
                    self.full_success += 1
                else:
                    self.full_false_success += 1
            elif st_upper == "FAILED":
                self.full_failed += 1
            elif st_upper == "UNKNOWN":
                self.full_unknown += 1

    def record_kill_switch_event(self) -> None:
        """Registra un evento de activación de Kill Switch de emergencia."""
        with self._lock:
            self.kill_switch_events += 1

    def record_rollback(self) -> None:
        """Registra un evento de rollback de autoridad."""
        with self._lock:
            self.rollbacks += 1

    @property
    def false_success_rate(self) -> float:
        with self._lock:
            if self.total_actions == 0:
                return 0.0
            return round(self.false_success / self.total_actions, 4)

    @property
    def unknown_rate(self) -> float:
        with self._lock:
            if self.total_actions == 0:
                return 0.0
            return round(self.unknown / self.total_actions, 4)

    @property
    def verification_rate(self) -> float:
        with self._lock:
            if self.total_actions == 0:
                return 0.0
            return round((self.verified_success + self.failed) / self.total_actions, 4)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_actions": self.total_actions,
                "verified_success": self.verified_success,
                "failed": self.failed,
                "unknown": self.unknown,
                "not_executed": self.not_executed,
                "false_success": self.false_success,
                "false_failure": self.false_failure,
                "policy_divergence": self.policy_divergence,
                "verification_divergence": self.verification_divergence,
                "decision_divergence": self.decision_divergence,
                "double_execution": self.double_execution,
                "false_success_rate": self.false_success_rate,
                "unknown_rate": self.unknown_rate,
                "verification_rate": self.verification_rate,
                # Telemetría CANARY
                "canary_total": self.canary_total,
                "canary_allowed": self.canary_allowed,
                "canary_denied": self.canary_denied,
                "canary_success": self.canary_success,
                "canary_failed": self.canary_failed,
                "canary_unknown": self.canary_unknown,
                "canary_not_executed": self.canary_not_executed,
                "canary_false_success": self.canary_false_success,
                "canary_double_execution": self.canary_double_execution,
                # Telemetría LIMITED (Fase 6)
                "limited_total": self.limited_total,
                "limited_allowed": self.limited_allowed,
                "limited_denied": self.limited_denied,
                "limited_blocked": self.limited_blocked,
                "limited_success": self.limited_success,
                "limited_failed": self.limited_failed,
                "limited_unknown": self.limited_unknown,
                "limited_not_executed": self.limited_not_executed,
                "limited_false_success": self.limited_false_success,
                "limited_double_execution": self.limited_double_execution,
                # Telemetría PROGRESSIVE y Promoción (Fase 7)
                "progressive_total": self.progressive_total,
                "progressive_allowed": self.progressive_allowed,
                "progressive_denied": self.progressive_denied,
                "promotion_requests": self.promotion_requests,
                "promotion_allowed": self.promotion_allowed,
                "promotion_denied": self.promotion_denied,
                "promotion_review_required": self.promotion_review_required,
                "demotions": self.demotions,
                "progressive_success": self.progressive_success,
                "progressive_failed": self.progressive_failed,
                "progressive_unknown": self.progressive_unknown,
                "progressive_false_success": self.progressive_false_success,
                "progressive_double_execution": self.progressive_double_execution,
                # Telemetría FULL Authority (Fase 8)
                "full_total": self.full_total,
                "full_allowed": self.full_allowed,
                "full_denied": self.full_denied,
                "full_success": self.full_success,
                "full_failed": self.full_failed,
                "full_unknown": self.full_unknown,
                "full_false_success": self.full_false_success,
                "full_double_execution": self.full_double_execution,
                "kill_switch_events": self.kill_switch_events,
                "rollbacks": self.rollbacks,
            }

    # Alias para compatibilidad
    to_dict = summary


class JDEAuthorityGate:
    """Puerta de Autoridad Progresiva de JDE (Fase 4 y Fase 5).

    Gestiona los permisos y límites de intervención de JDE en el ciclo de vida
    de ejecución, garantizando contención estricta en SHADOW y autoridad
    quirúrgica en CANARY.
    """

    def __init__(
        self,
        mode: AuthorityMode | str | None = None,
        canary_scope: set[str] | None = None,
        authorized_capabilities: set[str] | None = None,
        allow_global_full_authority: bool = False,
    ) -> None:
        self._raw_mode_input = mode
        self._allow_global_full = allow_global_full_authority
        self._canary_scope: set[str] = set(canary_scope if canary_scope is not None else DEFAULT_CANARY_ALLOWLIST)
        self._authorized_capabilities: set[str] = set(authorized_capabilities or [])
        self._kill_switch_active: bool = False
        self._mode = self._resolve_fail_safe_mode(mode)
        self.metrics = JDEAuthorityMetrics()

    @staticmethod
    def _resolve_fail_safe_mode(raw_input: Any) -> AuthorityMode:
        """Resuelve el modo de autoridad aplicando el Fail-Safe más estricto.

        Si el valor es None, vacío, no reconocido, inválido o corrupto,
        siempre retorna AuthorityMode.SHADOW. NUNCA retorna FULL por omisión.
        Si el Kill Switch de emergencia está activo, siempre retorna SHADOW.
        """
        if os.getenv("JDE_KILL_SWITCH", "").strip().lower() in ("true", "1", "yes", "on"):
            logger.critical("[JDE KILL SWITCH] Kill Switch activo en variables de entorno. Forzando SHADOW.")
            return AuthorityMode.SHADOW

        if raw_input is None:
            env_val = os.getenv("JDE_AUTHORITY_MODE")
            if not env_val:
                return AuthorityMode.SHADOW
            raw_input = env_val

        if not isinstance(raw_input, str):
            logger.warning(f"[JDE AUTHORITY GATE] Entrada de modo inválida (tipo {type(raw_input)}). Usando SHADOW.")
            return AuthorityMode.SHADOW

        cleaned = raw_input.strip().upper()
        if not cleaned:
            return AuthorityMode.SHADOW

        try:
            return AuthorityMode(cleaned)
        except ValueError:
            logger.warning(f"[JDE AUTHORITY GATE] Modo '{cleaned}' no reconocido. Fail-Safe activado: SHADOW.")
            return AuthorityMode.SHADOW

    @property
    def is_kill_switch_active(self) -> bool:
        env_ks = os.getenv("JDE_KILL_SWITCH", "").strip().lower() in ("true", "1", "yes", "on")
        return bool(self._kill_switch_active or env_ks)

    @property
    def current_mode(self) -> AuthorityMode:
        """Modo de autoridad actualmente activo."""
        if self.is_kill_switch_active:
            logger.warning("[JDE AUTHORITY GATE] Kill Switch activo. Forzando SHADOW.")
            return AuthorityMode.SHADOW
        if self._mode == AuthorityMode.FULL and not self._allow_global_full:
            logger.error("[JDE AUTHORITY GATE] FULL mode solicitado pero condiciones de seguridad no cumplidas. Forzando SHADOW.")
            return AuthorityMode.SHADOW
        return self._mode

    @property
    def is_shadow(self) -> bool:
        return self.current_mode in (AuthorityMode.SHADOW, AuthorityMode.OFF, AuthorityMode.LAB)

    @property
    def is_advisory(self) -> bool:
        return self.current_mode == AuthorityMode.ADVISORY

    @property
    def is_canary(self) -> bool:
        return self.current_mode == AuthorityMode.CANARY

    @property
    def is_limited(self) -> bool:
        return self.current_mode == AuthorityMode.LIMITED

    @property
    def is_progressive(self) -> bool:
        return self.current_mode == AuthorityMode.PROGRESSIVE

    @property
    def is_controlled(self) -> bool:
        return self.current_mode in (
            AuthorityMode.CONTROLLED,
            AuthorityMode.CANARY,
            AuthorityMode.LIMITED,
            AuthorityMode.PROGRESSIVE,
        )

    @property
    def is_full(self) -> bool:
        return self.current_mode == AuthorityMode.FULL

    def trigger_kill_switch(self, reason: str = "") -> None:
        """Activa inmediatamente el Kill Switch de emergencia, forzando SHADOW."""
        with self.metrics._lock:
            self._kill_switch_active = True
            self.metrics.record_kill_switch_event()
        logger.critical(f"[JDE KILL SWITCH ACTIVATED] {reason or 'Emergencia operacional'}. Desescalando inmediatamente a SHADOW.")

    def reset_kill_switch(self) -> None:
        """Restablece el Kill Switch a su estado inactivo."""
        self._kill_switch_active = False
        logger.info("[JDE KILL SWITCH RESET] Operación normal restablecida.")

    def rollback_authority(self, target_mode: AuthorityMode | str = AuthorityMode.PROGRESSIVE, reason: str = "") -> tuple[bool, str]:
        """Revierte de forma segura e inmediata la autoridad hacia un modo controlado inferior."""
        target_mode_resolved = AuthorityMode(str(getattr(target_mode, "value", target_mode)).upper())
        if target_mode_resolved == AuthorityMode.FULL:
            return False, "Rollback hacia FULL no es permitido: debe revertir a un modo inferior."
        self._mode = target_mode_resolved
        self.metrics.record_rollback()
        logger.warning(f"[JDE ROLLBACK] Autoridad revertida a {target_mode_resolved.value}. Motivo: {reason or 'Rollback de seguridad'}")
        return True, f"Autoridad revertida con éxito a {target_mode_resolved.value}."

    def can_execute(self, action: str, tool: str = "") -> bool:
        """Indica si JDE tiene permiso para despachar la ejecución de esta acción."""
        mode = self.current_mode
        if mode == AuthorityMode.SHADOW:
            return False

        action_key = f"{tool}:{action}".lower()
        if mode == AuthorityMode.CANARY:
            if is_canary_excluded_action(action, tool):
                return False
            return action_key in self._canary_scope or action.lower() in self._canary_scope

        if mode == AuthorityMode.LIMITED:
            if action_key in self._authorized_capabilities or action.lower() in self._authorized_capabilities:
                return True
            from core.jde.capabilities import get_capability_registry
            cap = get_capability_registry().find_by_action(action, tool)
            if not cap or not cap.enabled or cap.is_high_risk:
                return False
            return cap.is_allowed_for_mode(AuthorityMode.LIMITED)

        if mode == AuthorityMode.PROGRESSIVE:
            if action_key in self._authorized_capabilities or action.lower() in self._authorized_capabilities:
                return True
            from core.jde.capabilities import get_capability_registry
            cap = get_capability_registry().find_by_action(action, tool)
            if not cap or not cap.enabled or cap.is_high_risk:
                return False
            return cap.is_allowed_for_mode(AuthorityMode.PROGRESSIVE)

        if mode == AuthorityMode.FULL:
            return True

        return False

    def can_block(self, action: str, tool: str = "") -> bool:
        """Indica si JDE tiene permiso para bloquear la ejecución en producción."""
        mode = self.current_mode
        if mode == AuthorityMode.SHADOW:
            return False

        action_key = f"{tool}:{action}".lower()
        if mode == AuthorityMode.CANARY:
            return (
                action_key in self._canary_scope
                or action.lower() in self._canary_scope
                or is_canary_excluded_action(action, tool)
            )

        if mode in (AuthorityMode.LIMITED, AuthorityMode.PROGRESSIVE, AuthorityMode.FULL):
            return True

        return False

    def attempt_escalation(
        self,
        requested_mode: str | AuthorityMode | None = None,
        target_mode: str | AuthorityMode | None = None,
        caller: str = "",
        is_formally_certified: bool = False,
        **kwargs: Any,
    ) -> tuple[bool, str]:
        """Intenta escalar el nivel de autoridad.

        Regla Anti-Escalation:
        - Ni LLM, ni subagentes, ni llamadas externas pueden auto-escalar a FULL.
        - Escalada a FULL requiere certificación formal explícita (is_formally_certified=True)
          y autorización explícita a nivel de sistema (allow_global_full=True).
        - En cualquier otro caso, la escalada es rechazada de inmediato.
        """
        mode_val = str(getattr(target_mode or requested_mode or "UNKNOWN", "value", target_mode or requested_mode or "UNKNOWN")).upper()
        caller_clean = str(caller).strip().lower()

        # Bloqueo total a llamadas de LLM / agente
        if caller_clean in ("llm", "assistant", "agent", "subagent", "prompt", "user_prompt"):
            logger.critical(
                f"[JDE SECURITY ALERT] Intento de escalada de autoridad por LLM/agente ('{caller}'): "
                f"{self.current_mode.value} -> {mode_val}. RECHAZADO INCONDICIONALMENTE."
            )
            return False, f"Escalada a {mode_val} no permitida: agentes o modelos no tienen autoridad para auto-escalar."

        if not is_formally_certified:
            logger.warning(
                f"[JDE SECURITY ALERT] Intento de escalada de autoridad no autorizada: "
                f"{self.current_mode.value} -> {mode_val}. Rechazado."
            )
            reason = f"Escalada a {mode_val} no permitida: {self.current_mode.value} no puede auto-escalar sin certificación formal."
            return False, reason

        if mode_val == AuthorityMode.FULL.value:
            if not self._allow_global_full:
                logger.warning(
                    f"[JDE SECURITY ALERT] Intento de escalada a FULL sin flag allow_global_full_authority activo. Rechazado."
                )
                return False, f"Escalada a {mode_val} no permitida: bandera allow_global_full_authority no habilitada."

            # Aprobado bajo certificación formal
            self._mode = AuthorityMode.FULL
            logger.info("[JDE AUTHORITY] Escalada a FULL AUTHORITY completada bajo certificación formal.")
            return True, "Escalada a FULL AUTHORITY autorizada formalmente."

        # Escalada hacia modos intermedios (ej. CANARY -> LIMITED -> PROGRESSIVE) bajo certificación formal
        try:
            target_enum = AuthorityMode(mode_val)
            if target_enum in (AuthorityMode.LIMITED, AuthorityMode.PROGRESSIVE):
                self._mode = target_enum
                return True, f"Modo de autoridad actualizado a {target_enum.value}."
        except ValueError:
            pass

        reason = f"Escalada a {mode_val} no permitida: {self.current_mode.value} no puede auto-escalar sin certificación formal."
        return False, reason

    def evaluate_authority(
        self,
        action: str,
        tool: str = "",
        parameters: dict[str, Any] | None = None,
        user_confirmed: bool = False,
        in_canary_scope: bool = False,
        is_registered_capability: bool = True,
    ) -> AuthorityGateResult:
        """Evalúa las políticas de autoridad y gobernanza para una acción propuesta.

        Principio Anti-False Success:
        Esta evaluación NUNCA produce un estado de 'SUCCESS'.
        Solo responde: ALLOW, DENY, REQUIRE_VERIFICATION, u OBSERVE_ONLY.
        """
        mode = self.current_mode
        risk = classify_action_risk(action, tool)
        action_key = f"{tool}:{action}".lower()

        # ── 1. MODO SHADOW (COMPORTAMIENTO POR DEFECTO SEGURO) ──
        if mode == AuthorityMode.SHADOW:
            return AuthorityGateResult(
                mode=AuthorityMode.SHADOW,
                decision=AuthorityDecision.OBSERVE_ONLY,
                can_execute=False,
                can_block=False,
                risk_tier=risk,
                action=action,
                tool=tool,
                is_authorized=False,
                requires_human_confirmation=False,
                reason="JDE opera en SHADOW mode: observación pasiva estricta, sin ejecución ni bloqueo.",
            )

        # ── 2. MODO CANARY ──
        if mode == AuthorityMode.CANARY:
            # Comprobar exclusiones formales y alto riesgo
            if is_canary_excluded_action(action, tool) or risk == ActionRiskTier.HIGH:
                return AuthorityGateResult(
                    mode=AuthorityMode.CANARY,
                    decision=AuthorityDecision.DENY,
                    can_execute=False,
                    can_block=True,
                    risk_tier=risk,
                    action=action,
                    tool=tool,
                    is_authorized=False,
                    requires_human_confirmation=False,
                    reason=f"Acción '{action}' excluida formalmente del scope CANARY (riesgo {risk.value}).",
                )

            # Comprobar pertenencia a la allowlist CANARY
            in_scope = (
                in_canary_scope
                or (action_key in self._canary_scope)
                or (action.lower() in self._canary_scope)
            )
            if not in_scope:
                return AuthorityGateResult(
                    mode=AuthorityMode.CANARY,
                    decision=AuthorityDecision.OBSERVE_ONLY,
                    can_execute=False,
                    can_block=False,
                    risk_tier=risk,
                    action=action,
                    tool=tool,
                    is_authorized=False,
                    requires_human_confirmation=False,
                    reason=f"Acción '{action}' fuera del scope Canary autorizado. Permanece en OBSERVE_ONLY.",
                )

            # Comprobar validación de scope de parámetros (rutas temporales)
            param_ok, param_reason = validate_canary_scope(action, tool, parameters)
            if not param_ok:
                return AuthorityGateResult(
                    mode=AuthorityMode.CANARY,
                    decision=AuthorityDecision.DENY,
                    can_execute=False,
                    can_block=True,
                    risk_tier=risk,
                    action=action,
                    tool=tool,
                    is_authorized=False,
                    requires_human_confirmation=False,
                    reason=param_reason,
                )

            # Acción formalmente permitida bajo autoridad CANARY
            return AuthorityGateResult(
                mode=AuthorityMode.CANARY,
                decision=AuthorityDecision.ALLOW,
                can_execute=True,
                can_block=True,
                risk_tier=risk,
                action=action,
                tool=tool,
                is_authorized=True,
                requires_human_confirmation=False,
                reason=f"Acción '{action}' autorizada bajo gobernanza CANARY de JDE.",
            )

        # ── 3. MODO LIMITED (FASE 6: CONTROL POR CAPACIDADES) ──
        if mode == AuthorityMode.LIMITED:
            from core.jde.capabilities import get_capability_registry
            reg = get_capability_registry()
            cap = reg.find_by_action(action, tool)
            cap_risk = cap.risk_tier if cap else None
            effective_risk = ActionRiskTier.HIGH if (risk == ActionRiskTier.HIGH or cap_risk == ActionRiskTier.HIGH) else (cap_risk or risk)

            # HIGH risk queda estrictamente excluido de LIMITED
            if effective_risk == ActionRiskTier.HIGH or (cap and cap.destructive):
                if not user_confirmed:
                    return AuthorityGateResult(
                        mode=AuthorityMode.LIMITED,
                        decision=AuthorityDecision.REQUIRE_VERIFICATION,
                        can_execute=False,
                        can_block=True,
                        risk_tier=ActionRiskTier.HIGH,
                        action=action,
                        tool=tool,
                        capability_id=cap.capability_id if cap else None,
                        is_authorized=False,
                        requires_human_confirmation=True,
                        reason=f"Acción de alto riesgo '{cap.capability_id if cap else action}' requiere confirmación humana explícita.",
                    )
                return AuthorityGateResult(
                    mode=AuthorityMode.LIMITED,
                    decision=AuthorityDecision.DENY,
                    can_execute=False,
                    can_block=True,
                    risk_tier=ActionRiskTier.HIGH,
                    action=action,
                    tool=tool,
                    capability_id=cap.capability_id if cap else None,
                    is_authorized=False,
                    requires_human_confirmation=False,
                    reason=f"Acción de alto riesgo '{cap.capability_id if cap else action}' excluida formalmente de LIMITED.",
                )

            if not cap:
                if action_key in self._authorized_capabilities or action.lower() in self._authorized_capabilities:
                    return AuthorityGateResult(
                        mode=AuthorityMode.LIMITED,
                        decision=AuthorityDecision.ALLOW,
                        can_execute=True,
                        can_block=True,
                        risk_tier=risk,
                        action=action,
                        tool=tool,
                        capability_id=None,
                        is_authorized=True,
                        requires_human_confirmation=False,
                        reason=f"Acción '{action}' en allowlist explícita de LIMITED.",
                    )
                return AuthorityGateResult(
                    mode=AuthorityMode.LIMITED,
                    decision=AuthorityDecision.DENY,
                    can_execute=False,
                    can_block=True,
                    risk_tier=risk,
                    action=action,
                    tool=tool,
                    capability_id=None,
                    is_authorized=False,
                    requires_human_confirmation=False,
                    reason=f"Capacidad '{action}' no existe en CapabilityRegistry para LIMITED.",
                )

            if not cap.enabled:
                return AuthorityGateResult(
                    mode=AuthorityMode.LIMITED,
                    decision=AuthorityDecision.DENY,
                    can_execute=False,
                    can_block=True,
                    risk_tier=effective_risk,
                    action=action,
                    tool=tool,
                    capability_id=cap.capability_id,
                    is_authorized=False,
                    requires_human_confirmation=False,
                    reason=f"Capacidad '{cap.capability_id}' está deshabilitada en CapabilityRegistry.",
                )

            # Comprobar si está permitida para LIMITED
            if not cap.is_allowed_for_mode(AuthorityMode.LIMITED):
                return AuthorityGateResult(
                    mode=AuthorityMode.LIMITED,
                    decision=AuthorityDecision.DENY,
                    can_execute=False,
                    can_block=True,
                    risk_tier=effective_risk,
                    action=action,
                    tool=tool,
                    capability_id=cap.capability_id,
                    is_authorized=False,
                    requires_human_confirmation=False,
                    reason=f"Capacidad '{cap.capability_id}' no está autorizada para modo LIMITED (requiere {cap.authority_level.value}).",
                )

            # Comprobar validación de scope
            scope_ok, scope_reason = reg.validate_scope(cap, parameters)
            if not scope_ok:
                return AuthorityGateResult(
                    mode=AuthorityMode.LIMITED,
                    decision=AuthorityDecision.DENY,
                    can_execute=False,
                    can_block=True,
                    risk_tier=effective_risk,
                    action=action,
                    tool=tool,
                    capability_id=cap.capability_id,
                    is_authorized=False,
                    requires_human_confirmation=False,
                    reason=scope_reason,
                )

            # Autorizada bajo LIMITED
            return AuthorityGateResult(
                mode=AuthorityMode.LIMITED,
                decision=AuthorityDecision.ALLOW,
                can_execute=True,
                can_block=True,
                risk_tier=effective_risk,
                action=action,
                tool=tool,
                capability_id=cap.capability_id,
                is_authorized=True,
                requires_human_confirmation=False,
                reason=f"Capacidad '{cap.capability_id}' autorizada bajo gobernanza LIMITED de JDE.",
            )

        # ── 4. MODO PROGRESSIVE (FASE 7: AUTORIDAD PROGRESIVA Y CONTROL DE PROMOCIÓN) ──
        if mode == AuthorityMode.PROGRESSIVE:
            from core.jde.capabilities import get_capability_registry
            reg = get_capability_registry()
            cap = reg.find_by_action(action, tool)
            cap_risk = cap.risk_tier if cap else None
            effective_risk = ActionRiskTier.HIGH if (risk == ActionRiskTier.HIGH or cap_risk == ActionRiskTier.HIGH) else (cap_risk or risk)

            # HIGH risk queda incondicionalmente excluido de PROGRESSIVE
            if effective_risk == ActionRiskTier.HIGH or (cap and cap.destructive):
                if not user_confirmed:
                    return AuthorityGateResult(
                        mode=AuthorityMode.PROGRESSIVE,
                        decision=AuthorityDecision.REQUIRE_VERIFICATION,
                        can_execute=False,
                        can_block=True,
                        risk_tier=ActionRiskTier.HIGH,
                        action=action,
                        tool=tool,
                        capability_id=cap.capability_id if cap else None,
                        promotion_status="BLOCKED_HIGH_RISK",
                        is_authorized=False,
                        requires_human_confirmation=True,
                        reason=f"Acción de alto riesgo '{cap.capability_id if cap else action}' requiere confirmación humana explícita.",
                    )
                return AuthorityGateResult(
                    mode=AuthorityMode.PROGRESSIVE,
                    decision=AuthorityDecision.DENY,
                    can_execute=False,
                    can_block=True,
                    risk_tier=ActionRiskTier.HIGH,
                    action=action,
                    tool=tool,
                    capability_id=cap.capability_id if cap else None,
                    promotion_status="BLOCKED_HIGH_RISK",
                    is_authorized=False,
                    requires_human_confirmation=False,
                    reason=f"Acción de alto riesgo '{cap.capability_id if cap else action}' excluida formalmente de PROGRESSIVE.",
                )

            if not cap:
                if action_key in self._authorized_capabilities or action.lower() in self._authorized_capabilities:
                    return AuthorityGateResult(
                        mode=AuthorityMode.PROGRESSIVE,
                        decision=AuthorityDecision.ALLOW,
                        can_execute=True,
                        can_block=True,
                        risk_tier=risk,
                        action=action,
                        tool=tool,
                        capability_id=None,
                        promotion_status="AUTHORIZED_SCOPE",
                        is_authorized=True,
                        requires_human_confirmation=False,
                        reason=f"Acción '{action}' en allowlist explícita de PROGRESSIVE.",
                    )
                return AuthorityGateResult(
                    mode=AuthorityMode.PROGRESSIVE,
                    decision=AuthorityDecision.DENY,
                    can_execute=False,
                    can_block=True,
                    risk_tier=risk,
                    action=action,
                    tool=tool,
                    capability_id=None,
                    promotion_status=None,
                    is_authorized=False,
                    requires_human_confirmation=False,
                    reason=f"Capacidad '{action}' no existe en CapabilityRegistry para PROGRESSIVE.",
                )

            if not cap.enabled:
                return AuthorityGateResult(
                    mode=AuthorityMode.PROGRESSIVE,
                    decision=AuthorityDecision.DENY,
                    can_execute=False,
                    can_block=True,
                    risk_tier=effective_risk,
                    action=action,
                    tool=tool,
                    capability_id=cap.capability_id,
                    promotion_status="DISABLED",
                    is_authorized=False,
                    requires_human_confirmation=False,
                    reason=f"Capacidad '{cap.capability_id}' está deshabilitada en CapabilityRegistry.",
                )

            # Comprobar si está permitida para PROGRESSIVE
            if not cap.is_allowed_for_mode(AuthorityMode.PROGRESSIVE):
                return AuthorityGateResult(
                    mode=AuthorityMode.PROGRESSIVE,
                    decision=AuthorityDecision.DENY,
                    can_execute=False,
                    can_block=True,
                    risk_tier=effective_risk,
                    action=action,
                    tool=tool,
                    capability_id=cap.capability_id,
                    promotion_status="NOT_PROMOTED",
                    is_authorized=False,
                    requires_human_confirmation=False,
                    reason=f"Capacidad '{cap.capability_id}' no está autorizada para modo PROGRESSIVE (no promovida explícitamente).",
                )

            # Comprobar validación de scope
            scope_ok, scope_reason = reg.validate_scope(cap, parameters)
            if not scope_ok:
                return AuthorityGateResult(
                    mode=AuthorityMode.PROGRESSIVE,
                    decision=AuthorityDecision.DENY,
                    can_execute=False,
                    can_block=True,
                    risk_tier=effective_risk,
                    action=action,
                    tool=tool,
                    capability_id=cap.capability_id,
                    promotion_status="SCOPE_VIOLATION",
                    is_authorized=False,
                    requires_human_confirmation=False,
                    reason=scope_reason,
                )

            prom_status = "PROMOTED" if cap.promoted_to_progressive else "LIMITED_IN_PROGRESSIVE"
            reason_text = (
                f"Capacidad '{cap.capability_id}' autorizada bajo autoridad PROGRESSIVE de JDE."
                if cap.promoted_to_progressive
                else f"Capacidad '{cap.capability_id}' autorizada bajo autoridad LIMITED dentro de entorno PROGRESSIVE."
            )

            # Autorizada bajo PROGRESSIVE
            return AuthorityGateResult(
                mode=AuthorityMode.PROGRESSIVE,
                decision=AuthorityDecision.ALLOW,
                can_execute=True,
                can_block=True,
                risk_tier=effective_risk,
                action=action,
                tool=tool,
                capability_id=cap.capability_id,
                promotion_status=prom_status,
                is_authorized=True,
                requires_human_confirmation=False,
                reason=reason_text,
            )



        # ── 5. MODO FULL AUTHORITY (FASE 8: AUTORIDAD PLENA CERTIFICADA) ──
        if mode == AuthorityMode.FULL:
            from core.jde.capabilities import get_capability_registry
            reg = get_capability_registry()
            cap = reg.find_by_action(action, tool)
            cap_risk = cap.risk_tier if cap else None
            effective_risk = ActionRiskTier.HIGH if (risk == ActionRiskTier.HIGH or cap_risk == ActionRiskTier.HIGH) else (cap_risk or risk)

            # REGLA FUNDAMENTAL: JDE decide pero NO puede saltarse capas de seguridad ni confirmación humana en acciones destructivas/HIGH RISK
            if effective_risk == ActionRiskTier.HIGH or (cap and cap.destructive):
                if not user_confirmed:
                    return AuthorityGateResult(
                        mode=AuthorityMode.FULL,
                        decision=AuthorityDecision.REQUIRE_VERIFICATION,
                        can_execute=False,
                        can_block=True,
                        risk_tier=ActionRiskTier.HIGH,
                        action=action,
                        tool=tool,
                        capability_id=cap.capability_id if cap else None,
                        promotion_status="FULL_REQUIRE_CONFIRMATION",
                        is_authorized=False,
                        requires_human_confirmation=True,
                        reason=f"Acción de alto riesgo/destructiva '{cap.capability_id if cap else action}' en FULL requiere confirmación humana explícita.",
                    )

            # Si la capacidad tiene validación de scope de parámetros definida, debe respetarse
            if cap:
                scope_ok, scope_reason = reg.validate_scope(cap, parameters)
                if not scope_ok:
                    return AuthorityGateResult(
                        mode=AuthorityMode.FULL,
                        decision=AuthorityDecision.DENY,
                        can_execute=False,
                        can_block=True,
                        risk_tier=effective_risk,
                        action=action,
                        tool=tool,
                        capability_id=cap.capability_id,
                        promotion_status="FULL_SCOPE_VIOLATION",
                        is_authorized=False,
                        requires_human_confirmation=False,
                        reason=scope_reason,
                    )

            # En FULL mode, JDE posee autoridad de decisión total (ejecución y bloqueo) para todas las acciones operacionales
            return AuthorityGateResult(
                mode=AuthorityMode.FULL,
                decision=AuthorityDecision.ALLOW,
                can_execute=True,
                can_block=True,
                risk_tier=effective_risk,
                action=action,
                tool=tool,
                capability_id=cap.capability_id if cap else None,
                promotion_status="FULL_AUTHORITY",
                is_authorized=True,
                requires_human_confirmation=False,
                reason=f"Acción '{action}' plenamente autorizada bajo gobernanza FULL AUTHORITY de JDE.",
            )

        # ── 6. CAPACIDAD NO REGISTRADA ──
        if not is_registered_capability:
            return AuthorityGateResult(
                mode=mode,
                decision=AuthorityDecision.DENY,
                can_execute=False,
                can_block=self.can_block(action, tool),
                risk_tier=risk,
                action=action,
                tool=tool,
                is_authorized=False,
                requires_human_confirmation=False,
                reason=f"Capacidad '{action}' no está registrada en el catálogo oficial de JDE.",
            )

        # ── 4. POLÍTICA DE ACCIONES DE ALTO RIESGO ──
        if risk == ActionRiskTier.HIGH:
            if not user_confirmed:
                return AuthorityGateResult(
                    mode=mode,
                    decision=AuthorityDecision.REQUIRE_VERIFICATION,
                    can_execute=False,
                    can_block=self.can_block(action, tool),
                    risk_tier=risk,
                    action=action,
                    tool=tool,
                    is_authorized=False,
                    requires_human_confirmation=True,
                    reason=f"Acción de alto riesgo '{action}' requiere confirmación humana explícita.",
                )

        # ── 5. EVALUACIÓN DE AUTORIDAD SEGÚN MODO ──
        allowed_exec = self.can_execute(action, tool)
        allowed_block = self.can_block(action, tool)

        if allowed_exec:
            dec = AuthorityDecision.ALLOW
            reason = f"Acción '{action}' autorizada bajo gobernanza JDE ({mode.value})."
        else:
            dec = AuthorityDecision.DENY
            reason = f"Acción '{action}' no autorizada para ejecución en modo {mode.value}."

        return AuthorityGateResult(
            mode=mode,
            decision=dec,
            can_execute=allowed_exec,
            can_block=allowed_block,
            risk_tier=risk,
            action=action,
            tool=tool,
            is_authorized=allowed_exec,
            requires_human_confirmation=False,
            reason=reason,
        )


_GLOBAL_AUTHORITY_GATE: JDEAuthorityGate | None = None
_GATE_LOCK = threading.Lock()


def get_authority_gate() -> JDEAuthorityGate:
    """Retorna la instancia global singleton de JDEAuthorityGate.

    Por diseño seguro, resuelve el modo de forma Fail-Safe (SHADOW por defecto).
    """
    global _GLOBAL_AUTHORITY_GATE
    with _GATE_LOCK:
        if _GLOBAL_AUTHORITY_GATE is None:
            resolved_mode = JDEAuthorityGate._resolve_fail_safe_mode(None)
            _GLOBAL_AUTHORITY_GATE = JDEAuthorityGate(mode=resolved_mode)
        return _GLOBAL_AUTHORITY_GATE


def reset_authority_gate(mode: AuthorityMode | str | None = None) -> JDEAuthorityGate:
    """Reinicia la instancia global de JDEAuthorityGate (útil para pruebas)."""
    global _GLOBAL_AUTHORITY_GATE
    with _GATE_LOCK:
        resolved_mode = JDEAuthorityGate._resolve_fail_safe_mode(mode)
        _GLOBAL_AUTHORITY_GATE = JDEAuthorityGate(mode=resolved_mode)
        return _GLOBAL_AUTHORITY_GATE
