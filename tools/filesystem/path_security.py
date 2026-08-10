"""Path Security Layer y Protección de Sandbox (Subetapa 06.2).

Trata todas las rutas de archivo como UNTRUSTED INPUT.
Canonicaliza y resuelve rutas absolutas reales (`os.path.realpath`) para garantizar que la ruta
resida obligatoriamente dentro del directorio sandbox autorizado (`FILESYSTEM_SANDBOX_ROOT`).
Bloquea Path Traversal (`../`, `..\`), enlaces simbólicos inseguros, junctions, UNC y paths especiales de Windows.
"""

from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

from config.settings import AppSettings
from core.audit_logger import AuditEvent, AuditEventType, get_audit_logger
from core.logger import get_logger
from tools.filesystem.errors import (
    PathSecurityError,
    PathTraversalError,
    SandboxViolationError,
    UnsafePathError,
    UnsupportedPathError,
)
from tools.filesystem.models import PathValidationResult

logger = get_logger("jessyca.tools.filesystem.path_security")


class PathSecurityManager:
    """Gestor de seguridad de rutas y frontera del sandbox para el sistema de archivos."""

    def __init__(self, sandbox_root: str | Path | None = None) -> None:
        settings = AppSettings()
        root_path = Path(sandbox_root) if sandbox_root else settings.FILESYSTEM_SANDBOX_ROOT

        # Asegurar directorio de sandbox
        root_path.mkdir(parents=True, exist_ok=True)
        self.sandbox_root: Path = root_path.resolve()
        self.canonical_sandbox_str: str = os.path.realpath(str(self.sandbox_root))
        self.audit_logger = get_audit_logger()

        logger.info(f"PathSecurityManager inicializado. Sandbox Root: '{self.canonical_sandbox_str}'")

    def validate_and_canonicalize(self, raw_path: str) -> PathValidationResult:
        """Valida, canonicaliza y verifica que una ruta resida estrictamente dentro del sandbox.

        Lanza excepciones específicas de PathSecurityError ante cualquier intento de fuga.
        """
        if not raw_path or not str(raw_path).strip():
            raise PathSecurityError("La ruta de archivo no puede estar vacía.")

        clean_raw = str(raw_path).strip()

        # 1. Detección de caracteres nulos
        if "\x00" in clean_raw:
            raise UnsupportedPathError("La ruta contiene caracteres nulos de terminación (null bytes).")

        # 2. Detección de codificaciones URL Traversal (%2e%2e)
        decoded_path = urllib.parse.unquote(clean_raw)
        if "%2e" in clean_raw.lower() or "%2f" in clean_raw.lower() or "%5c" in clean_raw.lower():
            if ".." in decoded_path:
                raise PathTraversalError(clean_raw)

        # 3. Detección de rutas UNC y de dispositivos Windows (\\server\share, \\?\C:\, \\.\)
        if clean_raw.startswith(("\\\\", "//", "\\\\?\\", "\\\\.\\")):
            raise UnsupportedPathError("Las rutas UNC, de red o de dispositivos nativos de Windows no están autorizadas.")

        # 4. Construcción de ruta absoluta respecto al sandbox si es relativa
        try:
            path_obj = Path(clean_raw)
            if not path_obj.is_absolute():
                # Ruta relativa -> anclar a sandbox_root
                target_path_str = str(self.sandbox_root / path_obj)
            else:
                target_path_str = str(path_obj)
        except Exception as e:
            raise PathSecurityError(f"Error al analizar la sintaxis de la ruta: {e}")

        # 5. Resolucin canónica realpath (resuelve symlinks, .. y accesos relativos)
        canonical_target_str = os.path.realpath(target_path_str)

        # 6. Verificación de pertenencia al Sandbox por commonpath
        try:
            common = os.path.commonpath([self.canonical_sandbox_str, canonical_target_str])
            is_inside = common == self.canonical_sandbox_str
        except ValueError:
            # Ocurre si están en diferentes letras de unidad en Windows (ej. C: vs D:)
            is_inside = False

        if not is_inside:
            logger.warning(
                f"[PATH SECURITY VIOLATION] Intento de acceso fuera del sandbox: "
                f"raw='{clean_raw}' -> realpath='{canonical_target_str}' vs sandbox='{self.canonical_sandbox_str}'"
            )
            raise SandboxViolationError(clean_raw, self.canonical_sandbox_str)

        # 7. Verificación de Symlinks / Reparse Points intermedios
        # Si un archivo existente dentro del sandbox es un symlink/junction que apunta fuera -> Denegar
        if os.path.islink(target_path_str) or os.path.islink(canonical_target_str):
            real_link_target = os.path.realpath(target_path_str)
            try:
                link_common = os.path.commonpath([self.canonical_sandbox_str, real_link_target])
                if link_common != self.canonical_sandbox_str:
                    raise UnsafePathError(clean_raw)
            except ValueError:
                raise UnsafePathError(clean_raw)

        # 8. Registrar evento de auditoría de ruta validada
        self.audit_logger.log_audit_event(
            AuditEvent(
                event_type=AuditEventType.FILESYSTEM_PATH_VALIDATED,
                tool_name="windows.files",
                operation="validate_path",
                reason="Ruta validada exitosamente dentro del sandbox.",
                metadata={
                    "raw_path": clean_raw,
                    "canonical_path": canonical_target_str,
                    "sandbox_root": self.canonical_sandbox_str,
                },
            )
        )

        return PathValidationResult(
            is_valid=True,
            raw_path=clean_raw,
            canonical_path=canonical_target_str,
            sandbox_root=self.canonical_sandbox_str,
            reason="Ruta dentro del sandbox validada exitosamente.",
        )
