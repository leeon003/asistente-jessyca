"""Pruebas unitarias completas del Mecanismo Estructurado de Confirmación (ConfirmationManager y ConfirmationRequest)."""

from __future__ import annotations

from typing import Any

from core.confirmation import ConfirmationManager
from core.event_bus import EventBus
from core.security import (
    PermissionAction,
    RiskLevel,
    SecurityManager,
    SecurityPolicy,
    SecurityStatus,
    ToolSecurityProfile,
)


def test_create_structured_confirmation_request() -> None:
    mgr = ConfirmationManager()
    msg = "Esta acción eliminará 25 archivos en 'C:\\Temp'. ¿Deseas continuar?"
    impact = {"file_count": 25, "action": "delete", "target_dir": "C:\\Temp"}

    req = mgr.create_request(
        tool_name="delete_files_tool",
        message=msg,
        risk_level=RiskLevel.DANGEROUS,
        impact_summary=impact,
    )

    assert req.request_id is not None
    assert req.tool_name == "delete_files_tool"
    assert req.message == msg
    assert req.risk_level == RiskLevel.DANGEROUS
    assert req.impact_summary["file_count"] == 25
    assert req.status == "pending"
    assert PermissionAction.ALLOW_ONCE in req.available_actions
    assert PermissionAction.ALWAYS_ALLOW in req.available_actions
    assert PermissionAction.DENY in req.available_actions


def test_list_and_get_pending_requests() -> None:
    mgr = ConfirmationManager()
    req = mgr.create_request(
        tool_name="clean_disk",
        message="Esta acción eliminará 25 archivos. ¿Deseas continuar?",
    )

    pending_list = mgr.list_pending_requests()
    assert len(pending_list) == 1
    assert pending_list[0].request_id == req.request_id

    retrieved = mgr.get_pending_request(req.request_id)
    assert retrieved is not None
    assert retrieved.tool_name == "clean_disk"


def test_resolve_confirmation_request_allow_once() -> None:
    sec = SecurityManager(policy=SecurityPolicy(require_admin_for_critical=False))
    mgr = ConfirmationManager(security_manager=sec)

    req = mgr.create_request(
        tool_name="delete_bulk_files",
        message="Esta acción eliminará 25 archivos. ¿Deseas continuar?",
        risk_level=RiskLevel.DANGEROUS,
    )

    profile = ToolSecurityProfile(name="delete_bulk_files", category="filesystem", risk_level=RiskLevel.DANGEROUS)

    # Resolver con ALLOW_ONCE
    decision = mgr.resolve_request(req.request_id, selected_action=PermissionAction.ALLOW_ONCE, profile=profile)
    assert decision.is_allowed is True
    assert decision.status == SecurityStatus.ALLOWED
    assert decision.action == PermissionAction.ALLOW_ONCE
    assert decision.confirmation_request is not None
    assert decision.confirmation_request.status == "approved"

    # Verificar que ya no está pendiente
    assert mgr.get_pending_request(req.request_id) is None


def test_resolve_confirmation_request_deny() -> None:
    sec = SecurityManager()
    mgr = ConfirmationManager(security_manager=sec)

    req = mgr.create_request(
        tool_name="format_partition",
        message="Esta acción formateará el disco. ¿Deseas continuar?",
        risk_level=RiskLevel.CRITICAL,
    )

    profile = ToolSecurityProfile(name="format_partition", category="system", risk_level=RiskLevel.CRITICAL)

    # Resolver con DENY
    decision = mgr.resolve_request(req.request_id, selected_action=PermissionAction.DENY, profile=profile)
    assert decision.is_allowed is False
    assert decision.action == PermissionAction.DENY
    assert decision.confirmation_request.status == "rejected"


def test_event_bus_confirmation_notifications() -> None:
    bus = EventBus()
    received_requested: list[dict[str, Any]] = []
    received_resolved: list[dict[str, Any]] = []

    bus.subscribe("confirmation:requested", lambda event: received_requested.append(event.payload))
    bus.subscribe("confirmation:resolved", lambda event: received_resolved.append(event.payload))

    mgr = ConfirmationManager(event_bus=bus)

    # 1. Crear solicitud -> Emite confirmation:requested
    req = mgr.create_request(
        tool_name="delete_files",
        message="Esta acción eliminará 25 archivos. ¿Deseas continuar?",
        impact_summary={"file_count": 25},
    )

    assert len(received_requested) == 1
    assert received_requested[0]["request_id"] == req.request_id
    assert received_requested[0]["message"] == "Esta acción eliminará 25 archivos. ¿Deseas continuar?"

    # 2. Resolver solicitud -> Emite confirmation:resolved
    mgr.resolve_request(req.request_id, selected_action=PermissionAction.ALLOW_ONCE)
    assert len(received_resolved) == 1
    assert received_resolved[0]["request_id"] == req.request_id
    assert received_resolved[0]["action"] == PermissionAction.ALLOW_ONCE.value
    assert received_resolved[0]["status"] == "approved"
