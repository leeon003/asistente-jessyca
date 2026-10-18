/**
 * Controlador de Estados Visuales y Cliente WebSocket
 * JESSYCA ORB 4.0 — NÚCLEO AURORA
 */

class AuroraVisualController {
  constructor(auroraCore) {
    this.core = auroraCore;
    this.currentState = 'IDLE';
    this.ws = null;
    this.reconnectTimer = null;
    this.themes = {};

    this.initThemes();
    this.connectWebSocket();
  }

  initThemes() {
    this.themes = {
      IDLE: {
        primary_color: '#368BFF',
        secondary_color: '#071A35',
        accent_color: '#70D9FF',
        core_pulse_speed: 0.45,
        noise_displacement: 0.04,
        orbital_speed: 0.35,
        particle_activity: 0.25,
        glow_intensity: 0.90,
        desc: 'Rotación lenta, vórtice interior suave y respiración sutil.'
      },
      WAKEWORD: {
        primary_color: '#00F0FF',
        secondary_color: '#368BFF',
        accent_color: '#FFFFFF',
        core_pulse_speed: 1.5,
        noise_displacement: 0.10,
        orbital_speed: 0.90,
        particle_activity: 0.85,
        glow_intensity: 1.40,
        desc: 'Activación instantánea y expansión radiante de energía.'
      },
      LISTENING: {
        primary_color: '#00F0FF',
        secondary_color: '#368BFF',
        accent_color: '#70D9FF',
        core_pulse_speed: 0.9,
        noise_displacement: 0.08,
        orbital_speed: 0.50,
        particle_activity: 0.7,
        glow_intensity: 1.30,
        desc: 'Receptividad acústica total: expansión y vibración reactiva al habla.'
      },
      TRANSCRIBING: {
        primary_color: '#70D9FF',
        secondary_color: '#9D65FF',
        accent_color: '#EAFBFF',
        core_pulse_speed: 1.0,
        noise_displacement: 0.05,
        orbital_speed: 0.70,
        particle_activity: 0.65,
        glow_intensity: 1.10,
        desc: 'Ondas sutiles de procesamiento fonético y decodificación de audio.'
      },
      ROUTING: {
        primary_color: '#7668D8',
        secondary_color: '#368BFF',
        accent_color: '#70D9FF',
        core_pulse_speed: 1.2,
        noise_displacement: 0.06,
        orbital_speed: 1.10,
        particle_activity: 0.80,
        glow_intensity: 1.20,
        desc: 'Movimiento interno de distribución e inferencia de intención cognitiva.'
      },
      THINKING: {
        primary_color: '#9D65FF',
        secondary_color: '#368BFF',
        accent_color: '#00F0FF',
        core_pulse_speed: 1.6,
        noise_displacement: 0.06,
        orbital_speed: 0.90,
        particle_activity: 0.9,
        glow_intensity: 1.35,
        desc: 'Aceleración centrípeta del vórtice con llamarada violeta y destellos neuronales.'
      },
      CLARIFYING: {
        primary_color: '#70D9FF',
        secondary_color: '#071A35',
        accent_color: '#EAFBFF',
        core_pulse_speed: 0.7,
        noise_displacement: 0.04,
        orbital_speed: 0.45,
        particle_activity: 0.50,
        glow_intensity: 1.00,
        desc: 'Animación de atención serena y espera de aclaración del usuario.'
      },
      CONFIRMING: {
        primary_color: '#00F0FF',
        secondary_color: '#4ADE80',
        accent_color: '#FFFFFF',
        core_pulse_speed: 1.2,
        noise_displacement: 0.05,
        orbital_speed: 0.60,
        particle_activity: 0.70,
        glow_intensity: 1.25,
        desc: 'Pulso de confirmación y autorización de acción sensible.'
      },
      EXECUTING: {
        primary_color: '#368BFF',
        secondary_color: '#70D9FF',
        accent_color: '#00F0FF',
        core_pulse_speed: 1.2,
        noise_displacement: 0.05,
        orbital_speed: 1.45,
        particle_activity: 0.95,
        glow_intensity: 1.40,
        desc: 'Sobrecarga cinética: rotación orbital intensa y ráfagas de potencia.'
      },
      VERIFYING: {
        primary_color: '#70D9FF',
        secondary_color: '#368BFF',
        accent_color: '#DDEFFF',
        core_pulse_speed: 0.6,
        noise_displacement: 0.03,
        orbital_speed: 0.7,
        particle_activity: 0.4,
        glow_intensity: 1.05,
        desc: 'Haz de luz deslizándose con precisión en el anillo exterior.'
      },
      SEARCHING: {
        primary_color: '#00F0FF',
        secondary_color: '#368BFF',
        accent_color: '#70D9FF',
        core_pulse_speed: 1.1,
        noise_displacement: 0.05,
        orbital_speed: 1.15,
        particle_activity: 0.85,
        glow_intensity: 1.30,
        desc: 'Barrido holográfico de radar explorando fuentes y resultados.'
      },
      RESPONDING: {
        primary_color: '#368BFF',
        secondary_color: '#70D9FF',
        accent_color: '#00F0FF',
        core_pulse_speed: 1.3,
        noise_displacement: 0.07,
        orbital_speed: 0.65,
        particle_activity: 0.8,
        glow_intensity: 1.35,
        desc: 'Modulación silábica armónica y emisión de ondas acústicas con ecualizador radial.'
      },
      SPEAKING: {
        primary_color: '#368BFF',
        secondary_color: '#70D9FF',
        accent_color: '#00F0FF',
        core_pulse_speed: 1.3,
        noise_displacement: 0.07,
        orbital_speed: 0.65,
        particle_activity: 0.8,
        glow_intensity: 1.35,
        desc: 'Modulación silábica armónica y emisión de ondas de choque radiales.'
      },
      ERROR: {
        primary_color: '#E6A23C',
        secondary_color: '#071A35',
        accent_color: '#FFA726',
        core_pulse_speed: 0.5,
        noise_displacement: 0.03,
        orbital_speed: 0.2,
        particle_activity: 0.3,
        glow_intensity: 0.7,
        desc: 'Atenuación del brillo con indicador ámbar discreto y profesional.'
      }
    };
  }

  setState(newState) {
    if (!newState) return;
    let s = newState.toUpperCase();
    if (s === 'SPEAKING') s = 'RESPONDING';
    if (!this.themes[s] && !this.themes[newState]) return;
    const finalState = this.themes[s] ? s : newState;
    this.currentState = finalState;
    const theme = this.themes[finalState];
    this.core.setTheme(theme, finalState);

    // Notificar también al módulo FX de fusión si existe
    if (window._auroraFXInstance && typeof window._auroraFXInstance.setState === 'function') {
      window._auroraFXInstance.setState(finalState);
    }

    // Clase dinámica en el body para animaciones CSS
    document.body.className = `state-${newState.toLowerCase()}`;

    // Actualizar indicador de estado inferior
    const bannerName = document.getElementById('state-name');
    const bannerDesc = document.getElementById('state-desc');
    const dot = document.getElementById('state-indicator-dot');
    const metricState = document.getElementById('metric-state');

    if (bannerName) bannerName.textContent = newState;
    if (bannerDesc) bannerDesc.textContent = theme.desc;
    if (metricState) metricState.textContent = newState;

    if (dot) {
      dot.style.backgroundColor = theme.primary_color;
      dot.style.boxShadow = `0 0 10px ${theme.primary_color}, 0 0 20px ${theme.accent_color}`;
    }

    // Actualizar botones activos
    document.querySelectorAll('.state-btn').forEach(btn => {
      if (btn.dataset.state === newState) {
        btn.classList.add('active');
        btn.style.borderColor = theme.primary_color;
      } else {
        btn.classList.remove('active');
        btn.style.borderColor = 'rgba(255, 255, 255, 0.08)';
      }
    });

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'state_change', state: newState }));
    }
  }

  connectWebSocket() {
    const loc = window.location;
    const wsProto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProto}//${loc.host}/ws/aurora`;

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        const dot = document.getElementById('header-status-dot');
        if (dot) {
          dot.style.backgroundColor = '#70D9FF';
          dot.style.boxShadow = '0 0 6px #70D9FF';
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'state_update') {
            this.setState(data.state);
          } else if (data.type === 'audio_metrics' || data.type === 'audio_level') {
            const amp = Math.max(0.0, Math.min(1.0, Number(data.normalized_amplitude ?? data.level) || 0.0));
            if (this.core && typeof this.core.setAudioAmplitude === 'function') {
              this.core.setAudioAmplitude(amp);
            }
            if (window._auroraFXInstance && typeof window._auroraFXInstance.setAudioLevel === 'function') {
              window._auroraFXInstance.setAudioLevel(amp);
            }
            const ampMeter = document.getElementById('metric-audio');
            if (ampMeter) {
              const pct = Math.round(amp * 100);
              ampMeter.textContent = `${pct}%`;
            }
          }
        } catch (e) {
          console.error('[AURORA WS] Error parseando mensaje:', e);
        }
      };

      this.ws.onclose = () => {
        const dot = document.getElementById('header-status-dot');
        if (dot) {
          dot.style.backgroundColor = '#E6A23C';
          dot.style.boxShadow = '0 0 6px #E6A23C';
        }
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = setTimeout(() => this.connectWebSocket(), 2000);
      };

      this.ws.onerror = () => {
        if (this.ws) this.ws.close();
      };
    } catch (e) {
      console.warn('[AURORA WS] Modo offline/stand-alone.');
    }
  }
}
