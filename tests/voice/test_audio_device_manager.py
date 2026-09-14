"""Suite de pruebas unitarias para AudioDeviceManager (Fase 71).

Cubre los 12 casos obligatorios:
- TEST 1: Selección según preferencia configurada cuando ambos dispositivos están disponibles.
- TEST 2: Fallback automático cuando el preferido no está disponible.
- TEST 3: Persistencia de identidad y resolución cuando el runtime_index numérico cambia.
- TEST 4: Asignador de sonido / Mapper no se asume como preferido y se descarta.
- TEST 5: Dispositivos sin canales de entrada (max_input_channels == 0) son descartados.
- TEST 6: Dispositivo con error de captura es descartado con fallback al funcional.
- TEST 7: Dispositivo disponible pero silencioso (SILENT) no se marca como hardware roto.
- TEST 8: Detección de pérdida de dispositivo y recuperación automática / reselección.
- TEST 9: Error controlado cuando ningún dispositivo de entrada válido existe.
- TEST 10: Normalización de nombres y comparación tolerante (Logi C270, G435).
- TEST 11: No persistir runtime index como identidad (stable_id no depende de runtime_index).
- TEST 12: Concurrencia segura: dos llamadas simultáneas a selección no corrompen el estado.
"""

from __future__ import annotations

import concurrent.futures

import pytest

from services.voice.audio_device_manager import (
    AudioDeviceManager,
    SignalValidationStatus,
)


def test_01_selection_by_configured_preference() -> None:
    """TEST 1: Dos dispositivos disponibles (C270, G435) -> selección según preferencia configurada."""
    devices = [
        {"name": "Asignador de sonido Microsoft - Input", "max_input_channels": 2, "hostapi": 0},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
        {"name": "Micrófono (G435 Wireless Gaming Headset)", "max_input_channels": 1, "hostapi": 0},
    ]

    # Preferencia 1: C270 primero
    mgr1 = AudioDeviceManager(preferred_devices=["C270", "G435"])
    sel1 = mgr1.select_device(device_list=devices, validate_signal=False)
    assert sel1.matched_pattern == "C270"
    assert "C270" in sel1.display_name

    # Preferencia 2: G435 primero
    mgr2 = AudioDeviceManager(preferred_devices=["G435", "C270"])
    sel2 = mgr2.select_device(device_list=devices, validate_signal=False)
    assert sel2.matched_pattern == "G435"
    assert "G435" in sel2.display_name


def test_02_fallback_when_preferred_not_available() -> None:
    """TEST 2: C270 no disponible, G435 disponible -> fallback a G435."""
    devices = [
        {"name": "Asignador de sonido Microsoft - Input", "max_input_channels": 2, "hostapi": 0},
        {"name": "Micrófono (G435 Wireless Gaming Headset)", "max_input_channels": 1, "hostapi": 0},
    ]

    mgr = AudioDeviceManager(preferred_devices=["C270", "G435"])
    sel = mgr.select_device(device_list=devices, validate_signal=False)

    assert sel.matched_pattern == "G435"
    assert "G435" in sel.display_name
    assert sel.runtime_index == 1


def test_03_index_changes_identity_preserved() -> None:
    """TEST 3: El índice de C270 cambia -> se sigue identificando por sus características estables."""
    # Estado inicial: C270 está en el índice 1
    devices_initial = [
        {"name": "Asignador de sonido Microsoft - Input", "max_input_channels": 2, "hostapi": 0},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
    ]
    mgr = AudioDeviceManager(preferred_devices=["C270"])
    dev1 = mgr.select_device(device_list=devices_initial, validate_signal=False)
    assert dev1.runtime_index == 1
    stable_id_1 = dev1.stable_id

    # Nuevo estado tras reconexión: se insertaron otros dispositivos y C270 ahora es índice 4
    devices_reordered = [
        {"name": "Asignador de sonido Microsoft - Input", "max_input_channels": 2, "hostapi": 0},
        {"name": "Altavoces (Realtek Audio)", "max_input_channels": 0, "hostapi": 0},
        {"name": "Output Auxiliar", "max_input_channels": 0, "hostapi": 0},
        {"name": "Micrófono Genérico", "max_input_channels": 1, "hostapi": 0},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
    ]

    dev2 = mgr.select_device(device_list=devices_reordered, validate_signal=False)
    assert dev2.runtime_index == 4
    # La identidad estable es idéntica a pesar de que el índice temporal cambió
    assert dev2.stable_id == stable_id_1
    assert dev2.matched_pattern == "C270"


def test_04_mapper_not_assumed_preferred() -> None:
    """TEST 4: Device mapper (Sound Mapper) aparece como default -> no asumir como preferido y descartarlo."""
    devices = [
        {"name": "Microsoft Sound Mapper - Input", "max_input_channels": 2, "hostapi": 0},
        {"name": "Controlador primario de captura de sonido", "max_input_channels": 2, "hostapi": 0},
        {"name": "Micrófono (G435 Wireless Gaming Headset)", "max_input_channels": 1, "hostapi": 0},
    ]

    mgr = AudioDeviceManager(preferred_devices=["G435"])
    sel = mgr.select_device(device_list=devices, validate_signal=False)

    assert "sound mapper" not in sel.name.lower()
    assert "controlador primario" not in sel.name.lower()
    assert sel.matched_pattern == "G435"


def test_05_device_without_input_channels_discarded() -> None:
    """TEST 5: Dispositivos sin canales de entrada (max_input_channels <= 0) son descartados."""
    devices = [
        {"name": "Altavoces (Realtek Audio)", "max_input_channels": 0, "hostapi": 0},
        {"name": "TE-3213G (NVIDIA Audio)", "max_input_channels": 0, "hostapi": 0},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
    ]

    mgr = AudioDeviceManager(preferred_devices=["C270"])
    inputs = mgr.list_input_devices(device_list=devices)

    assert len(inputs) == 1
    assert inputs[0].name == "Micrófono (Logi C270 HD WebCam)"
    assert inputs[0].max_input_channels == 1


def test_06_capture_error_device_discarded() -> None:
    """TEST 6: Dispositivo con error de captura es descartado con fallback al dispositivo funcional."""
    devices = [
        {"name": "Micrófono (G435 Wireless Gaming Headset)", "max_input_channels": 1, "hostapi": 0},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
    ]

    def mock_validator(idx: int, dur: float, sr: int) -> tuple[SignalValidationStatus, float, float]:
        if idx == 0:
            # G435 simula error de captura de hardware (ej. PortAudio stream crash)
            return SignalValidationStatus.ERROR, 0.0, 0.0
        # C270 funciona correctamente
        return SignalValidationStatus.VALID, 0.005, 0.01

    mgr = AudioDeviceManager(
        preferred_devices=["G435", "C270"],
        signal_validator_fn=mock_validator,
    )
    sel = mgr.select_device(device_list=devices, validate_signal=True)

    # G435 fue descartado por error, fallback automático a C270
    assert sel.matched_pattern == "C270"
    assert sel.signal_status == SignalValidationStatus.VALID
    assert sel.runtime_index == 1


def test_07_silent_device_not_marked_broken() -> None:
    """TEST 7: Dispositivo disponible pero silencioso -> no marcar como hardware roto (status SILENT)."""
    devices = [
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
    ]

    def silent_validator(idx: int, dur: float, sr: int) -> tuple[SignalValidationStatus, float, float]:
        # Funciona sin error, pero en una habitación totalmente en silencio
        return SignalValidationStatus.SILENT, 0.00002, 0.00005

    mgr = AudioDeviceManager(
        preferred_devices=["C270"],
        signal_validator_fn=silent_validator,
    )
    sel = mgr.select_device(device_list=devices, validate_signal=True)

    # El dispositivo no está roto; es accesible y se selecciona
    assert sel.is_available is True
    assert sel.signal_status == SignalValidationStatus.SILENT
    assert "accesible" in sel.selection_reason.lower() or "silencioso" in sel.selection_reason.lower()


def test_08_device_disappearance_and_recovery() -> None:
    """TEST 8: Dispositivo actual desaparece -> manager detecta pérdida y recupera seleccionando otro."""
    devices_initial = [
        {"name": "Micrófono (G435 Wireless Gaming Headset)", "max_input_channels": 1, "hostapi": 0},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
    ]

    mgr = AudioDeviceManager(preferred_devices=["G435", "C270"])
    initial_sel = mgr.select_device(device_list=devices_initial, validate_signal=False)
    assert initial_sel.matched_pattern == "G435"

    # El usuario desenchufa el headset G435
    devices_after_unplug = [
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
    ]

    # Comprobar detección de pérdida
    is_lost = mgr.detect_device_loss(initial_sel, device_list=devices_after_unplug)
    assert is_lost is True

    # Recuperación transparente
    recovered = mgr.handle_device_loss(device_list=devices_after_unplug, validate_signal=False)
    assert recovered.matched_pattern == "C270"
    assert recovered.runtime_index == 0
    assert mgr.current_device is not None
    assert mgr.current_device.matched_pattern == "C270"


def test_09_no_valid_devices_raises_controlled_error() -> None:
    """TEST 9: Ningún dispositivo de entrada válido -> error controlado sin crash."""
    devices = [
        {"name": "Altavoces (Realtek)", "max_input_channels": 0, "hostapi": 0},
        {"name": "Mezcla estéreo", "max_input_channels": 2, "hostapi": 0},
    ]

    mgr = AudioDeviceManager(preferred_devices=["G435", "C270"])
    with pytest.raises(RuntimeError) as exc_info:
        mgr.select_device(device_list=devices, validate_signal=False)

    assert "no se encontró ningún dispositivo" in str(exc_info.value).lower()


def test_10_tolerant_name_normalization() -> None:
    """TEST 10: Normalización tolerante de nombres para variaciones de hardware."""
    mgr = AudioDeviceManager()

    # Variaciones de Logitech C270
    assert mgr.matches_pattern("Micrófono (Logi C270 HD WebCam)", "Logitech C270") is True
    assert mgr.matches_pattern("Microfono logi c270", "C270") is True
    assert mgr.matches_pattern("C270 HD Webcam", "logi c270") is True
    assert mgr.matches_pattern("C270 HD Webcam", "Logitech C270") is True

    # Variaciones de Logitech G435
    assert mgr.matches_pattern("Micrófono (G435 Wireless Gaming Headset)", "Logitech G435") is True
    assert mgr.matches_pattern("G435 Wireless Gaming", "G435") is True
    assert mgr.matches_pattern("Headset G435", "Logitech G435") is True

    # Palabras genéricas solas NO deben hacer match arbitrario
    assert mgr.matches_pattern("Micrófono USB Genérico", "Microphone") is False
    assert mgr.matches_pattern("Audio Headset Realtek", "Headset") is False


def test_11_runtime_index_not_persisted_as_identity() -> None:
    """TEST 11: El runtime_index es temporal; stable_id depende de características estables."""
    mgr = AudioDeviceManager()

    id1 = mgr.generate_stable_id(name="Micrófono (Logi C270 HD WebCam)", host_api="MME", max_input_channels=1)
    id2 = mgr.generate_stable_id(name="Micrófono (Logi C270 HD WebCam)", host_api="MME", max_input_channels=1)

    # El stable_id es determinista e invariante ante índices numéricos
    assert id1 == id2
    assert "mme" in id1
    assert "c270" in id1

    # Dispositivo con diferente hostapi o canales produce diferente stable_id
    id3 = mgr.generate_stable_id(name="Micrófono (Logi C270 HD WebCam)", host_api="Windows WASAPI", max_input_channels=2)
    assert id1 != id3


def test_12_thread_safe_concurrency() -> None:
    """TEST 12: Dos o más llamadas concurrentes a selección no corrompen el estado."""
    devices = [
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
        {"name": "Micrófono (G435 Wireless Gaming Headset)", "max_input_channels": 1, "hostapi": 0},
    ]

    mgr = AudioDeviceManager(preferred_devices=["G435", "C270"])
    results: list[str] = []

    def worker(pattern: str) -> str:
        dev = mgr.select_device(preferred_patterns=[pattern], device_list=devices, validate_signal=False)
        return dev.matched_pattern or ""

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futs = [
            executor.submit(worker, "G435"),
            executor.submit(worker, "C270"),
            executor.submit(worker, "G435"),
            executor.submit(worker, "C270"),
        ]
        for f in concurrent.futures.as_completed(futs):
            results.append(f.result())

    # Todas las ejecuciones concluyeron de forma válida sin excepciones de estado
    assert len(results) == 4
    assert set(results).issubset({"G435", "C270"})
    assert mgr.current_device is not None
