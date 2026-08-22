"""Paquete de Productización, Instalación y Distribución de JESSYCA (core.distribution - Fase 46).

Exporta los motores de instalación, diagnóstico, configuración segregada, backup, rollback,
distribución de Skills y wizard de primer inicio.
"""

from __future__ import annotations

from core.distribution.backup_rollback import (
    BackupManager,
    RollbackManager,
)
from core.distribution.config_manager import (
    AgentConfig,
    ModelConfig,
    ProductConfigManager,
    ProductUnifiedConfig,
    SecurityConfig,
    SkillConfig,
    SystemConfig,
    UserConfig,
)
from core.distribution.distribution_models import (
    BackupManifest,
    DiagnosticReport,
    FirstRunStatus,
    FirstRunStep,
    InstallationState,
    ProductVersion,
    ReleaseChannel,
    ReleaseManifest,
    UninstallScope,
)
from core.distribution.environment_diagnostics import (
    EnvironmentDiagnosticsEngine,
)
from core.distribution.first_run_wizard import (
    FirstRunWizard,
)
from core.distribution.installer_engine import (
    WindowsInstallerEngine,
)
from core.distribution.skill_distribution import (
    SkillDistributionManager,
    SkillPackageMetadata,
    SkillVerificationResult,
)

__all__ = [
    # Modelos y Enums
    "ReleaseChannel",
    "InstallationState",
    "FirstRunStep",
    "ProductVersion",
    "ReleaseManifest",
    "DiagnosticReport",
    "BackupManifest",
    "UninstallScope",
    "FirstRunStatus",
    # Configuración Segregada
    "UserConfig",
    "SystemConfig",
    "ModelConfig",
    "SkillConfig",
    "AgentConfig",
    "SecurityConfig",
    "ProductUnifiedConfig",
    "ProductConfigManager",
    # Motores y Gestores
    "EnvironmentDiagnosticsEngine",
    "BackupManager",
    "RollbackManager",
    "SkillPackageMetadata",
    "SkillVerificationResult",
    "SkillDistributionManager",
    "WindowsInstallerEngine",
    "FirstRunWizard",
]
