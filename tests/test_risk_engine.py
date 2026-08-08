"""Pruebas unitarias completas del RiskEngine e inspección dinámica de parámetros."""

from __future__ import annotations

from typing import Any

from core.risk_engine import (
    RiskEngine,
    RiskRule,
    StaticMetadataRiskRule,
)
from core.security import (
    RiskLevel,
    SecurityManager,
    SecurityPolicy,
    SecurityStatus,
    ToolSecurityProfile,
)


def test_static_metadata_risk_rule() -> None:
    engine = RiskEngine(rules=[StaticMetadataRiskRule()])
    profile = ToolSecurityProfile(name="safe_tool", category="filesystem", risk_level=RiskLevel.SAFE)

    assessment = engine.evaluate_risk(profile)
    assert assessment.risk_level == RiskLevel.SAFE
    assert assessment.score == 2
    assert "StaticMetadataRiskRule" in assessment.matched_rules


def test_system_path_risk_rule_elevation() -> None:
    engine = RiskEngine()
    profile = ToolSecurityProfile(name="read_file", category="filesystem", risk_level=RiskLevel.SAFE)

    # Argumentos con ruta inocua
    a1 = engine.evaluate_risk(profile, arguments={"path": "C:\\Users\\Public\\doc.txt"})
    assert a1.risk_level == RiskLevel.SAFE

    # Argumentos con ruta crítica del sistema operativo Windows -> Eleva a CRITICAL
    a2 = engine.evaluate_risk(profile, arguments={"path": "C:\\Windows\\System32\\drivers\\etc\\hosts"})
    assert a2.risk_level == RiskLevel.CRITICAL
    assert a2.requires_confirmation is True
    assert "SystemPathRiskRule" in a2.matched_rules


def test_bulk_operation_risk_rule_elevation() -> None:
    engine = RiskEngine()
    profile = ToolSecurityProfile(name="copy_files", category="filesystem", risk_level=RiskLevel.SAFE)

    # Argumento recursivo eleva riesgo a DANGEROUS
    assessment = engine.evaluate_risk(profile, arguments={"folder": "C:\\Temp", "recursive": True})
    assert assessment.risk_level == RiskLevel.DANGEROUS
    assert assessment.requires_confirmation is True
    assert "BulkOperationRiskRule" in assessment.matched_rules


class CustomRule(RiskRule):
    def __init__(self) -> None:
        super().__init__("CustomRule")

    def evaluate(self, profile: ToolSecurityProfile, arguments: dict[str, Any] | None = None) -> RiskLevel | None:
        if arguments and arguments.get("secret_action"):
            return RiskLevel.CRITICAL
        return None


def test_custom_risk_rule() -> None:
    engine = RiskEngine()
    engine.add_rule(CustomRule())

    profile = ToolSecurityProfile(name="test_tool", category="general", risk_level=RiskLevel.SAFE)
    assessment = engine.evaluate_risk(profile, arguments={"secret_action": True})

    assert assessment.risk_level == RiskLevel.CRITICAL
    assert "CustomRule" in assessment.matched_rules


def test_security_manager_risk_engine_integration() -> None:
    sec = SecurityManager(policy=SecurityPolicy(require_admin_for_critical=False))
    profile = ToolSecurityProfile(name="read_file", category="filesystem", risk_level=RiskLevel.SAFE)

    # Invocación con ruta inocua -> ALLOWED
    d1 = sec.evaluate(profile, arguments={"path": "C:\\Temp\\log.txt"})
    assert d1.is_allowed is True
    assert d1.status == SecurityStatus.ALLOWED

    # Invocación con ruta crítica C:\Windows\System32 -> REQUIRES_CONFIRMATION por elevación dinámica
    d2 = sec.evaluate(profile, arguments={"path": "C:\\Windows\\System32\\cmd.exe"})
    assert d2.is_allowed is False
    assert d2.status == SecurityStatus.REQUIRES_CONFIRMATION
    assert d2.requires_user_confirmation is True
