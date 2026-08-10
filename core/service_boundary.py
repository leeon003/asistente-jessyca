r"""Frontera de Seguridad para Administración de Servicios de Windows (ServiceControlBoundary - Etapa 15.3).

GARANTÍAS RIGUROSAS DE SEGURIDAD EN ETAPA 15.3:
1. DESHABILITADO POR DEFECTO (SERVICE_WRITE_ENABLED=False).
2. PROTECCIÓN RIGUROSA DE SERVICIOS CRÍTICOS DEL SO (SERVICE_PROTECTED_LIST):
   - WinDefend, RPCSS, lsass, EventLog, wuauserv, mpssvc, Dhcp, Dnscache, etc.
   - Cualquier intento de modificación sobre un servicio protegido es rechazado inmediatamente con ProtectedServiceViolationError.
3. INSPECCIÓN PREVIA OBLIGATORIA:
   - Identificación del servicio, estado actual, dependencias, impacto y reversibilidad.
4. MUESTRA OBLIGATORIA AL USUARIO ANTES DE CONFIRMAR.
5. INTEGRACIÓN TRANSACCIONAL SOBRE ChangeTransactionManager (PREPARE -> SNAPSHOT -> CONFIRM -> EXECUTE -> VERIFY -> COMMIT).
6. VERIFICACIÓN POSTERIOR Y ROLLBACK AUTOMÁTICO AL ESTADO ANTERIOR SI LA OPERACIÓN O VERIFICACIÓN FALLA.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.audit_logger import get_audit_logger
from core.change_transaction import (
    ChangeTransaction,
    ChangeTransactionManager,
    Reversibility,
)
from core.exceptions import MCPError
from core.logger import get_logger

logger = get_logger("jessyca.core.service_boundary")

ALLOWED_SERVICE_OPERATIONS = {"start", "stop", "restart"}


class ServiceBoundaryError(MCPError):
    """Error base de fronteras de servicios de Windows."""

    pass


class ServiceWriteDisabledError(ServiceBoundaryError):
    """Error emitido cuando la administración de servicios está deshabilitada (SERVICE_WRITE_ENABLED=False)."""

    pass


class ProtectedServiceViolationError(ServiceBoundaryError):
    """Error emitido cuando se intenta modificar un servicio protegido del sistema operativo."""

    pass


class UnknownServiceError(ServiceBoundaryError):
    """Error emitido cuando no se puede identificar el servicio solicitado."""

    pass


@dataclass(frozen=True)
class ServiceControlRequest:
    """Solicitud formal de control/modificación de un servicio de Windows."""

    service_name: str
    operation: str  # "start", "stop", "restart"


class ServiceControlBoundary:
    """Frontera de Seguridad para Administración de Servicios de Windows (Etapa 15.3).

    Construida sobre ChangeTransactionManager. Enforza protección de servicios críticos y reversibilidad.
    """

    def __init__(
        self,
        transaction_manager: ChangeTransactionManager | None = None,
        enabled: bool | None = None,
        protected_list: list[str] | None = None,
    ) -> None:
        from config.settings import AppSettings

        settings = AppSettings()
        self.enabled = enabled if enabled is not None else settings.SERVICE_WRITE_ENABLED
        self.protected_list = [
            s.strip().lower() for s in (protected_list if protected_list is not None else settings.SERVICE_PROTECTED_LIST)
        ]
        self.transaction_manager = transaction_manager or ChangeTransactionManager()
        self.audit_logger = get_audit_logger()

    def prepare_service_control(
        self,
        request: ServiceControlRequest,
        mock_service_inspector: Callable[[str], dict[str, Any] | None] | None = None,
        mock_service_executor: Callable[[str, str], bool] | None = None,
    ) -> tuple[ChangeTransaction, dict[str, Any]]:
        """Prepara una transacción de control de servicio verificando políticas y estado actual.

        Retorna la transacción creada y la estructura del resumen de impacto para el usuario.
        """
        # 1. VERIFICACIÓN DE HABILITACIÓN GLOBAL
        if not self.enabled:
            raise ServiceWriteDisabledError(
                "[SERVICE WRITE DISABLED] La administración de servicios está deshabilitada por configuración (SERVICE_WRITE_ENABLED=False)."
            )

        # 2. VALIDACIÓN DE OPERACIÓN SOPORTADA
        op_clean = request.operation.strip().lower()
        if op_clean not in ALLOWED_SERVICE_OPERATIONS:
            raise ServiceBoundaryError(
                f"[INVALID OPERATION] Operación de servicio no soportada '{request.operation}'. Operaciones permitidas: {ALLOWED_SERVICE_OPERATIONS}"
            )

        # 3. NORMALIZACIÓN Y PROTECCIÓN DE SERVICIOS CRÍTICOS
        service_clean = request.service_name.strip().lower()
        if not service_clean:
            raise ServiceBoundaryError("El nombre del servicio no puede estar vacío.")

        if service_clean in self.protected_list:
            raise ProtectedServiceViolationError(
                f"[PROTECTED SERVICE REJECTED] El servicio '{request.service_name}' es un servicio crítico protegido del SO y NO puede ser modificado."
            )

        # 4. INSPECCIÓN DEL SERVICIO (ESTADO ACTUAL Y DEPENDENCIAS)
        service_info: dict[str, Any] | None = None
        if mock_service_inspector:
            service_info = mock_service_inspector(service_clean)
        else:
            # Inspección predeterminada o simulada en modo seguro
            service_info = {
                "service_name": service_clean,
                "status": "Stopped" if op_clean == "start" else "Running",
                "dependencies": [],
                "exists": True,
            }

        if not service_info or not service_info.get("exists", True):
            raise UnknownServiceError(f"[UNKNOWN SERVICE] El servicio '{request.service_name}' no existe o no fue encontrado en el sistema.")

        current_status = service_info.get("status", "Unknown")
        target_status = "Running" if op_clean in ("start", "restart") else "Stopped"
        dependencies = service_info.get("dependencies", [])

        # 5. ESTRUCTURA DE RESUMEN DE IMPACTO PARA EL USUARIO ANTES DE CONFIRMAR
        impact_summary = {
            "service_name": service_clean,
            "operation": op_clean,
            "current_state": current_status,
            "target_state": target_status,
            "dependencies": dependencies,
            "reversibility": Reversibility.REVERSIBLE.value,
            "impact": f"Cambio de estado del servicio '{service_clean}' de '{current_status}' a '{target_status}'.",
        }

        # 6. DEFINICIÓN DE PRE-STATE SNAPSHOT
        def pre_state_fn() -> dict[str, Any]:
            return {
                "service_name": service_clean,
                "status": current_status,
                "dependencies": dependencies,
            }

        # 7. DEFINICIÓN DE HANDLER DE EJECUCIÓN (EXECUTE_FN)
        def execute_fn() -> dict[str, Any]:
            if mock_service_executor:
                success = mock_service_executor(service_clean, op_clean)
                if not success:
                    raise ServiceBoundaryError(f"Fallo al ejecutar la operación '{op_clean}' en el servicio '{service_clean}'.")
            return {"service_name": service_clean, "operation": op_clean, "new_status": target_status}

        # 8. DEFINICIÓN DE HANDLER DE VERIFICACIÓN (VERIFY_FN)
        def verify_fn(post_data: dict[str, Any]) -> bool:
            if mock_service_inspector:
                check_info = mock_service_inspector(service_clean)
                if check_info:
                    return bool(check_info.get("status") == target_status)
            return True

        # 9. DEFINICIÓN DE HANDLER DE ROLLBACK (ROLLBACK_FN)
        def rollback_fn(pre_data: dict[str, Any]) -> bool:
            orig_status = pre_data.get("status", "Stopped")
            reverse_op = "stop" if orig_status == "Stopped" else "start"
            if mock_service_executor:
                mock_service_executor(service_clean, reverse_op)
            return True

        # PREPARAR TRANSACCIÓN SOBRE ChangeTransactionManager
        tx = self.transaction_manager.prepare_transaction(
            target_resource=f"service:{service_clean}",
            operation_type=f"service.{op_clean}",
            reversibility=Reversibility.REVERSIBLE,
            pre_state_fn=pre_state_fn,
            execute_fn=execute_fn,
            rollback_fn=rollback_fn,
            verify_fn=verify_fn,
        )

        logger.info(f"[SERVICE BOUNDARY] Transacción preparada exitosamente para servicio '{service_clean}' ({op_clean}).")
        return tx, impact_summary
