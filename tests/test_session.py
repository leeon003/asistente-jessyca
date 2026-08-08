"""Pruebas unitarias completas del Session Manager y exportación de informes."""

from __future__ import annotations

import json
from pathlib import Path

from core.session_manager import SessionManager


def test_session_lifecycle() -> None:
    sm = SessionManager()

    # Iniciar sesión
    session = sm.start_session(user="TestUser", metadata={"env": "testing"})
    assert session.is_active is True
    assert session.user == "TestUser"
    assert session.session_id is not None

    # Registrar herramientas
    sm.record_tool_usage("system_health", {"include_metrics": True}, is_success=True)
    sm.record_tool_usage("copy_file", {"src": "a", "dst": "b"}, is_success=False, error="File not found")
    sm.record_error("Conexión de red inestable", details={"code": 500})

    # Finalizar sesión
    ended_session = sm.end_session()
    assert ended_session is not None
    assert ended_session.is_active is False
    assert ended_session.duration_seconds >= 0.0
    assert len(ended_session.tools_used) == 2
    assert len(ended_session.errors) == 1


def test_session_export_json_and_markdown(temp_dir: Path) -> None:
    sm = SessionManager()
    session = sm.start_session(user="ExportUser")

    sm.record_tool_usage("ping_tool", {"host": "127.0.0.1"}, is_success=True)
    sm.end_session()

    # Exportar JSON
    json_path = temp_dir / "session.json"
    json_str = sm.export_session(session.session_id, format="json", file_path=json_path)
    assert json_path.exists()
    parsed = json.loads(json_str)
    assert parsed["user"] == "ExportUser"
    assert parsed["tools_used_count"] == 1

    # Exportar Markdown
    md_path = temp_dir / "session.md"
    md_str = sm.export_session(session.session_id, format="markdown", file_path=md_path)
    assert md_path.exists()
    assert "# Reporte de Sesión MCP" in md_str
    assert "`ping_tool`" in md_str
