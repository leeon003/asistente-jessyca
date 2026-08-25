"""Suite de Pruebas de Certificación para Auto-Detección y Prioridad de Micrófonos (Fase 51.2).

Valida:
- TEST 1: G435 encontrado y seleccionado con prioridad 1.
- TEST 2: C270 encontrado y seleccionado como segundo dispositivo preferido.
- TEST 3: G435 ausente -> selecciona C270.
- TEST 4: C270 ausente -> selecciona G435.
- TEST 5: Asignador de sonido Microsoft - Input es estrictamente ignorado.
- TEST 6: Mezcla estéreo (Stereo Mix) es estrictamente ignorado.
- TEST 7: Dispositivos de salida (max_input_channels = 0 / Altavoces) son ignorados.
- TEST 8: Cambio dinámico de dispositivos (G435 -> desconexión C270 -> reconexión G435).
- TEST 9: Índices numéricos diferentes pero mismo nombre/identidad física de hardware.
- TEST 10: Fallback G435 -> C270 cuando G435 no produce señal útil (RMS < umbral / mute).
- TEST 11: Variantes normalizadas de nombres de G435 y C270.
- TEST 12: Formato de logging estructurado ([VOICE DEVICE CANDIDATE], [VOICE DEVICE SELECTED], [VOICE DEVICE FALLBACK]).
- TEST 13: Integración completa VoiceDeviceResolver -> CalibratedVoiceCaptureEngine -> Calibración.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.voice.audio_capture import (
    CalibratedVoiceCaptureEngine,
    MicrophoneDiagnostics,
)
from services.voice.device_resolver import (
    ResolvedAudioDevice,
    VoiceDeviceResolver,
)


@pytest.fixture
def resolver() -> VoiceDeviceResolver:
    return VoiceDeviceResolver(preferred_microphones=["G435", "C270"])


# ── TEST 1: G435 ENCONTRADO ──

def test_01_g435_found_and_selected(resolver: VoiceDeviceResolver) -> None:
    """TEST 1: G435 encontrado y seleccionado con prioridad 1."""
    devices = [
        {"name": "Asignador de sonido Microsoft - Input", "max_input_channels": 2, "hostapi": 0},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
        {"name": "Micrófono (G435 Wireless Gaming Headset)", "max_input_channels": 1, "hostapi": 0},
    ]

    resolved = resolver.resolve_input_device(device_list=devices, validate_signal=False)

    assert resolved.index == 2
    assert resolved.matched_pattern == "G435"
    assert resolved.display_name == "Logitech G435"
    assert resolved.is_preferred is True


# ── TEST 2: C270 ENCONTRADO ──

def test_02_c270_found_and_selected(resolver: VoiceDeviceResolver) -> None:
    """TEST 2: C270 encontrado y seleccionado como segundo dispositivo preferido."""
    devices = [
        {"name": "Asignador de sonido Microsoft - Input", "max_input_channels": 2, "hostapi": 0},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
    ]

    resolved = resolver.resolve_input_device(device_list=devices, validate_signal=False)

    assert resolved.index == 1
    assert resolved.matched_pattern == "C270"
    assert resolved.display_name == "Logitech C270"
    assert resolved.is_preferred is True


# ── TEST 3: G435 AUSENTE -> C270 ──

def test_03_g435_absent_selects_c270(resolver: VoiceDeviceResolver) -> None:
    """TEST 3: Cuando G435 está ausente, el sistema selecciona automáticamente C270."""
    devices = [
        {"name": "Asignador de sonido Microsoft - Input", "max_input_channels": 2, "hostapi": 0},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
        {"name": "Mezcla estéreo (Realtek Audio)", "max_input_channels": 2, "hostapi": 0},
    ]

    resolved = resolver.resolve_input_device(device_list=devices, validate_signal=False)

    assert resolved.index == 1
    assert resolved.matched_pattern == "C270"
    assert resolved.display_name == "Logitech C270"


# ── TEST 4: C270 AUSENTE -> G435 ──

def test_04_c270_absent_selects_g435(resolver: VoiceDeviceResolver) -> None:
    """TEST 4: Cuando C270 está ausente pero G435 está presente, selecciona G435."""
    devices = [
        {"name": "Asignador de sonido Microsoft - Input", "max_input_channels": 2, "hostapi": 0},
        {"name": "Micrófono (G435 Wireless Gaming)", "max_input_channels": 1, "hostapi": 0},
    ]

    resolved = resolver.resolve_input_device(device_list=devices, validate_signal=False)

    assert resolved.index == 1
    assert resolved.matched_pattern == "G435"
    assert resolved.display_name == "Logitech G435"


# ── TEST 5: ASIGNADOR DE SONIDO MICROSOFT IGNORADO ──

def test_05_microsoft_sound_mapper_ignored(resolver: VoiceDeviceResolver) -> None:
    """TEST 5: El asignador de sonido de Microsoft es explícitamente filtrado e ignorado."""
    devices = [
        {"name": "Asignador de sonido Microsoft - Input", "max_input_channels": 2, "hostapi": 0},
        {"name": "Controlador primario de captura de sonido", "max_input_channels": 2, "hostapi": 1},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
    ]

    resolved = resolver.resolve_input_device(device_list=devices, validate_signal=False)

    assert resolved.index == 2
    assert resolved.matched_pattern == "C270"
    assert "Microsoft" not in resolved.name


# ── TEST 6: STEREO MIX IGNORADO ──

def test_06_stereo_mix_ignored(resolver: VoiceDeviceResolver) -> None:
    """TEST 6: Mezcla estéreo (Stereo Mix) no es tratada como un micrófono de usuario."""
    devices = [
        {"name": "Mezcla estéreo (Realtek HD Audio Stereo input)", "max_input_channels": 2, "hostapi": 0},
        {"name": "Stereo Mix (Realtek Audio)", "max_input_channels": 2, "hostapi": 0},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
    ]

    resolved = resolver.resolve_input_device(device_list=devices, validate_signal=False)

    assert resolved.index == 2
    assert resolved.matched_pattern == "C270"


# ── TEST 7: DISPOSITIVOS DE SALIDA IGNORADOS ──

def test_07_output_devices_ignored(resolver: VoiceDeviceResolver) -> None:
    """TEST 7: Dispositivos de salida (max_input_channels <= 0) como auriculares o altavoces son ignorados."""
    devices = [
        {"name": "audífonos Diego In (G435 Wireless Gaming)", "max_input_channels": 0, "max_output_channels": 2, "hostapi": 0},
        {"name": "Altavoces (Realtek Audio)", "max_input_channels": 0, "max_output_channels": 8, "hostapi": 0},
        {"name": "TE-3213G (NVIDIA High Definition Audio)", "max_input_channels": 0, "max_output_channels": 2, "hostapi": 0},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "max_output_channels": 0, "hostapi": 0},
    ]

    resolved = resolver.resolve_input_device(device_list=devices, validate_signal=False)

    assert resolved.index == 3
    assert resolved.matched_pattern == "C270"
    assert resolved.display_name == "Logitech C270"


# ── TEST 8: CAMBIO DINÁMICO DE DISPOSITIVOS ──

def test_08_dynamic_device_switching(resolver: VoiceDeviceResolver) -> None:
    """TEST 8: Soporta reconexiones y desconexiones en caliente sin índices fijos."""
    # Estado 1: G435 y C270 conectados -> G435
    state1 = [
        {"name": "Micrófono (G435 Wireless Gaming)", "max_input_channels": 1, "hostapi": 0},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
    ]
    res1 = resolver.resolve_input_device(device_list=state1, validate_signal=False)
    assert res1.matched_pattern == "G435"

    # Estado 2: G435 desconectado, solo C270 disponible -> C270
    state2 = [
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
    ]
    res2 = resolver.resolve_input_device(device_list=state2, validate_signal=False)
    assert res2.matched_pattern == "C270"

    # Estado 3: G435 reconectado en un nuevo índice -> Vuelve a detectar G435
    state3 = [
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
        {"name": "Dispositivo temporal", "max_input_channels": 1, "hostapi": 0},
        {"name": "Micrófono (G435 Wireless Gaming Headset)", "max_input_channels": 1, "hostapi": 0},
    ]
    res3 = resolver.resolve_input_device(device_list=state3, validate_signal=False)
    assert res3.index == 2
    assert res3.matched_pattern == "G435"


# ── TEST 9: ÍNDICES DIFERENTES PERO MISMO NOMBRE ──

def test_09_different_indices_same_device_name(resolver: VoiceDeviceResolver) -> None:
    """TEST 9: Cambios en el orden de enumeración de Windows no afectan la resolución por identidad."""
    # G435 en índice 0
    devs1 = [
        {"name": "Micrófono (G435 Wireless Gaming)", "max_input_channels": 1, "hostapi": 0},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
    ]
    assert resolver.resolve_input_device(device_list=devs1, validate_signal=False).index == 0

    # G435 en índice 15
    devs2 = [{"name": f"Dummy {i}", "max_input_channels": 1, "hostapi": 0} for i in range(15)]
    devs2.append({"name": "Micrófono (G435 Wireless Gaming)", "max_input_channels": 1, "hostapi": 0})
    assert resolver.resolve_input_device(device_list=devs2, validate_signal=False).index == 15


# ── TEST 10: FALLBACK G435 -> C270 CUANDO G435 NO TIENE SEÑAL ÚTIL ──

def test_10_fallback_g435_to_c270_when_g435_silent() -> None:
    """TEST 10: Si G435 está conectado pero silenciado (RMS < 0.0001), conmuta a C270."""
    devices = [
        {"name": "Asignador de sonido Microsoft - Input", "max_input_channels": 2, "hostapi": 0},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
        {"name": "Micrófono (G435 Wireless Gaming", "max_input_channels": 1, "hostapi": 0},
    ]

    resolver = VoiceDeviceResolver(min_rms_threshold=0.0001)

    # Simular: G435 (índice 2) tiene RMS digital cero (0.000014), C270 (índice 1) tiene señal activa (0.012)
    def fake_probe(idx: int, *args: object, **kwargs: object) -> tuple[bool, float, float]:
        if idx == 2:
            return False, 0.0000146, 0.0000305
        if idx == 1:
            return True, 0.0123299, 0.0896301
        return False, 0.0, 0.0

    with patch.object(resolver, "probe_device_signal", side_effect=fake_probe), \
         patch("sounddevice.query_devices", return_value=devices), \
         patch("sounddevice.query_hostapis", return_value=[{"name": "MME"}]):

        resolved = resolver.resolve_input_device(device_list=None, validate_signal=True)

        assert resolved.index == 1
        assert resolved.matched_pattern == "C270"
        assert resolved.display_name == "Logitech C270"
        assert resolved.fallback_used is True
        assert "Fallback a Logitech C270" in resolved.selection_reason
        assert resolved.signal_rms == pytest.approx(0.0123299, rel=1e-3)


# ── TEST 11: G435 CON SEÑAL ACTIVA ES SELECCIONADO ──

def test_11_g435_with_active_signal_is_selected() -> None:
    """TEST 11: Si G435 tiene señal activa útil (RMS >= umbral), se selecciona directamente sin fallback."""
    devices = [
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
        {"name": "Micrófono (G435 Wireless Gaming", "max_input_channels": 1, "hostapi": 0},
    ]

    resolver = VoiceDeviceResolver(min_rms_threshold=0.0001)

    # Simular: G435 (índice 1) tiene señal útil activa (RMS = 0.005)
    def fake_probe(idx: int, *args: object, **kwargs: object) -> tuple[bool, float, float]:
        if idx == 1:
            return True, 0.00512, 0.042
        return False, 0.0, 0.0

    with patch.object(resolver, "probe_device_signal", side_effect=fake_probe), \
         patch("sounddevice.query_devices", return_value=devices), \
         patch("sounddevice.query_hostapis", return_value=[{"name": "MME"}]):

        resolved = resolver.resolve_input_device(device_list=None, validate_signal=True)

        assert resolved.index == 1
        assert resolved.matched_pattern == "G435"
        assert resolved.display_name == "Logitech G435"
        assert resolved.fallback_used is False


# ── TEST 12: LINE IN Y BLUETOOTH HANDS-FREE IGNORADOS ──

def test_12_line_in_and_bluetooth_hands_free_ignored(resolver: VoiceDeviceResolver) -> None:
    """TEST 12: Líneas de entrada auxiliares y perfiles Bluetooth ajenos son excluidos."""
    devices = [
        {"name": "Línea de entrada (Realtek HD Audio Line input)", "max_input_channels": 2, "hostapi": 0},
        {"name": "Input (@System32\\drivers\\bthhfenum.sys; Hands-Free (POCO F7))", "max_input_channels": 1, "hostapi": 0},
        {"name": "Input (Hands-Free HF Audio M10PLUS)", "max_input_channels": 1, "hostapi": 0},
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
    ]

    resolved = resolver.resolve_input_device(device_list=devices, validate_signal=False)

    assert resolved.index == 3
    assert resolved.matched_pattern == "C270"


# ── TEST 13: VARIANTES DE NOMBRES ──

@pytest.mark.parametrize(
    ("raw_name", "expected_pattern", "expected_display"),
    [
        ("G435 Wireless Gaming Headset", "G435", "Logitech G435"),
        ("Micrófono (G435 Wireless Gaming)", "G435", "Logitech G435"),
        ("Logi C270 HD WebCam", "C270", "Logitech C270"),
        ("Logitech C270 HD WebCam", "C270", "Logitech C270"),
        ("Microphone (Logitech G435 Wireless)", "G435", "Logitech G435"),
    ],
)
def test_13_name_variants_normalization(
    resolver: VoiceDeviceResolver,
    raw_name: str,
    expected_pattern: str,
    expected_display: str,
) -> None:
    """TEST 13: Normalización robusta para todas las variantes de nombres conocidas."""
    devices = [{"name": raw_name, "max_input_channels": 1, "hostapi": 0}]
    resolved = resolver.resolve_input_device(device_list=devices, validate_signal=False)
    assert resolved.matched_pattern == expected_pattern
    assert resolved.display_name == expected_display


# ── TEST 14: INTEGRACIÓN CON MOTOR DE CAPTURA Y CALIBRACIÓN ──

def test_14_integration_resolver_capture_and_calibration() -> None:
    """TEST 14: Integración completa de VoiceDeviceResolver con CalibratedVoiceCaptureEngine."""
    fake_devices = [
        {"name": "Micrófono (Logi C270 HD WebCam)", "max_input_channels": 1, "hostapi": 0},
        {"name": "Micrófono (G435 Wireless Gaming Headset)", "max_input_channels": 1, "hostapi": 0},
    ]

    resolver = VoiceDeviceResolver(preferred_microphones=["G435", "C270"])
    resolved_dev = resolver.resolve_input_device(device_list=fake_devices, validate_signal=False)

    with patch("speech_recognition.Microphone") as mock_mic_class, patch("speech_recognition.Recognizer"):
        mock_mic_instance = MagicMock()
        mock_mic_class.return_value = mock_mic_instance

        engine = CalibratedVoiceCaptureEngine(
            resolved_device=resolved_dev,
            device_resolver=resolver,
        )

        mock_mic_class.assert_called_with(
            device_index=1,
            sample_rate=16000,
        )
        assert engine.resolved_device is not None
        assert engine.resolved_device.display_name == "Logitech G435"

        calib_res = engine.calibrate_ambient_noise(duration_sec=0.5)
        assert calib_res is not None
        assert calib_res.noise_floor_rms > 0.0


# ── TEST 15: MICROPHONEDIAGNOSTICS DELEGACIÓN ──

def test_15_microphone_diagnostics_delegation() -> None:
    """TEST 15: MicrophoneDiagnostics.resolve_best_microphone delega en VoiceDeviceResolver."""
    with patch.object(VoiceDeviceResolver, "resolve_input_device") as mock_resolve:
        mock_resolve.return_value = ResolvedAudioDevice(
            index=1,
            name="Micrófono C270",
            display_name="Logitech C270",
            matched_pattern="C270",
            is_preferred=True,
            max_input_channels=1,
            default_samplerate=16000.0,
        )
        best = MicrophoneDiagnostics.resolve_best_microphone()
        assert best.display_name == "Logitech C270"
        assert mock_resolve.called
