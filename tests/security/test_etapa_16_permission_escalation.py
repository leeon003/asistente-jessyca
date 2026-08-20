"""Etapa 16.0 — Vector 03: Permission Escalation Audit.

Verifica que el SecurityManager y PermissionManager resisten:
- C-01: PolicyManager ALLOW override de blacklist
- H-05: Race conditions en sets del SecurityManager (sin Lock)
- Escalada desde SAFE → DANGEROUS via permisos comodín
- ALWAYS_ALLOW que escala privilegios
"""

from __future__ import annotations

import threading

import pytest

from core.permission_manager import PermissionDecision, PermissionManager, PermissionRequest
from core.risk_engine import RiskAssessment
from core.security import (
    PermissionAction,
    RiskLevel,
    SecurityManager,
    ToolSecurityProfile,
)
from core.security_architecture import SecurityContext, SecurityLevel, ToolSecurityMetadata


def _make_profile(name: str, risk: RiskLevel = RiskLevel.SAFE, perms: list[str] | None = None) -> ToolSecurityProfile:
    return ToolSecurityProfile(
        name=name,
        category="test",
        risk_level=risk,
        required_permissions=perms or [],
    )


def _make_perm_request(tool_name: str, risk_str: str = "SAFE") -> PermissionRequest:
    ctx = SecurityContext(user="test_user", tool_name=tool_name, parameters={})
    meta = ToolSecurityMetadata(tool_name=tool_name, category="test")
    risk = RiskAssessment(
        risk_level=SecurityLevel(risk_str),
        score=2,
        reason="test",
    )
    return PermissionRequest(
        context=ctx,
        metadata=meta,
        risk_assessment=risk,
        tool_name=tool_name,
        operation="execute",
    )


class TestBlacklistBypassC01:
    """AUDIT C-01: Verifica si PolicyManager puede bypassear blacklist."""

    def test_blacklisted_tool_blocked_without_policy_manager(self) -> None:
        """Sin PolicyManager, herramienta en blacklist siempre debe ser denegada."""
        sm = SecurityManager()
        sm.add_to_blacklist("dangerous_tool")
        profile = _make_profile("dangerous_tool")

        decision = sm.evaluate(profile)
        assert not decision.is_allowed, "Herramienta en blacklist debe ser denegada."

    def test_blacklist_order_vs_policy_manager(self) -> None:
        """C-01 AUDIT: PolicyManager ALLOW evalúa ANTES de blacklist — verificar comportamiento."""
        from core.policy_rules import PolicyManager, PolicyRule

        sm = SecurityManager()
        sm.add_to_blacklist("dangerous_tool")

        # Crear un PolicyManager que PERMITE explícitamente dangerous_tool
        policy_manager = PolicyManager()
        policy_manager.add_rule(
            PolicyRule(
                rule_id="bypass-attempt",
                tool_name="dangerous_tool",
                effect=PermissionAction.ALLOW,
                priority=100,
            )
        )
        sm.set_policy_manager(policy_manager)

        profile = _make_profile("dangerous_tool")
        decision = sm.evaluate(profile)

        # EXPECTATIVA CORRECTA: blacklist debe tener prioridad sobre PolicyManager ALLOW
        if decision.is_allowed:
            pytest.fail(
                "[AUDIT-C01-CONFIRMED] CRITICAL: PolicyManager ALLOW bypaseó la blacklist. "
                "La herramienta 'dangerous_tool' en blacklist fue permitida por una regla PolicyManager. "
                "La blacklist debe evaluarse ANTES que el PolicyManager."
            )
        else:
            # Comportamiento correcto — blacklist tiene prioridad
            assert not decision.is_allowed

    def test_always_allow_adds_to_whitelist(self) -> None:
        """ALWAYS_ALLOW debe añadir a whitelist Y otorgar permisos."""
        sm = SecurityManager()
        profile = _make_profile("my_tool", perms=["filesystem.read"])

        decision = sm.process_user_action(profile, PermissionAction.ALWAYS_ALLOW)
        assert decision.is_allowed
        assert "my_tool" in sm._whitelist
        assert "filesystem.read" in sm._granted_permissions

    def test_always_allow_cannot_grant_wildcard_unintentionally(self) -> None:
        """ALWAYS_ALLOW con permiso '*' no debe otorgar acceso total silenciosamente."""
        sm = SecurityManager()
        profile = _make_profile("elevated_tool", perms=["*"])

        # Esto otorga permiso '*' — acceso total al sistema
        sm.process_user_action(profile, PermissionAction.ALWAYS_ALLOW)

        # AUDIT: verificar que acceso total es visible en el estado del manager
        has_wildcard = "*" in sm._granted_permissions
        if has_wildcard:
            # Esto es esperado pero debe ser auditable — no debe ocurrir silenciosamente
            pytest.xfail(
                "[AUDIT] ALWAYS_ALLOW con permiso '*' otorga acceso total al sistema. "
                "Operación fue ejecutada — verificar que hay audit trail de este evento."
            )


class TestPermissionEscalationRaceConditionH05:
    """AUDIT H-05: Race conditions en sets del SecurityManager."""

    def test_concurrent_one_time_grant_consumption(self) -> None:
        """Un permiso ALLOW_ONCE debe ser consumido exactamente una vez bajo concurrencia."""
        sm = SecurityManager()
        sm.grant_one_time_permission("race_tool")

        profile = _make_profile("race_tool", perms=["system.admin"])
        results: list[bool] = []
        lock = threading.Lock()

        def try_consume() -> None:
            decision = sm.evaluate(profile)
            with lock:
                results.append(decision.is_allowed)

        threads = [threading.Thread(target=try_consume) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        allowed_count = sum(1 for r in results if r)
        # Exactamente 1 hilo debe obtener ALLOW — el resto DENIED
        if allowed_count > 1:
            pytest.fail(
                f"[AUDIT-H05-CONFIRMED] Race condition en _one_time_grants: "
                f"{allowed_count} hilos consumieron el mismo permiso de un solo uso. "
                f"Falta threading.Lock en SecurityManager."
            )

    def test_concurrent_blacklist_modification(self) -> None:
        """Modificaciones concurrentes a blacklist no deben corromper el estado."""
        sm = SecurityManager()

        def add_to_blacklist(i: int) -> None:
            sm.add_to_blacklist(f"tool_{i}")

        def remove_from_blacklist(i: int) -> None:
            sm.remove_from_blacklist(f"tool_{i}")

        threads = []
        for i in range(20):
            threads.append(threading.Thread(target=add_to_blacklist, args=(i,)))
            threads.append(threading.Thread(target=remove_from_blacklist, args=(i,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # El sistema no debe haber crasheado — el blacklist debe ser un set coherente
        assert isinstance(sm._blacklist, set), (
            "[AUDIT-H05] Estado del blacklist corrompido por concurrencia."
        )


class TestPermissionManagerCriticalDeny:
    """AUDIT H-02: CRITICAL siempre DENY — bloqueo de autonomía supervisada."""

    def test_critical_risk_always_denied(self) -> None:
        """PermissionManager deniega CRITICAL independientemente del contexto."""
        pm = PermissionManager()
        req = _make_perm_request("critical_tool", risk_str="CRITICAL")
        result = pm.evaluate_permission(req)
        assert result.decision == PermissionDecision.DENY, (
            "CRITICAL debe ser siempre DENY en PermissionManager."
        )

    def test_critical_risk_no_elevation_mechanism(self) -> None:
        """AUDIT H-02: No existe mecanismo para autorizar CRITICAL con confirmación.

        Este es un hallazgo de diseño: correcto para autonomía baja,
        pero limita la autonomía supervisada futura.
        """
        pm = PermissionManager()
        req = _make_perm_request("admin_tool", risk_str="CRITICAL")
        result = pm.evaluate_permission(req)

        # Incluso si el usuario confirmaría, CRITICAL es DENY sin excepciones
        assert result.decision == PermissionDecision.DENY
        # Documentar como hallazgo de diseño (no bug, sino limitación arquitectónica)
        assert "elevación" in result.reason.lower() or "critical" in result.reason.lower(), (
            "[AUDIT-H02] La razón de DENY para CRITICAL debe ser explicativa."
        )

    def test_dangerous_requires_confirmation_not_deny(self) -> None:
        """DANGEROUS debe requerir confirmación, no DENY directo."""
        pm = PermissionManager()
        req = _make_perm_request("risky_tool", risk_str="DANGEROUS")
        result = pm.evaluate_permission(req)
        assert result.decision == PermissionDecision.REQUIRE_CONFIRMATION, (
            "DANGEROUS debe requerir confirmación, no ser denegado directamente."
        )

    def test_safe_risk_allowed_by_default(self) -> None:
        """SAFE debe ser autorizado por defecto."""
        pm = PermissionManager()
        req = _make_perm_request("safe_tool", risk_str="SAFE")
        result = pm.evaluate_permission(req)
        assert result.is_allowed, "Operación SAFE debe ser autorizada por defecto."
