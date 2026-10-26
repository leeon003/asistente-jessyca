"""Optional, fail-closed OpenHands Agent Server connectivity adapter.

OpenHands must be run in a separate sandbox. This module does not submit tasks,
execute shell commands, access arbitrary paths or grant OS permissions.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class OpenHandsConfig:
    endpoint: str = "http://127.0.0.1:8000"
    enabled: bool = False
    timeout_seconds: float = 3.0

    def __post_init__(self) -> None:
        parts = urlsplit(self.endpoint)
        if parts.scheme != "http" or parts.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("OpenHands requires a local loopback HTTP endpoint")
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("Endpoint must not include credentials or queries")
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError("Timeout must be > 0 and <= 30 seconds")


class OpenHandsBridge:
    """Read-only server discovery; explicit human approval required for future tasks."""

    def __init__(self, config: OpenHandsConfig | None = None):
        self.config = config or OpenHandsConfig()

    def status(self) -> dict[str, object]:
        if not self.config.enabled:
            return {"enabled": False, "reachable": False, "message": "OpenHands desactivado"}
        request = Request(
            self.config.endpoint.rstrip("/") + "/openapi.json",
            headers={"Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.config.timeout_seconds) as response:
                if getattr(response, "status", 200) != 200:
                    return {"enabled": True, "reachable": False, "message": "Respuesta no exitosa"}
                body = response.read(32768)
            document = json.loads(body)
            valid = isinstance(document, dict) and "openapi" in document
            return {
                "enabled": True, "reachable": valid,
                "message": "Servidor API detectado" if valid else "API incompatible",
            }
        except (OSError, ValueError, UnicodeError):
            return {"enabled": True, "reachable": False, "message": "Servidor no disponible"}
