"""tests/security/test_fase1_security_and_consolidation.py
Pruebas formales de regresión y validación para la FASE 1: SEGURIDAD Y CONSOLIDACIÓN.

Verifica:
1. pyautogui.FAILSAFE = True forzado y verificado.
2. Cancelación efectiva de mouse y teclado mediante EmergencyStopManager y CancellationToken.
3. Protección contra extracción de credenciales (.env, .ssh, id_rsa, sam, security, ntds.dit).
4. Protección contra desactivación de Windows Defender, Firewall, UAC y elevación indebida.
5. Invariante de elevación de privilegios: Prohibición estricta de auto-elevación.
6. Anti-False Success: Ninguna acción puede declarar éxito sin evidencia verificable.
7. Operaciones normales autorizadas (SAFE/READ_ONLY) se ejecutan automáticamente.
8. Operaciones destructivas o de alto riesgo exigen confirmación obligatoria.
"""

from __future__ import annotations

import os
import pytest
import pyautogui

from core.emergency_stop import EmergencyStopManager, CancellationToken
from core.execution.execution_verifier import ExecutionEvidence, ExecutionResult, ExecutionStatus
from core.integration.adapters.computer_use_adapter import ComputerUseAdapter
from core.integration.hub import IntegrationContext
from core.permission_manager import PermissionDecision, PermissionManager, PermissionRequest
from core.risk_engine import (
    PROTECTED_CREDENTIAL_PATTERNS,
    SECURITY_TAMPER_PATTERNS,
    WINDOWS_CRITICAL_PATHS,
    RiskAssessment,
    RiskEngine,
    RiskFactor,
)
from core.security_architecture import SecurityContext, SecurityLevel, ToolSecurityMetadata
from skills.files_skills import _is_path_critical
from core.desktop.driver_protocol import NativeWindowsDriver, DesktopActionResult


@pytest.fixture(autouse=True)
def ensure_emergency_stop_reset():
    """Garantiza que el sistema de parada de emergencia esté restablecido antes y después de cada test."""
    manager = EmergencyStopManager.get_instance()
    manager.reset("setup_phase1_test")
    yield
    manager.reset("teardown_phase1_test")


def test_pyautogui_failsafe_invariant_is_strictly_enabled() -> None:
    """Verifica que pyautogui.FAILSAFE permanezca siempre en True como garantía de seguridad física."""
    driver = NativeWindowsDriver()
    assert pyautogui.FAILSAFE is True


def test_emergency_stop_aborts_mouse_and_keyboard_in_driver() -> None:
    """Comprueba que NativeWindowsDriver aborte de inmediato ante parada de emergencia."""
    manager = EmergencyStopManager.get_instance()
    manager.trigger_stop(reason="Test Emergency Trigger", source="unit_test")
    assert manager.is_stopped() is True

    driver = NativeWindowsDriver()
    res_type = driver.type_text("malicious text")
    assert res_type.success is False
    assert res_type.evidence["is_verified"] is False
    assert "Parada de Emergencia activa" in (res_type.error or "")

    res_click = driver.click_element(coords=(100, 100))
    assert res_click.success is False
    assert res_click.evidence["is_verified"] is False
    assert "Parada de Emergencia activa" in (res_click.error or "")


@pytest.mark.anyio
async def test_emergency_stop_aborts_computer_use_adapter_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Comprueba que ComputerUseAdapter aborte de inmediato si el gestor de emergencia está activo."""
    monkeypatch.setattr(pyautogui, "write", lambda *a, **k: None)
    monkeypatch.setattr(pyautogui, "click", lambda *a, **k: None)

    manager = EmergencyStopManager.get_instance()
    manager.trigger_stop(reason="Test Stop", source="unit_test")

    adapter = ComputerUseAdapter()
    await adapter.initialize()

    ctx = IntegrationContext(
        session_id="test_sess_sec",
        parameters={"action": "write_text", "text": "hello"},
    )
    res = await adapter.execute("computer_use.keyboard_type", ctx)
    assert res.executed is False
    assert res.status == ExecutionStatus.CANCELLED
    assert "Parada de Emergencia activa" in (res.error or "")


@pytest.mark.anyio
async def test_cancellation_token_aborts_computer_use_adapter_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Comprueba que un CancellationToken activado aborte el despacho en ComputerUseAdapter."""
    monkeypatch.setattr(pyautogui, "write", lambda *a, **k: None)

    token = CancellationToken()
    token.cancel(reason="User cancelled")

    adapter = ComputerUseAdapter()
    await adapter.initialize()

    ctx = IntegrationContext(
        session_id="test_sess_cancel",
        parameters={"action": "write_text", "text": "aborted typing"},
        cancellation_token=token,
    )
    res = await adapter.execute("computer_use.keyboard_type", ctx)
    assert res.executed is False
    assert res.status == ExecutionStatus.CANCELLED
    assert "token de cancelación" in (res.error or "").lower()


def test_sensitive_credentials_detection_in_risk_engine() -> None:
    """Verifica que RiskEngine detecte y clasifique el acceso a credenciales (.env, .ssh, id_rsa, sam) como CRITICAL."""
    engine = RiskEngine()

    for cred_sample in [".env", "C:\\Users\\user\\.ssh\\id_rsa", "config/secrets.env", "c:\\windows\\system32\\config\\sam"]:
        sec_ctx = SecurityContext(
            user="user",
            tool_name="files.read",
            parameters={"file_path": cred_sample},
        )
        meta = ToolSecurityMetadata(tool_name="files.read", category="filesystem", risk_level=SecurityLevel.SAFE)
        req = PermissionRequest(
            context=sec_ctx,
            metadata=meta,
            risk_assessment=RiskAssessment(risk_level=SecurityLevel.SAFE),
            tool_name="files.read",
            operation="read",
            parameters=sec_ctx.parameters,
        )
        assessment = engine.evaluate_risk(req)
        assert assessment.risk_level == SecurityLevel.CRITICAL
        assert RiskFactor.CREDENTIAL_ACCESS in assessment.risk_factors


def test_security_tampering_attempts_classified_as_critical() -> None:
    """Comprueba que intentos de desactivar Windows Defender, Firewall o UAC sean clasificados como CRITICAL."""
    engine = RiskEngine()

    tamper_commands = [
        "Set-MpPreference -DisableRealtimeMonitoring $true",
        "netsh advfirewall set allprofiles state off",
        "reg add HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Policies\\System /v EnableLUA /t REG_DWORD /d 0 /f",
        "powershell Start-Process cmd -Verb RunAs",
    ]

    for cmd in tamper_commands:
        sec_ctx = SecurityContext(
            user="user",
            tool_name="terminal.execute",
            parameters={"command": cmd},
        )
        meta = ToolSecurityMetadata(tool_name="terminal.execute", category="system", risk_level=SecurityLevel.WARNING)
        req = PermissionRequest(
            context=sec_ctx,
            metadata=meta,
            risk_assessment=RiskAssessment(risk_level=SecurityLevel.WARNING),
            tool_name="terminal.execute",
            operation="execute",
            parameters=sec_ctx.parameters,
        )
        assessment = engine.evaluate_risk(req)
        assert assessment.risk_level == SecurityLevel.CRITICAL
        assert RiskFactor.SYSTEM_CONFIGURATION in assessment.risk_factors or RiskFactor.ELEVATED_PRIVILEGES in assessment.risk_factors


def test_prohibition_of_automatic_privilege_elevation() -> None:
    """Garantiza que cualquier operación que requiera elevación de privilegios sea DENEGADA por defecto."""
    perm_manager = PermissionManager()

    sec_ctx = SecurityContext(user="user", tool_name="system_installer", parameters={})
    meta = ToolSecurityMetadata(
        tool_name="system_installer",
        category="install",
        risk_level=SecurityLevel.CRITICAL,
        requires_elevation=True,
    )
    req = PermissionRequest(
        context=sec_ctx,
        metadata=meta,
        risk_assessment=RiskAssessment(risk_level=SecurityLevel.CRITICAL),
        tool_name="system_installer",
        operation="install",
    )

    decision = perm_manager.evaluate_permission(req)
    assert decision.decision == PermissionDecision.DENY
    assert decision.is_allowed is False
    assert "requiere elevación de privilegios" in decision.reason


def test_is_path_critical_blocks_credentials_and_windows_paths() -> None:
    """Verifica que _is_path_critical bloquee rutas de sistema y archivos de credenciales."""
    assert _is_path_critical(".env") is True
    assert _is_path_critical("C:\\Users\\user\\.env") is True
    assert _is_path_critical("C:\\Users\\user\\.ssh\\id_rsa") is True
    assert _is_path_critical("C:\\Windows\\System32\\cmd.exe") is True
    assert _is_path_critical("C:\\Program Files\\App\\app.exe") is True


def test_anti_false_success_invariant() -> None:
    """Garantiza la regla fundamental: NO EXECUTION EVIDENCE = NO SUCCESS CLAIM."""
    # 1. Sin evidencia -> claims_success False
    res_no_evidence = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED,
        action="open_app",
        target="notepad",
        evidence=None,
    )
    assert res_no_evidence.claims_success is False

    # 2. Con evidencia pero is_verified = False -> claims_success False
    ev_unverified = ExecutionEvidence(
        verification_type="process_check",
        target="notepad",
        is_verified=False,
    )
    res_unverified = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED,
        action="open_app",
        target="notepad",
        evidence=ev_unverified,
    )
    assert res_unverified.claims_success is False

    # 3. Con evidencia real verificada -> claims_success True
    ev_verified = ExecutionEvidence(
        verification_type="gui_application_visible",
        target="notepad",
        is_verified=True,
    )
    res_verified = ExecutionResult(
        status=ExecutionStatus.SUCCEEDED,
        action="open_app",
        target="notepad",
        evidence=ev_verified,
    )
    assert res_verified.claims_success is True


def test_normal_operations_auto_authorized_vs_destructive_requiring_confirmation() -> None:
    """Verifica que SAFE/READ_ONLY se autoricen automáticamente y DANGEROUS exija confirmación."""
    perm_manager = PermissionManager()

    # 1. Operación normal segura (Lectura de archivos o listado) -> ALLOW automático
    ctx_safe = SecurityContext(user="user", tool_name="files.list", parameters={})
    meta_safe = ToolSecurityMetadata(tool_name="files.list", category="read", risk_level=SecurityLevel.SAFE)
    req_safe = PermissionRequest(
        context=ctx_safe,
        metadata=meta_safe,
        risk_assessment=RiskAssessment(risk_level=SecurityLevel.SAFE),
        tool_name="files.list",
        operation="list",
    )
    res_safe = perm_manager.evaluate_permission(req_safe)
    assert res_safe.decision == PermissionDecision.ALLOW
    assert res_safe.is_allowed is True

    # 2. Operación destructiva (Eliminación) -> REQUIRE_CONFIRMATION
    ctx_danger = SecurityContext(user="user", tool_name="files.delete", parameters={"path": "test.txt"})
    meta_danger = ToolSecurityMetadata(
        tool_name="files.delete",
        category="delete",
        risk_level=SecurityLevel.DANGEROUS,
        requires_confirmation=True,
    )
    req_danger = PermissionRequest(
        context=ctx_danger,
        metadata=meta_danger,
        risk_assessment=RiskAssessment(risk_level=SecurityLevel.DANGEROUS),
        tool_name="files.delete",
        operation="delete",
    )
    res_danger = perm_manager.evaluate_permission(req_danger)
    assert res_danger.decision == PermissionDecision.REQUIRE_CONFIRMATION
    assert res_danger.is_allowed is False
