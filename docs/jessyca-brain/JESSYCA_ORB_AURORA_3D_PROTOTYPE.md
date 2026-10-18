# JESSYCA ORB — NÚCLEO AURORA 3D: PROTOTIPO INDEPENDIENTE

**Proyecto:** JESSYCA Asistente Personal  
**Versión:** 1.0.0-prototype  
**Entorno:** Windows 11 (Build 26200), Python 3.11.9, GPU NVIDIA GeForce RTX 3060 (12 GB VRAM)  
**Motor Gráfico:** Three.js (WebGL 2.0 Hardware Accelerated) + Shaders GLSL  
**Fecha:** 2026-10-16  

---

## 1. RESULTADO DE LA VALIDACIÓN TÉCNICA

Se realizó la verificación exhaustiva de los módulos del asistente para garantizar cero regresiones y compatibilidad arquitectónica:

1. **Inmutabilidad de `SessionState` (`core/state/states.py`):**
   - Se verificó que los estados canónicos son estrictamente diez: `IDLE`, `WAKEWORD`, `LISTENING`, `TRANSCRIBING`, `ROUTING`, `CONFIRMING`, `CLARIFYING`, `EXECUTING`, `VERIFYING`, `RESPONDING`.
   - Estados propuestos en diseño visual (`THINKING`, `SPEAKING`, `ERROR`) **no** fueron agregados a `SessionState`. Se implementó la clase desacoplada `SessionStateToAuroraAdapter` en `interfaces/aurora/visual_states.py` para mapear los estados de negocio a los estados de renderizado visual sin alterar la máquina de estados original.
2. **Bus de Eventos Tipado (`core/bus.py`):**
   - Se validó el singleton `get_event_bus()`. Emite eventos inmutables (`WakeWordDetected`, `UtteranceFinal`, `ActionProposed`, `ActionExecuted`, `VerificationResult`, `SpeakRequested`, `UserInterrupted`).
   - El subsistema visual Aurora está preparado para suscribirse a estos eventos mediante el adaptador sin acoplamiento circular.
3. **Audio I/O y Captura Calibrada (`services/voice/`):**
   - `CalibratedVoiceCaptureEngine` gestiona el micrófono con VAD adaptativo y buffers de pre-roll.
   - Para no abrir un segundo flujo de captura del micrófono (lo que provocaría bloqueos de dispositivo en Windows WASAPI), se implementó `AuroraAudioAdapter.process_pcm_chunk()` para calcular RMS, amplitud normalizada (0.0 a 1.0) y tasa de cruces por cero (Zero-Crossing Rate) sobre los mismos fragmentos de audio de la sesión activa.
   - Se desacopló la detección de habla TTS: no se asume que `SpeakRequested` signifique audio activo; se diseñaron los hooks de notificación de inicio y fin real de reproducción acústica (`notify_tts_playback_start` y `notify_tts_playback_end`).

---

## 2. COMPARATIVA Y SELECCIÓN DEL MOTOR GRÁFICO

Se evaluaron las tecnologías disponibles bajo los criterios de rendimiento, consumo, integración con Windows 11 y facilidad de distribución:

| Tecnología | 3D Real | Consumo GPU/CPU | Shaders GLSL | Integración Windows 11 | Dependencias Nuevas | Veredicto |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **Tkinter Canvas** | ❌ (Pseudo 2D) | CPU pura (Lento) | ❌ No soportado | Nativa en Python | 0 | **Descartado:** No permite deformación orgánica ni partículas 3D reales. |
| **Pygame (SDL2)** | ❌ (2D por defecto) | Medio | ⚠️ Requiere PyOpenGL | Nativo | Requiere PyOpenGL | **Descartado:** Requiere enlazar C/OpenGL manual y carece de soporte nativo para ventanas transparentes complejas. |
| **PySide6 + Qt Quick 3D** | ✔️ Sí | Medio-Alto | ✔️ QSB/GLSL | Nativa pesada | >350 MB | **Descartado:** Excesivo peso y riesgo de dependencias binarias. |
| **moderngl / PyOpenGL** | ✔️ Sí | Bajo | ✔️ Sí | Compleja en Win311 | Requiere instalación C | **Descartado:** Manejo complejo de capas transparentes `WS_EX_LAYERED`. |
| **Three.js (WebGL 2.0)** | ✔️ **Sí (Acelerado)** | **Óptimo (60 FPS)** | ✔️ **Shaders completos** | **Excelente (Edge App Mode / WebView2)** | **0 (Usa FastAPI y Three.js local offline)** | **SELECCIONADO** |

### Justificación Técnica de la Elección:
1. **Rendimiento Máximo:** Renderizado nativo por GPU (NVIDIA RTX 3060) mediante WebGL 2.0 a 60 FPS estables.
2. **Cero Dependencias Nuevas:** Reutiliza `fastapi` y `uvicorn` que ya están instalados en el proyecto. La biblioteca `three.min.js` (r128) fue empaquetada localmente en `interfaces/aurora/static/vendor/three.min.js` operando 100% offline.
3. **Aislamiento de Procesos:** La ventana gráfica corre en su propio subproceso desacoplado, comunicándose por WebSocket (`ws://127.0.0.1:8765/ws/aurora`). Nunca compite por recursos de CPU con el hilo de inferencia de Whisper STT ni con Ollama.
4. **Seguridad de Foco:** Ejecutable en modo aplicación mediante Microsoft Edge (`--app=http://127.0.0.1:8765`), sin barras de navegador, sin interferir con el foco de teclado de Bloc de notas ni de otras aplicaciones de escritorio.

---

## 3. ARQUITECTURA DEL PROTOTIPO NÚCLEO AURORA

```
interfaces/aurora/
├── __init__.py               # Versión y metadatos del prototipo
├── visual_states.py          # Enums de estado visual, temas cromáticos y adaptador SessionState
├── audio_adapter.py          # Cálculo desacoplado de RMS, amplitud y simulación de modulación
├── server.py                 # Servidor local FastAPI + WebSocket bidireccional
├── window_manager.py         # Administrador de ventana nativa de escritorio Windows 11
├── launcher.py               # Lanzador CLI independiente (python -m interfaces.aurora.launcher)
└── static/
    ├── index.html            # Lienzo WebGL, telemetría HUD y panel interactivo de pruebas
    ├── css/
    │   └── aurora.css        # Estilos Glassmorphism futurista, fuentes y controles
    ├── js/
    │   ├── aurora_core.js    # Motor Three.js: Núcleo orgánico, Membrana Fresnel, 3 Anillos, Partículas
    │   ├── visual_controller.js # Interpolación de estados y cliente WebSocket
    │   └── test_panel.js     # Manejador del panel de pruebas, FPS, calidad y audio
    └── vendor/
        └── three.min.js      # Biblioteca Three.js r128 local (603 KB, offline)
```

### Componentes Visuales Tridimensionales (Identidad Visual Original):
1. **Núcleo Central Orgánico:** Icosaedro subdividido con vertex shader de ruido 3D Simplex (`snoise`), deformación procedural y pulsación sinusoidal suave modulada por amplitud acústica.
2. **Membrana Energética Holográfica:** Esfera concéntrica con shader de Fresnel iridiscente (`pow(1.0 - abs(dot(normal, viewDir)), 3.0)`), produciendo bordes lumínicos cyan y violeta con ondas de refracción.
3. **Tres Anillos Orbitales Asimétricos:** Anillos toroidales tridimensionales con diferentes radios (2.15, 2.50, 2.85), inclinaciones en ejes X/Y y velocidades de rotación contrarias.
4. **Filamentos Cuánticos:** Líneas de luz que interconectan vértices dinámicos del núcleo.
5. **Enjambre de Partículas Orbitales:** 1100 micropartículas tridimensionales distribuidas en trayectorias espirales toroidales continuas (no una esfera estática de puntos planos).

---

## 4. ESTADOS VISUALES DEL PROTOTIPO

| Estado Visual | Concepto | Colores Primario / Secundario / Acento | Comportamiento Dinámico |
| :--- | :--- | :--- | :--- |
| **`IDLE`** | Reposo | `#4CC9F0` (Azul eléctrico) / `#7B2CFB` (Violeta) / `#2EE6D6` (Turquesa) | Respiración lenta a 0.6 Hz; partículas en órbita calmada. |
| **`LISTENING`** | Escucha Activa | `#2EE6D6` (Turquesa) / `#4CC9F0` (Azul) / `#EAFBFF` (Blanco hielo) | Deformación radial reactiva a la amplitud de la voz del usuario. |
| **`THINKING`** | Razonamiento | `#7B2CFB` (Violeta) / `#D500F9` (Magenta) / `#4CC9F0` (Cyan) | Giros orbitales rápidos (1.8x), refracción interna intensa. |
| **`SPEAKING`** | Habla (TTS) | `#4CC9F0` (Azul eléctrico) / `#2EE6D6` (Turquesa) / `#EAFBFF` (Blanco) | Modulación armónica rítmica en sintonía con las frases vocales. |
| **`EXECUTING`** | Acción Desktop | `#FF9100` (Ámbar) / `#7B2CFB` (Violeta) / `#00E5FF` (Cyan) | Máxima energía en anillos orbitales y pulso acelerado. |
| **`VERIFYING`** | Verificación | `#2979FF` (Azul cobalto) / `#00E5FF` (Cyan) / `#FFFFFF` (Blanco puro) | Escaneo concéntrico y alineación visual de precisión. |
| **`ERROR`** | Alerta / Fallo | `#FF1744` (Carmesí) / `#D50000` (Rojo) / `#FF8A80` (Coral) | Dispersión caótica de partículas y pulso de advertencia a 3.0 Hz. |

---

## 5. RESULTADOS DE RENDIMIENTO Y PRUEBAS

### 5.1 Pruebas Automatizadas (Pytest)
Se ejecutó la suite `tests/aurora/test_aurora_prototype.py` con **9 pruebas unitarias y de integración**:
- `test_01_session_state_immutability_and_mapping`: APROBADO (Inmutabilidad garantizada).
- `test_02_all_visual_themes_defined`: APROBADO (7 temas validados).
- `test_03_static_files_integrity`: APROBADO (Three.js, CSS, JS verificados).
- `test_04_server_rest_endpoints`: APROBADO (Health, Themes, State OK).
- `test_05_audio_adapter_pcm_processing`: APROBADO (Cálculo de RMS a 440 Hz verificado).
- `test_06_audio_simulation_modes`: APROBADO (Marcado `is_simulated=True` verificado).
- `test_07_tts_playback_notifications`: APROBADO (Ciclo de reproducción verificado).
- `test_08_window_manager_detection`: APROBADO (Detección de Edge en Windows 11).
- `test_09_no_interference_with_cognitive_brain`: APROBADO (JessycaBrain intacto).
- **Resultado:** `9 passed in 5.02s` (100% de éxito).

### 5.2 Validación Visual Interactiva en Tiempo Real (Browser Subagent)
Se ejecutó una sesión interactiva automatizada validando todos los componentes en ejecución:
- **Tasa de refresco:** **60 FPS constantes** reportados en el HUD de telemetría.
- **Transiciones:** Se verificó la transición entre los estados `IDLE` → `LISTENING` → `THINKING` → `SPEAKING` → `EXECUTING` → `ERROR`.
- **Interpolación cromática:** Las transiciones de color y geometría ocurren de forma suave mediante LERP sin saltos bruscos.
- **Grabación WebP:** Guardada como evidencia verificable en:
  `file:///C:/Users/PC/.gemini/antigravity-ide/brain/606da34d-dc14-45b4-8307-89f169bd2b93/aurora_3d_demo_1792198460329.webp`

---

## 6. INSTRUCCIONES PARA EJECUTAR EL PROTOTIPO

Para abrir el prototipo independiente en Windows 11:

```powershell
# Opción 1: Ejecución completa con ventana de escritorio
python -m interfaces.aurora.launcher

# Opción 2: Ejecución en puerto específico con modulación de audio activa
python -m interfaces.aurora.launcher --port 8765

# Opción 3: Modo Headless (solo servidor para acceder desde cualquier navegador en http://localhost:8765)
python -m interfaces.aurora.launcher --headless
```

---

## 7. PLAN DE INTEGRACIÓN FUTURA CON EL ASISTENTE REAL

Una vez autorizado por el usuario:
1. **Conexión de Audio en Vivo:** Enlazar el callback de `CalibratedVoiceCaptureEngine` en `services/voice/audio_capture.py` para alimentar fragmentos PCM a `AuroraAudioAdapter.process_pcm_chunk()`.
2. **Sincronización de Estados de Sesión:** En `interfaces/modo_voz.py`, conectar las transiciones de `state_machine.transition_to()` con el adaptador `SessionStateToAuroraAdapter` y difundir automáticamente vía WebSocket.
3. **Sincronización de Locución TTS:** Conectar los eventos `SpeakRequested` e interrupción de `BargeInController` con `notify_tts_playback_start()` y `notify_tts_playback_end()`.
4. **Flag de Inicio Opcional:** Añadir la opción `--orb` a `iniciar_jessyca.py` para levantar el orbe junto al modo de voz si el usuario lo desea.
