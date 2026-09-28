"""Laboratorio de Pruebas de Integración y Aislamiento para Archify (lab/archify/archify_lab.py).

Permite:
- Probar el ciclo completo en aislamiento sin tocar datos de producción.
- Inyección de fallas (timeouts, especificaciones malformadas, path traversal).
- Evaluación comparativa en Shadow Mode.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Any

from core.archify.adapter import (
    ArchifyDiagramType,
    ArchifyMode,
    JessycaArchifyAdapter,
)


class ArchifyLab:
    """Entorno de laboratorio y pruebas de aislamiento de Archify."""

    def __init__(self, temp_dir: str | None = None) -> None:
        self.lab_dir = temp_dir or tempfile.mkdtemp(prefix="jessyca_archify_lab_")
        self.adapter = JessycaArchifyAdapter(mode=ArchifyMode.ACTIVE, output_dir=self.lab_dir)

    def cleanup(self) -> None:
        if os.path.exists(self.lab_dir):
            shutil.rmtree(self.lab_dir, ignore_errors=True)

    def run_health_check(self) -> dict[str, Any]:
        return self.adapter.health_check()

    def run_sample_architecture(self) -> tuple[bool, str, str]:
        spec = {
            "title": "JESSYCA 3.0 Core Architecture",
            "nodes": [
                {"id": "agent", "name": "JessycaLocalAgent"},
                {"id": "jde", "name": "Decision Engine (JDE)"},
                {"id": "skills", "name": "Skill Framework"},
                {"id": "verifier", "name": "ExecutionVerifier"},
            ],
            "edges": [
                {"from": "agent", "to": "jde"},
                {"from": "jde", "to": "skills"},
                {"from": "skills", "to": "verifier"},
            ],
        }
        return self.adapter.render_diagram(spec, "architecture", "lab_architecture.html")

    def run_failure_injections(self) -> dict[str, bool]:
        """Ejecuta batería de inyección de fallas y comprueba que todas sean manejadas de forma segura."""
        results: dict[str, bool] = {}

        # 1. Path traversal injection
        spec = {"nodes": [{"id": "n1", "name": "Node"}]}
        success, msg, path = self.adapter.render_diagram(spec, "architecture", "../../system32_evil.html")
        results["path_traversal_blocked"] = (not success and "Path Traversal" in msg)

        # 2. XSS payload in node label
        xss_spec = {
            "title": "<script>alert('xss')</script>",
            "nodes": [{"id": "x1", "name": "<img src=x onerror=alert(1)>"}],
        }
        sanitized = self.adapter.sanitize_spec(xss_spec)
        results["xss_escaped"] = ("&lt;script&gt;" in sanitized["title"] and "&lt;img" in sanitized["nodes"][0]["name"])

        # 3. Secret redaction in node details
        secret_spec = {
            "nodes": [{"id": "db", "name": "Database", "api_key": "SECRET_KEY_12345"}],
        }
        sanitized_sec = self.adapter.sanitize_spec(secret_spec)
        results["secrets_redacted"] = (sanitized_sec["nodes"][0]["api_key"] == "***REDACTED_SECRET***")

        # 4. DoS excess nodes
        huge_spec = {"nodes": [{"id": f"node_{i}"} for i in range(150)]}
        val = self.adapter.validate_spec(huge_spec)
        results["dos_limit_enforced"] = (not val.is_valid and any("máximo de nodos" in e for e in val.errors))

        return results
