"""services/voice/audio_device_manager.py
Administrador inteligente y estable de dispositivos de audio para JESSYCA (Fase 71).

Resuelve el problema de índices dinámicos e inestables:
- El índice numérico (`runtime_index`) se considera dinámico y temporal.
- La identidad persistente se basa en características estables (`stable_id`, nombre normalizado, host_api, canales).
- Soporta configuración de preferencias por nombres/patrones.
- Validación activa de señal: diferencia entre dispositivo con señal (VALID), silencioso (SILENT)
  y error de captura/desconectado (ERROR/UNAVAILABLE).
- Detección de pérdida de dispositivo y recuperación automática / fallback transparente.
- Concurrencia segura mediante bloqueos RLock.
"""

from __future__ import annotations

import re
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from config.manager import get_settings
from core.logger import get_logger
from services.voice.device_resolver import ResolvedAudioDevice

logger = get_logger("jessyca.voice.audio_device_manager")

# Patrones explícitos de exclusión de mappers o fuentes no deseadas
EXCLUDED_DEVICE_PATTERNS: tuple[str, ...] = (
    "asignador de sonido microsoft",
    "microsoft sound mapper",
    "controlador primario de captura",
    "controlador primario de sonido",
    "primary sound capture",
    "mezcla estereo",
    "stereo mix",
    "linea de entrada",
    "line in",
    "line input",
    "hands free",
    "bthhfenum",
    "poco f7",
    "m10plus",
)

# Palabras genéricas que NO deben justificar coincidencia de hardware por sí solas
GENERIC_STOP_WORDS: frozenset[str] = frozenset({
    "microphone",
    "microfono",
    "headset",
    "audio",
    "device",
    "dispositivo",
    "usb",
    "wireless",
    "gaming",
    "hd",
    "webcam",
    "camera",
    "in",
    "input",
    "entrada",
    "sonido",
    "sound",
})

# Sinónimos o alias de marcas
BRAND_SYNONYMS: dict[str, str] = {
    "logi": "logitech",
    "logitech": "logi",
}


class SignalValidationStatus(StrEnum):
    """Estado de validación de señal de un dispositivo de entrada."""

    VALID = "VALID"
    SILENT = "SILENT"
    ERROR = "ERROR"
    UNAVAILABLE = "UNAVAILABLE"
    UNTESTED = "UNTESTED"


@dataclass(frozen=True)
class AudioDeviceDescriptor:
    """Descriptor inmutable de un dispositivo de audio con identidad estable."""

    runtime_index: int
    name: str
    normalized_name: str
    host_api: str
    host_api_index: int
    max_input_channels: int
    default_sample_rate: float
    is_input: bool
    stable_id: str
    is_available: bool = True
    signal_status: SignalValidationStatus = SignalValidationStatus.UNTESTED
    signal_rms: float = 0.0
    signal_peak: float = 0.0
    score: float = 0.0
    selection_reason: str = ""
    matched_pattern: str | None = None
    is_preferred: bool = False
    display_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serializa el descriptor a diccionario seguro para telemetría y auditoría."""
        return {
            "runtime_index": self.runtime_index,
            "name": self.name,
            "display_name": self.display_name or self.name,
            "normalized_name": self.normalized_name,
            "host_api": self.host_api,
            "host_api_index": self.host_api_index,
            "max_input_channels": self.max_input_channels,
            "default_sample_rate": self.default_sample_rate,
            "is_input": self.is_input,
            "stable_id": self.stable_id,
            "is_available": self.is_available,
            "signal_status": self.signal_status.value,
            "signal_rms": self.signal_rms,
            "signal_peak": self.signal_peak,
            "score": self.score,
            "selection_reason": self.selection_reason,
            "matched_pattern": self.matched_pattern,
            "is_preferred": self.is_preferred,
        }

    def to_resolved_audio_device(self) -> ResolvedAudioDevice:
        """Convierte al modelo ResolvedAudioDevice para interoperabilidad con subsistemas previos."""
        return ResolvedAudioDevice(
            index=self.runtime_index,
            name=self.name,
            display_name=self.display_name or self.name,
            matched_pattern=self.matched_pattern,
            is_preferred=self.is_preferred,
            max_input_channels=self.max_input_channels,
            default_samplerate=self.default_sample_rate,
            hostapi_index=self.host_api_index,
            hostapi_name=self.host_api,
            signal_rms=self.signal_rms,
            signal_peak=self.signal_peak,
            selection_reason=self.selection_reason,
            fallback_used=not self.is_preferred or "fallback" in self.selection_reason.lower(),
        )


@dataclass
class AudioDeviceSelectionReport:
    """Reporte formal de la evaluación y selección de dispositivos de audio."""

    selected_device: AudioDeviceDescriptor | None
    candidates: list[AudioDeviceDescriptor] = field(default_factory=list)
    discarded: list[tuple[AudioDeviceDescriptor, str]] = field(default_factory=list)
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def format_diagnostic(self) -> str:
        """Formatea un reporte técnico legible de la selección de audio."""
        lines = [
            "=== AUDIO DEVICE SELECTION REPORT ===",
            f"Timestamp: {self.timestamp.isoformat()}",
            f"Selected Device: {self.selected_device.display_name if self.selected_device else 'None'}",
            f"Runtime Index: {self.selected_device.runtime_index if self.selected_device else 'N/A'}",
            f"Selection Reason: {self.reason}",
            "\nEvaluated Candidates:",
        ]
        for c in self.candidates:
            lines.append(
                f"  - [{c.runtime_index}] {c.display_name} (HostAPI: {c.host_api}) "
                f"Score: {c.score:.1f} | Signal: {c.signal_status.value} (RMS: {c.signal_rms:.6f})"
            )
        if self.discarded:
            lines.append("\nDiscarded Devices:")
            for d, why in self.discarded:
                lines.append(f"  - [{d.runtime_index}] {d.name} -> {why}")
        lines.append("=====================================")
        return "\n".join(lines)


class AudioDeviceManager:
    """Administrador centralizado y gobernado de dispositivos de entrada de audio para JESSYCA."""

    def __init__(
        self,
        preferred_devices: list[str] | None = None,
        min_rms_threshold: float = 0.0001,
        probe_duration_sec: float = 0.15,
        default_sample_rate: int = 16000,
        signal_validator_fn: Callable[[int, float, int], tuple[SignalValidationStatus, float, float]] | None = None,
    ) -> None:
        settings = get_settings()
        self.preferred_devices = (
            preferred_devices
            if preferred_devices is not None
            else list(getattr(settings, "VOICE_PREFERRED_MICROPHONES", ["G435", "C270"]))
        )
        self.min_rms_threshold = float(min_rms_threshold)
        self.probe_duration_sec = float(probe_duration_sec)
        self.default_sample_rate = int(default_sample_rate)
        self._signal_validator_fn = signal_validator_fn

        self._lock = threading.RLock()
        self._current_device: AudioDeviceDescriptor | None = None
        self._last_report: AudioDeviceSelectionReport | None = None
        self._cached_devices: list[AudioDeviceDescriptor] = []

    @property
    def current_device(self) -> AudioDeviceDescriptor | None:
        with self._lock:
            return self._current_device

    @property
    def last_report(self) -> AudioDeviceSelectionReport | None:
        with self._lock:
            return self._last_report

    @staticmethod
    def normalize_name(name: str) -> str:
        """Normaliza cadenas eliminando acentos, caracteres no alfanuméricos y espaciado redundante."""
        if not name:
            return ""
        # Normalizar caracteres con tildes comunes
        nfd = unicodedata.normalize("NFD", name.strip().lower())
        unaccented = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
        # Sustituir no alfanuméricos por espacios
        clean = re.sub(r"[^\w\s]", " ", unaccented)
        return " ".join(clean.split())

    @classmethod
    def matches_pattern(cls, device_name: str, pattern: str) -> bool:
        """Determina de forma tolerante y precisa si el dispositivo coincide con el patrón objetivo.

        Reglas:
        - Tolerancia de marcas: 'logi' coincide con 'logitech'.
        - Palabras clave de modelo: 'c270' o 'g435' tienen alta especificidad.
        - Rechazo de falsos positivos: Palabras genéricas solas ('microphone', 'usb') no coinciden.
        """
        norm_dev = cls.normalize_name(device_name)
        norm_pat = cls.normalize_name(pattern)

        if not norm_pat or not norm_dev:
            return False

        pat_tokens = norm_pat.split()
        dev_tokens = norm_dev.split()

        # Filtrar tokens genéricos del patrón
        specific_pat_tokens = [t for t in pat_tokens if t not in GENERIC_STOP_WORDS]

        # Si el patrón solo tenía palabras genéricas (ej: 'Microphone', 'Headset', 'USB'),
        # rechazar explícitamente para evitar falsos positivos
        if not specific_pat_tokens:
            return False

        # 1. Coincidencia directa de subcadena (sólo si no es palabra genérica)
        if norm_pat not in GENERIC_STOP_WORDS and norm_pat in norm_dev:
            return True

        # Identificar tokens de modelo específicos (ej: 'c270', 'g435', que contienen dígitos)
        model_tokens_pat = [t for t in specific_pat_tokens if any(c.isdigit() for c in t)]
        if model_tokens_pat and any(mt in dev_tokens for mt in model_tokens_pat):
            return True
        model_tokens_dev = [t for t in dev_tokens if any(c.isdigit() for c in t) and t not in GENERIC_STOP_WORDS]
        if model_tokens_dev and any(mt in pat_tokens for mt in model_tokens_dev):
            return True

        # Comprobar que todos los tokens específicos del patrón estén en el nombre del dispositivo
        for token in specific_pat_tokens:
            token_matched = False
            if token in dev_tokens:
                token_matched = True
            elif token in BRAND_SYNONYMS and BRAND_SYNONYMS[token] in dev_tokens:
                token_matched = True
            elif any(token in dt for dt in dev_tokens):
                token_matched = True

            if not token_matched:
                return False

        return True

    @classmethod
    def is_excluded(cls, device_name: str, max_input_channels: int = 1) -> bool:
        """Determina si un dispositivo debe ser descartado (mappers, altavoces, stereo mix)."""
        if max_input_channels <= 0:
            return True
        norm_name = cls.normalize_name(device_name)
        for excl in EXCLUDED_DEVICE_PATTERNS:
            norm_excl = cls.normalize_name(excl)
            if norm_excl and norm_excl in norm_name:
                return True
        return False

    @staticmethod
    def format_display_name(raw_name: str, matched_pattern: str | None) -> str:
        """Genera un nombre limpio y legible para el usuario."""
        if matched_pattern:
            p_upper = matched_pattern.upper().strip()
            if "G435" in p_upper:
                return "Logitech G435 Wireless Headset"
            if "C270" in p_upper:
                return "Logitech C270 HD Webcam"
            return f"Micrófono ({matched_pattern})"

        clean = raw_name.replace("Micrófono (", "").replace(")", "").strip()
        return clean or "Micrófono del Sistema"

    @classmethod
    def generate_stable_id(cls, name: str, host_api: str, max_input_channels: int) -> str:
        """Genera una identidad persistente e independiente del runtime index temporal."""
        norm_name = cls.normalize_name(name)
        norm_host = cls.normalize_name(host_api)
        # Extraer tokens distintivos
        tokens = [t for t in norm_name.split() if t not in GENERIC_STOP_WORDS]
        core_name = "_".join(tokens) if tokens else norm_name.replace(" ", "_")
        return f"{norm_host}:{core_name}:ch{max_input_channels}"

    def list_devices(
        self,
        device_list: list[dict[str, Any]] | None = None,
        force_refresh: bool = False,
    ) -> list[AudioDeviceDescriptor]:
        """Enumera y describe todos los dispositivos de audio disponibles."""
        with self._lock:
            if self._cached_devices and not force_refresh and device_list is None:
                return list(self._cached_devices)

            hostapis: list[dict[str, Any]] = []
            if device_list is None:
                try:
                    import sounddevice as sd  # type: ignore[import-untyped]

                    device_list = [dict(d) for d in sd.query_devices()]
                    hostapis = [dict(h) for h in sd.query_hostapis()]
                except Exception as exc:
                    logger.warning(f"[AUDIO_MANAGER] sounddevice query_devices falló ({exc}), lista vacía.")
                    device_list = []

            def _get_hostapi_name(h_idx: int) -> str:
                if 0 <= h_idx < len(hostapis):
                    return str(hostapis[h_idx].get("name", f"HostAPI-{h_idx}"))
                return f"HostAPI-{h_idx}"

            descriptors: list[AudioDeviceDescriptor] = []
            for idx, dev in enumerate(device_list):
                dev_name = str(dev.get("name", ""))
                max_in = int(dev.get("max_input_channels", 0))
                h_idx = int(dev.get("hostapi", 0))
                h_name = _get_hostapi_name(h_idx)
                norm_name = self.normalize_name(dev_name)
                stable_id = self.generate_stable_id(dev_name, h_name, max_in)

                matched_pat = None
                is_pref = False
                for pat in self.preferred_devices:
                    if self.matches_pattern(dev_name, pat):
                        matched_pat = pat
                        is_pref = True
                        break

                disp_name = self.format_display_name(dev_name, matched_pat)

                descriptors.append(
                    AudioDeviceDescriptor(
                        runtime_index=idx,
                        name=dev_name,
                        display_name=disp_name,
                        normalized_name=norm_name,
                        host_api=h_name,
                        host_api_index=h_idx,
                        max_input_channels=max_in,
                        default_sample_rate=float(dev.get("default_samplerate", self.default_sample_rate)),
                        is_input=(max_in > 0),
                        stable_id=stable_id,
                        is_available=True,
                        matched_pattern=matched_pat,
                        is_preferred=is_pref,
                    )
                )

            self._cached_devices = descriptors
            return list(descriptors)

    def list_input_devices(
        self,
        device_list: list[dict[str, Any]] | None = None,
        force_refresh: bool = False,
    ) -> list[AudioDeviceDescriptor]:
        """Filtra y retorna únicamente dispositivos de entrada que no sean mappers o stereo mix."""
        all_devs = self.list_devices(device_list=device_list, force_refresh=force_refresh)
        return [
            d for d in all_devs
            if d.is_input and not self.is_excluded(d.name, d.max_input_channels)
        ]

    def find_device_by_name(
        self,
        name_query: str,
        input_only: bool = True,
        device_list: list[dict[str, Any]] | None = None,
    ) -> AudioDeviceDescriptor | None:
        """Busca un dispositivo por nombre o patrón tolerante."""
        devs = self.list_input_devices(device_list=device_list) if input_only else self.list_devices(device_list=device_list)
        for d in devs:
            if self.matches_pattern(d.name, name_query):
                return d
        return None

    def find_device_by_stable_id(
        self,
        stable_id: str,
        device_list: list[dict[str, Any]] | None = None,
    ) -> AudioDeviceDescriptor | None:
        """Localiza un dispositivo por su identificador persistente."""
        devs = self.list_devices(device_list=device_list)
        for d in devs:
            if d.stable_id == stable_id:
                return d
        return None

    def validate_signal(
        self,
        runtime_index: int,
        duration_sec: float | None = None,
        sample_rate: int | None = None,
    ) -> tuple[SignalValidationStatus, float, float]:
        """Comprueba de forma no destructiva si el dispositivo físico entrega señal medible.

        Diferencia de forma rigurosa:
        - VALID: RMS >= min_rms_threshold (voz o ruido ambiente medible).
        - SILENT: Captura sin errores pero RMS < min_rms_threshold (ambiente quieto o micrófono silenciado).
        - ERROR: Fallo al abrir el stream o captura de buffer.
        """
        dur = duration_sec if duration_sec is not None else self.probe_duration_sec
        sr = sample_rate if sample_rate is not None else self.default_sample_rate

        # Si se inyectó una función personalizada de validación (tests)
        if self._signal_validator_fn is not None:
            return self._signal_validator_fn(runtime_index, dur, sr)

        try:
            import numpy as np
            import sounddevice as sd

            frames = max(256, int(dur * sr))
            recording = sd.rec(
                frames,
                samplerate=sr,
                channels=1,
                device=runtime_index,
                dtype="float32",
            )
            sd.wait()
            rms = float(np.sqrt(np.mean(recording * recording)))
            peak = float(np.max(np.abs(recording)))

            if rms >= self.min_rms_threshold:
                return SignalValidationStatus.VALID, rms, peak
            else:
                return SignalValidationStatus.SILENT, rms, peak
        except Exception as exc:
            logger.debug(f"[AUDIO_MANAGER] Error probando señal en índice {runtime_index}: {exc}")
            return SignalValidationStatus.ERROR, 0.0, 0.0

    def score_device(
        self,
        device: AudioDeviceDescriptor,
        preferred_rank: int | None,
        signal_status: SignalValidationStatus,
    ) -> float:
        """Calcula una puntuación explicable y determinista para ordenar candidatos.

        Factores:
        - Coincidencia con preferencias del usuario (+50 para rango 0, +35 para rango 1, etc.)
        - Disponibilidad de canales de entrada (+10)
        - Estabilidad de HostAPI (MME preferido en Windows +5)
        - Estado de señal (+25 VALID, +15 SILENT, -100 ERROR)
        """
        if not device.is_input or device.max_input_channels <= 0:
            return -999.0
        if self.is_excluded(device.name, device.max_input_channels):
            return -999.0

        score = 10.0  # Base por ser dispositivo de entrada válido

        # Bonificación por preferencia configurada
        if preferred_rank is not None:
            rank_bonus = max(10.0, 50.0 - (preferred_rank * 15.0))
            score += rank_bonus

        # Bonificación por HostAPI estándar (MME / DirectSound)
        if "mme" in device.host_api.lower():
            score += 5.0
        elif "directsound" in device.host_api.lower():
            score += 3.0

        # Evaluación de señal
        if signal_status == SignalValidationStatus.VALID:
            score += 25.0
        elif signal_status == SignalValidationStatus.SILENT:
            score += 15.0
        elif signal_status == SignalValidationStatus.ERROR:
            score -= 100.0
        elif signal_status == SignalValidationStatus.UNAVAILABLE:
            score -= 200.0

        return score

    def select_device(
        self,
        preferred_patterns: list[str] | None = None,
        validate_signal: bool = True,
        device_list: list[dict[str, Any]] | None = None,
    ) -> AudioDeviceDescriptor:
        """Ejecuta el pipeline completo de descubrimiento, scoring y selección de dispositivo.

        Flujo canónico:
        1. Enumerar dispositivos de entrada y filtrar excluidos.
        2. Clasificar según patrones de preferencia.
        3. Evaluar y validar señal de cada candidato.
        4. Seleccionar el candidato de mayor puntuación válida.
        5. Registrar reporte diagnóstico y actualizar current_device.
        """
        with self._lock:
            patterns = (
                preferred_patterns
                if preferred_patterns is not None
                else self.preferred_devices
            )

            all_inputs = self.list_input_devices(device_list=device_list, force_refresh=True)
            if not all_inputs:
                logger.error("[AUDIO_MANAGER] No se encontraron dispositivos de entrada válidos.")
                raise RuntimeError("No se encontró ningún dispositivo de entrada de audio disponible en el sistema.")

            evaluated_candidates: list[AudioDeviceDescriptor] = []
            discarded: list[tuple[AudioDeviceDescriptor, str]] = []

            is_simulated = device_list is not None

            for dev in all_inputs:
                # Determinar rango de preferencia
                pref_rank: int | None = None
                matched_pat: str | None = None
                for idx_pat, pat in enumerate(patterns):
                    if self.matches_pattern(dev.name, pat):
                        pref_rank = idx_pat
                        matched_pat = pat
                        break

                sig_status = SignalValidationStatus.UNTESTED
                rms = 0.0
                peak = 0.0

                should_validate = validate_signal and (not is_simulated or self._signal_validator_fn is not None)
                if should_validate:
                    sig_status, rms, peak = self.validate_signal(dev.runtime_index)
                else:
                    sig_status = SignalValidationStatus.VALID

                if sig_status == SignalValidationStatus.ERROR:
                    discarded.append((dev, f"Fallo al abrir stream de captura ({sig_status.value})"))
                    continue

                sc = self.score_device(dev, pref_rank, sig_status)

                evaluated_candidates.append(
                    AudioDeviceDescriptor(
                        runtime_index=dev.runtime_index,
                        name=dev.name,
                        display_name=dev.display_name,
                        normalized_name=dev.normalized_name,
                        host_api=dev.host_api,
                        host_api_index=dev.host_api_index,
                        max_input_channels=dev.max_input_channels,
                        default_sample_rate=dev.default_sample_rate,
                        is_input=dev.is_input,
                        stable_id=dev.stable_id,
                        is_available=True,
                        signal_status=sig_status,
                        signal_rms=rms,
                        signal_peak=peak,
                        score=sc,
                        selection_reason="",
                        matched_pattern=matched_pat,
                        is_preferred=(pref_rank is not None),
                    )
                )

            if not evaluated_candidates:
                logger.error("[AUDIO_MANAGER] Todos los candidatos fueron descartados por error de señal.")
                raise RuntimeError("Ningún dispositivo de entrada superó las condiciones mínimas de captura.")

            # Ordenar candidatos de mayor a menor puntuación
            evaluated_candidates.sort(key=lambda d: d.score, reverse=True)
            top_candidate = evaluated_candidates[0]

            # Construir motivo descriptivo de selección
            if top_candidate.is_preferred:
                if top_candidate.signal_status == SignalValidationStatus.VALID:
                    reason = f"Dispositivo preferido '{top_candidate.matched_pattern}' verificado con señal activa."
                elif top_candidate.signal_status == SignalValidationStatus.SILENT:
                    reason = f"Dispositivo preferido '{top_candidate.matched_pattern}' accesible (silencioso)."
                else:
                    reason = f"Dispositivo preferido '{top_candidate.matched_pattern}' seleccionado por prioridad."
            else:
                reason = "Fallback a dispositivo de entrada del sistema (ningún preferido disponible con señal)."

            selected_descriptor = AudioDeviceDescriptor(
                runtime_index=top_candidate.runtime_index,
                name=top_candidate.name,
                display_name=top_candidate.display_name,
                normalized_name=top_candidate.normalized_name,
                host_api=top_candidate.host_api,
                host_api_index=top_candidate.host_api_index,
                max_input_channels=top_candidate.max_input_channels,
                default_sample_rate=top_candidate.default_sample_rate,
                is_input=top_candidate.is_input,
                stable_id=top_candidate.stable_id,
                is_available=True,
                signal_status=top_candidate.signal_status,
                signal_rms=top_candidate.signal_rms,
                signal_peak=top_candidate.signal_peak,
                score=top_candidate.score,
                selection_reason=reason,
                matched_pattern=top_candidate.matched_pattern,
                is_preferred=top_candidate.is_preferred,
            )

            self._current_device = selected_descriptor
            self._last_report = AudioDeviceSelectionReport(
                selected_device=selected_descriptor,
                candidates=evaluated_candidates,
                discarded=discarded,
                reason=reason,
            )

            logger.info(
                f"[AUDIO_MANAGER SELECTED] Dispositivo: {selected_descriptor.display_name} "
                f"(RuntimeIndex: {selected_descriptor.runtime_index}, HostAPI: {selected_descriptor.host_api}, "
                f"Score: {selected_descriptor.score:.1f}, Motivo: {reason})"
            )
            return selected_descriptor

    def detect_device_loss(
        self,
        device: AudioDeviceDescriptor | None = None,
        device_list: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Detecta si el dispositivo actual o indicado ha dejado de estar disponible."""
        with self._lock:
            target = device or self._current_device
            if target is None:
                return True

            # Re-enumerar dispositivos
            current_inputs = self.list_input_devices(device_list=device_list, force_refresh=True)
            for d in current_inputs:
                if d.stable_id == target.stable_id or self.matches_pattern(d.name, target.name):
                    return False
            return True

    def handle_device_loss(
        self,
        device_list: list[dict[str, Any]] | None = None,
        validate_signal: bool = True,
    ) -> AudioDeviceDescriptor:
        """Recupera la captura seleccionando un dispositivo alternativo sin reiniciar la sesión."""
        with self._lock:
            lost = self._current_device
            logger.warning(
                f"[AUDIO_MANAGER DEVICE LOSS] Dispositivo '{lost.display_name if lost else 'N/A'}' "
                "desconectado o no disponible. Iniciando re-selección..."
            )
            self._current_device = None
            return self.select_device(
                validate_signal=validate_signal,
                device_list=device_list,
            )


# Singleton
_global_audio_device_manager: AudioDeviceManager | None = None


def get_audio_device_manager() -> AudioDeviceManager:
    """Obtiene la instancia singleton global del AudioDeviceManager."""
    global _global_audio_device_manager
    if _global_audio_device_manager is None:
        _global_audio_device_manager = AudioDeviceManager()
    return _global_audio_device_manager


__all__ = [
    "AudioDeviceDescriptor",
    "AudioDeviceManager",
    "AudioDeviceSelectionReport",
    "EXCLUDED_DEVICE_PATTERNS",
    "SignalValidationStatus",
    "get_audio_device_manager",
]
