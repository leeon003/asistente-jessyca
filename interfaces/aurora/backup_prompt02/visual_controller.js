/**
 * Controlador de Estados Visuales y Cliente WebSocket
 * JESSYCA ORB — Núcleo Aurora 3D
 */

class AuroraVisualController {
  constructor(auroraCore) {
    this.core = auroraCore;
    this.currentState = 'IDLE';
    this.ws = null;
    this.reconnectTimer = null;
    this.themes = {}; // Se cargan dinámicamente desde el backend o fallback local

    this.initFallbackThemes();
    this.connectWebSocket();
  }

  initFallbackThemes() {
    this.themes = {
      IDLE: {
        primary_color: '#4CC9F0',
        secondary_color: '#7B2CFB',
        accent_color: '#2EE6D6',
        core_pulse_speed: 0.6,
        noise_displacement: 0.15,
        orbital_speed: 0.4,
        particle_activity: 0.3,
        glow_intensity: 0.8
      },
      LISTENING: {
        primary_color: '#2EE6D6',
        secondary_color: '#4CC9F0',
        accent_color: '#EAFBFF',
        core_pulse_speed: 1.5,
        noise_displacement: 0.35,
        orbital_speed: 1.0,
        particle_activity: 1.2,
        glow_intensity: 1.4
      },
      THINKING: {
        primary_color: '#7B2CFB',
        secondary_color: '#D500F9',
        accent_color: '#4CC9F0',
        core_pulse_speed: 2.2,
        noise_displacement: 0.45,
        orbital_speed: 1.8,
        particle_activity: 1.6,
        glow_intensity: 1.3
      },
      SPEAKING: {
        primary_color: '#4CC9F0',
        secondary_color: '#2EE6D6',
        accent_color: '#EAFBFF',
        core_pulse_speed: 1.8,
        noise_displacement: 0.40,
        orbital_speed: 0.8,
        particle_activity: 1.4,
        glow_intensity: 1.5
      },
      EXECUTING: {
        primary_color: '#FF9100',
        secondary_color: '#7B2CFB',
        accent_color: '#00E5FF',
        core_pulse_speed: 2.5,
        noise_displacement: 0.50,
        orbital_speed: 2.2,
        particle_activity: 2.0,
        glow_intensity: 1.6
      },
      VERIFYING: {
        primary_color: '#2979FF',
        secondary_color: '#00E5FF',
        accent_color: '#FFFFFF',
        core_pulse_speed: 1.2,
        noise_displacement: 0.20,
        orbital_speed: 1.2,
        particle_activity: 0.8,
        glow_intensity: 1.2
      },
      ERROR: {
        primary_color: '#FF1744',
        secondary_color: '#D50000',
        accent_color: '#FF8A80',
        core_pulse_speed: 3.0,
        noise_displacement: 0.60,
        orbital_speed: 0.5,
        particle_activity: 2.5,
        glow_intensity: 1.8
      }
    };
  }

  setState(newState) {
    if (!this.themes[newState]) return;
    this.currentState = newState;
    const theme = this.themes[newState];
    this.core.setTheme(theme);

    // Actualizar indicador visual en HUD
    const bannerText = document.getElementById('state-name');
    const indicator = document.getElementById('state-indicator');
    if (bannerText) bannerText.textContent = newState;
    if (indicator) {
      indicator.style.backgroundColor = theme.primary_color;
      indicator.style.boxShadow = `0 0 12px ${theme.primary_color}`;
    }

    // Actualizar botones activos
    document.querySelectorAll('.state-btn').forEach(btn => {
      if (btn.dataset.state === newState) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    // Notificar al backend si el WebSocket está conectado
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
        const dot = document.getElementById('ws-status-dot');
        if (dot) {
          dot.style.backgroundColor = '#00E676';
          dot.style.boxShadow = '0 0 8px #00E676';
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'state_update') {
            this.setState(data.state);
          } else if (data.type === 'audio_metrics') {
            this.core.setAudioAmplitude(data.normalized_amplitude || 0.0);
            const ampMeter = document.getElementById('hud-amp');
            if (ampMeter) ampMeter.textContent = `${Math.round((data.normalized_amplitude || 0) * 100)}%`;
          }
        } catch (e) {
          console.error('[AURORA WS] Error parseando mensaje:', e);
        }
      };

      this.ws.onclose = () => {
        const dot = document.getElementById('ws-status-dot');
        if (dot) {
          dot.style.backgroundColor = '#FF9100';
          dot.style.boxShadow = '0 0 8px #FF9100';
        }
        // Reintento en 2 segundos
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = setTimeout(() => this.connectWebSocket(), 2000);
      };

      this.ws.onerror = () => {
        if (this.ws) this.ws.close();
      };
    } catch (e) {
      console.warn('[AURORA WS] Conexión no disponible en modo offline/stand-alone.');
    }
  }
}
