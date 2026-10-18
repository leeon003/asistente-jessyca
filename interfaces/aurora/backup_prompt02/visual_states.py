"""Definición de estados visuales y adaptadores para JESSYCA ORB — Núcleo Aurora.

IMPORTANTE: Los estados canónicos de SessionState (core/state/states.py) NO se modifican.
Este módulo proporciona una capa de abstracción y mapeo puramente visual.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.state.states import SessionState


class AuroraVisualState(StrEnum):
    """Estados visuales del prototipo Núcleo Aurora 3D."""

    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    ERROR = "ERROR"


@dataclass(frozen=True)
class AuroraStateTheme:
    """Configuración estética y cromática asociada a un estado visual."""

    state: AuroraVisualState
    name_es: str
    primary_color: str      # Color hexadecimal primario
    secondary_color: str    # Color hexadecimal complementario
    accent_color: str       # Color de destello / luz
    core_pulse_speed: float # Velocidad de respiración sinusoidal
    noise_displacement: float # Intensidad de deformación orgánica
    orbital_speed: float    # Velocidad de rotación de anillos 3D
    particle_activity: float # Agitación y velocidad de enjambre de partículas
    glow_intensity: float   # Brillo de halo y bloom
    description: str


AURORA_THEMES: dict[AuroraVisualState, AuroraStateTheme] = {
    AuroraVisualState.IDLE: AuroraStateTheme(
        state=AuroraVisualState.IDLE,
        name_es="En Reposo",
        primary_color="#4CC9F0",      # Azul eléctrico
        secondary_color="#7B2CFB",    # Violeta neón
        accent_color="#2EE6D6",       # Turquesa
        core_pulse_speed=0.6,
        noise_displacement=0.15,
        orbital_speed=0.4,
        particle_activity=0.3,
        glow_intensity=0.8,
        description="Respiración lenta y elegante; partículas en órbita suave.",
    ),
    AuroraVisualState.LISTENING: AuroraStateTheme(
        state=AuroraVisualState.LISTENING,
        name_es="Escuchando",
        primary_color="#2EE6D6",      # Turquesa brillante
        secondary_color="#4CC9F0",    # Azul eléctrico
        accent_color="#EAFBFF",       # Blanco hielo
        core_pulse_speed=1.5,
        noise_displacement=0.35,
        orbital_speed=1.0,
        particle_activity=1.2,
        glow_intensity=1.4,
        description="Recepción activa; ondas reactivas y partículas atraídas al núcleo.",
    ),
    AuroraVisualState.THINKING: AuroraStateTheme(
        state=AuroraVisualState.THINKING,
        name_es="Pensando / Razonando",
        primary_color="#7B2CFB",      # Violeta cuántico
        secondary_color="#D500F9",    # Magenta intenso
        accent_color="#4CC9F0",       # Destellos cyan
        core_pulse_speed=2.2,
        noise_displacement=0.45,
        orbital_speed=1.8,
        particle_activity=1.6,
        glow_intensity=1.3,
        description="Procesamiento cognitivo interno; giros orbitales acelerados y refracción.",
    ),
    AuroraVisualState.SPEAKING: AuroraStateTheme(
        state=AuroraVisualState.SPEAKING,
        name_es="Hablando (TTS)",
        primary_color="#4CC9F0",      # Azul eléctrico
        secondary_color="#2EE6D6",    # Turquesa
        accent_color="#EAFBFF",       # Blanco hielo
        core_pulse_speed=1.8,
        noise_displacement=0.40,
        orbital_speed=0.8,
        particle_activity=1.4,
        glow_intensity=1.5,
        description="Modulación armónica sincronizada con la voz neuronal.",
    ),
    AuroraVisualState.EXECUTING: AuroraStateTheme(
        state=AuroraVisualState.EXECUTING,
        name_es="Ejecutando Acción",
        primary_color="#FF9100",      # Ámbar energético
        secondary_color="#7B2CFB",    # Violeta
        accent_color="#00E5FF",       # Cyan
        core_pulse_speed=2.5,
        noise_displacement=0.50,
        orbital_speed=2.2,
        particle_activity=2.0,
        glow_intensity=1.6,
        description="Operación de herramientas de escritorio; alta energía orbital.",
    ),
    AuroraVisualState.VERIFYING: AuroraStateTheme(
        state=AuroraVisualState.VERIFYING,
        name_es="Verificando",
        primary_color="#2979FF",      # Azul cobalto de precisión
        secondary_color="#00E5FF",    # Cyan eléctrico
        accent_color="#FFFFFF",       # Blanco puro
        core_pulse_speed=1.2,
        noise_displacement=0.20,
        orbital_speed=1.2,
        particle_activity=0.8,
        glow_intensity=1.2,
        description="Escaneo radial y alineación concéntrica de verificación.",
    ),
    AuroraVisualState.ERROR: AuroraStateTheme(
        state=AuroraVisualState.ERROR,
        name_es="Alerta / Error",
        primary_color="#FF1744",      # Carmesí neón
        secondary_color="#D50000",    # Rojo profundo
        accent_color="#FF8A80",       # Destello coral
        core_pulse_speed=3.0,
        noise_displacement=0.60,
        orbital_speed=0.5,
        particle_activity=2.5,
        glow_intensity=1.8,
        description="Dispersión caótica de partículas y pulso de advertencia.",
    ),
}


class SessionStateToAuroraAdapter:
    """Adaptador que mapea los estados canónicos de JESSYCA a estados visuales de Aurora."""

    _MAPPING: dict[SessionState, AuroraVisualState] = {
        SessionState.IDLE: AuroraVisualState.IDLE,
        SessionState.WAKEWORD: AuroraVisualState.LISTENING,
        SessionState.LISTENING: AuroraVisualState.LISTENING,
        SessionState.TRANSCRIBING: AuroraVisualState.THINKING,
        SessionState.ROUTING: AuroraVisualState.THINKING,
        SessionState.CONFIRMING: AuroraVisualState.THINKING,
        SessionState.CLARIFYING: AuroraVisualState.LISTENING,
        SessionState.EXECUTING: AuroraVisualState.EXECUTING,
        SessionState.VERIFYING: AuroraVisualState.VERIFYING,
        SessionState.RESPONDING: AuroraVisualState.SPEAKING,
    }

    @classmethod
    def to_visual_state(cls, session_state: SessionState | str) -> AuroraVisualState:
        """Convierte de forma segura un SessionState a AuroraVisualState."""
        if isinstance(session_state, str):
            try:
                session_state = SessionState(session_state)
            except ValueError:
                return AuroraVisualState.IDLE
        return cls._MAPPING.get(session_state, AuroraVisualState.IDLE)

    @classmethod
    def get_theme(cls, visual_state: AuroraVisualState) -> AuroraStateTheme:
        """Obtiene la configuración estética para un estado visual."""
        return AURORA_THEMES.get(visual_state, AURORA_THEMES[AuroraVisualState.IDLE])
