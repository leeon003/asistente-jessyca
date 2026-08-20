"""Catálogo Oficial de Perfiles de Autonomía por Capability (CapabilityAutonomyRegistry - Etapa 16.2).

GARANTÍAS DE SEGURIDAD:
1. El catálogo es de SÓLO LECTURA en runtime tras la inicialización del sistema.
2. La única fuente autorizada para registrar perfiles es SYSTEM o CONFIGURATION.
3. Ningún actor externo (LLM, memoria, plugin, scheduler, workflow) puede modificar el catálogo.
4. La llamada a `lock_registry()` sella el catálogo de forma permanente en el arranque del sistema.
5. `get_profile_strict()` lanza `CapabilityProfileNotFoundError` si una capability no está declarada —
   forzando la declaración explícita de toda capability antes de que pueda ejecutarse.

CATÁLOGO PRECARGADO (Capabilities del sistema Jessyca 3.0):
Ver `_build_default_catalog()` para el listado completo.
"""

from __future__ import annotations

import threading
from typing import Any

from core.autonomy.autonomy_level import AutonomyLevel, TaskActionRisk
from core.autonomy.capability_autonomy_profile import (
    AuditRequirement,
    CapabilityAutonomyProfile,
    ConfirmationRequirement,
    ReversibilityClass,
)
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.autonomy.registry")

# ─────────────────────────────────────────────────────────────────────────────
# Atajos locales para legibilidad del catálogo
# ─────────────────────────────────────────────────────────────────────────────
L0 = AutonomyLevel.LEVEL_0_OBSERVE
L1 = AutonomyLevel.LEVEL_1_SUGGEST
L2 = AutonomyLevel.LEVEL_2_LOW_RISK_EXECUTION
L3 = AutonomyLevel.LEVEL_3_CONFIRMATION_REQUIRED
L4 = AutonomyLevel.LEVEL_4_CONTROLLED_AUTONOMY

RO = TaskActionRisk.READ_ONLY
LR = TaskActionRisk.LOW_RISK
MR = TaskActionRisk.MEDIUM_RISK
DG = TaskActionRisk.DANGEROUS
CR = TaskActionRisk.CRITICAL

REV = ReversibilityClass.REVERSIBLE
PREV = ReversibilityClass.PARTIALLY_REVERSIBLE
IRR = ReversibilityClass.IRREVERSIBLE

C_NEVER = ConfirmationRequirement.NEVER
C_ONCE = ConfirmationRequirement.ONCE_PER_SESSION
C_ALWAYS = ConfirmationRequirement.ALWAYS
C_THRESH = ConfirmationRequirement.WHEN_ABOVE_THRESHOLD

A_BASIC = AuditRequirement.BASIC
A_FULL = AuditRequirement.FULL
A_TE = AuditRequirement.TAMPER_EVIDENT


def _p(
    key: str,
    min_level: AutonomyLevel,
    risk: TaskActionRisk,
    confirmation: ConfirmationRequirement,
    reversibility: ReversibilityClass,
    audit: AuditRequirement,
    *,
    emergency_stop: bool = True,
    desc: str = "",
    category: str = "general",
) -> CapabilityAutonomyProfile:
    """Función auxiliar de construcción de perfiles para el catálogo."""
    return CapabilityAutonomyProfile(
        capability_key=key,
        minimum_autonomy_level=min_level,
        risk_level=risk,
        requires_confirmation=confirmation,
        reversibility=reversibility,
        audit_requirement=audit,
        emergency_stop_applicable=emergency_stop,
        description=desc,
        category=category,
    )


class CapabilityProfileNotFoundError(MCPError):
    """Error emitido cuando se solicita un perfil que no está registrado en el catálogo oficial."""
    pass


class CapabilityRegistryLockedError(MCPError):
    """Error emitido cuando se intenta modificar el catálogo sellado en runtime."""
    pass


def _build_default_catalog() -> dict[str, CapabilityAutonomyProfile]:
    """Construye el catálogo oficial precargado de perfiles de autonomía.

    REGLAS DE DISEÑO DEL CATÁLOGO:
    - READ_ONLY → LEVEL_0 mínimo, C_NEVER, REVERSIBLE, BASIC audit
    - LOW_RISK  → LEVEL_2 mínimo, C_NEVER, REVERSIBLE, BASIC audit
    - MEDIUM_RISK → LEVEL_2-3, C_THRESH, PARTIALLY_REVERSIBLE/REVERSIBLE, FULL audit
    - DANGEROUS → LEVEL_3 mínimo, C_ALWAYS, IRREVERSIBLE/PARTIALLY, FULL/TE audit
    - CRITICAL  → LEVEL_3-4, C_ALWAYS (inmutable), IRREVERSIBLE/PARTIALLY, TE audit
    """
    profiles = [
        # ─── FILESYSTEM ───────────────────────────────────────────────────
        _p("filesystem.read",      L0, RO, C_NEVER,  REV,  A_BASIC, desc="Lectura de archivos del sistema de ficheros.", category="filesystem"),
        _p("filesystem.list",      L0, RO, C_NEVER,  REV,  A_BASIC, desc="Listar contenido de directorios.", category="filesystem"),
        _p("filesystem.stat",      L0, RO, C_NEVER,  REV,  A_BASIC, desc="Consultar metadatos de un archivo (tamaño, fechas).", category="filesystem"),
        _p("filesystem.write",     L2, MR, C_THRESH, REV,  A_FULL,  desc="Escritura de contenido en archivos existentes o nuevos.", category="filesystem"),
        _p("filesystem.create",    L2, LR, C_NEVER,  REV,  A_BASIC, desc="Creación de nuevos archivos vacíos.", category="filesystem"),
        _p("filesystem.move",      L2, MR, C_THRESH, PREV, A_FULL,  desc="Mover o renombrar archivos. Parcialmente reversible.", category="filesystem"),
        _p("filesystem.copy",      L2, LR, C_NEVER,  REV,  A_BASIC, desc="Copiar archivos. Reversible (eliminar la copia).", category="filesystem"),
        _p("filesystem.delete",    L3, DG, C_ALWAYS, IRR,  A_TE,    desc="Eliminar archivos. IRREVERSIBLE sin papelera de reciclaje.", category="filesystem"),

        # ─── DOCUMENTO ────────────────────────────────────────────────────
        _p("document.read",        L0, RO, C_NEVER,  REV,  A_BASIC, desc="Leer contenido de documentos (docx, pdf, txt).", category="document"),
        _p("document.create",      L2, LR, C_NEVER,  REV,  A_BASIC, desc="Crear nuevos documentos. Reversible (eliminar).", category="document"),
        _p("document.modify",      L2, MR, C_THRESH, PREV, A_FULL,  desc="Modificar documentos existentes.", category="document"),
        _p("document.delete",      L3, DG, C_ALWAYS, IRR,  A_TE,    desc="Eliminar documentos.", category="document"),
        _p("document.export",      L2, LR, C_NEVER,  REV,  A_BASIC, desc="Exportar documento a otro formato.", category="document"),

        # ─── MENSAJERÍA / COMUNICACIÓN ────────────────────────────────────
        _p("message.send",         L3, MR, C_ALWAYS, IRR,  A_FULL,  desc="Enviar mensaje (email, chat, notificación externa). IRREVERSIBLE.", category="communication"),
        _p("message.draft",        L2, LR, C_NEVER,  REV,  A_BASIC, desc="Crear borrador de mensaje sin enviarlo.", category="communication"),
        _p("notification.send",    L2, LR, C_NEVER,  IRR,  A_BASIC, desc="Enviar notificación del sistema al usuario.", category="communication"),
        _p("notification.schedule", L3, MR, C_THRESH, PREV, A_FULL, desc="Programar notificación futura.", category="communication"),

        # ─── PROCESOS DEL SISTEMA ─────────────────────────────────────────
        _p("process.list",         L0, RO, C_NEVER,  REV,  A_BASIC, desc="Listar procesos activos del sistema.", category="process"),
        _p("process.info",         L0, RO, C_NEVER,  REV,  A_BASIC, desc="Consultar información de un proceso.", category="process"),
        _p("process.launch",       L3, DG, C_ALWAYS, PREV, A_TE,    desc="Lanzar un proceso nuevo. Requiere confirmación.", category="process"),
        _p("process.terminate",    L3, DG, C_ALWAYS, PREV, A_TE,    desc="Terminar proceso en ejecución.", category="process"),
        _p("process.kill",         L3, CR, C_ALWAYS, PREV, A_TE,    desc="Forzar finalización de proceso (SIGKILL). CRITICAL.", category="process"),

        # ─── SHELL / TERMINAL ─────────────────────────────────────────────
        _p("windows.shell.cmd",    L4, CR, C_ALWAYS, IRR,  A_TE, emergency_stop=True, desc="Ejecución de comandos CMD. CRITICAL, IRREVERSIBLE.", category="shell"),
        _p("windows.shell.powershell", L4, CR, C_ALWAYS, IRR, A_TE, emergency_stop=True, desc="Ejecución de scripts PowerShell. CRITICAL, IRREVERSIBLE.", category="shell"),

        # ─── REGISTRO DE WINDOWS ──────────────────────────────────────────
        _p("system.registry_read",  L0, RO, C_NEVER,  REV,  A_BASIC, desc="Leer valores del registro de Windows.", category="system"),
        _p("system.registry_write", L3, CR, C_ALWAYS, PREV, A_TE,    desc="Escribir en el registro de Windows. CRITICAL.", category="system"),
        _p("system.registry_delete", L3, CR, C_ALWAYS, IRR, A_TE,    desc="Eliminar claves del registro. CRITICAL, IRREVERSIBLE.", category="system"),

        # ─── SERVICIOS DE WINDOWS ─────────────────────────────────────────
        _p("system.service_start",  L3, CR, C_ALWAYS, PREV, A_TE, desc="Iniciar servicio del sistema. CRITICAL.", category="system"),
        _p("system.service_stop",   L3, CR, C_ALWAYS, PREV, A_TE, desc="Detener servicio del sistema. CRITICAL.", category="system"),
        _p("system.service_query",  L0, RO, C_NEVER,  REV,  A_BASIC, desc="Consultar estado de servicios.", category="system"),

        # ─── INSTALACIÓN DE SOFTWARE ──────────────────────────────────────
        _p("system.software_install", L4, CR, C_ALWAYS, IRR, A_TE, desc="Instalar software via winget. CRITICAL, IRREVERSIBLE.", category="system"),
        _p("system.software_uninstall", L4, CR, C_ALWAYS, IRR, A_TE, desc="Desinstalar software. CRITICAL, IRREVERSIBLE.", category="system"),

        # ─── INFORMACIÓN DEL SISTEMA ──────────────────────────────────────
        _p("system.info",           L0, RO, C_NEVER,  REV,  A_BASIC, desc="Consultar información del sistema (OS, hardware).", category="system"),
        _p("system.health",         L0, RO, C_NEVER,  REV,  A_BASIC, desc="Verificar salud del sistema.", category="system"),

        # ─── NAVEGADOR WEB ────────────────────────────────────────────────
        _p("browser.navigate",      L2, LR, C_NEVER,  REV,  A_BASIC, desc="Navegar a URL dentro del allowlist.", category="browser"),
        _p("browser.screenshot",    L1, RO, C_NEVER,  REV,  A_BASIC, desc="Capturar pantalla del navegador.", category="browser"),
        _p("browser.click",         L3, MR, C_THRESH, PREV, A_FULL,  desc="Hacer clic en elemento del navegador.", category="browser"),
        _p("browser.type",          L3, MR, C_THRESH, PREV, A_FULL,  desc="Escribir texto en elemento del navegador.", category="browser"),
        _p("browser.form_submit",   L3, DG, C_ALWAYS, IRR,  A_TE,    desc="Enviar formulario web. IRREVERSIBLE.", category="browser"),

        # ─── ESCRITORIO / DESKTOP AUTOMATION ─────────────────────────────
        _p("desktop.screenshot",    L1, RO, C_NEVER,  REV,  A_BASIC, emergency_stop=True, desc="Capturar pantalla.", category="desktop"),
        _p("desktop.ocr",           L1, RO, C_NEVER,  REV,  A_BASIC, emergency_stop=True, desc="OCR de la pantalla.", category="desktop"),
        _p("desktop.click",         L3, MR, C_THRESH, PREV, A_FULL,  emergency_stop=True, desc="Click en elemento de la interfaz.", category="desktop"),
        _p("desktop.type",          L3, MR, C_THRESH, PREV, A_FULL,  emergency_stop=True, desc="Escribir texto en la interfaz.", category="desktop"),
        _p("desktop.drag",          L3, DG, C_ALWAYS, PREV, A_TE,    emergency_stop=True, desc="Drag-and-drop de elementos.", category="desktop"),
        _p("desktop.hotkey",        L3, DG, C_ALWAYS, PREV, A_TE,    emergency_stop=True, desc="Enviar combinación de teclas de sistema.", category="desktop"),
        _p("desktop.clipboard_read",  L1, RO, C_NEVER, REV, A_BASIC, desc="Leer contenido del portapapeles.", category="desktop"),
        _p("desktop.clipboard_write", L2, LR, C_NEVER, IRR, A_BASIC, desc="Escribir al portapapeles.", category="desktop"),

        # ─── MEMORIA SEMÁNTICA ────────────────────────────────────────────
        _p("memory.read",           L0, RO, C_NEVER,  REV,  A_BASIC, desc="Recuperar evidencias de memoria semántica. MEMORY=EVIDENCE.", category="memory"),
        _p("memory.store",          L2, LR, C_NEVER,  REV,  A_BASIC, desc="Almacenar nueva evidencia en memoria semántica.", category="memory"),
        _p("memory.delete",         L3, MR, C_THRESH, IRR,  A_FULL,  desc="Eliminar entradas de memoria semántica.", category="memory"),
        _p("memory.consolidate",    L2, LR, C_NEVER,  PREV, A_BASIC, desc="Ejecutar consolidación de memoria.", category="memory"),

        # ─── SCHEDULER ────────────────────────────────────────────────────
        _p("scheduler.create",      L3, MR, C_THRESH, REV,  A_FULL,  desc="Crear tarea programada.", category="scheduler"),
        _p("scheduler.delete",      L3, MR, C_THRESH, PREV, A_FULL,  desc="Eliminar tarea programada.", category="scheduler"),
        _p("scheduler.list",        L0, RO, C_NEVER,  REV,  A_BASIC, desc="Listar tareas programadas.", category="scheduler"),
        _p("scheduler.trigger",     L3, DG, C_ALWAYS, PREV, A_TE,    desc="Disparar manualmente una tarea programada.", category="scheduler"),

        # ─── RED / NETWORK ────────────────────────────────────────────────
        _p("network.inspect",       L0, RO, C_NEVER,  REV,  A_BASIC, desc="Inspeccionar estado de la red.", category="network"),
        _p("network.http_get",      L2, LR, C_NEVER,  REV,  A_BASIC, desc="HTTP GET a URL autorizada.", category="network"),
        _p("network.http_post",     L3, MR, C_THRESH, IRR,  A_FULL,  desc="HTTP POST. Potencialmente irreversible.", category="network"),
        _p("network.route_modify",  L4, CR, C_ALWAYS, PREV, A_TE,    desc="Modificar tabla de rutas de red. CRITICAL.", category="network"),

        # ─── PLUGINS ──────────────────────────────────────────────────────
        _p("plugin.execute",        L3, MR, C_THRESH, PREV, A_FULL,  desc="Ejecutar acción de plugin. Evaluada por PluginSecurityPolicy.", category="plugin"),
        _p("plugin.install",        L4, CR, C_ALWAYS, PREV, A_TE,    desc="Instalar nuevo plugin. CRITICAL.", category="plugin"),
        _p("plugin.uninstall",      L4, CR, C_ALWAYS, PREV, A_TE,    desc="Desinstalar plugin. CRITICAL.", category="plugin"),

        # ─── WAKE WORD ────────────────────────────────────────────────────
        _p("wake_word.trigger",     L1, RO, C_NEVER,  REV,  A_BASIC, desc="Activación por wake word. Sólo dispara pipeline, no ejecuta.", category="wake_word"),

        # ─── AUTONOMY CONTROL ─────────────────────────────────────────────
        _p("autonomy.query_level",  L0, RO, C_NEVER,  REV,  A_BASIC, desc="Consultar nivel de autonomía activo.", category="autonomy"),
        # NOTA: No existe 'autonomy.set_level' como capability — el cambio de nivel
        # es una operación fuera del pipeline de herramientas, exclusiva del usuario.
    ]

    return {p.capability_key: p for p in profiles}


class CapabilityAutonomyRegistry:
    """Registro de sólo lectura (en runtime) del catálogo oficial de perfiles de autonomía.

    INVARIANTE DE SEGURIDAD:
    Tras llamar a `lock_registry()`, el catálogo queda sellado permanentemente.
    Cualquier intento de registrar o eliminar perfiles lanza `CapabilityRegistryLockedError`.

    El registro es thread-safe mediante `threading.RLock`.
    """

    def __init__(self, *, preload_defaults: bool = True) -> None:
        self._profiles: dict[str, CapabilityAutonomyProfile] = {}
        self._lock = threading.RLock()
        self._is_locked: bool = False

        if preload_defaults:
            self._profiles = _build_default_catalog()
            logger.info(f"[CapabilityAutonomyRegistry] Catálogo precargado con {len(self._profiles)} perfiles.")

    def lock_registry(self) -> None:
        """Sella el catálogo. Tras esta llamada, el registro es estrictamente de sólo lectura."""
        with self._lock:
            self._is_locked = True
            logger.info("[CapabilityAutonomyRegistry] Catálogo sellado — sólo lectura en runtime.")

    @property
    def is_locked(self) -> bool:
        """Indica si el registro fue sellado."""
        return self._is_locked

    def register_profile(self, profile: CapabilityAutonomyProfile) -> None:
        """Registra un nuevo perfil en el catálogo.

        SÓLO permitido antes de `lock_registry()`. Usar exclusivamente en:
        - Inicialización del sistema (fuente SYSTEM)
        - Configuración de tests

        Lanza `CapabilityRegistryLockedError` si el catálogo está sellado.
        """
        with self._lock:
            if self._is_locked:
                raise CapabilityRegistryLockedError(
                    f"[CapabilityAutonomyRegistry] Catálogo sellado. No se puede registrar '{profile.capability_key}'."
                )

            key = profile.capability_key.strip().lower()
            if not key:
                raise ValueError("El capability_key no puede estar vacío.")

            self._profiles[key] = profile
            logger.debug(f"[CapabilityAutonomyRegistry] Perfil registrado: '{key}'")

    def get_profile(self, capability_key: str) -> CapabilityAutonomyProfile | None:
        """Obtiene el perfil de autonomía para una capability. Retorna None si no existe."""
        with self._lock:
            return self._profiles.get(capability_key.strip().lower())

    def get_profile_strict(self, capability_key: str) -> CapabilityAutonomyProfile:
        """Obtiene el perfil o lanza `CapabilityProfileNotFoundError` si no está registrado.

        Usar en el SecureExecutionPipeline para forzar declaración explícita.
        """
        profile = self.get_profile(capability_key)
        if profile is None:
            raise CapabilityProfileNotFoundError(
                f"[CapabilityAutonomyRegistry] Capability '{capability_key}' no tiene perfil de autonomía declarado. "
                "Toda capability debe declararse explícitamente antes de poder ejecutarse."
            )
        return profile

    def get_minimum_level(self, capability_key: str) -> AutonomyLevel | None:
        """Obtiene el nivel mínimo de autonomía requerido para una capability.

        Retorna None si la capability no está en el catálogo.
        """
        profile = self.get_profile(capability_key)
        return profile.minimum_autonomy_level if profile else None

    def list_capabilities(self) -> list[str]:
        """Lista todos los capability_key registrados en orden alfabético."""
        with self._lock:
            return sorted(self._profiles.keys())

    def list_profiles(self) -> list[CapabilityAutonomyProfile]:
        """Lista todos los perfiles registrados."""
        with self._lock:
            return list(self._profiles.values())

    def get_capabilities_for_level(self, level: AutonomyLevel) -> list[str]:
        """Retorna todas las capabilities ejecutables en el nivel de autonomía dado."""
        with self._lock:
            return sorted(
                key for key, p in self._profiles.items()
                if level >= p.minimum_autonomy_level
            )

    def get_stats(self) -> dict[str, Any]:
        """Retorna estadísticas del catálogo para auditoría."""
        with self._lock:
            stats: dict[str, Any] = {
                "total_profiles": len(self._profiles),
                "is_locked": self._is_locked,
                "by_risk": {},
                "by_min_level": {},
                "by_category": {},
            }
            for p in self._profiles.values():
                risk_key = str(p.risk_level)
                level_key = p.minimum_autonomy_level.label
                cat_key = p.category
                stats["by_risk"][risk_key] = stats["by_risk"].get(risk_key, 0) + 1
                stats["by_min_level"][level_key] = stats["by_min_level"].get(level_key, 0) + 1
                stats["by_category"][cat_key] = stats["by_category"].get(cat_key, 0) + 1
            return stats


# ─────────────────────────────────────────────────────────────────────────────
# Singleton Global del CapabilityAutonomyRegistry
# ─────────────────────────────────────────────────────────────────────────────
_global_registry: CapabilityAutonomyRegistry | None = None
_registry_lock = threading.Lock()


def get_capability_autonomy_registry() -> CapabilityAutonomyRegistry:
    """Obtiene (o crea) la instancia singleton global del CapabilityAutonomyRegistry."""
    global _global_registry
    if _global_registry is None:
        with _registry_lock:
            if _global_registry is None:
                _global_registry = CapabilityAutonomyRegistry(preload_defaults=True)
    return _global_registry
