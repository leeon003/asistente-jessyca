"""Gestor de Git Worktrees reales para el laboratorio y pruebas controladas de ORCA + ADE.

Fase 2 — Controlled Integration.
Utiliza el binario de Git del sistema operativo para crear worktrees reales,
verificar aislamiento estricto entre ramas de trabajo y detectar colisiones.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Any

from core.logger import get_logger

logger = get_logger("jessyca.lab.orca_ade.worktree_manager")


class RealGitWorktreeManager:
    """Administrador de repositorios y worktrees de Git reales para pruebas de laboratorio."""

    def __init__(self, repo_dir: str | None = None) -> None:
        if repo_dir:
            self.repo_dir = os.path.realpath(repo_dir)
            self._is_temp = False
        else:
            self.repo_dir = os.path.realpath(tempfile.mkdtemp(prefix="jessyca_real_git_repo_"))
            self._is_temp = True

        self.worktrees_dir = os.path.join(self.repo_dir, "worktrees")
        os.makedirs(self.worktrees_dir, exist_ok=True)
        self._active_worktrees: dict[str, dict[str, Any]] = {}
        self._init_git_repository()

    def _run_git(self, args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        target_cwd = cwd or self.repo_dir
        cmd = ["git"] + args
        res = subprocess.run(
            cmd,
            cwd=target_cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        return res

    def _init_git_repository(self) -> None:
        """Inicializa un repositorio Git real con commit inicial."""
        self._run_git(["init"])
        self._run_git(["config", "user.name", "Jessyca Test Agent"])
        self._run_git(["config", "user.email", "agent@jessyca.local"])

        # Crear archivo base compartido
        base_file = os.path.join(self.repo_dir, "shared_file.txt")
        with open(base_file, "w", encoding="utf-8") as f:
            f.write("Línea base compartida 1\nLínea base compartida 2\n")

        readme_file = os.path.join(self.repo_dir, "README.md")
        with open(readme_file, "w", encoding="utf-8") as f:
            f.write("# Repositorio de Pruebas ORCA ADE\n")

        self._run_git(["add", "."])
        self._run_git(["commit", "-m", "Initial commit"])

    def create_worktree(self, task_id: str, branch_name: str) -> dict[str, Any]:
        """Crea un worktree de Git real en una rama independiente."""
        wt_path = os.path.realpath(os.path.join(self.worktrees_dir, task_id))
        if os.path.exists(wt_path):
            shutil.rmtree(wt_path, ignore_errors=True)

        res = self._run_git(["worktree", "add", "-b", branch_name, wt_path, "HEAD"])
        if res.returncode != 0:
            raise RuntimeError(f"Failed to create git worktree: {res.stderr.strip()}")

        info = {
            "task_id": task_id,
            "branch_name": branch_name,
            "path": wt_path,
            "active": True,
        }
        self._active_worktrees[task_id] = info
        return info

    def remove_worktree(self, task_id: str) -> bool:
        """Elimina un worktree de Git real y limpia la rama."""
        if task_id not in self._active_worktrees:
            return False

        info = self._active_worktrees[task_id]
        wt_path = info["path"]
        branch = info["branch_name"]

        self._run_git(["worktree", "remove", "--force", wt_path])
        self._run_git(["branch", "-D", branch])

        if os.path.exists(wt_path):
            shutil.rmtree(wt_path, ignore_errors=True)

        del self._active_worktrees[task_id]
        return True

    def detect_collision(
        self,
        task_id_a: str,
        task_id_b: str,
        filename: str = "shared_file.txt",
    ) -> dict[str, Any]:
        """Comprueba si dos agentes en worktrees independientes tienen cambios conflictivos sobre el mismo archivo."""
        if task_id_a not in self._active_worktrees or task_id_b not in self._active_worktrees:
            raise ValueError("Both tasks must have active worktrees")

        path_a = os.path.join(self._active_worktrees[task_id_a]["path"], filename)
        path_b = os.path.join(self._active_worktrees[task_id_b]["path"], filename)

        if not os.path.exists(path_a) or not os.path.exists(path_b):
            return {"conflict": False, "reason": "File does not exist in both workspaces"}

        with open(path_a, "r", encoding="utf-8") as fa:
            content_a = fa.read()

        with open(path_b, "r", encoding="utf-8") as fb:
            content_b = fb.read()

        has_conflict = (content_a != content_b)
        return {
            "conflict": has_conflict,
            "task_a": task_id_a,
            "task_b": task_id_b,
            "target_file": filename,
            "content_a_len": len(content_a),
            "content_b_len": len(content_b),
            "isolated": True,
            "resolution_policy": "ISOLATE_AND_NOTIFY_JDE",
        }

    def cleanup(self) -> None:
        """Limpia todos los worktrees y directorios temporales."""
        for task_id in list(self._active_worktrees.keys()):
            try:
                self.remove_worktree(task_id)
            except Exception:
                pass
        self._run_git(["worktree", "prune"])

        if self._is_temp and os.path.exists(self.repo_dir):
            try:
                shutil.rmtree(self.repo_dir, ignore_errors=True)
            except Exception:
                pass
