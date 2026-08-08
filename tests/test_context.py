"""Pruebas unitarias completas del Context Manager."""

from __future__ import annotations

import time

from core.context_manager import ContextManager


def test_context_crud_operations() -> None:
    ctx = ContextManager()

    # Set and Get
    ctx.set("theme", "dark")
    assert ctx.get("theme") == "dark"
    assert ctx.has("theme") is True

    # Update
    ctx.set("theme", "light")
    assert ctx.get("theme") == "light"

    # Delete
    assert ctx.delete("theme") is True
    assert ctx.get("theme") is None
    assert ctx.has("theme") is False

    # Default fallback
    assert ctx.get("non_existent", "default_val") == "default_val"


def test_context_expiration_ttl() -> None:
    ctx = ContextManager()
    # Asignar un TTL muy corto de 0.1 segundos
    ctx.set("temp_token", "abc123", ttl_seconds=0.1)
    assert ctx.get("temp_token") == "abc123"

    # Esperar a que expire
    time.sleep(0.15)
    assert ctx.get("temp_token") is None
    assert ctx.has("temp_token") is False


def test_windows_desktop_helpers() -> None:
    ctx = ContextManager()

    # Active Window Helper
    ctx.set_active_window("Notepad.exe - Documento", "notepad.exe", pid=4321)
    win = ctx.get("active_window")
    assert win["title"] == "Notepad.exe - Documento"
    assert win["process_name"] == "notepad.exe"
    assert win["pid"] == 4321

    # Current File Helper
    ctx.set_current_file("README.md", mime_type="text/markdown")
    file_info = ctx.get("current_file")
    assert file_info["name"] == "README.md"
    assert file_info["mime_type"] == "text/markdown"

    # Snapshot
    snapshot = ctx.get_snapshot()
    assert "active_window" in snapshot
    assert "current_file" in snapshot


def test_context_clear() -> None:
    ctx = ContextManager()
    ctx.set("k1", "v1")
    ctx.set("k2", "v2")
    ctx.clear()
    assert ctx.get_snapshot() == {}
