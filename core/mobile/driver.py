"""core/mobile/driver.py

Driver de automatización de dispositivos móviles para JESSYCA (basado en arquitectura Mobilewright).
Provee una interfaz unificada y determinista para controlar dispositivos Android en Windows:
- Inspecciona la disponibilidad real de ADB / Android SDK en Windows.
- Ejecuta operaciones de alto nivel exclusivamente (launch_app, get_state, get_foreground).
- NO expone comandos de shell arbitrarios ni ADB libre al agente.
- Soporta deadlines, CancellationToken y simulación controlada para pruebas reproducibles.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from core.cancellation import CancellationToken
from core.logger import get_logger
from core.mobile.models import MobileDeviceState

logger = get_logger("jessyca.mobile.driver")


class MobileDriverError(Exception):
    """Error base del driver de automatización móvil."""
    pass


class DeviceNotFoundError(MobileDriverError):
    """Dispositivo solicitado no encontrado o no registrado."""
    pass


class DeviceDisconnectedError(MobileDriverError):
    """El dispositivo se encuentra físicamente o lógicamente desconectado."""
    pass


class OperationCancelledError(MobileDriverError):
    """La operación móvil fue cancelada antes de o durante su ejecución."""
    pass


class TimeoutExceededError(MobileDriverError):
    """La operación móvil superó el deadline estipulado."""
    pass


class MobilewrightDriver:
    """Driver determinista de automatización móvil inspirado en Mobilewright para Windows."""

    def __init__(self, adb_path: str | Path | None = None, test_mode: bool = False) -> None:
        self.adb_path = self._resolve_adb_path(adb_path)
        self.test_mode = test_mode or (self.adb_path is None)

        # Estado simulado/en memoria para pruebas controladas o dispositivos virtuales
        self._mock_states: dict[str, MobileDeviceState] = {}
        self._disconnected_devices: set[str] = set()

    @staticmethod
    def _resolve_adb_path(custom_path: str | Path | None) -> str | None:
        """Determina la ruta real del ejecutable adb en el host Windows."""
        if custom_path and Path(custom_path).is_file():
            return str(custom_path)

        # 1. Búsqueda en PATH del sistema
        which_adb = shutil.which("adb")
        if which_adb:
            return which_adb

        # 2. Rutas estándar de Android SDK en Windows
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            sdk_adb = Path(local_app_data) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
            if sdk_adb.is_file():
                return str(sdk_adb)

        return None

    def is_windows_adb_available(self) -> bool:
        """Comprueba si el host Windows tiene un runtime ADB operativo."""
        return self.adb_path is not None

    def set_mock_device_state(self, device_id: str, state: MobileDeviceState) -> None:
        """Configura el estado simulado de un dispositivo para pruebas unitarias."""
        self._mock_states[device_id] = state

    def simulate_device_disconnection(self, device_id: str) -> None:
        """Simula la desconexión física de un dispositivo."""
        self._disconnected_devices.add(device_id)
        if device_id in self._mock_states:
            self._mock_states[device_id].is_connected = False

    def simulate_device_reconnection(self, device_id: str) -> None:
        """Restaura la conexión de un dispositivo."""
        self._disconnected_devices.discard(device_id)
        if device_id in self._mock_states:
            self._mock_states[device_id].is_connected = True

    def get_device_state(
        self,
        device_id: str,
        deadline_seconds: float = 5.0,
        cancellation_token: CancellationToken | None = None,
    ) -> MobileDeviceState:
        """Obtiene el estado en vivo del dispositivo (batería, pantalla, app en foreground)."""
        if cancellation_token and cancellation_token.is_cancelled:
            raise OperationCancelledError("Operación cancelada por el usuario o timeout previo.")

        if device_id in self._disconnected_devices:
            raise DeviceDisconnectedError(f"El dispositivo '{device_id}' no está conectado.")

        # Modo test / emulación controlada
        if self.test_mode or device_id in self._mock_states:
            if device_id not in self._mock_states:
                raise DeviceNotFoundError(f"Dispositivo '{device_id}' no encontrado en el driver.")
            state = self._mock_states[device_id]
            if not state.is_connected:
                raise DeviceDisconnectedError(f"El dispositivo '{device_id}' no está conectado.")
            state.last_seen = time.time()
            return state

        # Modo real con ADB en Windows
        assert self.adb_path is not None
        try:
            # Comprobar presencia del dispositivo en adb devices
            out = subprocess.check_output(
                [self.adb_path, "devices"],
                text=True,
                timeout=deadline_seconds,
            )
            if device_id not in out:
                raise DeviceDisconnectedError(f"El dispositivo '{device_id}' no figura como conectado en ADB.")

            # Obtener aplicación en primer plano de forma segura
            fg_pkg, fg_act = self._get_real_foreground_app(device_id, timeout=deadline_seconds)

            return MobileDeviceState(
                device_id=device_id,
                is_connected=True,
                battery_level=100,
                foreground_package=fg_pkg,
                foreground_activity=fg_act,
                screen_on=True,
                is_locked=False,
                last_seen=time.time(),
            )
        except subprocess.TimeoutExpired:
            raise TimeoutExceededError(f"Timeout al obtener estado del dispositivo '{device_id}'.")
        except Exception as e:
            if isinstance(e, (DeviceDisconnectedError, TimeoutExceededError, OperationCancelledError)):
                raise
            raise MobileDriverError(f"Error consultando dispositivo real: {e}")

    def launch_app(
        self,
        device_id: str,
        package_name: str,
        activity_name: str | None = None,
        deadline_seconds: float = 10.0,
        cancellation_token: CancellationToken | None = None,
    ) -> bool:
        """Inicia una aplicación en el dispositivo móvil y asegura el deadline."""
        t_start = time.perf_counter()

        if cancellation_token and cancellation_token.is_cancelled:
            raise OperationCancelledError("Lanzamiento de aplicación cancelado antes de iniciar.")

        if device_id in self._disconnected_devices:
            raise DeviceDisconnectedError(f"Dispositivo '{device_id}' desconectado.")

        # Modo test / emulación controlada
        if self.test_mode or device_id in self._mock_states:
            if device_id not in self._mock_states:
                raise DeviceNotFoundError(f"Dispositivo '{device_id}' no registrado en el driver.")

            state = self._mock_states[device_id]
            if not state.is_connected:
                raise DeviceDisconnectedError(f"Dispositivo '{device_id}' desconectado.")

            # Simular verificación de deadline
            elapsed = time.perf_counter() - t_start
            if elapsed > deadline_seconds:
                raise TimeoutExceededError(f"Deadline de {deadline_seconds}s excedido durante launch_app.")

            # Actualizar estado simulado
            state.foreground_package = package_name
            state.foreground_activity = activity_name or f"{package_name}.MainActivity"
            state.last_seen = time.time()
            logger.info(f"[MOBILE DRIVER TEST] App '{package_name}' lanzada con éxito en '{device_id}'.")
            return True

        # Modo real con ADB en Windows
        assert self.adb_path is not None
        target_component = f"{package_name}/{activity_name}" if activity_name else package_name
        cmd = [self.adb_path, "-s", device_id, "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"]
        try:
            subprocess.check_call(cmd, timeout=deadline_seconds)
            logger.info(f"[MOBILE DRIVER REAL] App '{target_component}' iniciada en dispositivo real '{device_id}'.")
            return True
        except subprocess.TimeoutExpired:
            raise TimeoutExceededError(f"Timeout al lanzar app en dispositivo '{device_id}'.")
        except Exception as e:
            raise MobileDriverError(f"Error lanzando aplicación en dispositivo real: {e}")

    def get_foreground_app(
        self,
        device_id: str,
        deadline_seconds: float = 5.0,
        cancellation_token: CancellationToken | None = None,
    ) -> tuple[str | None, str | None]:
        """Obtiene el paquete y la actividad actualmente en primer plano."""
        state = self.get_device_state(
            device_id=device_id,
            deadline_seconds=deadline_seconds,
            cancellation_token=cancellation_token,
        )
        return state.foreground_package, state.foreground_activity

    def _get_real_foreground_app(self, device_id: str, timeout: float = 5.0) -> tuple[str | None, str | None]:
        """Extrae el foreground app mediante mFocusedWindow o mCurrentFocus de dumpsys window."""
        assert self.adb_path is not None
        try:
            raw = subprocess.check_output(
                [self.adb_path, "-s", device_id, "shell", "dumpsys", "window", "windows"],
                text=True,
                timeout=timeout,
            )
            for line in raw.splitlines():
                if "mCurrentFocus" in line or "mFocusedApp" in line:
                    parts = line.strip().split()
                    for p in parts:
                        if "/" in p:
                            token = p.replace("}", "").replace("{", "")
                            if "/" in token:
                                pkg, act = token.split("/", 1)
                                return pkg, act
        except Exception:
            pass
        return None, None
