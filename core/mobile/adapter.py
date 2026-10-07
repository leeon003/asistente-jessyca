"""core/mobile/adapter.py

Adaptador de Integración Canónico para Control Móvil (MobileControlAdapter).
Implementa la interfaz IntegrationAdapter de JESSYCA:
- Expone una única entrada principal gobernada sin duplicación de herramientas.
- No expone comandos ADB/shell arbitrarios.
- Subordina cada acción al motor determinista JDE.
"""

from __future__ import annotations

import time
from typing import Any

from core.cancellation import CancellationToken
from core.execution.execution_verifier import ExecutionStatus
from core.integration.adapter import IntegrationAdapter
from core.integration.models import (
    IntegrationCapability,
    IntegrationContext,
    IntegrationExecutionResult,
    IntegrationHealth,
    IntegrationStatus,
)
from core.logger import get_logger
from core.mobile.driver import DeviceDisconnectedError, DeviceNotFoundError
from core.mobile.orchestrator import (
    DeviceNotAuthorizedError,
    MobileOrchestrator,
    MobileSecurityError,
)

logger = get_logger("jessyca.mobile.adapter")


class MobileControlAdapter(IntegrationAdapter):
    """Adaptador canónico de control y automatización de dispositivos móviles para JESSYCA."""

    def __init__(
        self,
        orchestrator: MobileOrchestrator | None = None,
        name: str = "mobile_control",
        version: str = "1.0.0",
    ) -> None:
        super().__init__(name=name, version=version, dependencies=["pydantic"])
        self.orchestrator = orchestrator or MobileOrchestrator()
        self._register_declared_capabilities()

    def check_dependencies(self) -> tuple[bool, list[str]]:
        """Comprueba dependencias del adaptador móvil (pydantic instalado)."""
        import importlib.util
        missing: list[str] = []
        if importlib.util.find_spec("pydantic") is None:
            missing.append("pydantic")
        return len(missing) == 0, missing

    def _register_declared_capabilities(self) -> None:
        """Declara formalmente las capacidades permitidas del adaptador (sin shell arbitrario)."""
        self._capabilities = {
            "mobile.list_authorized_devices": IntegrationCapability(
                name="mobile.list_authorized_devices",
                description="Lista los dispositivos móviles autorizados y emparejados explícitamente.",
                parameters_schema={},
            ),
            "mobile.get_device_status": IntegrationCapability(
                name="mobile.get_device_status",
                description="Obtiene el estado en vivo de un dispositivo móvil autorizado (batería, pantalla, app activa).",
                parameters_schema={"device_id": {"type": "string"}},
            ),
            "mobile.launch_app": IntegrationCapability(
                name="mobile.launch_app",
                description="Abre una aplicación autorizada en el dispositivo móvil y verifica su estado en primer plano.",
                parameters_schema={
                    "device_id": {"type": "string"},
                    "package_name": {"type": "string"},
                    "activity_name": {"type": "string", "optional": True},
                    "deadline_seconds": {"type": "number", "default": 10.0},
                },
            ),
            "mobile.verify_foreground": IntegrationCapability(
                name="mobile.verify_foreground",
                description="Comprueba físicamente mediante inspección que una aplicación está en primer plano.",
                parameters_schema={
                    "device_id": {"type": "string"},
                    "package_name": {"type": "string"},
                },
            ),
            "mobile.orchestrate_app": IntegrationCapability(
                name="mobile.orchestrate_app",
                description="Orquesta funciones de la propia aplicación JESSYCA Mobile mediante su protocolo API.",
                parameters_schema={
                    "device_id": {"type": "string"},
                    "message": {"type": "string"},
                },
            ),
        }

    async def initialize(self, context: IntegrationContext | None = None) -> bool:
        """Inicializa el adaptador y verifica la compatibilidad del entorno."""
        self.status = IntegrationStatus.INITIALIZING
        try:
            has_adb = self.orchestrator.driver.is_windows_adb_available()
            logger.info(
                f"[MOBILE ADAPTER INIT] Inicializado con éxito (ADB en Windows: {'Disponible' if has_adb else 'Modo Emulado/Virtual'})."
            )
            self.status = IntegrationStatus.READY
            return True
        except Exception as e:
            logger.error(f"[MOBILE ADAPTER INIT ERROR] Error en inicialización: {e}")
            self.status = IntegrationStatus.ERROR
            return False

    async def shutdown(self) -> None:
        """Cierra el adaptador de forma ordenada."""
        self.status = IntegrationStatus.SHUTTING_DOWN
        self.status = IntegrationStatus.DISABLED

    async def execute(
        self,
        capability: str,
        context: IntegrationContext,
    ) -> IntegrationExecutionResult:
        """Ejecuta una capacidad declarada a través del contrato IntegrationAdapter."""
        params = context.parameters if (context and hasattr(context, "parameters") and context.parameters) else {}
        return await self.execute_capability(capability, params, context)

    async def health_check(self) -> IntegrationHealth:
        """Verifica la salud del subsistema móvil y los dispositivos conectados."""
        devices = self.orchestrator.list_authorized_devices()
        return IntegrationHealth(
            status=self.status,
            latency_ms=0.5,
            details={
                "authorized_devices_count": len(devices),
                "windows_adb_available": self.orchestrator.driver.is_windows_adb_available(),
                "test_mode": self.orchestrator.driver.test_mode,
            },
        )

    async def execute_capability(
        self,
        capability_id: str,
        params: dict[str, Any],
        context: IntegrationContext | None = None,
    ) -> IntegrationExecutionResult:
        """Ejecuta una capacidad declarada bajo la gobernanza estricta de JDE."""
        t0 = time.perf_counter()

        if capability_id not in self._capabilities:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                verification_required=False,
                error=f"Capacidad '{capability_id}' no reconocida o no declarada en MobileControlAdapter.",
                duration_ms=(time.perf_counter() - t0) * 1000,
            )

        deadline = float(params.get("deadline_seconds", 10.0))
        cancellation_token = params.get("cancellation_token") or CancellationToken()
        session_id = params.get("session_id", "integration-mobile-session")
        request_id = params.get("request_id")

        try:
            # 1. mobile.list_authorized_devices
            if capability_id == "mobile.list_authorized_devices":
                devs = self.orchestrator.list_authorized_devices()
                data = [d.model_dump() for d in devs]
                return IntegrationExecutionResult(
                    executed=True,
                    status=ExecutionStatus.SUCCEEDED,
                    verified=True,
                    verification_required=False,
                    output={"devices": data, "count": len(data)},
                    duration_ms=(time.perf_counter() - t0) * 1000,
                )

            # 2. mobile.get_device_status
            elif capability_id == "mobile.get_device_status":
                dev_id = str(params["device_id"])
                state = self.orchestrator.get_device_status(
                    device_id=dev_id,
                    deadline_seconds=deadline,
                    cancellation_token=cancellation_token,
                )
                return IntegrationExecutionResult(
                    executed=True,
                    status=ExecutionStatus.SUCCEEDED,
                    verified=True,
                    verification_required=False,
                    output=state.model_dump(),
                    duration_ms=(time.perf_counter() - t0) * 1000,
                )

            # 3. mobile.launch_app
            elif capability_id == "mobile.launch_app":
                dev_id = str(params["device_id"])
                pkg = str(params["package_name"])
                act = params.get("activity_name")
                res = self.orchestrator.launch_app_governed(
                    device_id=dev_id,
                    package_name=pkg,
                    activity_name=act,
                    session_id=session_id,
                    request_id=request_id,
                    deadline_seconds=deadline,
                    cancellation_token=cancellation_token,
                )
                return IntegrationExecutionResult(
                    executed=True,
                    status=ExecutionStatus.SUCCEEDED if res.final_status == "SUCCESS" else ExecutionStatus.FAILED,
                    verified=(res.receipt.verified if res.receipt else False),
                    verification_required=True,
                    output=res.to_dict(),
                    duration_ms=(time.perf_counter() - t0) * 1000,
                )

            # 4. mobile.verify_foreground
            elif capability_id == "mobile.verify_foreground":
                dev_id = str(params["device_id"])
                pkg = str(params["package_name"])
                fg_pkg, fg_act = self.orchestrator.driver.get_foreground_app(
                    device_id=dev_id,
                    deadline_seconds=deadline,
                    cancellation_token=cancellation_token,
                )
                is_match = (fg_pkg == pkg)
                return IntegrationExecutionResult(
                    executed=True,
                    status=ExecutionStatus.SUCCEEDED if is_match else ExecutionStatus.FAILED,
                    verified=is_match,
                    verification_required=True,
                    output={
                        "device_id": dev_id,
                        "expected_package": pkg,
                        "observed_package": fg_pkg,
                        "observed_activity": fg_act,
                        "is_verified": is_match,
                    },
                    duration_ms=(time.perf_counter() - t0) * 1000,
                )

            # 5. mobile.orchestrate_app (Need A)
            elif capability_id == "mobile.orchestrate_app":
                dev_id = str(params["device_id"])
                msg = str(params["message"])
                res_a = self.orchestrator.orchestrate_jessyca_app(
                    device_id=dev_id,
                    message=msg,
                    session_id=session_id,
                )
                return IntegrationExecutionResult(
                    executed=True,
                    status=ExecutionStatus.SUCCEEDED,
                    verified=True,
                    verification_required=False,
                    output=res_a,
                    duration_ms=(time.perf_counter() - t0) * 1000,
                )

        except DeviceNotFoundError as ex:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                verification_required=False,
                error=f"Dispositivo no encontrado: {ex}",
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
        except DeviceDisconnectedError as ex:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                verification_required=False,
                error=f"Dispositivo desconectado: {ex}",
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
        except DeviceNotAuthorizedError as ex:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.DENIED,
                verified=False,
                verification_required=False,
                error=f"Dispositivo no autorizado: {ex}",
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
        except MobileSecurityError as ex:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.DENIED,
                verified=False,
                verification_required=False,
                error=f"Error de seguridad móvil: {ex}",
                duration_ms=(time.perf_counter() - t0) * 1000,
            )
        except Exception as ex:
            return IntegrationExecutionResult(
                executed=False,
                status=ExecutionStatus.FAILED,
                verified=False,
                verification_required=False,
                error=f"Error inesperado en adaptador móvil: {ex}",
                duration_ms=(time.perf_counter() - t0) * 1000,
            )

        return IntegrationExecutionResult(
            executed=False,
            status=ExecutionStatus.FAILED,
            verified=False,
            verification_required=False,
            error="Ruta de capacidad no manejada.",
            duration_ms=(time.perf_counter() - t0) * 1000,
        )
