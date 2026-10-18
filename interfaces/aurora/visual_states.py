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
    """Estados visuales del Núcleo Aurora 3D & Fusión Reactiva."""

    IDLE = "IDLE"
    WAKEWORD = "WAKEWORD"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    ROUTING = "ROUTING"
    THINKING = "THINKING"        # Alias compatible con ROUTING / razonamiento
    CLARIFYING = "CLARIFYING"
    CONFIRMING = "CONFIRMING"
    EXECUTING = "EXECUTING"
    SEARCHING = "SEARCHING"      # Subestado visual de búsqueda web / investigación
    VERIFYING = "VERIFYING"
    RESPONDING = "RESPONDING"
    SPEAKING = "SPEAKING"        # Alias compatible con RESPONDING (TTS)
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
        primary_color="#368BFF",      # Azul energético
        secondary_color="#071A35",    # Azul profundo
        accent_color="#70D9FF",       # Cian hielo
        core_pulse_speed=0.45,
        noise_displacement=0.04,      # Mínimo para conservar esfericidad cristalina
        orbital_speed=0.3,
        particle_activity=0.25,
        glow_intensity=0.85,
        description="Rotación lenta y vórtice interior suave con respiración sutil.",
    ),
    AuroraVisualState.WAKEWORD: AuroraStateTheme(
        state=AuroraVisualState.WAKEWORD,
        name_es="Activación (WakeWord)",
        primary_color="#00F0FF",      # Cian eléctrico
        secondary_color="#368BFF",    # Azul energético
        accent_color="#FFFFFF",       # Destello blanco puro
        core_pulse_speed=1.5,
        noise_displacement=0.10,
        orbital_speed=0.9,
        particle_activity=0.85,
        glow_intensity=1.40,
        description="Activación instantánea y expansión radiante de energía.",
    ),
    AuroraVisualState.LISTENING: AuroraStateTheme(
        state=AuroraVisualState.LISTENING,
        name_es="Escuchando",
        primary_color="#70D9FF",      # Cian hielo predominante
        secondary_color="#368BFF",    # Azul energético
        accent_color="#DDEFFF",       # Blanco suave
        core_pulse_speed=0.8,
        noise_displacement=0.08,
        orbital_speed=0.5,
        particle_activity=0.6,
        glow_intensity=1.1,
        description="Ondas tenues en la membrana cristalina y expansión reactiva al habla.",
    ),
    AuroraVisualState.TRANSCRIBING: AuroraStateTheme(
        state=AuroraVisualState.TRANSCRIBING,
        name_es="Transcribiendo (STT)",
        primary_color="#70D9FF",      # Cian hielo
        secondary_color="#9D65FF",    # Violeta cuántico
        accent_color="#EAFBFF",       # Blanco suave
        core_pulse_speed=1.0,
        noise_displacement=0.05,
        orbital_speed=0.7,
        particle_activity=0.65,
        glow_intensity=1.05,
        description="Ondas sutiles de procesamiento fonético y decodificación acústica.",
    ),
    AuroraVisualState.ROUTING: AuroraStateTheme(
        state=AuroraVisualState.ROUTING,
        name_es="Enrutando / Evaluando",
        primary_color="#7668D8",      # Violeta tenue refinado
        secondary_color="#368BFF",    # Azul energético
        accent_color="#70D9FF",       # Cian hielo
        core_pulse_speed=1.1,
        noise_displacement=0.06,
        orbital_speed=1.1,
        particle_activity=0.8,
        glow_intensity=1.1,
        description="Movimiento interno de distribución e inferencia de intención.",
    ),
    AuroraVisualState.THINKING: AuroraStateTheme(
        state=AuroraVisualState.THINKING,
        name_es="Pensando / Razonando",
        primary_color="#7668D8",      # Violeta tenue refinado
        secondary_color="#368BFF",    # Azul energético
        accent_color="#70D9FF",       # Cian hielo
        core_pulse_speed=1.1,
        noise_displacement=0.06,
        orbital_speed=0.9,
        particle_activity=0.8,
        glow_intensity=1.0,
        description="Actividad moderada en el vórtice interior con tenue presencia violeta.",
    ),
    AuroraVisualState.CLARIFYING: AuroraStateTheme(
        state=AuroraVisualState.CLARIFYING,
        name_es="Esperando Aclaración",
        primary_color="#70D9FF",      # Cian hielo
        secondary_color="#071A35",    # Azul profundo
        accent_color="#EAFBFF",       # Blanco suave
        core_pulse_speed=0.7,
        noise_displacement=0.04,
        orbital_speed=0.45,
        particle_activity=0.5,
        glow_intensity=1.0,
        description="Animación de atención, pulso sereno y espera ante ambigüedad.",
    ),
    AuroraVisualState.CONFIRMING: AuroraStateTheme(
        state=AuroraVisualState.CONFIRMING,
        name_es="Confirmación Requerida",
        primary_color="#00F0FF",      # Cian eléctrico
        secondary_color="#4ADE80",    # Verde esmeralda sutil
        accent_color="#FFFFFF",       # Blanco puro
        core_pulse_speed=1.2,
        noise_displacement=0.05,
        orbital_speed=0.6,
        particle_activity=0.7,
        glow_intensity=1.2,
        description="Pulso de confirmación y solicitud de autorización de acción.",
    ),
    AuroraVisualState.EXECUTING: AuroraStateTheme(
        state=AuroraVisualState.EXECUTING,
        name_es="Ejecutando Acción",
        primary_color="#368BFF",      # Azul energético
        secondary_color="#70D9FF",    # Cian hielo
        accent_color="#7668D8",       # Violeta tenue
        core_pulse_speed=1.0,
        noise_displacement=0.05,
        orbital_speed=1.45,
        particle_activity=0.95,
        glow_intensity=1.25,
        description="Rotación orbital fluida y aceleración cinética intensa de nodos luminosos.",
    ),
    AuroraVisualState.SEARCHING: AuroraStateTheme(
        state=AuroraVisualState.SEARCHING,
        name_es="Buscando / Investigando",
        primary_color="#00F0FF",      # Cian eléctrico
        secondary_color="#368BFF",    # Azul energético
        accent_color="#70D9FF",       # Cian hielo
        core_pulse_speed=1.1,
        noise_displacement=0.05,
        orbital_speed=1.15,
        particle_activity=0.85,
        glow_intensity=1.30,
        description="Haz de barrido holográfico de radar explorando fuentes y resultados.",
    ),
    AuroraVisualState.VERIFYING: AuroraStateTheme(
        state=AuroraVisualState.VERIFYING,
        name_es="Verificando",
        primary_color="#70D9FF",      # Cian hielo
        secondary_color="#368BFF",    # Azul energético
        accent_color="#DDEFFF",       # Blanco suave
        core_pulse_speed=0.6,
        noise_displacement=0.03,
        orbital_speed=0.7,
        particle_activity=0.4,
        glow_intensity=0.95,
        description="Haz de luz deslizándose con precisión controlada sobre el anillo exterior.",
    ),
    AuroraVisualState.RESPONDING: AuroraStateTheme(
        state=AuroraVisualState.RESPONDING,
        name_es="Hablando (TTS)",
        primary_color="#368BFF",      # Azul energético
        secondary_color="#70D9FF",    # Cian hielo
        accent_color="#DDEFFF",       # Blanco suave
        core_pulse_speed=0.9,
        noise_displacement=0.07,
        orbital_speed=0.55,
        particle_activity=0.7,
        glow_intensity=1.20,
        description="Animación sincronizada con la voz, ecualizador radial y ondas acústicas.",
    ),
    AuroraVisualState.SPEAKING: AuroraStateTheme(
        state=AuroraVisualState.SPEAKING,
        name_es="Hablando (TTS)",
        primary_color="#368BFF",      # Azul energético
        secondary_color="#70D9FF",    # Cian hielo
        accent_color="#DDEFFF",       # Blanco suave
        core_pulse_speed=0.9,
        noise_displacement=0.07,
        orbital_speed=0.55,
        particle_activity=0.7,
        glow_intensity=1.15,
        description="Pulsaciones armónicas y ondulaciones suaves en azul-cian.",
    ),
    AuroraVisualState.ERROR: AuroraStateTheme(
        state=AuroraVisualState.ERROR,
        name_es="Alerta / Error",
        primary_color="#E6A23C",      # Ámbar discreto elegante (no rojo alarmista)
        secondary_color="#071A35",    # Azul profundo
        accent_color="#FFA726",       # Ámbar suave
        core_pulse_speed=0.5,
        noise_displacement=0.03,
        orbital_speed=0.2,
        particle_activity=0.3,
        glow_intensity=0.7,
        description="Atenuación del brillo con indicador ámbar discreto y profesional.",
    ),
}


class SessionStateToAuroraAdapter:
    """Adaptador que mapea los estados canónicos de JESSYCA a estados visuales de Aurora."""

    # Mapeo canónico legado (7 estados para compatibilidad con suites base)
    _LEGACY_MAPPING: dict[SessionState, AuroraVisualState] = {
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

    # Mapeo granular 1:1 para experiencia reactiva completa
    _GRANULAR_MAPPING: dict[SessionState, AuroraVisualState] = {
        SessionState.IDLE: AuroraVisualState.IDLE,
        SessionState.WAKEWORD: AuroraVisualState.WAKEWORD,
        SessionState.LISTENING: AuroraVisualState.LISTENING,
        SessionState.TRANSCRIBING: AuroraVisualState.TRANSCRIBING,
        SessionState.ROUTING: AuroraVisualState.ROUTING,
        SessionState.CONFIRMING: AuroraVisualState.CONFIRMING,
        SessionState.CLARIFYING: AuroraVisualState.CLARIFYING,
        SessionState.EXECUTING: AuroraVisualState.EXECUTING,
        SessionState.VERIFYING: AuroraVisualState.VERIFYING,
        SessionState.RESPONDING: AuroraVisualState.RESPONDING,
    }

    @classmethod
    def to_visual_state(cls, session_state: SessionState | str, granular: bool = False) -> AuroraVisualState:
        """Convierte de forma segura un SessionState a AuroraVisualState."""
        if isinstance(session_state, str):
            try:
                session_state = SessionState(session_state)
            except ValueError:
                # Intentar reconocer directamente como estado visual
                try:
                    return AuroraVisualState(session_state.upper())
                except ValueError:
                    return AuroraVisualState.IDLE

        mapping = cls._GRANULAR_MAPPING if granular else cls._LEGACY_MAPPING
        return mapping.get(session_state, AuroraVisualState.IDLE)

    @classmethod
    def to_granular_visual_state(cls, session_state: SessionState | str) -> AuroraVisualState:
        """Mapeo granular directo 1:1 a los estados visuales del orbe."""
        return cls.to_visual_state(session_state, granular=True)

    @classmethod
    def get_theme(cls, visual_state: AuroraVisualState) -> AuroraStateTheme:
        """Obtiene la configuración estética para un estado visual."""
        return AURORA_THEMES.get(visual_state, AURORA_THEMES[AuroraVisualState.IDLE])
