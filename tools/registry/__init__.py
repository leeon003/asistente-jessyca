"""Módulo de herramientas de lectura e inspección segura del Registro de Windows (windows.registry - Subetapa 06.4)."""

from tools.registry.backend import (
    FakeRegistryBackend,
    IRegistryBackend,
    WindowsWinregBackend,
    get_default_registry_backend,
)
from tools.registry.errors import (
    InvalidHiveError,
    RegistryAccessDeniedError,
    RegistryDepthLimitError,
    RegistryError,
    RegistryNotFoundError,
    RegistryPathError,
    RegistrySizeLimitError,
)
from tools.registry.executor import WindowsRegistryToolExecutor
from tools.registry.key_tool import (
    WindowsGetRegistryKeyTool,
    WindowsListRegistrySubkeysTool,
)
from tools.registry.models import (
    RegistryKeyInfo,
    RegistryKeyPath,
    RegistryQueryResult,
    RegistrySubKey,
    RegistryValue,
    RegistryValueInfo,
)
from tools.registry.path_security import RegistryPathSecurityManager
from tools.registry.registry_service import RegistryService
from tools.registry.value_tool import (
    WindowsGetRegistryValueTool,
    WindowsListRegistryValuesTool,
)
from tools.tool_registry import ToolRegistry, get_tool_registry

__all__ = [
    "RegistryError",
    "RegistryPathError",
    "InvalidHiveError",
    "RegistryNotFoundError",
    "RegistryAccessDeniedError",
    "RegistryDepthLimitError",
    "RegistrySizeLimitError",
    "RegistryKeyPath",
    "RegistryValue",
    "RegistrySubKey",
    "RegistryKeyInfo",
    "RegistryValueInfo",
    "RegistryQueryResult",
    "RegistryPathSecurityManager",
    "IRegistryBackend",
    "FakeRegistryBackend",
    "WindowsWinregBackend",
    "get_default_registry_backend",
    "RegistryService",
    "WindowsRegistryToolExecutor",
    "WindowsListRegistrySubkeysTool",
    "WindowsGetRegistryKeyTool",
    "WindowsListRegistryValuesTool",
    "WindowsGetRegistryValueTool",
    "ToolRegistry",
    "get_tool_registry",
]
