"""Módulo y Framework de Habilidades (Skills) de JESSYCA 3.0 (Fases 28.0 - 35.0).

Proporciona el Skill Framework completo junto con el Catálogo Oficial de Skills, el
Subsistema Seguro de Empaquetado, Instalación, Validación Transaccional y Desinstalación (Fase 32),
el Subsistema Formal de Versionado Semántico, Compatibilidad Técnica y Rollback Determinista (Fase 33),
el Subsistema de Marketplace / Repositorio Confiable de Skills con Trust Model y Caché Segura (Fase 34),
y el Motor de Composición de Skills (Skill Composition Engine) con soporte Secuencial, Paralelo y Condicional (Fase 35).
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
from skills.skill_composer import (
    ComposedSkill,
    SkillComposer,
)
from skills.skill_composition_dataflow import (
    DataFlowResolutionError,
    SkillConditionEvaluator,
    SkillDataFlowResolver,
)
from skills.skill_composition_executor import (
    SkillCompositionExecutionError,
    SkillCompositionExecutor,
)
from skills.skill_composition_models import (
    CompositionErrorPolicy,
    CompositionExecutionMode,
    CompositionStatus,
    SkillComposition,
    SkillCompositionContext,
    SkillCompositionResult,
    SkillCompositionStep,
    SkillCompositionStepResult,
)
from skills.skill_composition_validator import (
    CompositionValidationError,
    SkillCompositionValidator,
)
from skills.skill_dependency import (
    DependencyValidationResult,
    SkillDependencyValidator,
)
from skills.skill_diff import (
    SkillChangeReport,
    SkillDiffer,
)
from skills.skill_graph import SkillGraph
from skills.skill_graph_builder import SkillGraphBuilder
from skills.skill_graph_executor import SkillGraphExecutor
from skills.skill_graph_models import (
    GraphCacheEntry,
    SkillGraphContext,
    SkillGraphEdge,
    SkillGraphEdgeType,
    SkillGraphNode,
    SkillGraphNodeStatus,
    SkillGraphNodeType,
    SkillGraphResult,
    SkillGraphStatus,
)
from skills.skill_graph_planner import (
    SkillGraphOptimizer,
    SkillGraphPlanner,
)
from skills.skill_graph_validator import SkillGraphValidator
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
from skills.skill_marketplace import (
    SkillMarketplaceError,
    SkillMarketplaceService,
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
from skills.skill_repository import (
    BaseSkillRepository,
    CachingSkillRepository,
    CorruptedDownloadError,
    LocalDirectorySkillRepository,
    MockNetworkSkillRepository,
    PackageNotFoundError,
    RepositoryError,
    RepositoryTimeoutError,
    RepositoryUnavailableError,
)
from skills.skill_repository_models import (
    RepositorySkillEntry,
    SignatureTrustStatus,
    SkillReport,
    SkillReportType,
    SkillReputation,
    TrustStatus,
    redact_sensitive_data,
)
from skills.skill_revocation import (
    SkillRevocationRegistry,
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
from skills.skill_updater import (
    RollbackResult,
    SkillUpdateError,
    SkillUpdater,
    UpdateResult,
)
from skills.skill_validator import (
    SkillValidationError,
    SkillValidator,
)
from skills.skill_version import (
    SemVer,
    SemVerConstraint,
    SkillLifecycleState,
    VersionBumpType,
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
    # Skill Versioning & Rollback (Fase 33)
    "SemVer",
    "SemVerConstraint",
    "VersionBumpType",
    "SkillLifecycleState",
    "SkillChangeReport",
    "SkillDiffer",
    "SkillUpdater",
    "UpdateResult",
    "RollbackResult",
    "SkillUpdateError",
    # Skill Marketplace & Repository (Fase 34)
    "TrustStatus",
    "SignatureTrustStatus",
    "SkillReputation",
    "RepositorySkillEntry",
    "SkillReportType",
    "SkillReport",
    "redact_sensitive_data",
    "BaseSkillRepository",
    "LocalDirectorySkillRepository",
    "MockNetworkSkillRepository",
    "CachingSkillRepository",
    "RepositoryError",
    "RepositoryUnavailableError",
    "RepositoryTimeoutError",
    "PackageNotFoundError",
    "CorruptedDownloadError",
    "SkillRevocationRegistry",
    "SkillMarketplaceService",
    "SkillMarketplaceError",
    # Skill Composition Engine (Fase 35)
    "CompositionExecutionMode",
    "CompositionErrorPolicy",
    "CompositionStatus",
    "SkillCompositionStep",
    "SkillComposition",
    "SkillCompositionStepResult",
    "SkillCompositionContext",
    "SkillCompositionResult",
    "SkillDataFlowResolver",
    "SkillConditionEvaluator",
    "DataFlowResolutionError",
    "SkillCompositionValidator",
    "CompositionValidationError",
    "SkillCompositionExecutor",
    "SkillCompositionExecutionError",
    "SkillComposer",
    "ComposedSkill",
    # Skill Graph Engine (Fase 36)
    "SkillGraphNodeType",
    "SkillGraphEdgeType",
    "SkillGraphNodeStatus",
    "SkillGraphStatus",
    "SkillGraphNode",
    "SkillGraphEdge",
    "GraphCacheEntry",
    "SkillGraphContext",
    "SkillGraphResult",
    "SkillGraph",
    "SkillGraphBuilder",
    "SkillGraphValidator",
    "SkillGraphPlanner",
    "SkillGraphOptimizer",
    "SkillGraphExecutor",
]
