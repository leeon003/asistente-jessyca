/**
 * Panel de Demostración y Pruebas
 * JESSYCA ORB 4.0 — NÚCLEO AURORA FUSIÓN
 */

document.addEventListener('DOMContentLoaded', () => {
  const auroraCore = new AuroraCore3D('canvas-container');
  const visualController = new AuroraVisualController(auroraCore);

  window._auroraCoreInstance = auroraCore;
  window._visualControllerInstance = visualController;

  // 1. Selector de Estados
  document.querySelectorAll('.state-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const state = btn.dataset.state;
      visualController.setState(state);
      if (window.JESSYCAOrb && typeof window.JESSYCAOrb.setState === 'function') {
        window.JESSYCAOrb.setState(state);
      }
    });
  });

  // 2. Disparador de Acción / Acento (ACCENT)
  const accentBtn = document.getElementById('btn-trigger-accent');
  if (accentBtn) {
    accentBtn.addEventListener('click', () => {
      if (window.JESSYCAOrb && typeof window.JESSYCAOrb.triggerAccent === 'function') {
        window.JESSYCAOrb.triggerAccent(1.2);
      } else {
        auroraCore.triggerShockwave('#00F0FF', 1.8);
      }
    });
  }

  // 3. Control de Calidad
  const qualitySelect = document.getElementById('quality-select');
  if (qualitySelect) {
    qualitySelect.addEventListener('change', (e) => {
      auroraCore.setQuality(e.target.value);
    });
  }

  // 4. Movimiento Reducido
  const motionToggle = document.getElementById('reduced-motion-toggle');
  if (motionToggle) {
    motionToggle.addEventListener('change', (e) => {
      auroraCore.setReducedMotion(e.target.checked);
    });
  }

  // 5. Modulación de Audio
  const ampSlider = document.getElementById('audio-amp-slider');
  const ampValLabel = document.getElementById('audio-amp-val');
  const metricAudio = document.getElementById('metric-audio');

  if (ampSlider) {
    ampSlider.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      auroraCore.setAudioAmplitude(val);
      if (window._auroraFXInstance && typeof window._auroraFXInstance.setAudioLevel === 'function') {
        window._auroraFXInstance.setAudioLevel(val);
      }
      if (window.JESSYCAOrb && typeof window.JESSYCAOrb.setAudioLevel === 'function') {
        window.JESSYCAOrb.setAudioLevel(val);
      }
      const pct = `${Math.round(val * 100)}%`;
      if (ampValLabel) ampValLabel.textContent = pct;
      if (metricAudio) metricAudio.textContent = pct;
    });
  }

  // 6. Botón Discreto para Abrir / Cerrar Panel
  const openBtn = document.getElementById('btn-open-panel');
  const closeBtn = document.getElementById('btn-toggle-panel');
  const panel = document.getElementById('control-panel');

  if (openBtn && panel) {
    openBtn.addEventListener('click', () => {
      panel.classList.toggle('hidden');
    });
  }

  if (closeBtn && panel) {
    closeBtn.addEventListener('click', () => {
      panel.classList.add('hidden');
    });
  }

  // Iniciar en estado EXECUTING con 44% de audio (idéntico a la imagen de referencia aprobada)
  visualController.setState('EXECUTING');
  auroraCore.setAudioAmplitude(0.44);
});
