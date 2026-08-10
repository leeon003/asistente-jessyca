"""Pruebas del CapabilityResolver (Subetapa 06.1)."""

from __future__ import annotations

from core.capabilities import (
    CapabilityDecision,
    CapabilityOperation,
    CapabilityRiskLevel,
    CapabilitySource,
    CapabilityStatus,
    ToolCapability,
)
from core.capability_registry import CapabilityRegistry
from core.capability_resolver import CapabilityResolver


def test_resolver_resolves_registered_operation() -> None:
    registry = CapabilityRegistry()

    op = CapabilityOperation(
        operation_id="op_read",
        name="read_file",
        description="Leer archivo",
        risk_level=CapabilityRiskLevel.SAFE,
        decision=CapabilityDecision.ALLOW,
    )

    cap = ToolCapability(
        capability_id="cap_fs_v1",
        tool_name="windows.files",
        display_name="Files",
        description="Descr",
        version="1.0.0",
        source=CapabilitySource.BUILTIN,
        operations=(op,),
    )

    registry.register(cap)
    resolver = CapabilityResolver(registry)

    res = resolver.resolve("windows.files", "read_file")

    assert res.found is True
    assert res.decision == CapabilityDecision.ALLOW
    assert res.risk_level == CapabilityRiskLevel.SAFE
    assert res.fingerprint is not None


def test_resolver_returns_deny_on_unknown_tool() -> None:
    registry = CapabilityRegistry()
    resolver = CapabilityResolver(registry)

    res = resolver.resolve("non_existent_tool", "run")

    assert res.found is False
    assert res.decision == CapabilityDecision.DENY
    assert res.risk_level == CapabilityRiskLevel.UNKNOWN


def test_resolver_returns_deny_on_unknown_operation() -> None:
    registry = CapabilityRegistry()

    cap = ToolCapability(
        capability_id="cap_tool_v1",
        tool_name="my_tool",
        display_name="My Tool",
        description="Descr",
        version="1.0.0",
        source=CapabilitySource.SYSTEM,
        operations=(),
    )

    registry.register(cap)
    resolver = CapabilityResolver(registry)

    res = resolver.resolve("my_tool", "undefined_op")

    assert res.found is False
    assert res.decision == CapabilityDecision.DENY


def test_resolver_returns_deny_on_blocked_capability() -> None:
    registry = CapabilityRegistry()

    op = CapabilityOperation(
        operation_id="op_run",
        name="run",
        description="Run",
        risk_level=CapabilityRiskLevel.SAFE,
        decision=CapabilityDecision.ALLOW,
    )

    cap = ToolCapability(
        capability_id="cap_blocked_v1",
        tool_name="blocked_tool",
        display_name="Blocked Tool",
        description="Descr",
        version="1.0.0",
        source=CapabilitySource.SYSTEM,
        status=CapabilityStatus.BLOCKED,
        operations=(op,),
    )

    registry.register(cap)
    resolver = CapabilityResolver(registry)

    res = resolver.resolve("blocked_tool", "run")

    assert res.found is True
    assert res.decision == CapabilityDecision.DENY
    assert "bloqueada" in res.reason or "BLOCKED" in res.reason
