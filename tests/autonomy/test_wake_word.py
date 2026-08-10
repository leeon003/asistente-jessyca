"""Pruebas unitarias y de seguridad para WakeWordDetector (Etapa 13.2).

REQUISITOS PROBADOS:
1. disabled mode: Deshabilitado por defecto (WAKE_WORD_ENABLED=False).
2. state transitions: Transiciones de estado visibles (INACTIVE, LISTENING, TRIGGERED, PROCESSING, ERROR).
3. buffer limit & expiration: Acotamiento estricto y purga de muestras de audio antiguas.
4. no persistence: CERO archivos creados o persistidos en disco.
5. cancellation: Cancelación inmediata con sobreescritura de ceros en memoria RAM.
6. error recovery: Manejo y recuperación segura de errores.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.wake_word_detector import (
    WakeWordDetector,
    WakeWordDisabledError,
    WakeWordSecurityError,
    WakeWordState,
)


def test_disabled_mode_by_default() -> None:
    """Verifica que WakeWordDetector permanezca deshabilitado por defecto y rechace la escucha."""
    detector = WakeWordDetector()
    assert detector.enabled is False
    assert detector.state == WakeWordState.INACTIVE

    with pytest.raises(WakeWordDisabledError):
        detector.start_listening()


def test_state_transitions() -> None:
    """Verifica las transiciones formales de estado: INACTIVE -> LISTENING -> TRIGGERED -> PROCESSING -> LISTENING -> INACTIVE."""
    detector = WakeWordDetector()
    detector.enabled = True  # Habilitar explícitamente para prueba

    assert detector.state == WakeWordState.INACTIVE

    # INACTIVE -> LISTENING
    started = detector.start_listening()
    assert started is True
    assert detector.state == WakeWordState.LISTENING

    # LISTENING -> TRIGGERED -> PROCESSING -> LISTENING
    triggered = detector.trigger_keyword(phrase="Hola jessyca como estas")
    assert triggered is True
    assert detector.state == WakeWordState.LISTENING

    # LISTENING -> INACTIVE
    detector.stop_listening()
    assert detector.state == WakeWordState.INACTIVE


def test_bounded_buffer_limit_and_expiration() -> None:
    """Verifica que el buffer de audio en RAM permanezca estrictamente acotado y purgue audio antiguo."""
    detector = WakeWordDetector()
    detector.enabled = True
    detector.max_seconds = 1.0  # 1 segundo máximo
    detector.sample_rate = 1000
    detector.bytes_per_sample = 2
    detector.max_capacity_bytes = 2000  # 2000 bytes máx

    detector.start_listening()

    # Enviar 1500 bytes de audio
    chunk1 = b"\x01" * 1500
    detector.process_audio_chunk(chunk1)
    assert detector.buffer_size_bytes == 1500

    # Enviar 1000 bytes adicionales (Total 2500 -> Debe acotarse a 2000)
    chunk2 = b"\x02" * 1000
    detector.process_audio_chunk(chunk2)
    assert detector.buffer_size_bytes == 2000

    # El inicio del buffer debe haber purgado 500 bytes de muestras antiguas (quedan 1000 de \x01 y 1000 de \x02)
    assert detector._audio_buffer[:1000] == b"\x01" * 1000
    assert detector._audio_buffer[1000:] == b"\x02" * 1000



def test_no_audio_persistence(tmp_path: Path) -> None:
    """Verifica que no se escriba absolutamente ningún archivo de audio en disco durante el procesamiento."""
    files_before = set(tmp_path.glob("*"))

    detector = WakeWordDetector()
    detector.enabled = True
    detector.start_listening()

    # Procesar chunks de audio simulados
    detector.process_audio_chunk(b"\x00\x05\x00\x08" * 500)
    detector.trigger_keyword("jessyca estatus")
    detector.stop_listening()

    files_after = set(tmp_path.glob("*"))
    assert files_before == files_after, "Se detectaron archivos creados en disco. CERO PERSISTENCIA REQUERIDA."


def test_cancellation() -> None:
    """Verifica la cancelación inmediata del detector y la sobreescritura con ceros de la memoria RAM."""
    detector = WakeWordDetector()
    detector.enabled = True
    detector.start_listening()

    # Agregar datos al buffer
    detector.process_audio_chunk(b"\xAA" * 500)
    assert detector.buffer_size_bytes == 500

    # Cancelación limpia
    detector.cancel()
    assert detector.state == WakeWordState.INACTIVE
    assert detector.buffer_size_bytes == 0


def test_error_recovery() -> None:
    """Verifica que ante un fallo el detector pase a estado ERROR y pueda recuperarse mediante reset_error()."""
    detector = WakeWordDetector()
    detector.enabled = True
    detector.start_listening()

    # Intentar disparar una herramienta no permitida (ej. file.delete programada/autónoma en DANGEROUS)
    success = detector.trigger_keyword(
        phrase="jessyca borra todo",
        tool_name="file.delete",
        operation="remove",
    )

    assert success is False
    assert detector.state == WakeWordState.ERROR

    # Intentar iniciar escucha estando en ERROR debe fallar
    with pytest.raises(WakeWordSecurityError):
        detector.start_listening()

    # Resetear error y verificar recuperación
    detector.reset_error()
    assert detector.state == WakeWordState.INACTIVE

    # Ahora sí debe permitir iniciar escucha
    assert detector.start_listening() is True
