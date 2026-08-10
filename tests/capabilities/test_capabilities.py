"""Pruebas de modelos e inmutabilidad de Capabilities (Subetapa 06.1)."""

from __future__ import annotations

import pytest

from core.capabilities import (
    CapabilityDecision,
    CapabilityOperation,
    CapabilityRiskLevel,
    CapabilitySource,
    CapabilityStatus,
    ToolCapability,
)


def test_capability_creation_and_immutability() -> None:
    op = CapabilityOperation(
        operation_id="op_read",
        name="read_file",
        description="Leer un archivo",
        risk_level=CapabilityRiskLevel.SAFE,
        decision=CapabilityDecision.ALLOW,
    )

    cap = ToolCapability(
        capability_id="cap_file_reader_v1",
        tool_name="file_reader",
        display_name="File Reader",
        description="Lector de archivos",
        version="1.0.0",
        source=CapabilitySource.BUILTIN,
        status=CapabilityStatus.ENABLED,
        operations=(op,),
        is_immutable=True,
    )

    assert cap.tool_name == "file_reader"
    assert cap.is_immutable is True
    assert len(cap.operations) == 1
    assert cap.get_operation("read_file") == op

    # Probar que dataclass es congelada e inmutable
    with pytest.raises(AttributeError):
        cap.tool_name = "hacked_tool"  # type: ignore[misc]

    with pytest.raises(AttributeError):
        op.risk_level = CapabilityRiskLevel.SAFE  # type: ignore[misc]


def test_capability_get_operation_case_insensitive() -> None:
    op = CapabilityOperation(
        operation_id="op_del",
        name="Delete_File",
        description="Eliminar archivo",
        risk_level=CapabilityRiskLevel.DANGEROUS,
        decision=CapabilityDecision.REQUIRE_CONFIRMATION,
    )

    cap = ToolCapability(
        capability_id="cap_del_v1",
        tool_name="deleter",
        display_name="Deleter",
        description="Deleter",
        version="1.0.0",
        source=CapabilitySource.SYSTEM,
        operations=(op,),
    )

    assert cap.get_operation("delete_file") == op
    assert cap.get_operation("DELETE_FILE") == op
    assert cap.get_operation("non_existent") is None
