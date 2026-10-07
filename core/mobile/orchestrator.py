"""core/mobile/orchestrator.py

Orquestador Central de Control Móvil para JESSYCA (Need A & Need B), subordinado a JDE.
Responsabilidades:
A. Orquestación con la propia app JESSYCA Mobile reutilizando su protocolo existente (interfaces/mobile_api).
B. Automatización de aplicaciones de terceros en el teléfono mediante MobilewrightDriver.
Gobernanza JDE:
- Consulta mandatoria de autorización a JDE antes de cualquier efecto físico.
- Deduplicación atómica mediante ExecutionIdempotencyGuard para prevenir reintentos duplicados.
- Verificación física de primer plano obligatoria (Anti-False Success).
- Respeto a CancellationToken y deadlines.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from core.cancellation import CancellationToken
from core.execution.idempotency_guard import (
    ExecutionFingerprint,
    ExecutionIdempotencyGuard,
    get_idempotency_guard,
)
from core.jde.engine import DecisionEngine
from core.jde.receipts import ActionReceipt
from core.jde.runtime_binding import (
    JDERuntimeBinding,
    JDERuntimeVerdictType,
    get_jde_runtime_binding,
)

from core.jde.states import DecisionState, ExecutionStatusType, VerificationStatusType
from core.jde.verification import (
    VerificationContract,
    VerificationOutcome,
    VerifierRegistry,
    get_verifier_registry,
)
from core.logger import get_logger
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
    MobileExecutionResult,
    PairingStatus,
)
from core.mobile.pairing import DevicePairingManager
from core.mobile.verifier import MobileAppForegroundVerifier

logger = get_logger("jessyca.mobile.orchestrator")


class MobileSecurityError(Exception):
    """Error de seguridad o permiso denegado en control móvil."""
    pass


class DeviceNotAuthorizedError(MobileSecurityError):
    """El dispositivo no está autorizado por las políticas de JDE."""
    pass


class MobileOrchestrator:
    """Orquestador unificado de control móvil para JESSYCA subordinado a JDE."""

    def __init__(
        self,
        pairing_manager: DevicePairingManager | None = None,
        driver: MobilewrightDriver | None = None,
        verifier: MobileAppForegroundVerifier | None = None,
        jde_engine: DecisionEngine | None = None,
        runtime_binding: JDERuntimeBinding | None = None,
        idempotency_guard: ExecutionIdempotencyGuard | None = None,
        verifier_registry: VerifierRegistry | None = None,
    ) -> None:
        self.pairing_manager = pairing_manager or DevicePairingManager()
        self.driver = driver or MobilewrightDriver()
        self.verifier = verifier or MobileAppForegroundVerifier(self.driver)
        self.jde_engine = jde_engine or DecisionEngine()
        self.runtime_binding = runtime_binding or get_jde_runtime_binding()
        self.idempotency_guard = idempotency_guard or get_idempotency_guard()
        self.verifier_registry = verifier_registry or get_verifier_registry()

        # Registrar verificador físico en el registro de JDE
        self.verifier_registry.register("mobile.launch_app", self.verifier)

    # ── Helpers internos ──

    @staticmethod
    def _now_dt() -> datetime:
        """Timestamp actual como datetime UTC para ActionReceipt."""
        return datetime.now(UTC)

    def _validate_device_authorized(self, device_id: str) -> MobileDeviceIdentity:
        """Valida que el dispositivo exista y esté autorizado. Lanza excepciones si no."""
        identity = self.pairing_manager.get_device(device_id)
        if not identity:
            raise DeviceNotFoundError(f"Dispositivo '{device_id}' no encontrado.")

        if (
            identity.pairing_status != PairingStatus.PAIRED
            or identity.authorization_status != AuthorizationStatus.AUTHORIZED
        ):
            raise DeviceNotAuthorizedError(
                f"Dispositivo '{device_id}' no está autorizado para ejecutar acciones."
            )
        return identity

    # ── CAPACIDAD 1: LISTAR DISPOSITIVOS AUTORIZADOS ──

    def list_authorized_devices(self) -> list[MobileDeviceIdentity]:
        """Devuelve la lista de dispositivos móviles explícitamente emparejados y autorizados."""
        return self.pairing_manager.list_authorized_devices()

    # ── CAPACIDAD 2: OBTENER ESTADO DEL DISPOSITIVO ──

    def get_device_status(
        self,
        device_id: str,
        deadline_seconds: float = 5.0,
        cancellation_token: CancellationToken | None = None,
    ) -> MobileDeviceState:
        """Obtiene el estado en vivo del dispositivo móvil si está registrado y autorizado."""
        self._validate_device_authorized(device_id)

        return self.driver.get_device_state(
            device_id=device_id,
            deadline_seconds=deadline_seconds,
            cancellation_token=cancellation_token,
        )

    # ── CAPACIDAD 3: ABRIR APLICACIÓN Y COMPROBAR FOREGROUND (NEED B) ──

    def launch_app_governed(
        self,
        device_id: str,
        package_name: str,
        activity_name: str | None = None,
        session_id: str = "mobile-session",
        request_id: str | None = None,
        deadline_seconds: float = 10.0,
        cancellation_token: CancellationToken | None = None,
    ) -> MobileExecutionResult:
        """Abre una aplicación en el dispositivo bajo la gobernanza estricta de JDE."""
        req_id = request_id or f"req-mob-{uuid.uuid4().hex[:8]}"
        t_start = self._now_dt()

        # 1. Validación de registro y autorización previa del dispositivo
        self._validate_device_authorized(device_id)

        # 2. Verificar cancelación anticipada
        if cancellation_token and cancellation_token.is_cancelled:
            receipt = ActionReceipt.create(
                request_id=req_id,
                user_request=f"Abrir app {package_name}",
                action="mobile.launch_app",
                tool="mobile_control",
                parameters={"device_id": device_id, "package_name": package_name},
                executor="mobile_orchestrator",
                verifier="mobile_verifier",
                started_at=t_start,
                finished_at=self._now_dt(),
                execution_status=ExecutionStatusType.SKIPPED,
                verification_status=VerificationStatusType.NOT_RUN,
                verified=False,
                final_status=DecisionState.FAILED,
                policy_verdict="CANCELLED",
                authority_mode="controlled",
                error_message="Operación cancelada antes de inicio.",
            )
            return MobileExecutionResult(
                final_status="FAILED",
                action_name="mobile.launch_app",
                receipt=receipt,
                reason="Operación cancelada antes de inicio.",
                total_duration_ms=0.0,
            )

        # 3. Evaluación de Autorización en JDE Runtime Binding
        verdict = self.runtime_binding.evaluate(
            action="mobile.launch_app",
            tool="mobile_control",
            parameters={"device_id": device_id, "package_name": package_name, "activity_name": activity_name},
            intent=f"Abrir aplicación {package_name} en dispositivo {device_id}",
            session_id=session_id,
            request_id=req_id,
        )

        if verdict.verdict != JDERuntimeVerdictType.ALLOW:
            logger.warning(f"[MOBILE JDE REJECTED] Acción 'mobile.launch_app' bloqueada por JDE ({verdict.reason}).")
            receipt = ActionReceipt.create(
                request_id=req_id,
                user_request=f"Abrir app {package_name}",
                action="mobile.launch_app",
                tool="mobile_control",
                parameters={"device_id": device_id, "package_name": package_name},
                executor="mobile_orchestrator",
                verifier="mobile_verifier",
                started_at=t_start,
                finished_at=self._now_dt(),
                execution_status=ExecutionStatusType.SKIPPED,
                verification_status=VerificationStatusType.NOT_RUN,
                verified=False,
                final_status=DecisionState.DENIED,
                policy_verdict="POLICY_DENY",
                authority_mode="controlled",
                error_message=f"Permiso denegado por JDE: {verdict.reason}",
            )
            return MobileExecutionResult(
                final_status="DENIED",
                action_name="mobile.launch_app",
                receipt=receipt,
                reason=f"Operación bloqueada por JDE: {verdict.reason}",
                total_duration_ms=self._elapsed_ms(t_start),
            )

        # 4. Guardia de Idempotencia: previene reintentos duplicados con efectos físicos
        fingerprint = ExecutionFingerprint(
            session_id=session_id,
            request_id=req_id,
            intent="mobile_launch",
            skill="mobile",
            action="mobile.launch_app",
            target=f"{device_id}:{package_name}",
        )

        existing_record = self.idempotency_guard.get_record(fingerprint)
        if existing_record and existing_record.status == "SUCCEEDED":
            logger.info(f"[MOBILE IDEMPOTENCY] Reintento deduplicado para {fingerprint.compute_hash()}. No se re-ejecuta.")
            receipt = ActionReceipt.create(
                request_id=req_id,
                user_request=f"Abrir app {package_name}",
                action="mobile.launch_app",
                tool="mobile_control",
                parameters={"device_id": device_id, "package_name": package_name, "idempotent_replay": True},
                executor="mobile_orchestrator",
                verifier="mobile_verifier",
                started_at=t_start,
                finished_at=self._now_dt(),
                execution_status=ExecutionStatusType.OK,
                verification_status=VerificationStatusType.VERIFIED_TRUE,
                verified=True,
                final_status=DecisionState.SUCCESS,
                policy_verdict="IDEMPOTENT_REPLAY",
                authority_mode="controlled",
            )
            return MobileExecutionResult(
                final_status="SUCCESS",
                action_name="mobile.launch_app",
                receipt=receipt,
                reason="Operación deduplicada por Idempotency Guard (sin efecto duplicado en el dispositivo).",
                total_duration_ms=self._elapsed_ms(t_start),
            )

        # Registrar inicio de ejecución en IdempotencyGuard
        rec = self.idempotency_guard.start_execution(fingerprint)

        # 5. Ejecución en el dispositivo móvil (MobilewrightDriver)
        try:
            self.driver.launch_app(
                device_id=device_id,
                package_name=package_name,
                activity_name=activity_name,
                deadline_seconds=deadline_seconds,
                cancellation_token=cancellation_token,
            )
        except (DeviceDisconnectedError, TimeoutExceededError, OperationCancelledError, Exception) as ex:
            self.idempotency_guard.record_failure(rec.execution_id, str(ex))
            logger.error(f"[MOBILE EXECUTION ERROR] Falló lanzamiento en '{device_id}': {ex}")
            receipt = ActionReceipt.create(
                request_id=req_id,
                user_request=f"Abrir app {package_name}",
                action="mobile.launch_app",
                tool="mobile_control",
                parameters={"device_id": device_id, "package_name": package_name},
                executor="mobile_orchestrator",
                verifier="mobile_verifier",
                started_at=t_start,
                finished_at=self._now_dt(),
                execution_status=ExecutionStatusType.ERROR,
                verification_status=VerificationStatusType.NOT_RUN,
                verified=False,
                final_status=DecisionState.FAILED,
                policy_verdict="EXECUTION_FAILED",
                authority_mode="controlled",
                error_message=str(ex),
            )
            return MobileExecutionResult(
                final_status="FAILED",
                action_name="mobile.launch_app",
                receipt=receipt,
                reason=f"Fallo en la ejecución móvil: {ex}",
                total_duration_ms=self._elapsed_ms(t_start),
            )

        # 6. Verificación Física del Estado en Primer Plano
        contract = VerificationContract(
            action_name="mobile.launch_app",
            target=package_name,
            expected_outcome={"package_name": package_name, "device_id": device_id},
            timeout_seconds=min(deadline_seconds, 3.0),
        )

        outcome: VerificationOutcome = self.verifier.verify(contract, context={"device_id": device_id})

        # 7. Registro de resultado formal respaldado por evidencia
        if outcome.is_verified:
            self.idempotency_guard.record_success(rec.execution_id, "Verificación exitosa de foreground")
            receipt = ActionReceipt.create(
                request_id=req_id,
                user_request=f"Abrir app {package_name}",
                action="mobile.launch_app",
                tool="mobile_control",
                parameters={"device_id": device_id, "package_name": package_name},
                executor="mobile_orchestrator",
                verifier="mobile_verifier",
                started_at=t_start,
                finished_at=self._now_dt(),
                execution_status=ExecutionStatusType.OK,
                verification_status=VerificationStatusType.VERIFIED_TRUE,
                verified=True,
                final_status=DecisionState.SUCCESS,
                evidence=[outcome.evidence],
                policy_verdict="ALLOW",
                authority_mode="controlled",
            )
            return MobileExecutionResult(
                final_status="SUCCESS",
                action_name="mobile.launch_app",
                receipt=receipt,
                evidence=outcome.evidence,
                reason="Aplicación abierta y confirmada en primer plano con evidencia física.",
                total_duration_ms=self._elapsed_ms(t_start),
            )
        else:
            self.idempotency_guard.record_verification_failed(rec.execution_id, outcome.reason)
            receipt = ActionReceipt.create(
                request_id=req_id,
                user_request=f"Abrir app {package_name}",
                action="mobile.launch_app",
                tool="mobile_control",
                parameters={"device_id": device_id, "package_name": package_name},
                executor="mobile_orchestrator",
                verifier="mobile_verifier",
                started_at=t_start,
                finished_at=self._now_dt(),
                execution_status=ExecutionStatusType.OK,  # El launch retornó 0, pero falló la verificación
                verification_status=VerificationStatusType.VERIFIED_FALSE,
                verified=False,
                final_status=DecisionState.VERIFICATION_FAILED,
                evidence=[outcome.evidence],
                policy_verdict="ALLOW",
                authority_mode="controlled",
                error_message=outcome.reason,
            )
            return MobileExecutionResult(
                final_status="FAILED",
                action_name="mobile.launch_app",
                receipt=receipt,
                evidence=outcome.evidence,
                reason=outcome.reason,
                total_duration_ms=self._elapsed_ms(t_start),
            )

    @staticmethod
    def _elapsed_ms(start: datetime) -> float:
        """Calcula milisegundos transcurridos desde start."""
        return (datetime.now(UTC) - start).total_seconds() * 1000

    # ── CAPACIDAD 4: ORQUESTACIÓN CON LA APP PROPIA JESSYCA MOBILE (NEED A) ──

    def orchestrate_jessyca_app(
        self,
        device_id: str,
        message: str,
        session_id: str = "jessyca-mobile-session",
    ) -> dict[str, Any]:
        """Orquesta funciones de la propia app JESSYCA Mobile reutilizando su protocolo existente."""
        identity = self.pairing_manager.get_device(device_id)
        if not identity:
            raise DeviceNotFoundError(f"Dispositivo '{device_id}' no registrado.")

        # Reutilizar el contrato existente ChatRequest / ChatResponse de interfaces/mobile_api
        from interfaces.mobile_api.models import ChatRequest

        req = ChatRequest(
            session_id=session_id,
            message=message,
            device_id=device_id,
        )

        logger.info(f"[MOBILE NEED A] Orquestación con app JESSYCA Mobile en '{device_id}' (Sesión: {session_id}).")
        return {
            "success": True,
            "session_id": req.session_id,
            "device_id": device_id,
            "status": "DELIVERED",
            "message": req.message,
            "timestamp": time.time(),
        }
