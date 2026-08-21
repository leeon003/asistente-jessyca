"""Módulo y Framework de Habilidades (Skills) de JESSYCA 3.0 (Fases 28.0 - 32.0).

Proporciona el Skill Framework completo junto con el Catálogo Oficial de Skills y el
Subsistema Seguro de Empaquetado, Instalación, Validación Transaccional y Desinstalación (Fase 32):
- Windows: windows.apps, windows.screenshot, windows.clipboard, windows.notifications, windows.audio, windows.display
- Files: files.search, files.read, files.create, files.copy, files.move, files.rename, files.organize
- Browser: browser.open, browser.search, browser.navigate, browser.read, browser.download
- Documents: documents.read, documents.create, documents.summarize, documents.convert
- Installer & Security: SkillPackage, SkillIntegrityVerifier, SkillSignatureVerifier, SkillCompatibilityChecker,
  SkillDependencyValidator, SkillSecurityAnalyzer, SkillPermissionReviewer, IsolatedSkillLoader, SkillInstaller.
"""

from __future__ import annotations

from skills.apps import AbrirAplicacion, CerrarAplicacion
from skills.apps_skill import WindowsAppsSkill
from skills.archivos import BuscarArchivo
from skills.base_skill import BaseSkill
from skills.browser_search_skill import BrowserSearchSkill
from skills.browser_skills import (
    BrowserDownloadSkill,
    BrowserNavigateSkill,
    BrowserOpenSkill,
    BrowserReadSkill,
)
from skills.documents_skills import (
    DocumentsConvertSkill,
    DocumentsCreateSkill,
    DocumentsReadSkill,
    DocumentsSummarizeSkill,
)
from skills.file_search_skill import FilesSearchSkill
from skills.files_skills import (
    FilesCopySkill,
    FilesCreateSkill,
    FilesMoveSkill,
    FilesOrganizeSkill,
    FilesReadSkill,
    FilesRenameSkill,
)
from skills.isolated_loader import (
    IsolatedSkillLoader,
    SkillLoaderError,
)
from skills.screenshot_skill import WindowsScreenshotSkill
from skills.skill_compatibility import (
    CompatibilityCheckResult,
    SkillCompatibilityChecker,
)
from skills.skill_dependency import (
    DependencyValidationResult,
    SkillDependencyValidator,
)
from skills.skill_installer import (
    InstallationResult,
    SkillInstallationError,
    SkillInstaller,
    TransactionState,
    UninstallResult,
)
from skills.skill_integrity import (
    IntegrityVerificationResult,
    SkillIntegrityVerifier,
)
from skills.skill_manager import (
    SkillManager,
    get_skill_manager,
)
from skills.skill_models import (
    ALLOWED_SKILL_CAPABILITIES,
    SkillCapability,
    SkillContext,
    SkillDefinition,
    SkillManifest,
    SkillPermission,
    SkillResult,
    SkillStatus,
)
from skills.skill_package import (
    PackageFormat,
    SkillPackage,
    SkillPackageError,
    SkillPackageMetadata,
    SkillPackageSecurityError,
)
from skills.skill_permission_reviewer import (
    SkillPermissionReview,
    SkillPermissionReviewer,
)
from skills.skill_registry import (
    SkillRegistry,
    get_skill_registry,
)
from skills.skill_router import (
    SkillRouteDecision,
    SkillRouter,
    get_skill_router,
)
from skills.skill_runtime import (
    SkillRuntime,
)
from skills.skill_sandbox import (
    SkillRecursionLimitError,
    SkillSandboxExecutionResult,
    SkillSandboxSecurityError,
    SkillSecuritySandbox,
    SkillSecurityViolationError,
    SkillUndeclaredToolError,
    UntrustedDataWrapper,
)
from skills.skill_security_analyzer import (
    SecurityAnalysisResult,
    SkillSecurityAnalyzer,
)
from skills.skill_signature import (
    SignatureStatus,
    SignatureVerificationResult,
    SkillSignatureVerifier,
)
from skills.skill_validator import (
    SkillValidationError,
    SkillValidator,
)
from skills.windows_skills import (
    WindowsAudioSkill,
    WindowsClipboardSkill,
    WindowsDisplaySkill,
    WindowsNotificationsSkill,
)

# Catálogo Oficial de Skills de Producción registradas en el sistema
SKILLS_DISPONIBLES: dict[str, BaseSkill] = {
    # ── 1. GRUPO WINDOWS ──
    "windows.apps": WindowsAppsSkill(),
    "windows.screenshot": WindowsScreenshotSkill(),
    "windows.clipboard": WindowsClipboardSkill(),
    "windows.notifications": WindowsNotificationsSkill(),
    "windows.audio": WindowsAudioSkill(),
    "windows.display": WindowsDisplaySkill(),
    # ── 2. GRUPO FILES ──
    "files.search": FilesSearchSkill(),
    "files.read": FilesReadSkill(),
    "files.create": FilesCreateSkill(),
    "files.copy": FilesCopySkill(),
    "files.move": FilesMoveSkill(),
    "files.rename": FilesRenameSkill(),
    "files.organize": FilesOrganizeSkill(),
    # ── 3. GRUPO BROWSER ──
    "browser.open": BrowserOpenSkill(),
    "browser.search": BrowserSearchSkill(),
    "browser.navigate": BrowserNavigateSkill(),
    "browser.read": BrowserReadSkill(),
    "browser.download": BrowserDownloadSkill(),
    # ── 4. GRUPO DOCUMENTS ──
    "documents.read": DocumentsReadSkill(),
    "documents.create": DocumentsCreateSkill(),
    "documents.summarize": DocumentsSummarizeSkill(),
    "documents.convert": DocumentsConvertSkill(),
    # ── LEGACY ALIASES ──
    "abrir_aplicacion": AbrirAplicacion(),
    "cerrar_aplicacion": CerrarAplicacion(),
    "buscar_archivo": BuscarArchivo(),
}

# Auto-registro en el SkillRegistry global
_default_registry = get_skill_registry()
for _name, _skill_inst in SKILLS_DISPONIBLES.items():
    _default_registry.register_skill(_skill_inst)

__all__ = [
    # Legacy & Implementaciones Base
    "BaseSkill",
    "AbrirAplicacion",
    "CerrarAplicacion",
    "BuscarArchivo",
    "SKILLS_DISPONIBLES",
    # Grupo Windows
    "WindowsAppsSkill",
    "WindowsScreenshotSkill",
    "WindowsClipboardSkill",
    "WindowsNotificationsSkill",
    "WindowsAudioSkill",
    "WindowsDisplaySkill",
    # Grupo Files
    "FilesSearchSkill",
    "FilesReadSkill",
    "FilesCreateSkill",
    "FilesCopySkill",
    "FilesMoveSkill",
    "FilesRenameSkill",
    "FilesOrganizeSkill",
    # Grupo Browser
    "BrowserOpenSkill",
    "BrowserSearchSkill",
    "BrowserNavigateSkill",
    "BrowserReadSkill",
    "BrowserDownloadSkill",
    # Grupo Documents
    "DocumentsReadSkill",
    "DocumentsCreateSkill",
    "DocumentsSummarizeSkill",
    "DocumentsConvertSkill",
    # Skill Framework 2.0
    "SkillStatus",
    "SkillCapability",
    "ALLOWED_SKILL_CAPABILITIES",
    "SkillPermission",
    "SkillManifest",
    "SkillDefinition",
    "SkillContext",
    "SkillResult",
    "SkillValidator",
    "SkillValidationError",
    "SkillRegistry",
    "get_skill_registry",
    "SkillRouter",
    "SkillRouteDecision",
    "get_skill_router",
    "SkillRuntime",
    "SkillManager",
    "get_skill_manager",
    "SkillSecuritySandbox",
    "SkillSandboxExecutionResult",
    "UntrustedDataWrapper",
    "SkillSandboxSecurityError",
    "SkillUndeclaredToolError",
    "SkillRecursionLimitError",
    "SkillSecurityViolationError",
    # Skill Installer & Packaging (Fase 32)
    "PackageFormat",
    "SkillPackage",
    "SkillPackageMetadata",
    "SkillPackageError",
    "SkillPackageSecurityError",
    "IntegrityVerificationResult",
    "SkillIntegrityVerifier",
    "SignatureStatus",
    "SignatureVerificationResult",
    "SkillSignatureVerifier",
    "CompatibilityCheckResult",
    "SkillCompatibilityChecker",
    "DependencyValidationResult",
    "SkillDependencyValidator",
    "SecurityAnalysisResult",
    "SkillSecurityAnalyzer",
    "SkillPermissionReview",
    "SkillPermissionReviewer",
    "IsolatedSkillLoader",
    "SkillLoaderError",
    "TransactionState",
    "InstallationResult",
    "UninstallResult",
    "SkillInstaller",
    "SkillInstallationError",
]
