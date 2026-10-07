"""core/distribution/service_client.py

Modelo de servicio y cliente para la compartición de estado y concurrencia de JESSYCA.
Garantiza que CLI, WebUI y Voz interactúen a través del mismo Core:
- Si el servicio Core ya está corriendo (demonio/WebUI bridge en loopback):
  El CLI actúa como cliente liviano enviando las solicitudes al Core activo,
  preservando la memoria, sesiones en curso y estado en tiempo real.
- Si el servicio Core no está corriendo:
  El CLI o cliente ejecuta el Core embebido con bloqueo explícito inter-proceso
  (lockfile atómico con detección de procesos huérfanos) y SQLite en modo WAL,
  evitando colisiones en disco.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.distribution.paths import get_paths
from core.logger import get_logger

logger = get_logger("jessyca.distribution.service_client")

DEFAULT_CORE_HOST = "127.0.0.1"
DEFAULT_CORE_PORT = 8088


@dataclass
class CoreServiceStatus:
    """Estado en vivo del servicio Core."""
    is_running: bool
    host: str
    port: int
    pid: int | None = None
    endpoint_url: str | None = None
    details: dict[str, Any] | None = None


class CoreProcessLock:
    """Bloqueo concurrente inter-proceso explícito para evitar corrupción de estado en disco."""

    def __init__(self, lock_file: Path | str, timeout_seconds: float = 5.0) -> None:
        self.lock_file = Path(lock_file)
        self.timeout_seconds = timeout_seconds
        self._acquired = False

    def acquire(self) -> bool:
        """Intenta adquirir el lock atómico en disco."""
        deadline = time.time() + self.timeout_seconds
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)

        while time.time() < deadline:
            try:
                # Apertura exclusiva atómica
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
                fd = os.open(str(self.lock_file), flags)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    payload = {
                        "pid": os.getpid(),
                        "acquired_at": time.time(),
                        "owner": "jessyca-process",
                    }
                    json.dump(payload, f)
                self._acquired = True
                return True
            except FileExistsError:
                # Verificar si el lock pertenece a un proceso muerto
                if self._is_lock_stale():
                    try:
                        self.lock_file.unlink(missing_ok=True)
                        continue
                    except OSError:
                        pass
                time.sleep(0.05)
            except Exception as e:
                logger.warning(f"[CORE LOCK] Error intentando adquirir lock: {e}")
                time.sleep(0.05)

        return False

    def release(self) -> None:
        """Libera el lock eliminando el archivo."""
        if self._acquired:
            try:
                self.lock_file.unlink(missing_ok=True)
            except OSError as e:
                logger.warning(f"[CORE LOCK] Error liberando lock: {e}")
            finally:
                self._acquired = False

    def _is_lock_stale(self) -> bool:
        """Determina si el PID registrado en el lockfile ya no existe."""
        try:
            if not self.lock_file.exists():
                return True
            content = self.lock_file.read_text(encoding="utf-8")
            data = json.loads(content)
            pid = data.get("pid")
            if not pid or not isinstance(pid, int):
                return True

            # En Windows / POSIX comprobación de PID vivo
            if os.name == "nt":
                import ctypes
                kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
                # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                handle = kernel32.OpenProcess(0x1000, False, pid)
                if handle == 0:
                    return True
                kernel32.CloseHandle(handle)
                return False
            else:
                os.kill(pid, 0)
                return False
        except (ProcessLookupError, OSError, ValueError):
            return True


@contextmanager
def explicit_core_lock(timeout_seconds: float = 5.0) -> Generator[bool, None, None]:
    """Context manager para adquirir el lock de estado del Core."""
    paths = get_paths()
    lock_file = paths.data_dir / "core.lock"
    lock = CoreProcessLock(lock_file=lock_file, timeout_seconds=timeout_seconds)
    acquired = lock.acquire()
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()


class CoreClient:
    """Cliente para comunicarse con el servicio Core o invocar el Core embebido."""

    def __init__(self, host: str = DEFAULT_CORE_HOST, port: int = DEFAULT_CORE_PORT) -> None:
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"

    def check_service_status(self, timeout_seconds: float = 1.0) -> CoreServiceStatus:
        """Comprueba si el servicio Core está respondiendo en el host y puerto especificados."""
        health_url = f"{self.base_url}/health"
        try:
            req = urllib.request.Request(health_url, headers={"User-Agent": "JessycaCLI/3.0"})
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                if response.status == 200:
                    payload = json.loads(response.read().decode("utf-8"))
                    return CoreServiceStatus(
                        is_running=True,
                        host=self.host,
                        port=self.port,
                        endpoint_url=self.base_url,
                        details=payload,
                    )
        except Exception:
            pass

        return CoreServiceStatus(
            is_running=False,
            host=self.host,
            port=self.port,
            endpoint_url=None,
            details=None,
        )

    def send_prompt_to_service(
        self,
        prompt: str,
        session_id: str = "cli-session",
        auth_token: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> str:
        """Envía un prompt al servicio Core activo a través del endpoint OpenAI-Compatible."""
        endpoint = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": "jessyca-core",
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "JessycaCLI/3.0",
            "X-Session-ID": session_id,
        }
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(endpoint, data=data_bytes, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            choices = body.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "")
            return ""

    def execute_embedded(self, prompt: str, session_id: str = "cli-session") -> str:
        """Ejecuta la solicitud en el Core embebido garantizando bloqueo inter-proceso."""
        with explicit_core_lock(timeout_seconds=5.0) as acquired:
            if not acquired:
                raise TimeoutError("No se pudo adquirir el bloqueo de ejecución del Core (otro proceso activo).")

            # Importación diferida para no penalizar el tiempo de arranque de comandos rápidos
            from core.local_agent.local_agent import JessycaLocalAgent

            agent = JessycaLocalAgent.get_instance()
            resp = agent.process_interaction(prompt, session_id=session_id)
            return resp.response_text if hasattr(resp, "response_text") else str(resp)

    def execute(self, prompt: str, session_id: str = "cli-session", auth_token: str | None = None) -> str:
        """Ruta canónica: si el servicio está activo, delega en él; si no, ejecuta embebido."""
        status = self.check_service_status()
        if status.is_running:
            try:
                return self.send_prompt_to_service(
                    prompt=prompt,
                    session_id=session_id,
                    auth_token=auth_token,
                )
            except Exception as e:
                logger.warning(f"[CORE CLIENT] Falló llamada al servicio ({e}). Pasando a ejecución embebida.")

        return self.execute_embedded(prompt=prompt, session_id=session_id)
