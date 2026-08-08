"""Pruebas unitarias de utilidades de plataforma y compatibilidad con Windows."""

from __future__ import annotations

from utils.formatting import format_bytes, sanitize_string
from utils.platform import check_windows_compatibility, get_system_metrics, is_windows


def test_is_windows_returns_bool() -> None:
    res = is_windows()
    assert isinstance(res, bool)


def test_check_windows_compatibility() -> None:
    info = check_windows_compatibility()
    assert info.is_windows == is_windows()
    assert isinstance(info.is_compatible, bool)


def test_get_system_metrics() -> None:
    metrics = get_system_metrics()
    assert "cpu_usage_percent" in metrics
    assert "memory_total_bytes" in metrics
    assert "python_version" in metrics


def test_format_bytes() -> None:
    assert format_bytes(500) == "500.00 B"
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(1024 * 1024) == "1.00 MB"


def test_sanitize_string() -> None:
    raw = "  Hola \x00Mundo! \n "
    sanitized = sanitize_string(raw)
    assert "Hola" in sanitized
    assert "Mundo!" in sanitized
    assert "\x00" not in sanitized
