"""Sandbox de Aislamiento de Worktrees para el Laboratorio de ORCA + ADE.

Permite simular y gestionar ramas de trabajo temporales (Git Worktrees)
con estricta verificación de rutas y contención de permisos.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.lab.orca_ade.sandbox")

_SAFE_BRANCH_REGEX = re.compile(r"^[a-zA-Z0-9_\-\./]+$")


@dataclass
class SandboxedWorktree:
    """Representación de un worktree aislado en el laboratorio."""

    worktree_id: str
    branch_name: str
    path: str
    is_active: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class OrcaWorktreeSandbox:
    """Controlador seguro de worktrees para pruebas de laboratorio."""

    def __init__(self, root_dir: str | None = None) -> None:
        if root_dir:
            self.root_dir = os.path.realpath(root_dir)
            os.makedirs(self.root_dir, exist_ok=True)
            self._is_temp = False
        else:
            self.root_dir = os.path.realpath(tempfile.mkdtemp(prefix="jessyca_orca_sandbox_"))
            self._is_temp = True

        self._active_worktrees: dict[str, SandboxedWorktree] = {}

    def cleanup_all(self) -> None:
        """Limpia todos los worktrees y directorios temporales."""
        self._active_worktrees.clear()
        if self._is_temp and os.path.exists(self.root_dir):
            try:
                shutil.rmtree(self.root_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Error cleaning up sandbox root: {e}")

    def create_worktree(self, worktree_id: str, branch_name: str) -> SandboxedWorktree:
        """Crea un entorno de trabajo aislado bajo el directorio raíz del sandbox."""
        if not worktree_id or not _SAFE_BRANCH_REGEX.match(worktree_id):
            raise ValueError(f"Invalid worktree_id: {worktree_id}")

        if not branch_name or not _SAFE_BRANCH_REGEX.match(branch_name):
            raise ValueError(f"Invalid branch_name: {branch_name}")

        if ".." in branch_name or ".." in worktree_id:
            raise ValueError("Path traversal in worktree definition")

        target_path = os.path.realpath(os.path.join(self.root_dir, worktree_id))

        # Comprobar confinamiento
        try:
            common = os.path.commonpath([self.root_dir, target_path])
            if common != self.root_dir:
                raise ValueError("Target path escapes sandbox root")
        except ValueError:
            raise ValueError("Target path escapes sandbox root")

        os.makedirs(target_path, exist_ok=True)

        # Crear archivo marcador de metadatos
        marker_file = os.path.join(target_path, ".orca_worktree_meta.json")
        with open(marker_file, "w", encoding="utf-8") as f:
            f.write(f'{{"id": "{worktree_id}", "branch": "{branch_name}"}}')

        wt = SandboxedWorktree(
            worktree_id=worktree_id,
            branch_name=branch_name,
            path=target_path,
            is_active=True,
        )
        self._active_worktrees[worktree_id] = wt
        return wt

    def remove_worktree(self, worktree_id: str) -> bool:
        """Elimina un worktree del sandbox asegurando que permanece dentro de los límites."""
        if worktree_id not in self._active_worktrees:
            return False

        wt = self._active_worktrees[worktree_id]
        if os.path.exists(wt.path):
            shutil.rmtree(wt.path, ignore_errors=True)

        wt.is_active = False
        del self._active_worktrees[worktree_id]
        return True

    def list_worktrees(self) -> list[SandboxedWorktree]:
        return list(self._active_worktrees.values())
