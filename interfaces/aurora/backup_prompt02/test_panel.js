/**
 * Panel Interactivo de Pruebas y Control de Demostración
 * JESSYCA ORB — Núcleo Aurora 3D
 */

document.addEventListener('DOMContentLoaded', () => {
  // 1. Inicializar Motor 3D y Controlador
  const auroraCore = new AuroraCore3D('canvas-container');
  const visualController = new AuroraVisualController(auroraCore);

  // 2. Vincular Botones de Estados
  document.querySelectorAll('.state-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const state = btn.dataset.state;
      visualController.setState(state);
    });
  });

  // 3. Control de Calidad Gráfica
  const qualitySelect = document.getElementById('quality-select');
  if (qualitySelect) {
    qualitySelect.addEventListener('change', (e) => {
      auroraCore.setQuality(e.target.value);
    });
  }

  // 4. Modo de Movimiento Reducido (Accesibilidad / Bajo Consumo)
  const reducedMotionToggle = document.getElementById('reduced-motion-toggle');
  if (reducedMotionToggle) {
    reducedMotionToggle.addEventListener('change', (e) => {
      auroraCore.setReducedMotion(e.target.checked);
    });
  }

  // 5. Control de Simulación de Amplitud de Audio
  const audioSlider = document.getElementById('audio-amp-slider');
  const audioValLabel = document.getElementById('audio-amp-val');
  if (audioSlider) {
    audioSlider.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      auroraCore.setAudioAmplitude(val);
      if (audioValLabel) audioValLabel.textContent = `${Math.round(val * 100)}%`;
      const ampMeter = document.getElementById('hud-amp');
      if (ampMeter) ampMeter.textContent = `${Math.round(val * 100)}%`;
    });
  }

  // 6. Minimizar / Expandir Panel
  const toggleBtn = document.getElementById('btn-toggle-panel');
  const panel = document.getElementById('test-panel');
  if (toggleBtn && panel) {
    toggleBtn.addEventListener('click', () => {
      panel.classList.toggle('minimized');
      toggleBtn.textContent = panel.classList.contains('minimized') ? '⚙' : '—';
    });
  }

  // Estado inicial
  visualController.setState('IDLE');
});
