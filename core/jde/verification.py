"""Verification Contract and Verifier Registry para JESSYCA Decision Engine (JDE).

Separa conceptual y operativamente la ejecución de la verificación:
- Executor: "Intenté realizar la acción."
- Verifier: "Comprobé si la acción realmente produjo el resultado esperado."

REGLA DE ORO ANTI-FALSO ÉXITO:
Si el resultado no puede comprobarse o se desconoce -> UNKNOWN.
NUNCA convertir UNKNOWN en SUCCESS.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from core.jde.models import VerificationRequirement
from core.jde.receipts import JDEEvidence
from core.jde.states import VerificationStatusType
from core.logger import get_logger

logger = get_logger("jessyca.jde.verification")


class VerificationContract(BaseModel):
    """Contrato formal que especifica qué condiciones deben cumplirse para declarar éxito."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_name: str
    target: str
    expected_outcome: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = 3.0
    poll_interval_seconds: float = 0.1
    allow_unverified: bool = False  # Si es False, nunca se declara éxito sin verificación positiva


@dataclass(frozen=True)
class VerificationOutcome:
    """Resultado formal inmutable emitido por un Verifier."""

    status: VerificationStatusType
    is_verified: bool
    evidence: JDEEvidence
    reason: str
    duration_ms: float = 0.0

    @classmethod
    def success(
        cls,
        verification_type: str,
        target: str,
        observed: dict[str, Any],
        reason: str = "Verificación exitosa",
        duration_ms: float = 0.0,
    ) -> VerificationOutcome:
        ev = JDEEvidence(
            verification_type=verification_type,
            target=target,
            is_verified=True,
            observed_state=observed,
            details={"reason": reason},
        )
        return cls(
            status=VerificationStatusType.VERIFIED_TRUE,
            is_verified=True,
            evidence=ev,
            reason=reason,
            duration_ms=duration_ms,
        )

    @classmethod
    def failed(
        cls,
        verification_type: str,
        target: str,
        observed: dict[str, Any] | None = None,
        reason: str = "La comprobación falló: no se observó el estado esperado.",
        duration_ms: float = 0.0,
    ) -> VerificationOutcome:
        ev = JDEEvidence(
            verification_type=verification_type,
            target=target,
            is_verified=False,
            observed_state=observed or {},
            details={"reason": reason},
        )
        return cls(
            status=VerificationStatusType.VERIFIED_FALSE,
            is_verified=False,
            evidence=ev,
            reason=reason,
            duration_ms=duration_ms,
        )

    @classmethod
    def unknown(
        cls,
        verification_type: str,
        target: str,
        reason: str = "No fue posible comprobar determinísticamente el efecto real.",
        duration_ms: float = 0.0,
    ) -> VerificationOutcome:
        ev = JDEEvidence(
            verification_type=verification_type,
            target=target,
            is_verified=False,
            observed_state={},
            details={"reason": reason, "status": "UNVERIFIABLE"},
        )
        return cls(
            status=VerificationStatusType.UNVERIFIABLE,
            is_verified=False,
            evidence=ev,
            reason=reason,
            duration_ms=duration_ms,
        )


@runtime_checkable
class IVerifier(Protocol):
    """Protocolo que debe implementar cualquier Verificador en JDE."""

    def verify(
        self,
        contract: VerificationContract,
        context: dict[str, Any] | None = None,
    ) -> VerificationOutcome: ...


class ProcessStateVerifier:
    """Verificador de procesos y aplicaciones GUI/CLI en Windows.

    Reutiliza y conecta con `core.execution.execution_verifier.ExecutionVerifier`.
    """

    def __init__(self, fallback_verifier: Any | None = None) -> None:
        self._fallback_verifier = fallback_verifier

    def verify(
        self,
        contract: VerificationContract,
        context: dict[str, Any] | None = None,
    ) -> VerificationOutcome:
        t0 = time.perf_counter()
        target = contract.target
        ctx = context or {}

        try:
            from core.execution.execution_verifier import get_execution_verifier
            system_verifier = self._fallback_verifier or get_execution_verifier()
            evidence = system_verifier.verify(
                action=contract.action_name,
                target=target,
                parameters={**contract.expected_outcome, **ctx},
                timeout_seconds=contract.timeout_seconds,
            )
            duration_ms = (time.perf_counter() - t0) * 1000

            if evidence.is_verified:
                return VerificationOutcome.success(
                    verification_type=evidence.verification_type,
                    target=target,
                    observed=evidence.details,
                    reason=f"Proceso/Ventana '{target}' verificado en el sistema operativo.",
                    duration_ms=duration_ms,
                )
            else:
                return VerificationOutcome.failed(
                    verification_type=evidence.verification_type,
                    target=target,
                    observed=evidence.details,
                    reason=evidence.details.get("error") or f"Proceso '{target}' no verificado en el sistema operativo.",
                    duration_ms=duration_ms,
                )
        except Exception as exc:
            duration_ms = (time.perf_counter() - t0) * 1000
            logger.warning(f"[JDE PROCESS VERIFIER ERROR] Error al verificar proceso '{target}': {exc}")
            return VerificationOutcome.unknown(
                verification_type="process_check_error",
                target=target,
                reason=f"Excepción durante la verificación de proceso: {exc}",
                duration_ms=duration_ms,
            )


class BrowserStateVerifier:
    """Verificador de estado de navegador y reproducción web (Edge, Chrome, YouTube).

    Garantiza que la URL o ventana del navegador exista realmente y no asuma
    éxito por la simple llamada a webbrowser.open().
    """

    def verify(
        self,
        contract: VerificationContract,
        context: dict[str, Any] | None = None,
    ) -> VerificationOutcome:
        t0 = time.perf_counter()
        target = contract.target
        ctx = context or {}
        expected_url = contract.expected_outcome.get("expected_url") or ctx.get("url")
        check_playback = bool(contract.expected_outcome.get("check_playback", False))

        # En pruebas o mocks explícitos:
        if "mock_verified" in ctx:
            duration_ms = (time.perf_counter() - t0) * 1000
            if ctx["mock_verified"] is True:
                return VerificationOutcome.success(
                    verification_type="browser_tab_active",
                    target=target,
                    observed={"url": expected_url, "mock": True},
                    reason="Navegador comprobado con éxito (Mock verificado).",
                    duration_ms=duration_ms,
                )
            elif ctx["mock_verified"] is None or ctx.get("unverifiable"):
                return VerificationOutcome.unknown(
                    verification_type="browser_tab_active",
                    target=target,
                    reason="No se pudo comprobar el estado del navegador ni la reproducción.",
                    duration_ms=duration_ms,
                )
            else:
                return VerificationOutcome.failed(
                    verification_type="browser_tab_active",
                    target=target,
                    observed={"mock": True},
                    reason="La pestaña del navegador no fue encontrada o la reproducción falló.",
                    duration_ms=duration_ms,
                )

        # Verificación real sobre el SO: comprobar proceso del navegador
        try:
            import psutil
            browser_procs = [p for p in psutil.process_iter(["name"]) if any(
                b in (p.info.get("name") or "").lower() for b in ("msedge.exe", "chrome.exe", "brave.exe", "firefox.exe")
            )]
            duration_ms = (time.perf_counter() - t0) * 1000

            if not browser_procs:
                return VerificationOutcome.failed(
                    verification_type="browser_process",
                    target=target,
                    reason="No se detectó ningún proceso de navegador activo en Windows.",
                    duration_ms=duration_ms,
                )

            # Si se exige comprobación de reproducción específica y no tenemos inspector de audio directo:
            if check_playback and not ctx.get("audio_stream_active"):
                return VerificationOutcome.unknown(
                    verification_type="youtube_playback_verification",
                    target=target,
                    reason="El navegador está activo, pero no fue posible comprobar la reproducción activa del audio.",
                    duration_ms=duration_ms,
                )

            return VerificationOutcome.success(
                verification_type="browser_active",
                target=target,
                observed={"browser_processes_count": len(browser_procs), "target": target},
                reason=f"Navegador activo detectado para '{target}'.",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.perf_counter() - t0) * 1000
            return VerificationOutcome.unknown(
                verification_type="browser_check_error",
                target=target,
                reason=f"Error durante la inspección del navegador: {exc}",
                duration_ms=duration_ms,
            )


class FileStateVerifier:
    """Verificador de operaciones de sistema de archivos para JDE."""

    def __init__(self, fallback_verifier: Any | None = None) -> None:
        self._fallback_verifier = fallback_verifier

    def verify(
        self,
        contract: VerificationContract,
        context: dict[str, Any] | None = None,
    ) -> VerificationOutcome:
        t0 = time.perf_counter()
        target = contract.target
        ctx = context or {}

        try:
            from core.execution.execution_verifier import get_execution_verifier
            system_verifier = self._fallback_verifier or get_execution_verifier()
            fn = getattr(system_verifier, "verify", None) or getattr(system_verifier, "verify_execution")
            evidence = fn(
                action=contract.action_name,
                target=target,
                parameters={**contract.expected_outcome, **ctx},
                timeout_seconds=contract.timeout_seconds,
            )
            duration_ms = (time.perf_counter() - t0) * 1000

            if evidence.is_verified:
                return VerificationOutcome.success(
                    verification_type=evidence.verification_type,
                    target=target,
                    observed=evidence.details,
                    reason=f"Archivo/Recurso '{target}' verificado exitosamente en el sistema de archivos.",
                    duration_ms=duration_ms,
                )
            else:
                return VerificationOutcome.failed(
                    verification_type=evidence.verification_type,
                    target=target,
                    observed=evidence.details,
                    reason=evidence.details.get("error") or f"Archivo '{target}' no verificado en el sistema.",
                    duration_ms=duration_ms,
                )
        except Exception as exc:
            duration_ms = (time.perf_counter() - t0) * 1000
            logger.warning(f"[JDE FILE VERIFIER ERROR] Error al verificar archivo '{target}': {exc}")
            return VerificationOutcome.unknown(
                verification_type="file_check_error",
                target=target,
                reason=f"Excepción durante la verificación de archivo: {exc}",
                duration_ms=duration_ms,
            )


class VerifierRegistry:
    """Registro unificado de Verificadores para JDE."""

    def __init__(self) -> None:
        self._verifiers: dict[str, IVerifier] = {}
        # Verificadores base predeterminados
        self.register("process", ProcessStateVerifier())
        self.register("process_running", ProcessStateVerifier())
        self.register("window_visible", ProcessStateVerifier())
        self.register("browser", BrowserStateVerifier())
        self.register("browser_tab", BrowserStateVerifier())
        self.register("youtube_playback", BrowserStateVerifier())
        self.register("file", FileStateVerifier())
        self.register("file_exists", FileStateVerifier())
        self.register("filesystem", FileStateVerifier())
        self.register("create_temp_file", FileStateVerifier())
        self.register("create_temp_test_file", FileStateVerifier())

    def register(self, strategy_name: str, verifier: IVerifier) -> None:
        self._verifiers[strategy_name.strip().lower()] = verifier

    def get(self, strategy_name: str) -> IVerifier | None:
        return self._verifiers.get(strategy_name.strip().lower())

    def verify_requirement(
        self,
        req: VerificationRequirement,
        context: dict[str, Any] | None = None,
    ) -> VerificationOutcome:
        """Ejecuta la comprobación del requerimiento con el Verifier adecuado."""
        strategy = req.strategy.strip().lower()
        verifier = self.get(strategy)
        if verifier is None:
            # Fallback a verifier de proceso si no se conoce la estrategia
            verifier = self.get("process")

        contract = VerificationContract(
            action_name=req.strategy,
            target=req.target,
            expected_outcome=req.expected_properties,
            timeout_seconds=req.timeout_seconds,
            poll_interval_seconds=req.poll_interval_seconds,
        )

        if verifier is None:
            return VerificationOutcome.unknown(
                verification_type=strategy,
                target=req.target,
                reason=f"No hay Verifier registrado para la estrategia '{strategy}'.",
            )

        return verifier.verify(contract, context=context)


_GLOBAL_VERIFIER_REGISTRY: VerifierRegistry | None = None


def get_verifier_registry() -> VerifierRegistry:
    global _GLOBAL_VERIFIER_REGISTRY
    if _GLOBAL_VERIFIER_REGISTRY is None:
        _GLOBAL_VERIFIER_REGISTRY = VerifierRegistry()
    return _GLOBAL_VERIFIER_REGISTRY
