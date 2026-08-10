"""Abstracción backend de interacción con el Registro de Windows (Subetapa 06.4 - READ ONLY).

GARANTÍA DE CERO SHELL EXECUTION:
NO utiliza reg.exe, subprocess, os.system, powershell ni cmd.
Implementa `WindowsWinregBackend` utilizando el módulo nativo winreg de Python en Windows,
y `FakeRegistryBackend` como mock en memoria para pruebas y entornos fuera de Windows.
"""

from __future__ import annotations

import sys
from typing import Any, Protocol

from core.logger import get_logger
from tools.registry.errors import (
    RegistryAccessDeniedError,
    RegistryError,
    RegistryNotFoundError,
)
from tools.registry.models import (
    RegistryKeyInfo,
    RegistrySubKey,
    RegistryValue,
    RegistryValueInfo,
)

logger = get_logger("jessyca.tools.registry.backend")

# Intentar importar winreg únicamente en Windows
try:
    import winreg  # type: ignore

    HAS_WINREG = True
except ImportError:
    winreg = None
    HAS_WINREG = False


class IRegistryBackend(Protocol):
    """Protocolo de interfaz para el backend de lectura del Registro."""

    def list_subkeys(self, hive: str, sub_key_path: str, max_subkeys: int) -> tuple[RegistrySubKey, ...]:
        ...

    def get_key_info(self, hive: str, sub_key_path: str) -> RegistryKeyInfo:
        ...

    def list_values(
        self, hive: str, sub_key_path: str, max_values: int, max_value_size: int
    ) -> tuple[RegistryValue, ...]:
        ...

    def get_value(
        self, hive: str, sub_key_path: str, value_name: str, max_value_size: int
    ) -> RegistryValueInfo:
        ...


class FakeRegistryBackend:
    """Backend Mock en memoria para pruebas y plataformas sin Registro nativo."""

    def __init__(self) -> None:
        # Estructura: {(hive, sub_key_path): {"subkeys": [name1, name2], "values": {val_name: (val_type, val_data)}}}
        self._store: dict[tuple[str, str], dict[str, Any]] = {}
        self._setup_defaults()

    def _setup_defaults(self) -> None:
        """Inicializa claves y valores de prueba por defecto."""
        self.set_key(
            "HKEY_CURRENT_USER",
            "Software\\JessycaMCP",
            subkeys=["Settings", "Plugins"],
            values={
                "Version": ("REG_SZ", "0.6.4"),
                "Debug": ("REG_DWORD", 1),
                "SecretToken": ("REG_SZ", "redacted_token_value"),
            },
        )
        self.set_key(
            "HKEY_CURRENT_USER",
            "Software\\JessycaMCP\\Settings",
            subkeys=[],
            values={"Theme": ("REG_SZ", "Dark"), "MaxThreads": ("REG_DWORD", 4)},
        )
        self.set_key(
            "HKEY_LOCAL_MACHINE",
            "SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion",
            subkeys=["ProfileList"],
            values={"ProductName": ("REG_SZ", "Windows 11 Pro"), "CurrentBuild": ("REG_SZ", "22631")},
        )

    def set_key(
        self,
        hive: str,
        sub_key_path: str,
        subkeys: list[str] | None = None,
        values: dict[str, tuple[str, Any]] | None = None,
    ) -> None:
        """Inserta o actualiza una clave en el almacenamiento mock."""
        key = (hive.upper(), sub_key_path.strip("\\"))
        self._store[key] = {
            "subkeys": subkeys or [],
            "values": values or {},
        }

    def list_subkeys(self, hive: str, sub_key_path: str, max_subkeys: int) -> tuple[RegistrySubKey, ...]:
        key = (hive.upper(), sub_key_path.strip("\\"))
        if key not in self._store:
            raise RegistryNotFoundError(hive, sub_key_path)

        data = self._store[key]
        result: list[RegistrySubKey] = []
        base_path = sub_key_path.strip("\\")

        for name in data["subkeys"][:max_subkeys]:
            child_path = f"{base_path}\\{name}" if base_path else name
            result.append(RegistrySubKey(name=name, sub_key_path=child_path))

        return tuple(result)

    def get_key_info(self, hive: str, sub_key_path: str) -> RegistryKeyInfo:
        key = (hive.upper(), sub_key_path.strip("\\"))
        if key not in self._store:
            raise RegistryNotFoundError(hive, sub_key_path)

        data = self._store[key]
        return RegistryKeyInfo(
            hive=hive,
            key_path=sub_key_path,
            subkeys_count=len(data["subkeys"]),
            values_count=len(data["values"]),
            last_modified=1700000000.0,
        )

    def list_values(
        self, hive: str, sub_key_path: str, max_values: int, max_value_size: int
    ) -> tuple[RegistryValue, ...]:
        key = (hive.upper(), sub_key_path.strip("\\"))
        if key not in self._store:
            raise RegistryNotFoundError(hive, sub_key_path)

        data = self._store[key]
        result: list[RegistryValue] = []

        for name, (val_type, val_data) in list(data["values"].items())[:max_values]:
            result.append(RegistryValue(name=name, value_type=val_type, value_data=val_data))

        return tuple(result)

    def get_value(
        self, hive: str, sub_key_path: str, value_name: str, max_value_size: int
    ) -> RegistryValueInfo:
        key = (hive.upper(), sub_key_path.strip("\\"))
        if key not in self._store:
            raise RegistryNotFoundError(hive, sub_key_path)

        data = self._store[key]
        if value_name not in data["values"]:
            raise RegistryNotFoundError(hive, sub_key_path, value_name=value_name)

        val_type, val_data = data["values"][value_name]
        return RegistryValueInfo(
            hive=hive,
            key_path=sub_key_path,
            value_name=value_name,
            value_type=val_type,
            value_data=val_data,
        )


class WindowsWinregBackend:
    """Backend real utilizando la API nativa winreg de Windows (READ ONLY)."""

    HIVE_MAPPING = {
        "HKEY_CURRENT_USER": getattr(winreg, "HKEY_CURRENT_USER", None),
        "HKEY_LOCAL_MACHINE": getattr(winreg, "HKEY_LOCAL_MACHINE", None),
    }

    TYPE_MAPPING = {
        getattr(winreg, "REG_SZ", 1): "REG_SZ",
        getattr(winreg, "REG_EXPAND_SZ", 2): "REG_EXPAND_SZ",
        getattr(winreg, "REG_BINARY", 3): "REG_BINARY",
        getattr(winreg, "REG_DWORD", 4): "REG_DWORD",
        getattr(winreg, "REG_MULTI_SZ", 7): "REG_MULTI_SZ",
        getattr(winreg, "REG_QWORD", 11): "REG_QWORD",
    }

    def _get_hkey(self, hive: str) -> Any:
        hive_clean = hive.upper()
        if hive_clean not in self.HIVE_MAPPING or self.HIVE_MAPPING[hive_clean] is None:
            raise RegistryError(f"Hive del Registro no soportado: '{hive}'")
        return self.HIVE_MAPPING[hive_clean]

    def list_subkeys(self, hive: str, sub_key_path: str, max_subkeys: int) -> tuple[RegistrySubKey, ...]:
        if not HAS_WINREG or winreg is None:
            raise RegistryError("Módulo nativo winreg no disponible en este entorno.")

        hkey_root = self._get_hkey(hive)

        try:
            with winreg.OpenKey(hkey_root, sub_key_path, 0, winreg.KEY_READ) as key:
                subkeys_count, _, _ = winreg.QueryInfoKey(key)
                result: list[RegistrySubKey] = []
                base_path = sub_key_path.strip("\\")

                for i in range(min(subkeys_count, max_subkeys)):
                    try:
                        name = winreg.EnumKey(key, i)
                        child_path = f"{base_path}\\{name}" if base_path else name
                        result.append(RegistrySubKey(name=name, sub_key_path=child_path))
                    except OSError:
                        break

                return tuple(result)
        except FileNotFoundError:
            raise RegistryNotFoundError(hive, sub_key_path)
        except PermissionError:
            raise RegistryAccessDeniedError(hive, sub_key_path)
        except OSError as e:
            raise RegistryError(f"Error al abrir la clave '{hive}\\{sub_key_path}': {e}")

    def get_key_info(self, hive: str, sub_key_path: str) -> RegistryKeyInfo:
        if not HAS_WINREG or winreg is None:
            raise RegistryError("Módulo nativo winreg no disponible en este entorno.")

        hkey_root = self._get_hkey(hive)

        try:
            with winreg.OpenKey(hkey_root, sub_key_path, 0, winreg.KEY_READ) as key:
                subkeys_count, values_count, last_mod = winreg.QueryInfoKey(key)
                return RegistryKeyInfo(
                    hive=hive,
                    key_path=sub_key_path,
                    subkeys_count=subkeys_count,
                    values_count=values_count,
                    last_modified=float(last_mod) if last_mod else None,
                )
        except FileNotFoundError:
            raise RegistryNotFoundError(hive, sub_key_path)
        except PermissionError:
            raise RegistryAccessDeniedError(hive, sub_key_path)
        except OSError as e:
            raise RegistryError(f"Error al obtener información de '{hive}\\{sub_key_path}': {e}")

    def list_values(
        self, hive: str, sub_key_path: str, max_values: int, max_value_size: int
    ) -> tuple[RegistryValue, ...]:
        if not HAS_WINREG or winreg is None:
            raise RegistryError("Módulo nativo winreg no disponible en este entorno.")

        hkey_root = self._get_hkey(hive)

        try:
            with winreg.OpenKey(hkey_root, sub_key_path, 0, winreg.KEY_READ) as key:
                _, values_count, _ = winreg.QueryInfoKey(key)
                result: list[RegistryValue] = []

                for i in range(min(values_count, max_values)):
                    try:
                        v_name, v_data, v_type = winreg.EnumValue(key, i)
                        type_str = self.TYPE_MAPPING.get(v_type, f"REG_UNKNOWN({v_type})")

                        # Truncar binarios excesivamente grandes
                        if isinstance(v_data, bytes) and len(v_data) > max_value_size:
                            v_data = f"<binary_data_truncated_{len(v_data)}_bytes>"

                        result.append(RegistryValue(name=v_name, value_type=type_str, value_data=v_data))
                    except OSError:
                        break

                return tuple(result)
        except FileNotFoundError:
            raise RegistryNotFoundError(hive, sub_key_path)
        except PermissionError:
            raise RegistryAccessDeniedError(hive, sub_key_path)
        except OSError as e:
            raise RegistryError(f"Error al listar valores de '{hive}\\{sub_key_path}': {e}")

    def get_value(
        self, hive: str, sub_key_path: str, value_name: str, max_value_size: int
    ) -> RegistryValueInfo:
        if not HAS_WINREG or winreg is None:
            raise RegistryError("Módulo nativo winreg no disponible en este entorno.")

        hkey_root = self._get_hkey(hive)

        try:
            with winreg.OpenKey(hkey_root, sub_key_path, 0, winreg.KEY_READ) as key:
                v_data, v_type = winreg.QueryValueEx(key, value_name)
                type_str = self.TYPE_MAPPING.get(v_type, f"REG_UNKNOWN({v_type})")

                if isinstance(v_data, bytes) and len(v_data) > max_value_size:
                    v_data = f"<binary_data_truncated_{len(v_data)}_bytes>"

                return RegistryValueInfo(
                    hive=hive,
                    key_path=sub_key_path,
                    value_name=value_name,
                    value_type=type_str,
                    value_data=v_data,
                )
        except FileNotFoundError:
            raise RegistryNotFoundError(hive, sub_key_path, value_name=value_name)
        except PermissionError:
            raise RegistryAccessDeniedError(hive, sub_key_path)
        except OSError as e:
            raise RegistryError(f"Error al consultar el valor '{value_name}' en '{hive}\\{sub_key_path}': {e}")


def get_default_registry_backend() -> IRegistryBackend:
    """Fábrica para obtener el backend de Registro apropiado según el sistema operativo."""
    if sys.platform == "win32" and HAS_WINREG:
        logger.info("Utilizando backend nativo del Registro de Windows (WindowsWinregBackend).")
        return WindowsWinregBackend()
    logger.info("Utilizando backend simulado en memoria del Registro (FakeRegistryBackend).")
    return FakeRegistryBackend()
