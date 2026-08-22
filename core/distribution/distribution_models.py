"""Modelos de datos y contratos para Productización, Instalación y Distribución (distribution_models.py - Fase 46).

Define:
- Versiones semánticas y manifiestos de release (ReleaseManifest, ProductVersion)
- Estados del ciclo de vida de instalación (InstallationState, FirstRunStep, FirstRunStatus)
- Diagnósticos ambientales y sanitización de secretos
- Manifiestos de backup, rollback y desinstalación
- Gobernanza de distribución de Skills (Marketplace != Trust)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ReleaseChannel(StrEnum):
    """Canales de distribución de versiones."""

    STABLE = "stable"
    BETA = "beta"
    NIGHTLY = "nightly"
    DEV = "dev"


class InstallationState(StrEnum):
    """Estados del ciclo de vida del producto en el sistema anfitrión."""

    NOT_INSTALLED = "NOT_INSTALLED"
    INSTALLING = "INSTALLING"
    CONFIGURING = "CONFIGURING"
    INSTALLED = "INSTALLED"
    UPGRADING = "UPGRADING"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    UNINSTALLING = "UNINSTALLING"
    UNINSTALLED = "UNINSTALLED"
    CORRUPTED = "CORRUPTED"


class FirstRunStep(StrEnum):
    """Pasos secuenciales del wizard de primer inicio (First Run)."""

    INSTALLATION = "installation"
    CONFIGURATION = "configuration"
    ENVIRONMENT_CHECK = "environment_check"
    MODEL_CHECK = "model_check"
    MICROPHONE_CHECK = "microphone_check"
    PERMISSIONS_CHECK = "permissions_check"
    SECURITY_INITIALIZATION = "security_initialization"
    FIRST_LAUNCH = "first_launch"


@dataclass(frozen=True)
class ProductVersion:
    """Representación inmutable de una versión semántica del producto."""

    major: int
    minor: int
    patch: int
    build: int = 0
    channel: ReleaseChannel = ReleaseChannel.STABLE

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        if self.build > 0:
            base += f".{self.build}"
        if self.channel != ReleaseChannel.STABLE:
            base += f"-{self.channel}"
        return base

    def is_compatible_with(self, other: ProductVersion) -> bool:
        """Comprueba compatibilidad semántica (mismo major y versión menor o igual)."""
        if self.major != other.major:
            return False
        return (self.minor, self.patch) >= (other.minor, other.patch)


@dataclass(frozen=True)
class ReleaseManifest:
    """Manifiesto de entrega inmutable firmado para una versión distribuible."""

    product_name: str
    version: ProductVersion
    release_date: str
    changelog: tuple[str, ...]
    binary_sha256: str
    min_windows_build: int = 19041      # Windows 10 2004+
    min_python_version: str = "3.11.0"
    required_ollama_version: str = "0.3.0"
    supported_models: tuple[str, ...] = ("qwen2.5-coder:7b", "llama3.2:3b")
    compatibility_matrix: dict[str, str] = field(default_factory=dict)
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_name": self.product_name,
            "version": str(self.version),
            "release_date": self.release_date,
            "changelog": list(self.changelog),
            "binary_sha256": self.binary_sha256,
            "min_windows_build": self.min_windows_build,
            "min_python_version": self.min_python_version,
            "required_ollama_version": self.required_ollama_version,
            "supported_models": list(self.supported_models),
            "compatibility_matrix": dict(self.compatibility_matrix),
            "signature": self.signature,
        }


@dataclass
class DiagnosticReport:
    """Reporte estructurado y sanitizado de diagnóstico del entorno."""

    report_id: str = field(default_factory=lambda: f"diag-{uuid.uuid4().hex[:8]}")
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    windows_version: str = ""
    windows_build: int = 0
    python_version: str = ""
    gpu_name: str = ""
    vram_total_mb: float = 0.0
    vram_available_mb: float = 0.0
    ollama_running: bool = False
    ollama_models: list[str] = field(default_factory=list)
    microphone_available: bool = False
    speakers_available: bool = False
    browser_detected: str = ""
    missing_dependencies: list[str] = field(default_factory=list)
    skills_installed_count: int = 0
    security_status: str = "HEALTHY"
    logs_tail: list[str] = field(default_factory=list)
    is_sanitized: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "timestamp": self.timestamp.isoformat(),
            "windows_version": self.windows_version,
            "windows_build": self.windows_build,
            "python_version": self.python_version,
            "gpu": {
                "name": self.gpu_name,
                "vram_total_mb": self.vram_total_mb,
                "vram_available_mb": self.vram_available_mb,
            },
            "ollama": {
                "running": self.ollama_running,
                "models": self.ollama_models,
            },
            "audio": {
                "microphone": self.microphone_available,
                "speakers": self.speakers_available,
            },
            "browser": self.browser_detected,
            "missing_dependencies": self.missing_dependencies,
            "skills_count": self.skills_installed_count,
            "security_status": self.security_status,
            "logs_tail": self.logs_tail,
            "is_sanitized": self.is_sanitized,
        }


@dataclass
class BackupManifest:
    """Manifiesto de respaldo de configuración, memoria y metadatos."""

    backup_id: str = field(default_factory=lambda: f"bck-{uuid.uuid4().hex[:8]}")
    product_version: str = ""
    created_at: float = field(default_factory=time.time)
    includes_configs: bool = True
    includes_memory: bool = True
    includes_user_preferences: bool = True
    includes_skills_metadata: bool = True
    backup_path: str = ""
    content_hash: str = ""
    files_count: int = 0
    secrets_excluded: bool = True

    def verify_integrity(self, computed_hash: str) -> bool:
        """Verifica que el hash del contenido coincida con el manifiesto."""
        return self.content_hash == computed_hash


@dataclass
class UninstallScope:
    """Alcance explícito y transparente de desinstalación."""

    remove_application_binaries: bool = True
    remove_system_services: bool = True
    remove_shortcuts: bool = True
    preserve_user_data: bool = True
    remove_memory_databases: bool = False
    remove_configuration_files: bool = False
    remove_logs: bool = False

    def describe_actions(self) -> list[str]:
        """Describe en lenguaje natural qué componentes serán eliminados."""
        actions = []
        if self.remove_application_binaries:
            actions.append("Eliminar archivos binarios y librerías de JESSYCA")
        if self.remove_shortcuts:
            actions.append("Eliminar accesos directos del escritorio y Menú Inicio")
        if self.remove_system_services:
            actions.append("Desregistrar tareas programadas y servicios en segundo plano")
        if self.remove_configuration_files:
            actions.append("Eliminar configuraciones personalizadas del usuario")
        if self.remove_memory_databases:
            actions.append("Eliminar base de datos vectorial y memoria episódica")
        if self.remove_logs:
            actions.append("Eliminar archivos de log y trazas de auditoría")
        if self.preserve_user_data and not self.remove_memory_databases:
            actions.append("CONSERVAR documentos, memoria y preferencias del usuario")
        return actions


@dataclass
class FirstRunStatus:
    """Resultado estructurado de la ejecución del wizard de primer inicio."""

    completed_steps: list[FirstRunStep] = field(default_factory=list)
    current_step: FirstRunStep = FirstRunStep.INSTALLATION
    is_success: bool = False
    environment_ok: bool = False
    models_ready: bool = False
    audio_ready: bool = False
    security_ready: bool = False
    errors: list[str] = field(default_factory=list)
    first_launch_ready: bool = False
