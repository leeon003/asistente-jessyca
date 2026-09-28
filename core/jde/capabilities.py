"""Capability Registry y Gobernanza de Capacidades para JDE - Fase 6 (LIMITED).

Define el catálogo estructurado de capacidades del sistema, su clasificación de riesgo,
niveles de autoridad requeridos, y requisitos formales de verificación determinista.

REGLAS DE FASE 6 (LIMITED):
1. LIMITED opera con autoridad real exclusivamente dentro de un conjunto explícitamente
   autorizado de capacidades de bajo o medio riesgo controlado.
2. Cada capacidad declara formalmente:
   - capability_id
   - action
   - tool
   - risk_tier (LOW, MEDIUM, HIGH)
   - authority_level (CANARY, LIMITED, PROGRESSIVE, FULL)
   - requires_verification (bool)
   - destructive (bool)
   - external_side_effect (bool)
   - reversible (bool)
   - enabled (bool)
3. Acciones de riesgo HIGH quedan incondicionalmente excluidas de LIMITED (DENY).
4. Acciones desconocidas o deshabilitadas quedan bloqueadas (DENY).
5. Acciones con efectos observables en el sistema requieren verificación estricta.
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.jde.authority import ActionRiskTier, AuthorityMode
from core.logger import get_logger

logger = get_logger("jessyca.jde.capabilities")


class Capability(BaseModel):
    """Definición inmutable de una capacidad operable bajo gobernanza JDE."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_id: str
    action: str
    tool: str
    risk_tier: ActionRiskTier
    authority_level: AuthorityMode  # Nivel mínimo de autoridad requerido
    requires_verification: bool = True
    destructive: bool = False
    external_side_effect: bool = False
    reversible: bool = True
    enabled: bool = True
    promoted_to_progressive: bool = False
    promotion_epoch: int = 0
    description: str = ""
    allowed_scopes: list[str] | None = None

    @property
    def is_high_risk(self) -> bool:
        return self.risk_tier == ActionRiskTier.HIGH

    @property
    def canonical_key(self) -> str:
        return f"{self.tool}:{self.action}".lower()

    def is_allowed_for_mode(self, mode: AuthorityMode) -> bool:
        """Determina si la capacidad es admisible para un modo de autoridad."""
        if not self.enabled or self.is_high_risk:
            return False
        if mode == AuthorityMode.SHADOW:
            return False
        if mode == AuthorityMode.CANARY:
            return self.authority_level == AuthorityMode.CANARY
        if mode == AuthorityMode.LIMITED:
            return self.authority_level in (AuthorityMode.CANARY, AuthorityMode.LIMITED)
        if mode == AuthorityMode.PROGRESSIVE:
            # En PROGRESSIVE, sólo capacidades promovidas explícitamente o autorizadas en LIMITED
            if self.promoted_to_progressive:
                return True
            return self.authority_level in (AuthorityMode.CANARY, AuthorityMode.LIMITED)
        if mode == AuthorityMode.FULL:
            return True
        return False


class CapabilityRegistry:
    """Registro y coordinador central de capacidades para JDE."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._capabilities: dict[str, Capability] = {}
        self._action_to_id: dict[str, str] = {}
        self._load_default_catalog()

    def register(self, cap: Capability) -> None:
        """Registra o actualiza una capacidad en el catálogo."""
        with self._lock:
            self._capabilities[cap.capability_id] = cap
            # Mapear tanto tool:action como action sola
            self._action_to_id[cap.canonical_key] = cap.capability_id
            self._action_to_id[cap.action.lower()] = cap.capability_id
            logger.debug(f"[CAPABILITY REGISTRY] Registrada capacidad '{cap.capability_id}' ({cap.canonical_key}).")

    def get(self, capability_id: str) -> Capability | None:
        """Obtiene una capacidad por su capability_id."""
        with self._lock:
            return self._capabilities.get(capability_id)

    def find_by_action(self, action: str, tool: str = "") -> Capability | None:
        """Busca una capacidad por su nombre de acción y herramienta."""
        with self._lock:
            key = f"{tool}:{action}".lower() if tool else action.lower()
            cap_id = self._action_to_id.get(key)
            if not cap_id:
                # Intentar solo con action
                cap_id = self._action_to_id.get(action.lower())
            if cap_id:
                return self._capabilities.get(cap_id)
            return None

    def enable(self, capability_id: str) -> bool:
        """Habilita una capacidad registrada."""
        with self._lock:
            cap = self._capabilities.get(capability_id)
            if not cap:
                return False
            # Crear nueva instancia con enabled=True (frozen model)
            updated = cap.model_copy(update={"enabled": True})
            self._capabilities[capability_id] = updated
            return True

    def disable(self, capability_id: str) -> bool:
        """Deshabilita una capacidad registrada."""
        with self._lock:
            cap = self._capabilities.get(capability_id)
            if not cap:
                return False
            updated = cap.model_copy(update={"enabled": False})
            self._capabilities[capability_id] = updated
            return True

    def promote_capability(self, capability_id: str, target_mode: AuthorityMode = AuthorityMode.PROGRESSIVE) -> bool:
        """Promueve una capacidad individual a un nivel superior (ej. PROGRESSIVE)."""
        with self._lock:
            cap = self._capabilities.get(capability_id)
            if not cap:
                return False
            updated = cap.model_copy(
                update={
                    "promoted_to_progressive": (target_mode == AuthorityMode.PROGRESSIVE),
                    "promotion_epoch": cap.promotion_epoch + 1,
                }
            )
            self._capabilities[capability_id] = updated
            return True

    def demote_capability(self, capability_id: str, target_mode: AuthorityMode = AuthorityMode.LIMITED) -> bool:
        """Revierte la promoción de una capacidad a un nivel seguro (ej. LIMITED)."""
        with self._lock:
            cap = self._capabilities.get(capability_id)
            if not cap:
                return False
            updated = cap.model_copy(
                update={
                    "promoted_to_progressive": False,
                }
            )
            self._capabilities[capability_id] = updated
            return True

    def is_promoted(self, capability_id: str) -> bool:
        """Verifica si una capacidad está promovida a PROGRESSIVE."""
        with self._lock:
            cap = self._capabilities.get(capability_id)
            return bool(cap and cap.promoted_to_progressive)

    def list_capabilities(self) -> list[Capability]:
        """Lista todas las capacidades registradas."""
        with self._lock:
            return list(self._capabilities.values())

    def list_by_mode(self, mode: AuthorityMode) -> list[Capability]:
        """Lista las capacidades permitidas para un modo de autoridad específico."""
        with self._lock:
            return [
                c for c in self._capabilities.values()
                if c.is_allowed_for_mode(mode)
            ]

    def is_allowed_for_mode(self, capability_id: str, mode: AuthorityMode) -> bool:
        """Comprueba si una capacidad está habilitada y permitida para el modo actual."""
        with self._lock:
            cap = self._capabilities.get(capability_id)
            if not cap:
                return False
            return cap.is_allowed_for_mode(mode)

    def validate_scope(self, cap: Capability, parameters: dict[str, Any] | None) -> tuple[bool, str]:
        """Valida que los parámetros de la capacidad respeten los límites de seguridad."""
        params = parameters or {}
        target_path = (
            params.get("path")
            or params.get("file_path")
            or params.get("target")
            or params.get("destination")
        )

        if target_path and cap.tool in ("files", "filesystem", "windows.files"):
            path_str = str(target_path).strip()
            path_norm = os.path.normpath(path_str).lower()
            temp_norm = os.path.normpath(tempfile.gettempdir()).lower()

            forbidden_keywords = ("\\windows", "\\system32", "program files", "windows\\", "system32\\")
            if any(fk in path_norm for fk in forbidden_keywords):
                return False, f"Scope violado: acceso a ruta crítica del sistema prohibido ('{target_path}')."

            # Si es escritura o creación, exigir workspace temporal
            if cap.action in ("create_temp_file", "create_temp_test_file", "write_file", "create_file"):
                is_temp = (
                    path_norm.startswith(temp_norm)
                    or "\\temp\\" in path_norm
                    or "\\tmp\\" in path_norm
                    or "jde_limited" in path_norm
                    or "jde_test" in path_norm
                    or "jde_canary" in path_norm
                )
                if not is_temp:
                    return False, f"Scope violado: la ruta ('{target_path}') no pertenece al workspace temporal permitido en LIMITED."

        if target_path and cap.tool in ("archify", "tools.archify", "diagram"):
            path_str = str(target_path).strip()
            path_norm = os.path.normpath(path_str).lower()
            forbidden_keywords = (
                "\\windows", "\\system32", "program files", "windows\\", "system32\\",
                "\\users", "\\appdata", ".env", "secret", "config.json", "credentials", "id_rsa"
            )
            if any(fk in path_norm for fk in forbidden_keywords) or ".." in path_str or "%2e" in path_str.lower():
                return False, f"Scope violado: acceso o path traversal prohibido en Archify ('{target_path}')."

        return True, "Parámetros dentro del scope seguro de la capacidad."

    @staticmethod
    def _get_allowed_levels(mode: AuthorityMode) -> set[AuthorityMode]:
        """Jerarquía de niveles de autoridad acumulativa."""
        if mode == AuthorityMode.SHADOW:
            return set()
        if mode == AuthorityMode.CANARY:
            return {AuthorityMode.CANARY}
        if mode == AuthorityMode.LIMITED:
            return {AuthorityMode.CANARY, AuthorityMode.LIMITED}
        if mode == AuthorityMode.PROGRESSIVE:
            return {AuthorityMode.CANARY, AuthorityMode.LIMITED, AuthorityMode.PROGRESSIVE}
        if mode == AuthorityMode.FULL:
            return {AuthorityMode.CANARY, AuthorityMode.LIMITED, AuthorityMode.PROGRESSIVE, AuthorityMode.FULL}
        return set()

    def _load_default_catalog(self) -> None:
        """Carga el catálogo inicial canónico de capacidades para Fase 6."""
        # ── 1. CAPACIDADES LOW RISK (Autorizadas en LIMITED) ──
        self.register(
            Capability(
                capability_id="files.read",
                action="read_file",
                tool="files",
                risk_tier=ActionRiskTier.LOW,
                authority_level=AuthorityMode.LIMITED,
                requires_verification=False,
                destructive=False,
                external_side_effect=False,
                reversible=True,
                enabled=True,
                description="Lectura segura de archivos locales en espacio de trabajo.",
            )
        )
        self.register(
            Capability(
                capability_id="files.search",
                action="search_files",
                tool="files",
                risk_tier=ActionRiskTier.LOW,
                authority_level=AuthorityMode.LIMITED,
                requires_verification=False,
                destructive=False,
                external_side_effect=False,
                reversible=True,
                enabled=True,
                description="Búsqueda local de archivos por patrón o nombre.",
            )
        )
        self.register(
            Capability(
                capability_id="system.query",
                action="query_system_info",
                tool="system",
                risk_tier=ActionRiskTier.LOW,
                authority_level=AuthorityMode.LIMITED,
                requires_verification=False,
                destructive=False,
                external_side_effect=False,
                reversible=True,
                enabled=True,
                description="Consulta de información de sistema y métricas.",
            )
        )
        self.register(
            Capability(
                capability_id="process.inspect",
                action="inspect_process",
                tool="process",
                risk_tier=ActionRiskTier.LOW,
                authority_level=AuthorityMode.LIMITED,
                requires_verification=False,
                destructive=False,
                external_side_effect=False,
                reversible=True,
                enabled=True,
                description="Inspección pasiva de procesos activos en Windows.",
            )
        )
        self.register(
            Capability(
                capability_id="system.status",
                action="get_system_status",
                tool="system",
                risk_tier=ActionRiskTier.LOW,
                authority_level=AuthorityMode.LIMITED,
                requires_verification=False,
                destructive=False,
                external_side_effect=False,
                reversible=True,
                enabled=True,
                description="Consulta del estado operativo del sistema.",
            )
        )

        # ── 2. CAPACIDADES MEDIUM RISK (Autorizadas en LIMITED bajo scope temporal) ──
        self.register(
            Capability(
                capability_id="files.create_temp",
                action="create_temp_file",
                tool="files",
                risk_tier=ActionRiskTier.MEDIUM,
                authority_level=AuthorityMode.CANARY,  # Disponible tanto en CANARY como en LIMITED
                requires_verification=True,
                destructive=False,
                external_side_effect=False,
                reversible=True,
                enabled=True,
                description="Creación determinista de archivos en workspace temporal.",
            )
        )
        self.register(
            Capability(
                capability_id="files.create_temp_test",
                action="create_temp_test_file",
                tool="files",
                risk_tier=ActionRiskTier.MEDIUM,
                authority_level=AuthorityMode.CANARY,
                requires_verification=True,
                destructive=False,
                external_side_effect=False,
                reversible=True,
                enabled=True,
                description="Creación de archivos temporales de prueba.",
            )
        )

        # ── 3. CAPACIDADES MEDIUM RISK RESTRINGIDAS (Requieren PROGRESSIVE o FULL) ──
        self.register(
            Capability(
                capability_id="browser.navigate",
                action="open_url",
                tool="browser",
                risk_tier=ActionRiskTier.MEDIUM,
                authority_level=AuthorityMode.PROGRESSIVE,
                requires_verification=True,
                destructive=False,
                external_side_effect=True,
                reversible=False,
                enabled=True,
                description="Navegación web mediante navegador.",
            )
        )
        self.register(
            Capability(
                capability_id="browser.youtube",
                action="play_video",
                tool="browser",
                risk_tier=ActionRiskTier.MEDIUM,
                authority_level=AuthorityMode.PROGRESSIVE,
                requires_verification=True,
                destructive=False,
                external_side_effect=True,
                reversible=False,
                enabled=True,
                description="Reproducción de contenido multimedia en YouTube.",
            )
        )
        self.register(
            Capability(
                capability_id="computer_use.input",
                action="send_keys",
                tool="computer_use",
                risk_tier=ActionRiskTier.MEDIUM,
                authority_level=AuthorityMode.PROGRESSIVE,
                requires_verification=True,
                destructive=False,
                external_side_effect=True,
                reversible=False,
                enabled=True,
                description="Simulación de entrada de teclado o ratón via Computer Use.",
            )
        )
        self.register(
            Capability(
                capability_id="files.write_uncontrolled",
                action="write_file",
                tool="files",
                risk_tier=ActionRiskTier.MEDIUM,
                authority_level=AuthorityMode.PROGRESSIVE,
                requires_verification=True,
                destructive=False,
                external_side_effect=True,
                reversible=False,
                enabled=True,
                description="Escritura general fuera de directorio temporal.",
            )
        )

        # ── 4. CAPACIDADES HIGH RISK (Excluidas incondicionalmente de LIMITED) ──
        self.register(
            Capability(
                capability_id="files.delete",
                action="delete_file",
                tool="files",
                risk_tier=ActionRiskTier.HIGH,
                authority_level=AuthorityMode.FULL,
                requires_verification=True,
                destructive=True,
                external_side_effect=True,
                reversible=False,
                enabled=True,
                description="Eliminación de archivos del sistema.",
            )
        )
        self.register(
            Capability(
                capability_id="process.kill",
                action="kill_process",
                tool="process",
                risk_tier=ActionRiskTier.HIGH,
                authority_level=AuthorityMode.FULL,
                requires_verification=True,
                destructive=True,
                external_side_effect=True,
                reversible=False,
                enabled=True,
                description="Terminación forzada de procesos en ejecución.",
            )
        )
        self.register(
            Capability(
                capability_id="system.registry",
                action="write_registry",
                tool="system",
                risk_tier=ActionRiskTier.HIGH,
                authority_level=AuthorityMode.FULL,
                requires_verification=True,
                destructive=True,
                external_side_effect=True,
                reversible=False,
                enabled=True,
                description="Modificación del registro de Windows.",
            )
        )
        self.register(
            Capability(
                capability_id="system.shutdown",
                action="system_shutdown",
                tool="system",
                risk_tier=ActionRiskTier.HIGH,
                authority_level=AuthorityMode.FULL,
                requires_verification=True,
                destructive=True,
                external_side_effect=True,
                reversible=False,
                enabled=True,
                description="Apagado o reinicio del sistema operativo.",
            )
        )
        self.register(
            Capability(
                capability_id="security.credentials",
                action="get_credentials",
                tool="security",
                risk_tier=ActionRiskTier.HIGH,
                authority_level=AuthorityMode.FULL,
                requires_verification=True,
                destructive=False,
                external_side_effect=True,
                reversible=False,
                enabled=True,
                description="Acceso a credenciales, contraseñas o tokens.",
            )
        )

        # ── 5. CAPACIDADES DE DIAGRAMACIÓN TÉCNICA (Archify Provider - Fase 2 Controlled) ──
        for dtype in ("architecture", "workflow", "sequence", "dataflow", "lifecycle"):
            self.register(
                Capability(
                    capability_id=f"diagram_generation.{dtype}",
                    action=f"render_{dtype}_diagram",
                    tool="archify",
                    risk_tier=ActionRiskTier.LOW,
                    authority_level=AuthorityMode.LIMITED,
                    requires_verification=True,
                    destructive=False,
                    external_side_effect=False,
                    reversible=True,
                    enabled=True,
                    description=f"Generación de diagramas interactivos de {dtype} con Archify (Controlled).",
                )
            )
        self.register(
            Capability(
                capability_id="diagram_generation.generic",
                action="render_diagram",
                tool="archify",
                risk_tier=ActionRiskTier.LOW,
                authority_level=AuthorityMode.LIMITED,
                requires_verification=True,
                destructive=False,
                external_side_effect=False,
                reversible=True,
                enabled=False,  # NO CERTIFICADA en Fase 2/3 - Bloqueada en Producción
                description="Generación determinista de diagramas técnicos con Archify (DISABLED - uncertified).",
            )
        )
        self.register(
            Capability(
                capability_id="diagram_generation.skill",
                action="render",
                tool="tools.archify",
                risk_tier=ActionRiskTier.LOW,
                authority_level=AuthorityMode.LIMITED,
                requires_verification=True,
                destructive=False,
                external_side_effect=False,
                reversible=True,
                enabled=False,  # NO CERTIFICADA en Fase 2/3 - Bloqueada en Producción
                description="Invocación de ArchifySkill gobernada por JDE (DISABLED - uncertified).",
            )
        )

        # ── 6. CAPACIDADES DE ORQUESTACIÓN AGÉNTICA (ORCA + ADE Provider - Fase 2 Controlled) ──
        orca_capabilities = [
            ("agent_orchestration.task_creation", "create_task", "Creación gobernada de contratos de tareas para agentes."),
            ("agent_orchestration.worktree_isolation", "isolate_worktree", "Aislamiento estricto de tareas en Git Worktrees efímeros."),
            ("agent_orchestration.parallel_execution", "parallel_execute", "Coordinación y ejecución concurrente de múltiples agentes."),
            ("agent_orchestration.agent_lifecycle", "manage_lifecycle", "Control formal de la máquina de estados del ciclo de vida del agente."),
            ("agent_orchestration.result_collection", "collect_results", "Recolección estructurada de resultados con verificación física."),
            ("agent_orchestration.failure_isolation", "isolate_failure", "Aislamiento de fallos y prevención de corrupción del repositorio."),
            ("agent_orchestration.review", "review_gate", "Control de aprobación y revisión humana/JDE previo a merge de código."),
        ]
        for cap_id, act, desc in orca_capabilities:
            self.register(
                Capability(
                    capability_id=cap_id,
                    action=act,
                    tool="orca_ade",
                    risk_tier=ActionRiskTier.MEDIUM,
                    authority_level=AuthorityMode.LIMITED,
                    requires_verification=True,
                    destructive=False,
                    external_side_effect=False,
                    reversible=True,
                    enabled=True,
                    description=desc,
                )
            )


_GLOBAL_CAPABILITY_REGISTRY: CapabilityRegistry | None = None
_REGISTRY_LOCK = threading.Lock()


def get_capability_registry() -> CapabilityRegistry:
    """Retorna la instancia global singleton de CapabilityRegistry."""
    global _GLOBAL_CAPABILITY_REGISTRY
    with _REGISTRY_LOCK:
        if _GLOBAL_CAPABILITY_REGISTRY is None:
            _GLOBAL_CAPABILITY_REGISTRY = CapabilityRegistry()
        return _GLOBAL_CAPABILITY_REGISTRY


def reset_capability_registry() -> CapabilityRegistry:
    """Reinicia la instancia global de CapabilityRegistry (útil en pruebas)."""
    global _GLOBAL_CAPABILITY_REGISTRY
    with _REGISTRY_LOCK:
        _GLOBAL_CAPABILITY_REGISTRY = CapabilityRegistry()
        return _GLOBAL_CAPABILITY_REGISTRY
