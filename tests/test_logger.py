"""Pruebas unitarias del sistema centralizado de logging."""

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger, setup_logger


def test_logger_setup(temp_dir: Path) -> None:
    log_file = temp_dir / "unit_test.log"
    setup_logger(log_level="DEBUG", log_file=log_file, enable_console=False)

    logger = get_logger("jessyca.test")
    logger.info("Mensaje de prueba unitaria")

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Mensaje de prueba unitaria" in content
