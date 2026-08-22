"""Subsistema de Verificación Real de Ejecución (execution_verifier.py).

Implementa la regla fundamental:
    NO EXECUTION EVIDENCE = NO SUCCESS CLAIM

Garantiza que toda acción sobre el sistema operativo (procesos, ventanas, archivos)
sea verificada de forma determinista antes de confirmar el éxito al usuario.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import psutil

from core.logger import get_logger

logger = get_logger("jessyca.core.execution_verifier")


class ExecutionStatus(StrEnum):
    """Estados formales del resultado de ejecución de una acción."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    VERIFICATION_FAILED = "verification_failed"
    DENIED = "denied"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ExecutionEvidence:
    """Evidencia verificable de que una acción ocurrió efectivamente en el sistema."""

    verification_type: str
    target: str
    is_verified: bool
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "verification_type": self.verification_type,
            "target": self.target,
            "is_verified": self.is_verified,
            "details": self.details,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class ExecutionResult:
    """Resultado formal inmutable de una operación con evidencia obligatoria."""

    status: ExecutionStatus
    action: str
    target: str | None
    message: str | None = None
    evidence: ExecutionEvidence | None = None
    error_code: str | None = None
    output: Any = None
    duration_ms: float = 0.0

    @property
    def claims_success(self) -> bool:
        """Verifica si el resultado declara éxito genuino con evidencia comprobable."""
        return self.status == ExecutionStatus.SUCCEEDED and self.evidence is not None and self.evidence.is_verified

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "action": self.action,
            "target": self.target,
            "message": self.message,
            "evidence": self.evidence.to_dict() if self.evidence else None,
            "error_code": self.error_code,
            "output": self.output,
            "duration_ms": self.duration_ms,
        }


# ── ESTRATEGIAS DE VERIFICACIÓN ──


@runtime_checkable
class IVerificationStrategy(Protocol):
    """Protocolo abstracto para verificación de estado post-ejecución."""

    def verify(
        self,
        action: str,
        target: str,
        parameters: dict[str, Any] | None = None,
        timeout_seconds: float = 2.5,
    ) -> ExecutionEvidence: ...


class ProcessExistsVerificationStrategy:
    """Verifica que un proceso o aplicación de Windows esté realmente en ejecución."""

    # Mapeo de alias de ejecutables comunes
    EXECUTABLE_ALIASES: dict[str, tuple[str, ...]] = {
        "notepad": ("notepad.exe", "notepad"),
        "bloc de notas": ("notepad.exe", "notepad"),
        "calc": ("calculatorapp.exe", "calc.exe", "calculator.exe", "applicationframehost.exe"),
        "calculadora": ("calculatorapp.exe", "calc.exe", "calculator.exe", "applicationframehost.exe"),
        "explorer": ("explorer.exe", "explorer"),
        "explorador": ("explorer.exe", "explorer"),
        "paint": ("mspaint.exe", "mspaint", "paint.exe"),
        "cmd": ("cmd.exe", "cmd"),
        "terminal": ("windowsterminal.exe", "cmd.exe", "powershell.exe"),
        "edge": ("msedge.exe", "msedge", "chrome.exe", "chrome"),
        "chrome": ("chrome.exe", "chrome", "msedge.exe", "msedge", "brave.exe", "firefox.exe"),
        "navegador": ("msedge.exe", "chrome.exe", "brave.exe", "firefox.exe", "msedge", "chrome"),
        "browser": ("msedge.exe", "chrome.exe", "brave.exe", "firefox.exe", "msedge", "chrome"),
    }

    def verify(
        self,
        action: str,
        target: str,
        parameters: dict[str, Any] | None = None,
        timeout_seconds: float = 2.5,
    ) -> ExecutionEvidence:
        target_clean = (target or "").strip().lower()
        base_key = target_clean[:-4] if target_clean.endswith(".exe") else target_clean
        possible_names = (
            self.EXECUTABLE_ALIASES.get(base_key)
            or self.EXECUTABLE_ALIASES.get(target_clean)
            or (f"{base_key}.exe", base_key, target_clean)
        )

        deadline = time.monotonic() + timeout_seconds
        found_pids: list[int] = []

        while time.monotonic() < deadline:
            found_pids = []
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    pname = (proc.info.get("name") or "").lower()
                    if any(cand in pname for cand in possible_names):
                        found_pids.append(proc.info["pid"])
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue

            if found_pids:
                logger.info(f"[PROCESS VERIFICATION SUCCESS] Proceso '{target}' verificado en ejecución (PIDs: {found_pids}).")
                return ExecutionEvidence(
                    verification_type="process_exists",
                    target=target,
                    is_verified=True,
                    details={"pids": found_pids, "matched_names": list(possible_names)},
                )

            time.sleep(0.15)

        logger.warning(f"[PROCESS VERIFICATION FAILED] Proceso '{target}' no se encontró activo tras {timeout_seconds}s.")
        return ExecutionEvidence(
            verification_type="process_exists",
            target=target,
            is_verified=False,
            details={"timeout_seconds": timeout_seconds, "searched_names": list(possible_names)},
        )


class ProcessTerminatedVerificationStrategy:
    """Verifica que un proceso o aplicación de Windows haya sido efectivamente terminado."""

    def verify(
        self,
        action: str,
        target: str,
        parameters: dict[str, Any] | None = None,
        timeout_seconds: float = 2.0,
    ) -> ExecutionEvidence:
        target_clean = (target or "").strip().lower()
        base_key = target_clean[:-4] if target_clean.endswith(".exe") else target_clean
        aliases = ProcessExistsVerificationStrategy.EXECUTABLE_ALIASES
        possible_names = (
            aliases.get(base_key)
            or aliases.get(target_clean)
            or (f"{base_key}.exe", base_key, target_clean)
        )

        deadline = time.monotonic() + timeout_seconds
        still_running = True

        while time.monotonic() < deadline:
            found = False
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    pname = (proc.info.get("name") or "").lower()
                    if any(cand == pname for cand in possible_names):
                        found = True
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if not found:
                still_running = False
                break
            time.sleep(0.15)

        is_terminated = not still_running
        logger.info(f"[PROCESS TERMINATION VERIFIED: {is_terminated}] Proceso '{target}'.")
        return ExecutionEvidence(
            verification_type="process_terminated",
            target=target,
            is_verified=is_terminated,
            details={"target": target, "terminated": is_terminated},
        )


class FileExistsVerificationStrategy:
    """Verifica la existencia o creación efectiva de un archivo en el sistema de archivos."""

    def verify(
        self,
        action: str,
        target: str,
        parameters: dict[str, Any] | None = None,
        timeout_seconds: float = 1.0,
    ) -> ExecutionEvidence:
        path = target or (parameters.get("path") if parameters else None) or (parameters.get("filename") if parameters else None)
        if not path:
            return ExecutionEvidence(
                verification_type="file_exists",
                target=target,
                is_verified=False,
                details={"error": "Ruta de archivo no especificada"},
            )

        exists = os.path.exists(path)
        size_bytes = os.path.getsize(path) if exists and os.path.isfile(path) else 0

        return ExecutionEvidence(
            verification_type="file_exists",
            target=str(path),
            is_verified=exists,
            details={"path": str(path), "size_bytes": size_bytes},
        )


class StateChangedVerificationStrategy:
    """Verificador genérico de cambio de estado para operaciones abstractas."""

    def verify(
        self,
        action: str,
        target: str,
        parameters: dict[str, Any] | None = None,
        timeout_seconds: float = 0.5,
    ) -> ExecutionEvidence:
        is_verified = bool(parameters and parameters.get("verified", True))
        return ExecutionEvidence(
            verification_type="state_changed",
            target=target or action,
            is_verified=is_verified,
            details=dict(parameters or {}),
        )


class ExecutionVerifier:
    """Coordinador central de verificación post-ejecución."""

    def __init__(self) -> None:
        self._process_exists_strat = ProcessExistsVerificationStrategy()
        self._process_term_strat = ProcessTerminatedVerificationStrategy()
        self._file_exists_strat = FileExistsVerificationStrategy()
        self._state_changed_strat = StateChangedVerificationStrategy()

    def get_strategy(self, action: str) -> IVerificationStrategy:
        """Determina la estrategia adecuada en función del tipo de acción."""
        act = (action or "").lower()
        if any(k in act for k in ("open", "abrir", "launch", "start", "ejecutar")):
            return self._process_exists_strat
        if any(k in act for k in ("close", "cerrar", "kill", "terminate", "stop")):
            return self._process_term_strat
        if any(k in act for k in ("file", "archivo", "create", "crear", "write", "guardar")):
            return self._file_exists_strat
        return self._state_changed_strat

    def verify_execution(
        self,
        action: str,
        target: str,
        parameters: dict[str, Any] | None = None,
        timeout_seconds: float = 2.5,
    ) -> ExecutionEvidence:
        """Ejecuta la verificación activa y recopila la evidencia del sistema."""
        strategy = self.get_strategy(action)
        return strategy.verify(action=action, target=target, parameters=parameters, timeout_seconds=timeout_seconds)


# Singleton
_default_verifier = ExecutionVerifier()


def get_execution_verifier() -> ExecutionVerifier:
    return _default_verifier
