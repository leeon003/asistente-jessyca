"""Pruebas del CapabilityRegistry (Subetapa 06.1)."""

from __future__ import annotations

import pytest

from core.capabilities import (
    CapabilityDecision,
    CapabilityOperation,
    CapabilityRiskLevel,
    CapabilitySource,
    ToolCapability,
)
from core.capability_registry import CapabilityRegistry
from core.exceptions import SecurityValidationError


def test_registry_registration_and_lookup() -> None:
    registry = CapabilityRegistry()

    op = CapabilityOperation(
        operation_id="op_list",
        name="list_dir",
        description="Listar directorio",
        risk_level=CapabilityRiskLevel.SAFE,
        decision=CapabilityDecision.ALLOW,
    )

    cap = ToolCapability(
        capability_id="cap_fs_v1",
        tool_name="fs_tool",
        display_name="FS Tool",
        description="Tool FS",
        version="1.0.0",
        source=CapabilitySource.BUILTIN,
        operations=(op,),
        is_immutable=True,
    )

    registry.register(cap)

    assert registry.has_tool("fs_tool") is True
    assert registry.has_operation("fs_tool", "list_dir") is True
    assert registry.get_tool("fs_tool") == cap
    assert registry.get_operation("fs_tool", "list_dir") == op
    assert "fs_tool" in registry.list_tools()


def test_registry_rejects_duplicate_registration() -> None:
    registry = CapabilityRegistry()

    cap = ToolCapability(
        capability_id="cap_fs_v1",
        tool_name="fs_tool",
        display_name="FS Tool",
        description="Tool FS",
        version="1.0.0",
        source=CapabilitySource.BUILTIN,
    )

    registry.register(cap)

    with pytest.raises(SecurityValidationError):
        registry.register(cap)


def test_registry_prevents_unregistration_of_immutable_capability() -> None:
    registry = CapabilityRegistry()

    cap = ToolCapability(
        capability_id="cap_immutable_v1",
        tool_name="immutable_tool",
        display_name="Immutable Tool",
        description="Descr",
        version="1.0.0",
        source=CapabilitySource.SYSTEM,
        is_immutable=True,
    )

    registry.register(cap)

    with pytest.raises(SecurityValidationError):
        registry.unregister("cap_immutable_v1")


def test_registry_lock_seals_modifications() -> None:
    registry = CapabilityRegistry()
    registry.lock_registry()

    assert registry.is_locked is True

    cap = ToolCapability(
        capability_id="cap_after_lock",
        tool_name="locked_tool",
        display_name="Locked Tool",
        description="Descr",
        version="1.0.0",
        source=CapabilitySource.SYSTEM,
    )

    with pytest.raises(SecurityValidationError):
        registry.register(cap)
