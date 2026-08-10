"""Servicio seguro de inspección y gestión de procesos Windows (Subetapa 06.3).

Utiliza la biblioteca psutil exclusivamente para la consulta y administración directa de procesos.
GARANTÍA DE CERO SHELL EXECUTION:
NO utiliza subprocess, os.system, cmd.exe, powershell.exe, ctypes ni os.popen.
Enforza la Protección de Procesos del Sistema Protegidos y la Protección contra Reutilización de PID (PID Reuse Protection).
"""

from __future__ import annotations

import psutil

from config.settings import AppSettings
from core.logger import get_logger
from tools.process.errors import (
    InvalidPIDError,
    PIDReuseError,
    ProcessAccessDeniedError,
    ProcessError,
    ProcessNotFoundError,
    ProcessTerminationError,
    ProtectedProcessError,
)
from tools.process.models import (
    ProcessInfo,
    ProcessListResult,
    ProcessTerminationResult,
)

logger = get_logger("jessyca.tools.process.service")


class ProcessService:
    """Servicio desacoplado para interacción directa y segura con procesos de Windows."""

    def __init__(self) -> None:
        settings = AppSettings()
        self.max_list_entries: int = settings.PROCESS_MAX_LIST_ENTRIES
        self.query_timeout: float = settings.PROCESS_QUERY_TIMEOUT
        self.termination_timeout: float = settings.PROCESS_TERMINATION_TIMEOUT
        self.protected_names: set[str] = {name.lower() for name in settings.PROCESS_PROTECTED_NAMES}

    def validate_pid(self, pid: object) -> int:
        """Valida que el PID sea un número entero positivo."""
        if not isinstance(pid, (int, str)):
            raise InvalidPIDError(pid)
        try:
            pid_int = int(pid)
            if pid_int < 0:
                raise InvalidPIDError(pid)
            return pid_int
        except (ValueError, TypeError):
            raise InvalidPIDError(pid)

    def is_protected_process(self, process_name: str) -> bool:
        """Verifica si un nombre de proceso pertenece a la lista de procesos protegidos."""
        clean_name = process_name.strip().lower()
        return clean_name in self.protected_names

    def get_process_info_from_proc(self, proc: psutil.Process) -> ProcessInfo:
        """Extrae la información de metadatos segura de un objeto psutil.Process."""
        try:
            with proc.oneshot():
                pid = proc.pid
                ppid = proc.ppid()
                name = proc.name() or "unknown"
                try:
                    exe = proc.exe() or ""
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    exe = ""
                status = proc.status() or "unknown"
                try:
                    username = proc.username() or ""
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    username = ""
                create_time = proc.create_time()
                try:
                    mem_info = proc.memory_info()
                    memory_usage = mem_info.rss if mem_info else 0
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    memory_usage = 0
                cpu_percent = 0.0

                return ProcessInfo(
                    pid=pid,
                    parent_pid=ppid,
                    name=name,
                    executable_path=exe,
                    status=status,
                    username=username,
                    creation_time=create_time,
                    memory_usage=memory_usage,
                    cpu_percent=cpu_percent,
                )
        except psutil.NoSuchProcess:
            raise ProcessNotFoundError(proc.pid)
        except psutil.AccessDenied:
            raise ProcessAccessDeniedError(proc.pid, "get_info")

    def list_processes(self, limit: int | None = None) -> ProcessListResult:
        """Lista las entradas de procesos activos del sistema con límite acotado."""
        max_entries = limit if (limit and limit > 0) else self.max_list_entries
        processes_list: list[ProcessInfo] = []
        truncated = False

        for proc in psutil.process_iter():
            if len(processes_list) >= max_entries:
                truncated = True
                break
            try:
                info = self.get_process_info_from_proc(proc)
                processes_list.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessError):
                continue

        # Ordenar determinísticamente por PID
        processes_list.sort(key=lambda p: p.pid)

        return ProcessListResult(
            count=len(processes_list),
            truncated=truncated,
            processes=tuple(processes_list),
        )

    def get_process(self, pid: object) -> ProcessInfo:
        """Obtiene la información detallada de un proceso por su PID."""
        pid_int = self.validate_pid(pid)
        try:
            proc = psutil.Process(pid_int)
            return self.get_process_info_from_proc(proc)
        except psutil.NoSuchProcess:
            raise ProcessNotFoundError(pid_int)
        except psutil.AccessDenied:
            raise ProcessAccessDeniedError(pid_int, "get_process")

    def terminate_process(
        self,
        pid: object,
        expected_name: str | None = None,
        expected_creation_time: float | None = None,
    ) -> ProcessTerminationResult:
        """Termina un proceso activo verificando Protected Processes y PID Reuse Protection."""
        pid_int = self.validate_pid(pid)

        try:
            proc = psutil.Process(pid_int)
            proc_name = proc.name() or "unknown"
            proc_create_time = proc.create_time()
        except psutil.NoSuchProcess:
            raise ProcessNotFoundError(pid_int)
        except psutil.AccessDenied:
            raise ProcessAccessDeniedError(pid_int, "terminate")

        # 1. Protección contra Terminación de Procesos Críticos del Sistema
        if self.is_protected_process(proc_name):
            logger.warning(f"[PROTECTED PROCESS DENY] Intento de terminar proceso protegido: '{proc_name}' (PID: {pid_int})")
            raise ProtectedProcessError(proc_name, pid_int)

        # 2. Protección contra Reutilización de PID (PID Reuse Protection)
        if expected_name and proc_name.lower() != expected_name.lower():
            logger.error(
                f"[PID REUSE MISMATCH] El PID {pid_int} esperaba '{expected_name}', pero pertenece a '{proc_name}'"
            )
            raise PIDReuseError(pid_int, expected_name, proc_name)

        if expected_creation_time is not None:
            if abs(proc_create_time - expected_creation_time) > 1.5:
                logger.error(
                    f"[PID REUSE MISMATCH] El tiempo de creación de PID {pid_int} ({proc_create_time}) "
                    f"no coincide con el autorizado ({expected_creation_time})"
                )
                raise PIDReuseError(pid_int, expected_name or proc_name, proc_name)

        # 3. Intentar terminación segura
        try:
            proc.terminate()
            gone, alive = psutil.wait_procs([proc], timeout=self.termination_timeout)

            if proc in alive:
                # Si el proceso no finalizó con SIGTERM/terminate, forzar kill
                proc.kill()
                proc.wait(timeout=self.termination_timeout)

            return ProcessTerminationResult(
                pid=pid_int,
                process_name=proc_name,
                success=True,
                status="TERMINATED",
                reason="Proceso terminado exitosamente.",
            )
        except psutil.AccessDenied:
            raise ProcessAccessDeniedError(pid_int, "terminate")
        except psutil.NoSuchProcess:
            # El proceso ya finalizó durante la operación
            return ProcessTerminationResult(
                pid=pid_int,
                process_name=proc_name,
                success=True,
                status="TERMINATED",
                reason="Proceso finalizado durante la terminación.",
            )
        except Exception as e:
            raise ProcessTerminationError(pid_int, str(e))
