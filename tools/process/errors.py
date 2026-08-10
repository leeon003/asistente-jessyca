"""Excepciones estructuradas para herramientas de gestión de procesos (Subetapa 06.3)."""

from __future__ import annotations

from core.exceptions import MCPError


class ProcessError(MCPError):
    """Error base para operaciones sobre procesos de Windows."""

    def __init__(self, message: str = "Error en la operación sobre procesos.") -> None:
        super().__init__(message)


class ProtectedProcessError(ProcessError):
    """Intento denegado de terminar un proceso crítico protegido del sistema Windows."""

    def __init__(self, process_name: str, pid: int) -> None:
        super().__init__(f"Proceso Protegido del Sistema: No se permite terminar '{process_name}' (PID: {pid}).")
        self.process_name = process_name
        self.pid = pid


class ProcessNotFoundError(ProcessError):
    """El proceso especificado por PID o nombre no existe o ya ha finalizado."""

    def __init__(self, identifier: int | str) -> None:
        super().__init__(f"Proceso no encontrado o finalizado: '{identifier}'")
        self.identifier = identifier


class ProcessAccessDeniedError(ProcessError):
    """El sistema operativo denegó el acceso al consultar o terminar el proceso."""

    def __init__(self, pid: int, operation: str = "access") -> None:
        super().__init__(f"Acceso Denegado por el Sistema Operativo para operación '{operation}' en PID {pid}.")
        self.pid = pid
        self.operation = operation


class PIDReuseError(ProcessError):
    """Detección de reutilización de PID o sustitución del proceso objetivo tras la autorización."""

    def __init__(self, pid: int, expected_name: str, actual_name: str) -> None:
        super().__init__(
            f"Detección de Reutilización de PID (PID Reuse Mismatch): El PID {pid} pertenecía a '{expected_name}', "
            f"pero actualmente pertenece a '{actual_name}'. Operación denegada."
        )
        self.pid = pid
        self.expected_name = expected_name
        self.actual_name = actual_name


class InvalidPIDError(ProcessError):
    """Identificador de proceso (PID) con formato o valor numérico inválido."""

    def __init__(self, pid_value: object) -> None:
        super().__init__(f"Identificador de proceso PID inválido: {pid_value}")
        self.pid_value = pid_value


class ProcessTerminationError(ProcessError):
    """Error durante el intento de terminación de un proceso."""

    def __init__(self, pid: int, reason: str) -> None:
        super().__init__(f"Error al terminar proceso PID {pid}: {reason}")
        self.pid = pid
        self.reason = reason
