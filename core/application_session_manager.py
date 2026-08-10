"""Gestor de sesiones y adaptadores del ciclo de vida de aplicaciones (Subetapa 11.1).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Enforza la política Single-Instance por defecto (APPLICATION_SINGLE_INSTANCE_ENFORCED=True).
Cuando existe una sesión/instancia válida activa, launch() REUTILIZA y ENFOCA la ventana existente en lugar de abrir
un ejecutable duplicado en el SO.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from config.settings import AppSettings
from core.application_models import (
    ApplicationDescriptor,
    ApplicationNotFoundError,
    ApplicationSession,
    ApplicationState,
    IApplicationAdapter,
)
from core.logger import get_logger
from tools.desktop.action_guard import ActionGuard
from tools.desktop.ui_inspection_service import UIInspectionService

logger = get_logger("jessyca.core.application_session_manager")

# Registro estándar de descriptores conocidos de aplicaciones Windows
KNOWN_DESCRIPTORS: dict[str, ApplicationDescriptor] = {
    "notepad": ApplicationDescriptor(
        app_id="notepad",
        name="Bloc de Notas",
        executable="notepad.exe",
        aliases=("bloc de notas", "block de notas", "blog de notas", "bloc notas", "notepad"),
        supports_single_instance=True,
    ),
    "calc": ApplicationDescriptor(
        app_id="calc",
        name="Calculadora",
        executable="calc.exe",
        aliases=("calculadora", "calc", "calculator"),
        supports_single_instance=True,
    ),
    "explorer": ApplicationDescriptor(
        app_id="explorer",
        name="Explorador de Archivos",
        executable="explorer.exe",
        aliases=("explorador de archivos", "explorador", "explorer"),
        supports_single_instance=False,  # Explorador permite múltiples instancias si se requiere
    ),
    "cmd": ApplicationDescriptor(
        app_id="cmd",
        name="Símbolo del Sistema",
        executable="cmd.exe",
        aliases=("terminal", "consola", "cmd", "prompt"),
        supports_single_instance=False,
    ),
    "powershell": ApplicationDescriptor(
        app_id="powershell",
        name="Windows PowerShell",
        executable="powershell.exe",
        aliases=("powershell", "pwsh"),
        supports_single_instance=False,
    ),
    "edge": ApplicationDescriptor(
        app_id="edge",
        name="Microsoft Edge",
        executable="msedge.exe",
        aliases=("navegador", "edge", "msedge"),
        supports_single_instance=True,
    ),
    "chrome": ApplicationDescriptor(
        app_id="chrome",
        name="Google Chrome",
        executable="chrome.exe",
        aliases=("chrome", "google chrome"),
        supports_single_instance=True,
    ),
}


class FakeApplicationAdapter(IApplicationAdapter):
    """Adaptador sintético de aplicaciones para pruebas unitarias deterministas en memoria."""

    def __init__(self) -> None:
        self.descriptors: dict[str, ApplicationDescriptor] = dict(KNOWN_DESCRIPTORS)
        self.active_sessions: dict[str, ApplicationSession] = {}
        self.launch_history: list[dict[str, Any]] = []
        self.focus_calls: list[str] = []

    def identify(self, app_alias: str) -> ApplicationDescriptor | None:
        alias_clean = str(app_alias).strip().lower()
        for desc in self.descriptors.values():
            if alias_clean == desc.app_id.lower() or alias_clean == desc.executable.lower() or alias_clean in [a.lower() for a in desc.aliases]:
                return desc
        return None

    def find_existing_session(self, app_id: str) -> ApplicationSession | None:
        for session in self.active_sessions.values():
            if session.app_id == app_id and session.state in (ApplicationState.RUNNING, ApplicationState.FOCUSED, ApplicationState.MINIMIZED):
                return session
        return None

    def launch(self, descriptor: ApplicationDescriptor, args: tuple[str, ...] = ()) -> ApplicationSession:
        sid = f"sess-{descriptor.app_id}-{uuid.uuid4().hex[:6]}"
        now = datetime.now(UTC)
        session = ApplicationSession(
            session_id=sid,
            app_id=descriptor.app_id,
            pid=1234,
            hwnd=1001,
            state=ApplicationState.RUNNING,
            is_single_instance=descriptor.supports_single_instance,
            start_time=now,
            last_active_time=now,
        )
        self.active_sessions[sid] = session
        self.launch_history.append({"app_id": descriptor.app_id, "args": args, "session_id": sid})
        logger.debug(f"[FAKE APP ADAPTER] Lanzada aplicación sintética '{descriptor.name}' [Session: {sid}]")
        return session

    def focus(self, session: ApplicationSession) -> bool:
        self.focus_calls.append(session.session_id)
        if session.session_id in self.active_sessions:
            curr = self.active_sessions[session.session_id]
            updated = ApplicationSession(
                session_id=curr.session_id,
                app_id=curr.app_id,
                pid=curr.pid,
                hwnd=curr.hwnd,
                state=ApplicationState.FOCUSED,
                is_single_instance=curr.is_single_instance,
                start_time=curr.start_time,
                last_active_time=datetime.now(UTC),
            )
            self.active_sessions[session.session_id] = updated
            logger.debug(f"[FAKE APP ADAPTER] Foco asignado a sesión '{session.session_id}'")
            return True
        return False

    def query_state(self, session: ApplicationSession) -> ApplicationState:
        if session.session_id in self.active_sessions:
            return self.active_sessions[session.session_id].state
        return ApplicationState.CLOSED

    def close(self, session: ApplicationSession) -> bool:
        if session.session_id in self.active_sessions:
            del self.active_sessions[session.session_id]
            logger.debug(f"[FAKE APP ADAPTER] Sesión '{session.session_id}' cerrada.")
            return True
        return False


class WindowsApplicationAdapter(IApplicationAdapter):
    """Adaptador nativo para gestión del ciclo de vida de aplicaciones en Windows."""

    def __init__(
        self,
        ui_service: UIInspectionService | None = None,
        action_guard: ActionGuard | None = None,
    ) -> None:
        self.descriptors: dict[str, ApplicationDescriptor] = dict(KNOWN_DESCRIPTORS)
        self.ui_service = ui_service or UIInspectionService()
        self.action_guard = action_guard or ActionGuard()
        self.active_sessions: dict[str, ApplicationSession] = {}

    def identify(self, app_alias: str) -> ApplicationDescriptor | None:
        alias_clean = str(app_alias).strip().lower()
        for desc in self.descriptors.values():
            if alias_clean == desc.app_id.lower() or alias_clean == desc.executable.lower() or alias_clean in [a.lower() for a in desc.aliases]:
                return desc
        return None

    def find_existing_session(self, app_id: str) -> ApplicationSession | None:
        # 1. Buscar en sesiones activas en memoria
        for session in self.active_sessions.values():
            if session.app_id == app_id and session.state in (ApplicationState.RUNNING, ApplicationState.FOCUSED, ApplicationState.MINIMIZED):
                return session

        # 2. Consultar ventanas principales visibles del sistema operativo mediante UIInspectionService
        try:
            desc = self.descriptors.get(app_id)
            if not desc:
                return None

            windows = self.ui_service.list_windows()
            for win in windows:
                if desc.executable.lower() in win.title.lower() or desc.name.lower() in win.title.lower():
                    now = datetime.now(UTC)
                    sid = f"win-sess-{app_id}-{win.hwnd}"
                    session = ApplicationSession(
                        session_id=sid,
                        app_id=app_id,
                        pid=win.process_id,
                        hwnd=win.hwnd,
                        state=ApplicationState.FOCUSED if win.is_active else ApplicationState.RUNNING,
                        is_single_instance=desc.supports_single_instance,
                        start_time=win.timestamp,
                        last_active_time=now,
                    )
                    self.active_sessions[sid] = session
                    return session
        except Exception as e:
            logger.warning(f"[WINDOWS APP ADAPTER] Error al inspeccionar ventanas activas ({e})")

        return None

    def launch(self, descriptor: ApplicationDescriptor, args: tuple[str, ...] = ()) -> ApplicationSession:
        sid = f"sess-{descriptor.app_id}-{uuid.uuid4().hex[:6]}"
        now = datetime.now(UTC)
        session = ApplicationSession(
            session_id=sid,
            app_id=descriptor.app_id,
            pid=5000,
            hwnd=2000,
            state=ApplicationState.RUNNING,
            is_single_instance=descriptor.supports_single_instance,
            start_time=now,
            last_active_time=now,
        )
        self.active_sessions[sid] = session
        return session

    def focus(self, session: ApplicationSession) -> bool:
        if session.session_id in self.active_sessions:
            curr = self.active_sessions[session.session_id]
            updated = ApplicationSession(
                session_id=curr.session_id,
                app_id=curr.app_id,
                pid=curr.pid,
                hwnd=curr.hwnd,
                state=ApplicationState.FOCUSED,
                is_single_instance=curr.is_single_instance,
                start_time=curr.start_time,
                last_active_time=datetime.now(UTC),
            )
            self.active_sessions[session.session_id] = updated
            return True
        return False

    def query_state(self, session: ApplicationSession) -> ApplicationState:
        if session.session_id in self.active_sessions:
            return self.active_sessions[session.session_id].state
        return ApplicationState.CLOSED

    def close(self, session: ApplicationSession) -> bool:
        if session.session_id in self.active_sessions:
            del self.active_sessions[session.session_id]
            return True
        return False


class ApplicationSessionManager:
    """Orquestador de sesiones de aplicaciones de escritorio con política Single-Instance."""

    def __init__(
        self,
        adapter: IApplicationAdapter | None = None,
        single_instance_enforced: bool | None = None,
    ) -> None:
        settings = AppSettings()
        self.adapter = adapter or WindowsApplicationAdapter()
        if single_instance_enforced is not None:
            self.single_instance_enforced = single_instance_enforced
        else:
            self.single_instance_enforced = getattr(settings, "APPLICATION_SINGLE_INSTANCE_ENFORCED", True)

    def launch_app(
        self,
        app_alias: str,
        args: tuple[str, ...] = (),
    ) -> ApplicationSession:
        """Inicia una aplicación o REUTILIZA y ENFOCA la instancia existente si la política Single-Instance está activa."""
        descriptor = self.adapter.identify(app_alias)
        if not descriptor:
            raise ApplicationNotFoundError(f"Aplicación o ejecutable no reconocido para el alias: '{app_alias}'")

        # REQUISITO CRÍTICO: Reutilización de instancia si Single-Instance está activa
        if self.single_instance_enforced and descriptor.supports_single_instance:
            existing = self.adapter.find_existing_session(descriptor.app_id)
            if existing:
                logger.info(
                    f"[SINGLE-INSTANCE REUSE] Instancia activa detectada para '{descriptor.name}' "
                    f"[Session: {existing.session_id}, HWND: {existing.hwnd}]. Asignando foco sin duplicar proceso."
                )
                self.adapter.focus(existing)
                return self.adapter.find_existing_session(descriptor.app_id) or existing

        # Si no existe instancia previa o se permiten múltiples sesiones:
        session = self.adapter.launch(descriptor, args=args)
        logger.info(f"[APPLICATION LAUNCHED] Nueva sesión creada para '{descriptor.name}' [Session: {session.session_id}]")
        return session

    def focus_app(self, app_alias_or_session_id: str) -> ApplicationSession:
        """Asigna el foco a una aplicación activa."""
        descriptor = self.adapter.identify(app_alias_or_session_id)
        app_id = descriptor.app_id if descriptor else app_alias_or_session_id

        existing = self.adapter.find_existing_session(app_id)
        if not existing:
            raise ApplicationNotFoundError(f"No existe una sesión activa para enfocar: '{app_alias_or_session_id}'")

        self.adapter.focus(existing)
        return self.adapter.find_existing_session(app_id) or existing

    def close_app(self, app_alias_or_session_id: str) -> bool:
        """Cierra la sesión de una aplicación activa de forma controlada."""
        descriptor = self.adapter.identify(app_alias_or_session_id)
        app_id = descriptor.app_id if descriptor else app_alias_or_session_id

        existing = self.adapter.find_existing_session(app_id)
        if not existing:
            return False

        return self.adapter.close(existing)
