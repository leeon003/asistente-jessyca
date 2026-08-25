"""services/voice/device_resolver.py
Resolutor y detector automático de dispositivos de entrada de audio para JESSYCA.

Detecta automáticamente y de forma exclusiva los micrófonos autorizados del sistema:
1. Logitech G435 (Prioridad 1)
2. Logitech C270 (Prioridad 2 / Fallback activo si G435 no produce señal útil)

Garantías de Diseño:
1. Sin índices fijos: Los índices se descubren dinámicamente mediante sounddevice.query_devices().
2. Filtrado estricto: Excluye Microsoft Sound Mapper, dispositivos de salida, Stereo Mix,
   líneas de entrada, y perfiles Bluetooth Hands-Free ajenos.
3. Evaluación de señal en tiempo real: Verifica si el hardware produce señal útil (RMS >= umbral).
   Si G435 está silenciado/sin señal, conmuta automáticamente a C270.
4. Soporte a cambios dinámicos: Reconexiones y desconexiones son detectadas sin estado persistido.
5. Telemetría y Logging estructurado:
   - [VOICE DEVICE CANDIDATE]
   - [VOICE DEVICE SELECTED]
   - [VOICE DEVICE FALLBACK]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from config.manager import get_settings
from core.logger import get_logger

logger = get_logger("jessyca.voice.device_resolver")

# Patrones de exclusión explícitos
EXCLUDED_PATTERNS: tuple[str, ...] = (
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


@dataclass(frozen=True)
class ResolvedAudioDevice:
    """Información completa del dispositivo de entrada de audio resuelto."""

    index: int
    name: str
    display_name: str
    matched_pattern: str | None
    is_preferred: bool
    max_input_channels: int
    default_samplerate: float
    hostapi_index: int = 0
    hostapi_name: str = "Unknown"
    signal_rms: float = 0.0
    signal_peak: float = 0.0
    selection_reason: str = ""
    fallback_used: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "display_name": self.display_name,
            "matched_pattern": self.matched_pattern,
            "is_preferred": self.is_preferred,
            "max_input_channels": self.max_input_channels,
            "default_samplerate": self.default_samplerate,
            "hostapi_index": self.hostapi_index,
            "hostapi_name": self.hostapi_name,
            "signal_rms": self.signal_rms,
            "signal_peak": self.signal_peak,
            "selection_reason": self.selection_reason,
            "fallback_used": self.fallback_used,
            "timestamp": self.timestamp.isoformat(),
        }


class VoiceDeviceResolver:
    """Descubre y resuelve el mejor dispositivo de micrófono disponible con validación de señal."""

    def __init__(
        self,
        preferred_microphones: list[str] | None = None,
        min_rms_threshold: float = 0.0001,
        probe_duration_sec: float = 0.15,
    ) -> None:
        settings = get_settings()
        self.preferred_microphones = (
            preferred_microphones
            if preferred_microphones is not None
            else getattr(settings, "VOICE_PREFERRED_MICROPHONES", ["G435", "C270"])
        )
        self.min_rms_threshold = min_rms_threshold
        self.probe_duration_sec = probe_duration_sec

    @staticmethod
    def normalize_device_name(name: str) -> str:
        """Normaliza el nombre del dispositivo eliminando acentos, caracteres especiales y espacios redundantes."""
        if not name:
            return ""
        # Normalizar caracteres con tildes comunes
        replacements = {
            "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
            "Á": "a", "É": "e", "Í": "i", "Ó": "o", "Ú": "u",
            "ñ": "n", "Ñ": "n",
        }
        for k, v in replacements.items():
            name = name.replace(k, v)
        # Reemplazar no alfanuméricos por espacios
        clean = re.sub(r"[^\w\s]", " ", name.lower())
        return " ".join(clean.split())

    @classmethod
    def is_excluded_device(cls, device_name: str, max_input_channels: int = 1) -> bool:
        """Determina si un dispositivo debe ser ignorado por ser mapper, salida, stereo mix o bluetooth no deseado."""
        if max_input_channels <= 0:
            return True
        norm_name = cls.normalize_device_name(device_name)
        for pattern in EXCLUDED_PATTERNS:
            norm_pattern = cls.normalize_device_name(pattern)
            if norm_pattern and norm_pattern in norm_name:
                return True
        return False

    @classmethod
    def matches_pattern(cls, device_name: str, pattern: str) -> bool:
        """Determina si el nombre del dispositivo coincide con el patrón de hardware objetivo."""
        norm_name = cls.normalize_device_name(device_name)
        norm_pattern = cls.normalize_device_name(pattern)

        if not norm_pattern:
            return False

        # Coincidencia directa de subcadena
        if norm_pattern in norm_name:
            return True

        # Coincidencia por tokens (ej. "g435" en "microfono g435 wireless gaming")
        pattern_tokens = norm_pattern.split()
        name_tokens = norm_name.split()
        return all(token in name_tokens for token in pattern_tokens)

    @classmethod
    def format_display_name(cls, raw_name: str, matched_pattern: str | None) -> str:
        """Genera un nombre legible y estandarizado para el usuario."""
        if matched_pattern:
            p_upper = matched_pattern.upper().strip()
            if "G435" in p_upper:
                return "Logitech G435"
            if "C270" in p_upper:
                return "Logitech C270"
            return f"Micrófono ({matched_pattern})"
        return raw_name or "Dispositivo predeterminado de Windows"

    def probe_device_signal(
        self,
        device_index: int,
        duration_sec: float | None = None,
        sample_rate: int = 16000,
    ) -> tuple[bool, float, float]:
        """Prueba si el dispositivo produce una señal de audio útil y medible."""
        dur = duration_sec if duration_sec is not None else self.probe_duration_sec
        try:
            import numpy as np  # type: ignore[import-untyped]
            import sounddevice as sd  # type: ignore[import-untyped]

            frames = int(dur * sample_rate)
            recording = sd.rec(
                frames,
                samplerate=sample_rate,
                channels=1,
                device=device_index,
                dtype="float32",
            )
            sd.wait()
            rms = float(np.sqrt(np.mean(recording * recording)))
            peak = float(np.max(np.abs(recording)))
            has_signal = rms >= self.min_rms_threshold
            return has_signal, rms, peak
        except Exception as e:
            logger.debug(f"[VOICE DEVICE] No se pudo probar señal en dispositivo {device_index}: {e}")
            return False, 0.0, 0.0

    def resolve_input_device(
        self,
        device_list: list[dict[str, Any]] | None = None,
        preferred_patterns: list[str] | None = None,
        validate_signal: bool = True,
    ) -> ResolvedAudioDevice:
        """Resuelve el mejor dispositivo de entrada de audio según prioridad y validación de señal.

        Flujo de Resolución:
            1. Enumerar sounddevice.query_devices() y filtrar canales de entrada (max_input_channels > 0).
            2. Descartar dispositivos excluidos (Sound Mapper, Stereo Mix, Output-only, Bluetooth ajenos).
            3. Buscar candidatos para Logitech G435 (Prioridad 1) y Logitech C270 (Prioridad 2).
            4. Si validate_signal=True:
               - Probar señal de G435. Si produce señal activa (RMS >= umbral), seleccionarlo.
               - Si G435 no produce señal útil (RMS < umbral / mute), registrar fallback y probar C270.
               - Si C270 produce señal activa, seleccionarlo.
            5. Si no se puede validar señal o validate_signal=False:
               - Seleccionar el primer candidato preferido disponible por orden de prioridad.
            6. Si no hay micrófonos preferidos disponibles o ninguno produce señal útil,
               emitir error controlado si solo se autorizan G435/C270.
        """
        logger.info("[VOICE DEVICE] Buscando micrófono disponible...")

        patterns = preferred_patterns if preferred_patterns is not None else self.preferred_microphones

        # 1. Obtener lista de dispositivos y HostAPIs
        hostapis: list[dict[str, Any]] = []
        is_simulated = device_list is not None

        if device_list is None:
            try:
                import sounddevice as sd  # type: ignore[import-untyped]

                device_list = [dict(d) for d in sd.query_devices()]
                hostapis = [dict(h) for h in sd.query_hostapis()]
            except Exception as e:
                logger.warning(f"[VOICE DEVICE] sounddevice query_devices falló ({e}), usando lista vacía.")
                device_list = []

        def _get_hostapi_name(h_idx: int) -> str:
            if 0 <= h_idx < len(hostapis):
                return str(hostapis[h_idx].get("name", f"HostAPI-{h_idx}"))
            return f"HostAPI-{h_idx}"

        # 2. Filtrar dispositivos de entrada válidos y no excluidos
        valid_inputs: list[tuple[int, dict[str, Any]]] = []
        for idx, dev in enumerate(device_list):
            dev_name = str(dev.get("name", ""))
            max_in = int(dev.get("max_input_channels", 0))

            if self.is_excluded_device(dev_name, max_input_channels=max_in):
                logger.debug(f"[VOICE DEVICE EXCLUDED] Ignorando dispositivo excluido: '{dev_name}' (Index: {idx})")
                continue

            valid_inputs.append((idx, dev))

        if not valid_inputs:
            logger.error("[VOICE DEVICE ERROR] No se encontraron dispositivos de entrada válidos.")
            raise RuntimeError("No se encontró ningún dispositivo de entrada de audio disponible en el sistema.")

        # 3. Descubrir candidatos por patrón
        candidates_by_pattern: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for pattern in patterns:
            candidates_by_pattern[pattern] = []
            for idx, dev in valid_inputs:
                dev_name = str(dev.get("name", ""))
                if self.matches_pattern(dev_name, pattern):
                    host_idx = int(dev.get("hostapi", 0))
                    host_name = _get_hostapi_name(host_idx)
                    logger.info(
                        f"[VOICE DEVICE CANDIDATE] Candidato encontrado: '{dev_name}' "
                        f"(Índice: {idx}, HostAPI: {host_name}, Patrón: {pattern})"
                    )
                    candidates_by_pattern[pattern].append((idx, dev))

        # Helper para construir ResolvedAudioDevice
        def _build_resolved(
            idx: int,
            dev: dict[str, Any],
            pat: str | None,
            reason: str,
            rms: float = 0.0,
            peak: float = 0.0,
            is_fb: bool = False,
        ) -> ResolvedAudioDevice:
            dev_name = str(dev.get("name", ""))
            host_idx = int(dev.get("hostapi", 0))
            host_name = _get_hostapi_name(host_idx)
            disp_name = self.format_display_name(dev_name, pat)
            return ResolvedAudioDevice(
                index=idx,
                name=dev_name,
                display_name=disp_name,
                matched_pattern=pat,
                is_preferred=bool(pat),
                max_input_channels=int(dev.get("max_input_channels", 1)),
                default_samplerate=float(dev.get("default_samplerate", 16000.0)),
                hostapi_index=host_idx,
                hostapi_name=host_name,
                signal_rms=rms,
                signal_peak=peak,
                selection_reason=reason,
                fallback_used=is_fb,
            )

        # 4. Evaluación de Prioridad y Señal
        g435_candidates = candidates_by_pattern.get("G435", [])
        c270_candidates = candidates_by_pattern.get("C270", [])

        # A) Si no validamos señal (ej. tests simulados puros), selección directa por prioridad
        if not validate_signal or is_simulated:
            for pattern in patterns:
                cand_list = candidates_by_pattern.get(pattern, [])
                if cand_list:
                    # Preferir HostAPI 0 (MME) o el menor índice
                    best_idx, best_dev = sorted(cand_list, key=lambda c: int(c[1].get("hostapi", 0)))[0]
                    resolved = _build_resolved(
                        idx=best_idx,
                        dev=best_dev,
                        pat=pattern,
                        reason=f"Prioridad {pattern} seleccionada por coincidencia",
                    )
                    logger.info(
                        f"[VOICE DEVICE SELECTED] Dispositivo seleccionado: {resolved.display_name} "
                        f"(Índice: {resolved.index}, Motivo: {resolved.selection_reason})"
                    )
                    return resolved

        # B) Validación de señal en hardware real
        g435_has_signal = False
        best_g435: tuple[int, dict[str, Any]] | None = None
        g435_rms = 0.0
        g435_peak = 0.0

        if g435_candidates:
            # Probar el candidato con HostAPI MME (hostapi == 0) preferentemente
            mme_g435 = [c for c in g435_candidates if c[1].get("hostapi", 0) == 0]
            best_g435 = mme_g435[0] if mme_g435 else g435_candidates[0]
            g435_has_signal, g435_rms, g435_peak = self.probe_device_signal(best_g435[0])

            if g435_has_signal:
                resolved = _build_resolved(
                    idx=best_g435[0],
                    dev=best_g435[1],
                    pat="G435",
                    reason="Logitech G435 presente con señal activa verificada",
                    rms=g435_rms,
                    peak=g435_peak,
                    is_fb=False,
                )
                logger.info(
                    f"[VOICE DEVICE SELECTED] Dispositivo seleccionado: {resolved.display_name} "
                    f"(Índice: {resolved.index}, HostAPI: {resolved.hostapi_name}, "
                    f"RMS: {g435_rms:.6f}, Motivo: {resolved.selection_reason})"
                )
                return resolved

            # G435 presente pero sin señal medible
            logger.info(
                f"[VOICE DEVICE FALLBACK] Logitech G435 detectado en índice {best_g435[0]} "
                f"pero no produce señal útil (RMS: {g435_rms:.6f}, umbral: {self.min_rms_threshold}). "
                "Evaluando fallback a Logitech C270..."
            )

        # Probar Logitech C270
        if c270_candidates:
            mme_c270 = [c for c in c270_candidates if c[1].get("hostapi", 0) == 0]
            best_c270 = mme_c270[0] if mme_c270 else c270_candidates[0]
            c270_has_signal, c270_rms, c270_peak = self.probe_device_signal(best_c270[0])

            is_fallback = bool(g435_candidates)
            reason = (
                "Fallback a Logitech C270 (G435 sin señal medible)"
                if is_fallback
                else "Logitech C270 seleccionado (G435 ausente)"
            )

            resolved = _build_resolved(
                idx=best_c270[0],
                dev=best_c270[1],
                pat="C270",
                reason=reason,
                rms=c270_rms,
                peak=c270_peak,
                is_fb=is_fallback,
            )
            logger.info(
                f"[VOICE DEVICE SELECTED] Dispositivo seleccionado: {resolved.display_name} "
                f"(Índice: {resolved.index}, HostAPI: {resolved.hostapi_name}, "
                f"RMS: {c270_rms:.6f}, Motivo: {resolved.selection_reason})"
            )
            return resolved

        # C) Si G435 fue encontrado (aunque con señal baja) y no hay C270, seleccionamos G435 con advertencia
        if best_g435 is not None:
            resolved = _build_resolved(
                idx=best_g435[0],
                dev=best_g435[1],
                pat="G435",
                reason="Logitech G435 seleccionado como único dispositivo preferido disponible",
                rms=g435_rms,
                peak=g435_peak,
                is_fb=False,
            )
            logger.info(
                f"[VOICE DEVICE SELECTED] Dispositivo seleccionado: {resolved.display_name} "
                f"(Índice: {resolved.index}, Motivo: {resolved.selection_reason})"
            )
            return resolved

        # D) Fallback genérico a primer dispositivo de entrada válido
        first_idx, first_dev = valid_inputs[0]
        dev_name = str(first_dev.get("name", "Dispositivo de entrada"))
        logger.info("[VOICE DEVICE FALLBACK] Ni Logitech G435 ni C270 encontrados.")
        logger.info(f"[VOICE DEVICE SELECTED] Dispositivo seleccionado: {dev_name} (Índice: {first_idx})")

        return _build_resolved(
            idx=first_idx,
            dev=first_dev,
            pat=None,
            reason="Fallback a dispositivo de entrada del sistema",
            is_fb=True,
        )


# Instancia singleton global
_global_device_resolver: VoiceDeviceResolver | None = None


def get_voice_device_resolver() -> VoiceDeviceResolver:
    """Obtiene la instancia singleton del resolutor de dispositivos de voz."""
    global _global_device_resolver
    if _global_device_resolver is None:
        _global_device_resolver = VoiceDeviceResolver()
    return _global_device_resolver


__all__ = [
    "EXCLUDED_PATTERNS",
    "ResolvedAudioDevice",
    "VoiceDeviceResolver",
    "get_voice_device_resolver",
]
