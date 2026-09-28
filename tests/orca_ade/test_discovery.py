"""Tests de Descubrimiento e Identificación Técnica: ORCA + ADE (Fase 1)."""

from __future__ import annotations

import os
import pytest

from core.orca_ade.adapter import OrcaAdeAdapter
from core.orca_ade.models import OrcaAdeMode


class TestOrcaAdeDiscovery:
    """Verifica que el conocimiento sobre ORCA y ADE esté validado técnicamente."""

    def test_orca_ade_identity_and_metadata(self) -> None:
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
        assert adapter.name == "orca_ade"
        assert any(v in adapter.version for v in ("1.0.0", "2.0.0"))
        assert adapter.mode == OrcaAdeMode.LAB

    def test_official_capabilities_registered(self) -> None:
        adapter = OrcaAdeAdapter(mode=OrcaAdeMode.LAB)
        caps = {c.name for c in adapter.capabilities}
        assert "worktree_isolation" in caps
        assert "parallel_agent_dispatch" in caps
        assert "design_mode_inspection" in caps

    def test_license_and_origin_verification(self) -> None:
        # Verificamos que el reporte de licencia existe y dictamina compatibilidad
        license_report = os.path.join("reports", "orca_ade_license_audit.md")
        assert os.path.exists(license_report)
        with open(license_report, "r", encoding="utf-8") as f:
            content = f.read()
        assert "MIT License" in content
        assert "Lovecast Inc." in content
        assert "COMPATIBLE" in content

    def test_architecture_documentation_exists(self) -> None:
        arch_report = os.path.join("reports", "orca_ade_architecture.md")
        assert os.path.exists(arch_report)
        with open(arch_report, "r", encoding="utf-8") as f:
            content = f.read()
        assert "Git Worktree" in content
        assert "stablyai/orca" in content
