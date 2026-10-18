/**
 * JESSYCA ORB 4.0 — MÓDULO DE FUSIÓN DE EFECTOS REACTIVOS V2 (CANVAS FX)
 * 
 * Integra los efectos visuales cinéticos del orbe reactivo v2 sobre el Núcleo Aurora 3D:
 * - LISTENING: Ondas de sonar acústicas expansivas y espículas de captura de audio.
 * - SPEAKING: 44 barras de ecualizador de voz radiales moduladas por sílabas y audio.
 * - THINKING: Anillos concéntricos de radar con trazos discontinuos contrarrotatorios y nodos cognitivos.
 * - EXECUTING / WORKING: Corona de 24 engranajes cinéticos y anillo de calibración industrial.
 * - SEARCHING: Haz de barrido de radar holográfico con detección de blancos.
 * - ACCENT: Disparo de onda de choque de acción instantánea (triggerAccent).
 */

class AuroraFXFusion {
  constructor(canvasId, auroraCore) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas ? this.canvas.getContext('2d', { alpha: true }) : null;
    this.core = auroraCore;

    this.W = 0;
    this.H = 0;
    this.DPR = 1;
    this.elapsed = 0;
    this.previous = performance.now();
    this.accent = 0.0;
    this.audioLevel = 0.44;
    this.currentState = 'EXECUTING';
    this.enabled = true;

    // Fibras y partículas orbitales opcionales de fusión v2
    this.strands = Array.from({ length: 48 }, (_, i) => ({
      id: i,
      angle: i * 2.399963,
      tilt: Math.sin(i * 37.91) * 0.45,
      speed: 0.65 + ((i * 7) % 17) / 32,
      hue: i % 18 === 0 ? 'violet' : 'ice'
    }));

    if (this.canvas) {
      window.addEventListener('resize', () => this.resize());
      this.resize();
      this.animate();
    }
  }

  resize() {
    this.DPR = Math.min(window.devicePixelRatio || 1, 1.5);
    this.W = window.innerWidth;
    this.H = window.innerHeight;
    this.canvas.width = Math.floor(this.W * this.DPR);
    this.canvas.height = Math.floor(this.H * this.DPR);
    this.canvas.style.width = this.W + 'px';
    this.canvas.style.height = this.H + 'px';
    if (this.ctx) {
      this.ctx.setTransform(this.DPR, 0, 0, this.DPR, 0, 0);
    }
  }

  setState(state) {
    let s = state.toUpperCase();
    if (s === 'WORK' || s === 'WORKING') s = 'EXECUTING';
    if (s === 'SEARCH' || s === 'SEARCHING') s = 'SEARCHING';
    this.currentState = s;
    this.triggerAccent(0.65);
  }

  triggerAccent(boost = 1.0) {
    this.accent = Math.max(this.accent, boost);
    if (this.core && typeof this.core.triggerShockwave === 'function') {
      const color = this.currentState === 'THINKING' ? '#9D65FF' : (this.currentState === 'SPEAKING' ? '#70D9FF' : '#00F0FF');
      this.core.triggerShockwave(color, 1.6);
    }
  }

  setAudioLevel(lvl) {
    this.audioLevel = Math.max(0.0, Math.min(1.0, lvl));
    if (this.core) {
      this.core.setAudioAmplitude(this.audioLevel);
    }
  }

  circle(x, y, r, stroke, fill, lw = 1) {
    const ctx = this.ctx;
    ctx.beginPath();
    ctx.arc(x, y, Math.max(0.5, r), 0, Math.PI * 2);
    if (fill) { ctx.fillStyle = fill; ctx.fill(); }
    if (stroke) { ctx.lineWidth = lw; ctx.strokeStyle = stroke; ctx.stroke(); }
  }

  animate() {
    requestAnimationFrame(() => this.animate());

    const now = performance.now();
    const dt = Math.min(0.08, (now - this.previous) / 1000);
    this.previous = now;
    this.elapsed += dt;

    if (!this.ctx || !this.enabled) return;

    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.W, this.H);

    // Atenuación suave del pulso de acento
    this.accent *= Math.pow(0.08, dt * 1.2);
    if (this.accent < 0.005) this.accent = 0.0;

    const t = this.elapsed;
    const small = Math.min(this.W, this.H);
    // Radio sincronizado con la esfera 3D central
    const radius = small * 0.292;
    const cx = this.W * 0.5;
    const cy = this.H * 0.5;
    const mode = this.currentState.toLowerCase();

    ctx.save();
    ctx.globalCompositeOperation = 'screen';
    ctx.translate(cx, cy);

    const lev = this.core ? this.core.audioAmplitude : this.audioLevel;

    // ── 0. ESTADO WAKEWORD: EXPANSIÓN RADIANTE DE ENERGÍA Y DISPARO ──
    if (mode === 'wakeword') {
      const wp = (t * 2.5) % 1;
      const wr = radius * (1.0 + wp * 0.45);
      const alpha = (1.0 - wp) * 0.75;
      this.circle(0, 0, wr, `rgba(0, 240, 255, ${alpha})`, null, 2.5);
      this.circle(0, 0, wr * 1.08, `rgba(255, 255, 255, ${alpha * 0.5})`, null, 1.5);
    }

    // ── 1. ESTADO ESCUCHANDO (LISTENING): ONDAS DE SONAR Y ESPÍCULAS ──
    if (mode === 'listening') {
      ctx.lineWidth = 1.2;
      for (let i = 0; i < 4; i++) {
        const p = ((t * 1.5 + i * 0.28) % 1);
        const rr = radius * (1.02 + p * 0.38);
        const alpha = (1.0 - p) * 0.28 * (0.8 + lev * 0.6);
        this.circle(0, 0, rr, `rgba(0, 240, 255, ${alpha})`, null, 1.3);
      }

      // Espículas de captura de micrófono
      const spikes = 6;
      for (let i = 0; i < spikes; i++) {
        const ang = t * 1.8 + i * (Math.PI * 2 / spikes);
        const r1 = radius * (1.20 + lev * 0.15);
        const r2 = radius * (1.38 + lev * 0.35);
        ctx.strokeStyle = `rgba(112, 217, 255, ${0.25 + lev * 0.4})`;
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.moveTo(Math.cos(ang) * r1, Math.sin(ang) * r1);
        ctx.lineTo(Math.cos(ang) * r2, Math.sin(ang) * r2);
        ctx.stroke();
      }
    }

    // ── 2. ESTADO TRANSCRIBIENDO (TRANSCRIBING): ONDAS SUTILES DE PROCESAMIENTO ──
    if (mode === 'transcribing') {
      for (let i = 0; i < 3; i++) {
        const phase = (t * 1.8 + i * 0.33) % 1;
        const rr = radius * (1.04 + phase * 0.25);
        const a = (1.0 - phase) * 0.35;
        this.circle(0, 0, rr, `rgba(112, 217, 255, ${a})`, null, 1.2);
      }
    }

    // ── 3. ESTADO HABLANDO (SPEAKING / RESPONDING): 44 BARRAS RADIALES DE VOZ PALPITANTES ──
    if (mode === 'speaking' || mode === 'responding') {
      const bars = 44;
      ctx.lineWidth = 1.6;
      for (let i = 0; i < bars; i++) {
        const u = i / (bars - 1);
        const a = (u - 0.5) * Math.PI * 1.95;
        // Danza espectral de frecuencias al ritmo de la voz
        const barFreq = 6.0 + Math.abs(Math.sin(i * 0.35)) * 14.0;
        const speechSyllable = Math.abs(Math.sin(t * barFreq + i * 0.35)) * Math.abs(Math.cos(t * 4.0 + i * 0.15));
        const amp = 0.08 + (speechSyllable * 0.55 + 0.45) * (lev * 0.95 + this.accent * 0.40);

        const inner = radius * 1.025;
        const outer = inner + radius * 0.35 * amp;

        const x1 = Math.cos(a) * inner;
        const y1 = Math.sin(a) * inner * 0.88;
        const x2 = Math.cos(a) * outer;
        const y2 = Math.sin(a) * outer * 0.88;

        const alpha = Math.min(0.98, 0.15 + amp * 1.35);
        const grad = ctx.createLinearGradient(x1, y1, x2, y2);
        grad.addColorStop(0, `rgba(54, 139, 255, ${alpha * 0.45})`);
        grad.addColorStop(0.65, `rgba(112, 217, 255, ${alpha * 0.85})`);
        grad.addColorStop(1, `rgba(255, 255, 255, ${alpha})`);

        ctx.strokeStyle = grad;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
      }

      // Anillo reactivo de modulación que palpita con la voz
      const voicePulseRadius = radius * (1.035 + lev * 0.065);
      this.circle(0, 0, voicePulseRadius, `rgba(186, 238, 255, ${0.14 + lev * 0.45})`, null, 1.5);

      // Ondas acústicas concéntricas emitidas al ritmo de la cadencia de voz
      for (let w = 0; w < 3; w++) {
        const wp = ((t * 2.4 + w * 0.33) % 1);
        const wr = radius * (1.05 + wp * 0.40);
        const wAlpha = (1.0 - wp) * 0.26 * (lev * 1.3);
        if (wAlpha > 0.02) {
          this.circle(0, 0, wr, `rgba(112, 217, 255, ${wAlpha})`, null, 1.2);
        }
      }
    }

    // ── 4. ESTADO PENSANDO / ENRUTANDO (THINKING / ROUTING): RADAR Y NODOS COGNITIVOS ──
    if (mode === 'thinking' || mode === 'routing') {
      for (let i = 0; i < 3; i++) {
        const rr = radius * (1.06 + i * 0.08);
        ctx.setLineDash([3, 9]);
        ctx.lineDashOffset = -t * 22 * (i % 2 ? 1 : -1);
        this.circle(0, 0, rr, `rgba(157, 101, 255, ${0.16 + i * 0.06})`, null, 1.2);
      }
      ctx.setLineDash([]);

      // 4 Puntos de cálculo orbital cognitivo
      for (let i = 0; i < 4; i++) {
        const ang = t * 1.2 + i * (Math.PI / 2);
        const x = Math.cos(ang) * radius * 1.20;
        const y = Math.sin(ang) * radius * 1.20;
        this.circle(x, y, 2.8, null, 'rgba(0, 240, 255, 0.75)');
        this.circle(x, y, 5.5, null, 'rgba(157, 101, 255, 0.35)');
      }
    }

    // ── 5. ESTADO ACLARACIÓN (CLARIFYING): PULSO DE ATENCIÓN Y ESPERA ──
    if (mode === 'clarifying') {
      const pulse = 0.5 + 0.5 * Math.sin(t * 3.0);
      this.circle(0, 0, radius * (1.08 + pulse * 0.04), `rgba(112, 217, 255, ${0.25 + pulse * 0.3})`, null, 1.4);
      this.circle(0, 0, radius * 1.18, `rgba(234, 251, 255, ${0.15 + pulse * 0.2})`, null, 1.0);
    }

    // ── 6. ESTADO CONFIRMACIÓN (CONFIRMING): PULSO ESMERALDA / CIAN ──
    if (mode === 'confirming') {
      const pulse = 0.5 + 0.5 * Math.sin(t * 4.5);
      this.circle(0, 0, radius * (1.06 + pulse * 0.05), `rgba(74, 222, 128, ${0.35 + pulse * 0.4})`, null, 1.8);
      this.circle(0, 0, radius * 1.20, `rgba(0, 240, 255, ${0.2 + pulse * 0.25})`, null, 1.2);
    }

    // ── 7. ESTADO EJECUTANDO / TRABAJANDO (EXECUTING / WORKING): DIENTES DE ENGRANAJE Y CALIBRACIÓN ──
    if (mode === 'executing' || mode === 'working') {
      ctx.save();
      ctx.rotate(t * 0.35);

      // Corona de 24 marcas radiales de potencia cinemática
      for (let i = 0; i < 24; i++) {
        const a = i * (Math.PI * 2 / 24);
        const isMajor = (i % 3 === 0);
        const r1 = radius * 1.05;
        const r2 = radius * (isMajor ? 1.28 : 1.18);

        ctx.strokeStyle = `rgba(0, 240, 255, ${isMajor ? 0.35 : 0.16})`;
        ctx.lineWidth = isMajor ? 1.8 : 1.0;
        ctx.beginPath();
        ctx.moveTo(Math.cos(a) * r1, Math.sin(a) * r1);
        ctx.lineTo(Math.cos(a) * r2, Math.sin(a) * r2);
        ctx.stroke();
      }

      ctx.rotate(-t * 0.75);
      ctx.setLineDash([12, 8]);
      ctx.lineDashOffset = t * 36;
      this.circle(0, 0, radius * 1.16, 'rgba(54, 139, 255, 0.32)', null, 1.3);
      ctx.setLineDash([]);
      ctx.restore();
    }

    // ── 8. ESTADO BUSCANDO (SEARCHING): HAZ DE RADAR HOLOGRÁFICO Y BLANCOS ──
    if (mode === 'searching') {
      const sweep = (t * 1.35) % (Math.PI * 2);
      ctx.fillStyle = 'rgba(0, 240, 255, 0.08)';
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.arc(0, 0, radius * 1.45, sweep - 0.22, sweep + 0.22);
      ctx.closePath();
      ctx.fill();

      ctx.strokeStyle = 'rgba(112, 217, 255, 0.55)';
      ctx.lineWidth = 1.8;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(Math.cos(sweep) * radius * 1.45, Math.sin(sweep) * radius * 1.45);
      ctx.stroke();

      // Blancos detectados por el radar
      for (let i = 0; i < 5; i++) {
        const a = sweep + i * 1.15;
        const rr = radius * (1.14 + (i % 3) * 0.10);
        this.circle(Math.cos(a) * rr, Math.sin(a) * rr, 2.5, null, `rgba(0, 240, 255, ${0.45 + 0.3 * Math.sin(t * 5 + i)})`);
      }
    }

    // ── 9. ESTADO VERIFICANDO (VERIFYING): ESCANEO PERIMETRAL DE PRECISIÓN ──
    if (mode === 'verifying') {
      const scanAng = (t * 2.2) % (Math.PI * 2);
      ctx.beginPath();
      ctx.arc(0, 0, radius * 1.12, scanAng - 0.5, scanAng);
      ctx.strokeStyle = 'rgba(112, 217, 255, 0.85)';
      ctx.lineWidth = 2.0;
      ctx.stroke();

      const cx = Math.cos(scanAng) * radius * 1.12;
      const cy = Math.sin(scanAng) * radius * 1.12;
      this.circle(cx, cy, 3.5, null, 'rgba(255, 255, 255, 0.95)');
    }

    // ── 10. ESTADO ERROR (ERROR): SEÑAL ÁMBAR DISCRETA Y RECUPERACIÓN ──
    if (mode === 'error') {
      const pulse = 0.5 + 0.5 * Math.sin(t * 6.0);
      this.circle(0, 0, radius * (1.06 + pulse * 0.04), `rgba(230, 162, 60, ${0.3 + pulse * 0.35})`, null, 1.8);
      this.circle(0, 0, radius * 1.22, `rgba(255, 167, 38, ${0.15 + pulse * 0.2})`, null, 1.0);
    }

    // ── 11. PULSO DE ACCIÓN / ACENTO GLOBAL (ACCENT TRIGGER) ──
    if (this.accent > 0.02) {
      const shockR = radius * (1.04 + this.accent * 0.35);
      const alpha = Math.min(0.75, this.accent * 0.85);
      this.circle(0, 0, shockR, `rgba(0, 240, 255, ${alpha})`, null, 2.0);
      this.circle(0, 0, shockR * 1.08, `rgba(157, 101, 255, ${alpha * 0.5})`, null, 1.2);
    }

    ctx.restore();
  }
}

// Inicializar y exponer API global window.JESSYCAOrb
window.addEventListener('DOMContentLoaded', () => {
  // Asegurar existencia del canvas FX
  let fxCanvas = document.getElementById('fx');
  if (!fxCanvas) {
    fxCanvas = document.createElement('canvas');
    fxCanvas.id = 'fx';
    fxCanvas.style.position = 'absolute';
    fxCanvas.style.top = '0';
    fxCanvas.style.left = '0';
    fxCanvas.style.width = '100%';
    fxCanvas.style.height = '100%';
    fxCanvas.style.zIndex = '3';
    fxCanvas.style.pointerEvents = 'none';
    document.body.appendChild(fxCanvas);
  }

  // Enlazar con instancia global de auroraCore
  const checkCore = setInterval(() => {
    if (window._auroraCoreInstance) {
      clearInterval(checkCore);
      const fusion = new AuroraFXFusion('fx', window._auroraCoreInstance);
      window._auroraFXInstance = fusion;

      // API Global unificada JESSYCAOrb (100% compatible con v2 y v4)
      window.JESSYCAOrb = {
        setState(s) {
          if (s === 'work') s = 'EXECUTING';
          if (s === 'search') s = 'SEARCHING';
          if (window._visualControllerInstance) {
            window._visualControllerInstance.setState(s.toUpperCase());
          }
          fusion.setState(s);
        },
        pulseAction(kind = 'generic', strength = 1.0) {
          if (kind === 'listen') this.setState('LISTENING');
          else if (kind === 'speak') this.setState('SPEAKING');
          else if (kind === 'work' || kind === 'action') this.setState('EXECUTING');
          else if (kind === 'search') this.setState('SEARCHING');
          else if (kind === 'think') this.setState('THINKING');
          fusion.triggerAccent(Math.min(1.5, Math.max(0.2, strength)));
        },
        triggerAccent(strength = 1.0) {
          fusion.triggerAccent(strength);
        },
        setAudioLevel(lvl) {
          const val = Number(lvl) || 0.0;
          fusion.setAudioLevel(val);
          if (window._auroraCoreInstance && typeof window._auroraCoreInstance.setAudioAmplitude === 'function') {
            window._auroraCoreInstance.setAudioAmplitude(val);
          }
        },
        getState() {
          return fusion.currentState;
        }
      };
    }
  }, 50);
});
