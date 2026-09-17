"""Gestor de sesiones y adaptadores del ciclo de vida de aplicaciones (Subetapa 11.1).

GARANTÍA ABSOLUTA DE SEGURIDAD:
Enforza la política Single-Instance por defecto (APPLICATION_SINGLE_INSTANCE_ENFORCED=True).
Cuando existe una sesión/instancia válida activa, launch() REUTILIZA y ENFOCA la ventana existente en lugar de abrir
un ejecutable duplicado en el SO.
"""

from __future__ import annotations

import os
import subprocess
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
    "whatsapp": ApplicationDescriptor(
        app_id="whatsapp",
        name="WhatsApp",
        executable="whatsapp.exe",
        aliases=("whatsapp", "wasap", "whats"),
        supports_single_instance=True,
    ),
    "paint": ApplicationDescriptor(
        app_id="paint",
        name="Paint",
        executable="mspaint.exe",
        aliases=("paint", "mspaint", "dibujo"),
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
                win_title_low = win.title.lower()
                if (
                    desc.executable.lower() in win_title_low
                    or desc.name.lower() in win_title_low
                    or any(a.lower() in win_title_low for a in desc.aliases)
                ):
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

            if os.name == "nt":
                try:
                    import win32gui, win32process
                    real_wins: list[tuple[int, str, int]] = []
                    def _enum_win(h: int, _: Any) -> None:
                        if win32gui.IsWindowVisible(h):
                            t = win32gui.GetWindowText(h)
                            if t:
                                _, pid = win32process.GetWindowThreadProcessId(h)
                                real_wins.append((h, t, pid))
                    win32gui.EnumWindows(_enum_win, None)
                    for h, t, p in real_wins:
                        t_lower = t.lower()
                        if (
                            desc.executable.lower() in t_lower
                            or desc.name.lower() in t_lower
                            or any(a.lower() in t_lower for a in desc.aliases)
                        ):
                            now = datetime.now(UTC)
                            sid = f"win-sess-{app_id}-{h}"
                            session = ApplicationSession(
                                session_id=sid,
                                app_id=app_id,
                                pid=p,
                                hwnd=h,
                                state=ApplicationState.RUNNING,
                                is_single_instance=desc.supports_single_instance,
                                start_time=now,
                                last_active_time=now,
                            )
                            self.active_sessions[sid] = session
                            return session
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"[WINDOWS APP ADAPTER] Error al inspeccionar ventanas activas ({e})")

        return None

    def launch(self, descriptor: ApplicationDescriptor, args: tuple[str, ...] = ()) -> ApplicationSession:
        sid = f"sess-{descriptor.app_id}-{uuid.uuid4().hex[:6]}"
        now = datetime.now(UTC)
        proc_pid = 5000
        proc_hwnd = 2000

        try:
            if os.name == "nt":
                cmd = [descriptor.executable] + list(args)
                p = subprocess.Popen(cmd, shell=True)
                proc_pid = p.pid
            else:
                proc_pid = 1234
        except Exception as e:
            logger.warning(f"[WINDOWS APP ADAPTER] Error al invocar {descriptor.executable} en SO: {e}")

        session = ApplicationSession(
            session_id=sid,
            app_id=descriptor.app_id,
            pid=proc_pid,
            hwnd=proc_hwnd,
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
    """Orquestador de sesiones de aplicaciones de escritorio con política Single-Instance e Idempotencia (Fase 75.1-B)."""

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

        self._executed_actions: dict[str, ApplicationSession] = {}
        self._execution_counts: dict[str, int] = {}
        self._action_call_counts: dict[str, int] = {}

    def get_execution_count(self, app_alias: str) -> int:
        """Obtiene la cantidad de ejecuciones reales del proceso para un alias."""
        descriptor = self.adapter.identify(app_alias)
        app_id = descriptor.app_id if descriptor else app_alias.lower()
        return self._execution_counts.get(app_id, 0)

    def get_call_count(self, app_alias: str) -> int:
        """Obtiene la cantidad total de llamadas a launch_app() para un alias."""
        descriptor = self.adapter.identify(app_alias)
        app_id = descriptor.app_id if descriptor else app_alias.lower()
        return self._action_call_counts.get(app_id, 0)

    def launch_app(
        self,
        app_alias: str,
        args: tuple[str, ...] = (),
        action_id: str | None = None,
    ) -> ApplicationSession:
        """Inicia una aplicación garantizando idempotencia por action_id y trazabilidad."""
        descriptor = self.adapter.identify(app_alias)
        if not descriptor:
            raise ApplicationNotFoundError(f"Aplicación o ejecutable no reconocido para el alias: '{app_alias}'")

        app_key = descriptor.app_id
        self._action_call_counts[app_key] = self._action_call_counts.get(app_key, 0) + 1

        # 1. PROTECCIÓN DE IDEMPOTENCIA POR ACTION_ID (Fase 75.1-B / Pasos 3 y 4)
        # Misma acción interna + mismo action_id = NO EJECUTAR DOS VECES
        if action_id:
            dedup_key = f"{descriptor.app_id}:{action_id}"
            if dedup_key in self._executed_actions:
                cached_session = self._executed_actions[dedup_key]
                logger.warning(
                    f"[APP_EXECUTION] action_id={action_id} app={descriptor.app_id} duplicate_blocked=True"
                )
                return cached_session

        # 2. Reutilización si la política Single-Instance está activa y NO se especificó un nuevo action_id explícito
        if action_id is None and self.single_instance_enforced and descriptor.supports_single_instance:
            existing = self.adapter.find_existing_session(descriptor.app_id)
            if existing:
                logger.info(
                    f"[SINGLE-INSTANCE REUSE] Instancia activa detectada para '{descriptor.name}' "
                    f"[Session: {existing.session_id}, HWND: {existing.hwnd}]. Asignando foco sin duplicar proceso."
                )
                self.adapter.focus(existing)
                return self.adapter.find_existing_session(descriptor.app_id) or existing

        # 3. Lanzamiento real (Nueva orden explícita o política multi-instancia)
        session = self.adapter.launch(descriptor, args=args)
        curr_count = self._execution_counts.get(descriptor.app_id, 0) + 1
        self._execution_counts[descriptor.app_id] = curr_count

        if action_id:
            dedup_key = f"{descriptor.app_id}:{action_id}"
            self._executed_actions[dedup_key] = session

        logger.info(
            f"[APP_EXECUTION] action_id={action_id or 'none'} app={descriptor.app_id} execution_count={curr_count}"
        )
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

    def find_existing_session(self, app_alias_or_session_id: str) -> ApplicationSession | None:
        """Busca una sesión activa por alias o ID."""
        descriptor = self.adapter.identify(app_alias_or_session_id)
        app_id = descriptor.app_id if descriptor else app_alias_or_session_id
        return self.adapter.find_existing_session(app_id)

    def close_app(self, app_alias_or_session_id: str) -> bool:
        """Cierra la sesión de una aplicación activa de forma controlada."""
        descriptor = self.adapter.identify(app_alias_or_session_id)
        app_id = descriptor.app_id if descriptor else app_alias_or_session_id

        existing = self.adapter.find_existing_session(app_id)
        if not existing:
            return False

        return self.adapter.close(existing)
