"""Tests de Confinamiento de Permisos y Sandbox: ORCA + ADE (Fase 1)."""

from __future__ import annotations

import os
import pytest

from core.orca_ade.adapter import OrcaAdeAdapter
from core.orca_ade.models import OrcaAdeMode
from lab.orca_ade.sandbox import OrcaWorktreeSandbox


class TestOrcaAdePermissions:
    """Verifica que el entorno no posea permisos fuera del sandbox acotado."""

    def test_sandbox_worktree_confinement(self) -> None:
        sandbox = OrcaWorktreeSandbox()
        try:
            wt = sandbox.create_worktree("wt_test_01", "feature/auth")
            assert os.path.exists(wt.path)
            assert wt.path.startswith(sandbox.root_dir)

            # Intentar crear fuera del sandbox
            with pytest.raises(ValueError, match="(traversal|Invalid)"):
                sandbox.create_worktree("../escape_dir", "branch_escape")

            # Remoción segura
            removed = sandbox.remove_worktree("wt_test_01")
            assert removed is True
            assert not os.path.exists(wt.path)
        finally:
            sandbox.cleanup_all()

    def test_no_arbitrary_system_execution(self) -> None:
        # El adapter no posee métodos para invocar shells reales
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
        assert not hasattr(adapter, "spawn_shell")
        assert not hasattr(adapter, "execute_bash")
        assert not hasattr(adapter, "execute_powershell")

    def test_sandbox_cleanup_leaves_no_traces(self) -> None:
        sandbox = OrcaWorktreeSandbox()
        root = sandbox.root_dir
        sandbox.create_worktree("wt_clean_01", "branch1")
        sandbox.create_worktree("wt_clean_02", "branch2")
        assert len(sandbox.list_worktrees()) == 2

        sandbox.cleanup_all()
        assert len(sandbox.list_worktrees()) == 0
        assert not os.path.exists(root)
