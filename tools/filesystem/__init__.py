"""Módulo de herramientas de sistema de archivos seguro (windows.files - Subetapa 06.2)."""

from tools.filesystem.directory_tool import (
    WindowsCreateDirectoryTool,
    WindowsListDirectoryTool,
)
from tools.filesystem.errors import (
    FileNotFoundToolError,
    FileOperationError,
    FileSizeLimitError,
    FilesystemError,
    FilesystemPermissionError,
    PathSecurityError,
    PathTraversalError,
    SandboxViolationError,
    UnsafePathError,
    UnsupportedPathError,
)
from tools.filesystem.executor import WindowsFilesystemToolExecutor
from tools.filesystem.file_tool import (
    WindowsDeleteFileTool,
    WindowsReadFileTool,
    WindowsWriteFileTool,
)
from tools.filesystem.filesystem_service import FilesystemService
from tools.filesystem.models import (
    DirectoryListing,
    FileDeleteResult,
    FileEntry,
    FileReadResult,
    FileWriteResult,
    PathValidationResult,
)
from tools.filesystem.path_security import PathSecurityManager

__all__ = [
    "FilesystemError",
    "PathSecurityError",
    "SandboxViolationError",
    "PathTraversalError",
    "UnsupportedPathError",
    "FileSizeLimitError",
    "UnsafePathError",
    "FileOperationError",
    "FileNotFoundToolError",
    "FilesystemPermissionError",
    "PathValidationResult",
    "FileEntry",
    "DirectoryListing",
    "FileReadResult",
    "FileWriteResult",
    "FileDeleteResult",
    "PathSecurityManager",
    "FilesystemService",
    "WindowsFilesystemToolExecutor",
    "WindowsReadFileTool",
    "WindowsWriteFileTool",
    "WindowsDeleteFileTool",
    "WindowsListDirectoryTool",
    "WindowsCreateDirectoryTool",
]
