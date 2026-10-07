"""tests/mobile/test_mobile_control_jde.py

Batería completa de pruebas para la Capacidad Mobile Control de JESSYCA subordinada a JDE:
1. Listar dispositivos autorizados con emparejamiento explícito.
2. Obtener estado en vivo de un dispositivo móvil.
3. Abrir aplicación de prueba y verificar físicamente que quedó en primer plano con evidencia SHA-256.
4. Prueba de desconexión física/lógica del dispositivo (DeviceDisconnectedError / verificación fallida).
5. Prueba de dispositivo equivocado o no autorizado (DeviceNotFoundError / DeviceNotAuthorizedError).
6. Prueba de permiso denegado por JDE (Policy / Kill Switch -> 0 efectos en el dispositivo).
7. Prueba de reintento sin duplicados (Deduplicación atómica por ExecutionIdempotencyGuard).
8. Prueba de deadlines y CancellationToken.
9. Ausencia de comandos arbitrarios de ADB/shell como herramienta expuesta.
10. Transporte autenticado: rechazo de tokens inseguros y validación estricta de certificados.
11. Flujo completo E2E: PC -> Autorización JDE -> Dispositivo -> Evidencia -> Respuesta respaldada por recibo.
12. Orquestación con la propia aplicación JESSYCA Mobile (Need A) reutilizando su protocolo.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.cancellation import CancellationToken
from core.execution.idempotency_guard import ExecutionIdempotencyGuard
from core.integration.models import IntegrationContext, IntegrationStatus
from core.jde.runtime_binding import (
    JDERuntimeBinding,
    JDERuntimeMode,
    JDERuntimeVerdict,
    JDERuntimeVerdictType,
)
from core.mobile.adapter import MobileControlAdapter
from core.mobile.driver import (
    DeviceDisconnectedError,
    DeviceNotFoundError,
    MobilewrightDriver,
    OperationCancelledError,
    TimeoutExceededError,
)
from core.mobile.models import (
    AuthorizationStatus,
    MobileDeviceIdentity,
    MobileDeviceState,
    MobileTransportType,
    PairingStatus,
)
from core.mobile.orchestrator import (
    DeviceNotAuthorizedError,
    MobileOrchestrator,
)
from core.mobile.pairing import (
    DevicePairingManager,
    InsecureTokenError,
    InvalidCertificateError,
)
from core.mobile.verifier import MobileAppForegroundVerifier


@pytest.fixture
def temp_pairing_manager() -> DevicePairingManager:
    """Provee un gestor de emparejamiento aislado en directorio temporal."""
    temp_dir = Path(tempfile.mkdtemp(prefix="jessyca_mobile_test_"))
    storage = temp_dir / "paired_devices.json"
    manager = DevicePairingManager(storage_file=storage)
    return manager


@pytest.fixture
def mock_driver() -> MobilewrightDriver:
    """Provee un driver Mobilewright en modo test con estado pre-cargado."""
    driver = MobilewrightDriver(test_mode=True)
    state = MobileDeviceState(
        device_id="android-pixel-01",
        is_connected=True,
        battery_level=85,
        foreground_package="com.android.launcher3",
        foreground_activity="com.android.launcher3.uioverrides.QuickstepLauncher",
        screen_on=True,
        is_locked=False,
    )
    driver.set_mock_device_state("android-pixel-01", state)
    return driver


@pytest.fixture
def mobile_orchestrator(temp_pairing_manager: DevicePairingManager, mock_driver: MobilewrightDriver) -> MobileOrchestrator:
    """Provee el orquestador móvil con dispositivo emparejado y autorizado de prueba."""
    # Emparejar dispositivo de prueba con token robusto
    token = temp_pairing_manager.generate_pairing_token()
    temp_pairing_manager.register_device(
        device_id="android-pixel-01",
        device_name="Pixel 8 Test",
        pairing_secret=token,
        transport=MobileTransportType.USB,
    )

    verifier = MobileAppForegroundVerifier(mock_driver)
    guard = ExecutionIdempotencyGuard()
    orchestrator = MobileOrchestrator(
        pairing_manager=temp_pairing_manager,
        driver=mock_driver,
        verifier=verifier,
        idempotency_guard=guard,
    )
    return orchestrator


class TestDevicePairingAndSecurity:
    """Valida el emparejamiento explícito, transporte seguro y rechazo de credenciales inseguras."""

    def test_explicit_pairing_and_list_authorized_devices(self, temp_pairing_manager: DevicePairingManager) -> None:
        token = temp_pairing_manager.generate_pairing_token()
        identity = temp_pairing_manager.register_device(
            device_id="android-device-100",
            device_name="Galaxy S23",
            pairing_secret=token,
            transport=MobileTransportType.USB,
        )

        assert identity.pairing_status == PairingStatus.PAIRED
        assert identity.authorization_status == AuthorizationStatus.AUTHORIZED
        assert identity.device_id == "android-device-100"

        # Listar dispositivos autorizados
        auth_devices = temp_pairing_manager.list_authorized_devices()
        assert len(auth_devices) == 1
        assert auth_devices[0].device_id == "android-device-100"

    def test_rejects_insecure_development_tokens(self, temp_pairing_manager: DevicePairingManager) -> None:
        with pytest.raises(InsecureTokenError, match="token inseguro"):
            temp_pairing_manager.register_device(
                device_id="android-insecure",
                device_name="Insecure Phone",
                pairing_secret="jessyca-dev-token-insecure",  # Prohibido en producción
            )

        with pytest.raises(InsecureTokenError, match="demasiado corto"):
            temp_pairing_manager.register_device(
                device_id="android-short",
                device_name="Short Token Phone",
                pairing_secret="1234",  # Menor a 16 caracteres
            )

    def test_network_transport_requires_valid_tls_certificates(self, temp_pairing_manager: DevicePairingManager) -> None:
        token = temp_pairing_manager.generate_pairing_token()
        # Rechaza terminantemente desactivar validación de certificados
        with pytest.raises(InvalidCertificateError, match="estrictamente prohibido desactivar la validación"):
            temp_pairing_manager.register_device(
                device_id="android-wifi-1",
                device_name="WiFi Phone",
                pairing_secret=token,
                transport=MobileTransportType.WIFI_TLS,
                host="192.168.1.150",
                verify_certificates=False,  # NO PERMITIDO
            )

    def test_revocation_of_device(self, temp_pairing_manager: DevicePairingManager) -> None:
        token = temp_pairing_manager.generate_pairing_token()
        temp_pairing_manager.register_device(
            device_id="android-revokable",
            device_name="Revokable Device",
            pairing_secret=token,
        )
        assert len(temp_pairing_manager.list_authorized_devices()) == 1

        temp_pairing_manager.revoke_device("android-revokable")
        # Ya no debe aparecer en la lista de autorizados
        assert len(temp_pairing_manager.list_authorized_devices()) == 0


class TestMobileExecutionAndPhysicalVerification:
    """Valida la entrega funcional principal: estado, lanzamiento, verificación física y errores."""

    def test_01_get_device_status(self, mobile_orchestrator: MobileOrchestrator) -> None:
        state = mobile_orchestrator.get_device_status("android-pixel-01")
        assert state.device_id == "android-pixel-01"
        assert state.is_connected is True
        assert state.battery_level == 85
        assert state.foreground_package == "com.android.launcher3"

    def test_02_launch_test_app_and_verify_foreground(self, mobile_orchestrator: MobileOrchestrator) -> None:
        """Flujo exitoso: PC -> JDE -> Driver -> Verificador Físico -> Evidencia SHA-256."""
        test_package = "com.google.android.calculator"
        result = mobile_orchestrator.launch_app_governed(
            device_id="android-pixel-01",
            package_name=test_package,
            activity_name="com.android.calculator2.Calculator",
            session_id="test-session-01",
        )

        assert result.final_status == "SUCCESS"
        assert result.receipt is not None
        assert result.receipt.verified is True
        assert result.receipt.verification_status == "VERIFIED_TRUE"
        assert result.evidence is not None
        assert result.evidence.is_verified is True
        assert result.evidence.target == test_package
        assert len(result.evidence.observed_state.get("evidence_hash", "")) > 0

        # Comprobar que en el driver la app realmente quedó registrada en primer plano
        state = mobile_orchestrator.get_device_status("android-pixel-01")
        assert state.foreground_package == test_package

    def test_03_device_disconnected_fails_verification(self, mobile_orchestrator: MobileOrchestrator) -> None:
        """Desconexión del dispositivo no genera falso éxito."""
        mobile_orchestrator.driver.simulate_device_disconnection("android-pixel-01")

        result = mobile_orchestrator.launch_app_governed(
            device_id="android-pixel-01",
            package_name="com.google.android.calculator",
            session_id="test-session-02",
        )

        assert result.final_status == "FAILED"
        assert result.receipt is not None
        assert result.receipt.verified is False
        assert "desconectado" in str(result.receipt.error_message).lower()

    def test_04_wrong_device_not_found(self, mobile_orchestrator: MobileOrchestrator) -> None:
        """Dispositivo no registrado es rechazado de inmediato."""
        with pytest.raises(DeviceNotFoundError, match="no encontrado"):
            mobile_orchestrator.launch_app_governed(
                device_id="android-non-existent-device",
                package_name="com.google.android.calculator",
            )

    def test_05_unauthorized_device_rejected(self, mobile_orchestrator: MobileOrchestrator) -> None:
        """Dispositivo emparejado pero revocado/bloqueado no puede ejecutar acciones."""
        mobile_orchestrator.pairing_manager.revoke_device("android-pixel-01")

        with pytest.raises(DeviceNotAuthorizedError, match="no está autorizado"):
            mobile_orchestrator.launch_app_governed(
                device_id="android-pixel-01",
                package_name="com.google.android.calculator",
            )

    def test_06_permission_denied_by_jde_produces_zero_device_effects(
        self, mobile_orchestrator: MobileOrchestrator
    ) -> None:
        """Si JDE emite DENY, la acción física jamás se envía al dispositivo."""
        initial_pkg = mobile_orchestrator.driver.get_device_state("android-pixel-01").foreground_package

        # Simular denegación formal en JDERuntimeBinding
        mock_verdict = JDERuntimeVerdict(
            verdict=JDERuntimeVerdictType.DENY,
            reason="Acción restringida por política de seguridad JDE",
            action="mobile.launch_app",
            tool="mobile_control",
            risk_level="HIGH",
            runtime_mode=JDERuntimeMode.CONTROLLED,
            is_blocked=True,
        )

        with patch.object(mobile_orchestrator.runtime_binding, "evaluate", return_value=mock_verdict):
            result = mobile_orchestrator.launch_app_governed(
                device_id="android-pixel-01",
                package_name="com.untrusted.app",
            )

            assert result.final_status == "DENIED"
            assert result.receipt.verified is False
            assert "bloqueada por jde" in result.reason.lower()

            # Estado del dispositivo INTACTO (cero efectos secundarios)
            current_state = mobile_orchestrator.driver.get_device_state("android-pixel-01")
            assert current_state.foreground_package == initial_pkg

    def test_07_retry_without_duplicates_idempotency(self, mobile_orchestrator: MobileOrchestrator) -> None:
        """Reintentos con la misma petición son deduplicados sin ejecutar nuevamente en el dispositivo."""
        test_pkg = "com.google.android.calculator"
        req_id = "request-fixed-idempotent-001"

        # 1. Primera ejecución: real
        res1 = mobile_orchestrator.launch_app_governed(
            device_id="android-pixel-01",
            package_name=test_pkg,
            request_id=req_id,
            session_id="idempotency-session",
        )
        assert res1.final_status == "SUCCESS"
        assert res1.receipt.policy_verdict == "ALLOW"

        # 2. Segunda ejecución idéntica: deduplicada por IdempotencyGuard
        res2 = mobile_orchestrator.launch_app_governed(
            device_id="android-pixel-01",
            package_name=test_pkg,
            request_id=req_id,
            session_id="idempotency-session",
        )
        assert res2.final_status == "SUCCESS"
        assert res2.receipt.policy_verdict == "IDEMPOTENT_REPLAY"
        assert "deduplicada" in res2.reason.lower()

    def test_08_cancellation_token_aborts_operation(self, mobile_orchestrator: MobileOrchestrator) -> None:
        """Token de cancelación aborta el lanzamiento limpiamente."""
        token = CancellationToken()
        token.cancel("Cancelado por usuario antes de inicio")

        result = mobile_orchestrator.launch_app_governed(
            device_id="android-pixel-01",
            package_name="com.google.android.calculator",
            cancellation_token=token,
        )

        assert result.final_status == "FAILED"
        assert "cancelad" in str(result.receipt.error_message).lower()


class TestMobileControlAdapterAndIntegration:
    """Valida el adaptador canónico MobileControlAdapter frente al IntegrationHub."""

    def test_adapter_declared_capabilities_and_no_arbitrary_shell(
        self, mobile_orchestrator: MobileOrchestrator
    ) -> None:
        async def _test() -> None:
            adapter = MobileControlAdapter(orchestrator=mobile_orchestrator)
            context = IntegrationContext(session_id="test-mobile-init")

            init_ok = await adapter.initialize(context)
            assert init_ok is True
            assert adapter.status == IntegrationStatus.READY

            # Capacidades declaradas deben ser seguras y específicas
            cap_names = {c.name for c in adapter.capabilities}
            assert "mobile.list_authorized_devices" in cap_names
            assert "mobile.get_device_status" in cap_names
            assert "mobile.launch_app" in cap_names
            assert "mobile.verify_foreground" in cap_names
            assert "mobile.orchestrate_app" in cap_names

            # NO debe exponerse ejecución de shell/adb arbitrario
            assert "mobile.shell" not in cap_names
            assert "mobile.adb" not in cap_names
            assert "mobile.raw_command" not in cap_names

        asyncio.run(_test())

    def test_adapter_execution_flow(self, mobile_orchestrator: MobileOrchestrator) -> None:
        async def _test() -> None:
            adapter = MobileControlAdapter(orchestrator=mobile_orchestrator)

            # 1. Listar dispositivos
            res_list = await adapter.execute_capability("mobile.list_authorized_devices", {})
            assert res_list.success is True
            assert res_list.data["count"] == 1

            # 2. Obtener estado
            res_stat = await adapter.execute_capability(
                "mobile.get_device_status", {"device_id": "android-pixel-01"}
            )
            assert res_stat.success is True
            assert res_stat.data["device_id"] == "android-pixel-01"

            # 3. Lanzar app
            res_launch = await adapter.execute_capability(
                "mobile.launch_app",
                {"device_id": "android-pixel-01", "package_name": "com.google.android.calculator"},
            )
            assert res_launch.success is True
            assert res_launch.data["final_status"] == "SUCCESS"

        asyncio.run(_test())

    def test_need_a_orchestration_protocol_reuse(self, mobile_orchestrator: MobileOrchestrator) -> None:
        """Need A: Reutiliza el protocolo existente de JESSYCA Mobile sin inventar endpoints."""
        async def _test() -> None:
            adapter = MobileControlAdapter(orchestrator=mobile_orchestrator)

            res = await adapter.execute_capability(
                "mobile.orchestrate_app",
                {"device_id": "android-pixel-01", "message": "Hola desde PC Core"},
            )

            assert res.success is True
            assert res.data["status"] == "DELIVERED"
            assert res.data["message"] == "Hola desde PC Core"
            assert res.data["device_id"] == "android-pixel-01"

        asyncio.run(_test())
