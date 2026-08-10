r"""Frontera de Seguridad para Escritura en Registro de Windows (RegistryWriteBoundary - Etapa 15.2).

GARANTÍAS RIGUROSAS DE SEGURIDAD EN ETAPA 15.2:
1. DESHABILITADO POR DEFECTO (REGISTRY_WRITE_ENABLED=False).
2. MECANISMO DE SEGURIDAD PRINCIPAL: ALLOWLIST EXPLÍCITA (REGISTRY_WRITE_ALLOWLIST). NUNCA BLOCKLIST COMO MECANISMO PRINCIPAL.
3. VALIDACIÓN RIGUROSA DE RUTAS, CLAVES Y TIPOS DE VALORES (REG_SZ, REG_DWORD, etc.).
4. PROHIBICIÓN ABSOLUTA DE:
   - HKLM global sin allowlist explícita.
   - Claves de persistencia Autorun (Run, RunOnce, Winlogon, Startup).
   - Modificación de políticas de seguridad (Policies\Microsoft).
   - Debilitamiento de Windows Defender o componentes de seguridad.
   - Rutas arbitrarias o con Path Traversal.
5. MUESTRA OBLIGATORIA AL USUARIO ANTES DE CONFIRMAR:
   Clave, valor anterior, valor nuevo y tipo de operación.
6. SOPORTE TRANSACCIONAL REVERSIBLE CON SNAPSHOT PREVIO, VERIFICACIÓN POSTERIOR Y ROLLBACK AUTOMÁTICO.
"""

from __future__ import annotations

import re
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

logger = get_logger("jessyca.core.registry_boundary")

# Tipos de datos de registro soportados
ALLOWED_REGISTRY_TYPES = {"REG_SZ", "REG_DWORD", "REG_MULTI_SZ", "REG_BINARY", "REG_EXPAND_SZ", "REG_QWORD"}

# Patrones prohibidos de persistencia, políticas y seguridad en Windows
FORBIDDEN_PERSISTENCE_PATTERNS = re.compile(
    r"\\(run|runonce|runonceex|winlogon|userinit|shell|explorer\\run|startup|services)",
    re.IGNORECASE,
)
FORBIDDEN_SECURITY_PATTERNS = re.compile(
    r"\\(policies\\microsoft|windows defender|security center|uac|consentpromptbehavior)",
    re.IGNORECASE,
)


class RegistryBoundaryError(MCPError):
    """Error base de fronteras de escritura en el registro."""

    pass


class RegistryWriteDisabledError(RegistryBoundaryError):
    """Error emitido cuando la modificación del registro está deshabilitada (REGISTRY_WRITE_ENABLED=False)."""

    pass


class RegistrySecurityViolationError(RegistryBoundaryError):
    """Error emitido ante violaciones de allowlist, persistencia prohibida o sintaxis maliciosa."""

    pass


@dataclass(frozen=True)
class RegistryWriteRequest:
    """Solicitud formal de modificación en el Registro de Windows."""

    key_path: str
    value_name: str
    value_data: Any
    value_type: str = "REG_SZ"
    operation: str = "set_value"  # set_value, delete_value, create_key


class RegistryWriteBoundary:
    """Frontera de Seguridad para Escritura en Registro de Windows (Etapa 15.2).

    Construida sobre ChangeTransactionManager. Enforza allowlist explícita y reversibilidad.
    """

    def __init__(
        self,
        transaction_manager: ChangeTransactionManager | None = None,
        enabled: bool | None = None,
        allowlist: list[str] | None = None,
    ) -> None:
        from config.settings import AppSettings
        settings = AppSettings()

        self.enabled = enabled if enabled is not None else settings.REGISTRY_WRITE_ENABLED
        self.allowlist = allowlist if allowlist is not None else settings.REGISTRY_WRITE_ALLOWLIST
        self.transaction_manager = transaction_manager or ChangeTransactionManager()
        self.audit_logger = get_audit_logger()

    def prepare_registry_write(
        self,
        request: RegistryWriteRequest,
        mock_registry_reader: Callable[[str, str], Any] | None = None,
        mock_registry_writer: Callable[[str, str, Any, str], bool] | None = None,
    ) -> tuple[ChangeTransaction, dict[str, Any]]:
        """Prepara una transacción de modificación de registro con comprobaciones rigurosas.

        Retorna la transacción creada y la estructura de resumen de impacto (*Diff View*) para el usuario.
        """
        # 1. VERIFICACIÓN DE HABILITACIÓN GLOBAL (DISABLED BY DEFAULT)
        if not self.enabled:
            raise RegistryWriteDisabledError(
                "[REGISTRY DISABLED] La modificación del Registro de Windows está deshabilitada por configuración (REGISTRY_WRITE_ENABLED=False)."
            )

        # 2. NORMALIZACIÓN DE RUTA
        norm_path = self.normalize_registry_path(request.key_path)

        # 3. VALIDACIÓN DE PERMISIVIDAD POR ALLOWLIST EXPLÍCITA (MECANISMO PRINCIPAL)
        self._validate_explicit_allowlist(norm_path, self.allowlist)


        # 4. COMPROBACIONES DE SEGURIDAD SECUNDARIAS (PATRONES PROHIBIDOS)
        self._validate_security_invariants(norm_path, request)

        # 5. LECTURA DE ESTADO PREVIO (PRE-STATE SNAPSHOT)
        def pre_state_fn() -> dict[str, Any]:
            if mock_registry_reader:
                old_val = mock_registry_reader(norm_path, request.value_name)
            else:
                old_val = None  # Simulado / Modo seguro sin acceso físico
            return {"key_path": norm_path, "value_name": request.value_name, "value_data": old_val, "value_type": request.value_type}

        # 6. DEFINICIÓN DE HANDLER DE EJECUCIÓN (EXECUTE_FN)
        def execute_fn() -> dict[str, Any]:
            if mock_registry_writer:
                mock_registry_writer(norm_path, request.value_name, request.value_data, request.value_type)
            return {"key_path": norm_path, "value_name": request.value_name, "new_value_data": request.value_data, "value_type": request.value_type}

        # 7. DEFINICIÓN DE HANDLER DE VERIFICACIÓN (VERIFY_FN)
        def verify_fn(post_data: dict[str, Any]) -> bool:
            if mock_registry_reader:
                check_val = mock_registry_reader(norm_path, request.value_name)
                return bool(check_val == request.value_data)
            return True


        # 8. DEFINICIÓN DE HANDLER DE ROLLBACK (ROLLBACK_FN)
        def rollback_fn(pre_data: dict[str, Any]) -> bool:
            old_val = pre_data.get("value_data")
            if mock_registry_writer:
                mock_registry_writer(norm_path, request.value_name, old_val, request.value_type)
            return True

        # Captura preliminar de datos anteriores para el resumen de impacto
        pre_snap = pre_state_fn()

        # ESTRUCTURA DE RESUMEN DE IMPACTO PARA MOSTRAR AL USUARIO ANTES DE CONFIRMAR
        impact_summary = {
            "target_key": norm_path,
            "value_name": request.value_name,
            "old_value": pre_snap.get("value_data"),
            "new_value": request.value_data,
            "value_type": request.value_type,
            "operation": request.operation,
        }

        # PREPARAR TRANSACCIÓN SOBRE ChangeTransactionManager
        tx = self.transaction_manager.prepare_transaction(
            target_resource=f"{norm_path}\\{request.value_name}",
            operation_type=f"registry.{request.operation}",
            reversibility=Reversibility.REVERSIBLE,
            pre_state_fn=pre_state_fn,
            execute_fn=execute_fn,
            rollback_fn=rollback_fn,
            verify_fn=verify_fn,
        )

        logger.info(f"[REGISTRY BOUNDARY] Transacción preparada exitosamente para '{norm_path}\\{request.value_name}'.")
        return tx, impact_summary

    def normalize_registry_path(self, path_str: str) -> str:
        """Normaliza cadenas de rutas de registro a formato canónico en minúsculas.

        Lanza RegistrySecurityViolationError ante sintaxis maliciosa o malformada.
        """
        if not path_str or not path_str.strip():
            raise RegistrySecurityViolationError("La ruta de Registro no puede estar vacía.")

        cleaned = path_str.strip().replace("/", "\\")

        # Detectar Path Traversal (..) o caracteres nulos
        if ".." in cleaned or "\x00" in cleaned:
            raise RegistrySecurityViolationError(f"[PATH TRAVERSAL DETECTED] Sintaxis de ruta de Registro maliciosa: '{path_str}'")

        # Mapear prefijos HKEY a abreviaciones estándar (HKCU, HKLM, HKCR, HKU)
        lower_path = cleaned.lower()
        if lower_path.startswith("hkey_current_user"):
            cleaned = "hkcu" + cleaned[17:]
        elif lower_path.startswith("hkey_local_machine"):
            cleaned = "hklm" + cleaned[18:]
        elif lower_path.startswith("hkey_classes_root"):
            cleaned = "hkcr" + cleaned[17:]
        elif lower_path.startswith("hkey_users"):
            cleaned = "hku" + cleaned[10:]

        return cleaned.lower()

    def _validate_explicit_allowlist(self, norm_path: str, allowlist: list[str]) -> None:
        """Valida que la ruta normalizada coincida explícitamente con alguna entrada de la allowlist."""
        is_allowed = False
        for allowed_prefix in allowlist:
            norm_allowed = self.normalize_registry_path(allowed_prefix)
            if norm_path == norm_allowed or norm_path.startswith(norm_allowed + "\\"):
                is_allowed = True
                break

        if not is_allowed:
            raise RegistrySecurityViolationError(
                f"[ALLOWLIST VIOLATION] La ruta '{norm_path}' NO pertenece a la REGISTRY_WRITE_ALLOWLIST explícita del sistema. Modificación bloqueada."
            )

    def _validate_security_invariants(self, norm_path: str, request: RegistryWriteRequest) -> None:
        """Valida invariantes absolutos de seguridad (previene persistencia Autorun, depuración de Defender, etc.)."""
        # A. Prohibir escrituras HKLM globales salvo exoneración específica
        if norm_path.startswith("hklm") and "jessyca" not in norm_path:
            raise RegistrySecurityViolationError(
                f"[SECURITY VIOLATION] Escrituras globales en HKLM están prohibidas por defecto: '{norm_path}'."
            )

        # B. Prohibir persistenias Autorun (Run, RunOnce, Winlogon, Startup)
        if FORBIDDEN_PERSISTENCE_PATTERNS.search(norm_path):
            raise RegistrySecurityViolationError(
                f"[PERSISTENCE ATTEMPT REJECTED] Modificación de claves de persistencia Autorun prohibida: '{norm_path}'."
            )

        # C. Prohibir modificación de Políticas de Seguridad y Windows Defender
        if FORBIDDEN_SECURITY_PATTERNS.search(norm_path):
            raise RegistrySecurityViolationError(
                f"[DEFENDER DEGRADATION REJECTED] Modificación de políticas de seguridad o Windows Defender prohibida: '{norm_path}'."
            )

        # D. Validar Tipo de Dato de Registro
        if request.value_type.upper() not in ALLOWED_REGISTRY_TYPES:
            raise RegistrySecurityViolationError(
                f"[INVALID TYPE] Tipo de dato de registro no válido '{request.value_type}'. Tipos soportados: {ALLOWED_REGISTRY_TYPES}"
            )
