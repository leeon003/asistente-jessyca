"""Entorno Aislado Sandbox para Experimentación de Automejora (sandbox.py - Fase 60).

Proporciona un espacio seguro y aislado para:
1. Probar cambios y mejoras sin afectar el espacio de trabajo en producción.
2. Hacer cumplir de forma estricta la ZONA INMUTABLE DE SEGURIDAD.
3. Limitar tamaño y cantidad de archivos modificables.
4. Impedir acceso y modificación de secretos, credenciales o permisos.
5. Registrar un rastro de auditoría completo de cada acción en el sandbox.
"""

from __future__ import annotations

import re
import threading
from datetime import UTC, datetime
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.learning.sandbox")

# ZONA INMUTABLE DE SEGURIDAD: Componentes y rutas estrictamente protegidas
SECURITY_IMMUTABLE_ZONE: frozenset[str] = frozenset({
    "core/security",
    "security_policy",
    "permission_manager",
    "risk_engine",
    "confirmation_manager",
    "audit_logger",
    "execution_boundary",
    "authentication",
    "credential_handling",
    "secret_storage",
    "secret_management",
    "emergency_stop",
    "mcp_security",
    "sandbox_boundaries",
})


def is_in_immutable_security_zone(file_path_or_component: str) -> bool:
    """Verifica si una ruta o componente pertenece a la Zona Inmutable de Seguridad."""
    norm = file_path_or_component.lower().replace("\\", "/").strip()

    for protected in SECURITY_IMMUTABLE_ZONE:
        if protected in norm:
            return True

    tokens = set(re.split(r"[\./_\-\s]+", norm))
    return bool(tokens & SECURITY_IMMUTABLE_ZONE)


class SandboxSecurityError(Exception):
    """Excepción lanzada cuando una operación en sandbox intenta violar la Zona Inmutable de Seguridad."""


# Alias para compatibilidad
SandboxSecurityViolation = SandboxSecurityError


class SandboxEnvironment:
    """Entorno aislado de trabajo para experimentación sobre versiones candidatas."""

    def __init__(
        self,
        sandbox_id: str,
        max_files: int = 10,
        max_file_size_bytes: int = 500_000,
    ) -> None:
        self.sandbox_id = sandbox_id
        self.max_files = max_files
        self.max_file_size_bytes = max_file_size_bytes
        self._lock = threading.RLock()
        self._staged_files: dict[str, str] = {}
        self._audit_log: list[dict[str, Any]] = []

    def _record_audit(self, action: str, details: dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "sandbox_id": self.sandbox_id,
            "action": action,
            "details": details,
        }
        self._audit_log.append(entry)

    def stage_file(self, file_path: str, content: str) -> None:
        """Añade o modifica un archivo en el entorno aislado del sandbox."""
        with self._lock:
            # 1. VERIFICACIÓN INMUTABLE DE SEGURIDAD
            if is_in_immutable_security_zone(file_path):
                msg = (
                    f"CRITICAL SECURITY VIOLATION: El Sandbox rechaza cualquier modificación "
                    f"sobre la Zona Inmutable de Seguridad ('{file_path}')."
                )
                self._record_audit("SECURITY_VIOLATION_BLOCKED", {"file_path": file_path, "reason": msg})
                logger.critical(f"[SANDBOX SECURITY] {msg}")
                raise SandboxSecurityError(msg)

            # 2. Límite de cantidad de archivos
            if len(self._staged_files) >= self.max_files and file_path not in self._staged_files:
                raise ValueError(f"Límite de archivos en sandbox excedido (máximo {self.max_files}).")

            # 3. Límite de tamaño de contenido
            content_bytes = len(content.encode("utf-8"))
            if content_bytes > self.max_file_size_bytes:
                raise ValueError(
                    f"Tamaño de archivo excedido en sandbox: {content_bytes} bytes "
                    f"(máximo {self.max_file_size_bytes} bytes)."
                )

            # Registrar en sandbox
            self._staged_files[file_path] = content
            self._record_audit("STAGE_FILE", {"file_path": file_path, "bytes": content_bytes})
            logger.info(f"[SANDBOX] Archivo '{file_path}' preparado en sandbox {self.sandbox_id}.")

    def get_staged_content(self, file_path: str) -> str | None:
        with self._lock:
            return self._staged_files.get(file_path)

    def list_staged_files(self) -> list[str]:
        with self._lock:
            return sorted(self._staged_files.keys())

    def get_audit_log(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._audit_log)

    def run_isolated_tests(self, required_tests: list[str]) -> tuple[bool, int, list[str]]:
        """Simula la ejecución de pruebas requeridas sobre los cambios preparados en el sandbox."""
        with self._lock:
            if not required_tests:
                self._record_audit("TESTS_FAILED", {"reason": "No se definieron pruebas requeridas."})
                return (False, 0, ["Falta de especificación de pruebas unitarias o de integración obligatorias."])

            # Verificar que ningún archivo preparado toque zonas no autorizadas
            for f in self._staged_files:
                if is_in_immutable_security_zone(f):
                    reg = [f"Intento de modificación no autorizada detectado en {f}"]
                    self._record_audit("TESTS_FAILED", {"regressions": reg})
                    return (False, len(required_tests), reg)

            tests_run = len(required_tests)
            self._record_audit("TESTS_PASSED", {"tests_run": tests_run})
            return (True, tests_run, [])

    def clean(self) -> None:
        """Limpia el entorno del sandbox."""
        with self._lock:
            self._staged_files.clear()
            self._record_audit("CLEANUP", {})
