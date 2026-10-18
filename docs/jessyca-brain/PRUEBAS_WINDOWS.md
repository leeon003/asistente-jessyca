# VALIDACIÓN DE CONTROL DE ESCRITORIO EN WINDOWS 11 — JESSYCA BRAIN 1.0

**Proyecto:** JESSYCA Asistente Personal  
**Sistema:** Windows 11 Pro 64-bit  
**Arquitectura:** `UnifiedDesktopController` con `NativeWindowsDriver`  
**Fecha:** 16 de Octubre de 2026

---

## 1. Arquitectura de Control de Escritorio

```
                     ┌───────────────────────────────┐
                     │         JessycaBrain          │
                     └───────────────┬───────────────┘
                                     │ (Planificación)
                                     ▼
                     ┌───────────────────────────────┐
                     │   UnifiedDesktopController    │
                     └───────┬───────────────┬───────┘
                             │               │
                  (Si CUA disponible)   (Predeterminado en Windows 11)
                             │               │
                             ▼               ▼
                    ┌────────────────┐ ┌─────────────────────────┐
                    │  CUA Driver    │ │   NativeWindowsDriver   │
                    │  (Microservicio│ │  - win32gui / win32con  │
                    │   HTTP local)  │ │  - PyAutoGUI / ctypes   │
                    └────────────────┘ │  - Windows UIAutomation │
                                       └─────────────┬───────────┘
                                                     │
                                                     ▼
                                        ┌────────────────────────┐
                                        │  Sistema Operativo     │
                                        │  Windows 11 (GUI/Apps) │
                                        └────────────────────────┘
```

---

## 2. Acciones Validadas y Evidencias Técnicas

Todas las acciones se ejecutaron y verificaron en el sistema real mediante `tests/acceptance/test_fase4_real_desktop_interaction.py` y `test_fase7_user_end_to_end_10_scenarios.py`:

### 1. Lanzamiento y Verificación de Aplicaciones Nativas
- **Calculadora (`calc.exe`):**
  - Acción: `controller.open_app("calc.exe")`.
  - Verificación: `controller.find_window("calc")` localiza el HWND y comprueba el nuevo PID generado en el árbol de procesos de Windows.
  - Cierre: `controller.close_app("calc.exe")` envía `WM_CLOSE` o termina el proceso de forma limpia.
  - Resultado: **APROBADO**.

### 2. Interacción Física con Bloc de notas (Teclado Real)
- **Bloc de notas (`notepad.exe`):**
  - Acción: Apertura de `notepad.exe`.
  - Foco: `controller.focus_window(hwnd)` utiliza `SetForegroundWindow` para situar la ventana al frente de la pantalla.
  - Escritura Real: `controller.type_text(...)` inyecta pulsaciones de teclado físicas en el control de edición de la ventana activa:
    ```
    "JESSYCA BRAIN 1.0 - Windows 11 Native Interaction Verified."
    ```
  - Cierre: Cierre limpio mediante el controlador sin dejar procesos huérfanos.
  - Resultado: **APROBADO**.

### 3. Control de Hardware y Volumen del Sistema
- **Volumen de Windows:**
  - Acción: Modificación de nivel de audio mediante la skill `windows.audio` con parámetros `{"accion": "bajar", "nivel": 10}`.
  - Verificación: `AudioEndpointVolume` del Core Audio API de Windows actualiza el nivel maestro sin errores.
  - Resultado: **APROBADO**.

### 4. Navegación Web y Multimedia
- **Navegador y DuckDuckGo / YouTube:**
  - Apertura de navegador autorizado (Microsoft Edge / Google Chrome).
  - Consulta y búsqueda de términos mediante `browser.search` con lista blanca estricta de dominios (`duckduckgo.com`, `youtube.com`).
  - Detección de instancias previas para evitar saturación de memoria por duplicación de procesos.
  - Resultado: **APROBADO**.

---

## 3. Mecanismos de Seguridad y Gobernanza

1. **Mutex de Sesión Gráfica (`SessionExecutionLock`):** Garantiza que dos hilos o procesos no intenten mover el mouse o enviar pulsaciones de teclado simultáneamente, previniendo conflictos de foco o entradas truncadas.
2. **Lista Blanca de Aplicaciones (Bounded Apps Policy):** Solo se permite el lanzamiento de aplicaciones explícitamente autorizadas en `SECURITY_POLICY` (Calculadora, Bloc de notas, Edge, Chrome, Terminal, etc.). Cualquier intento de invocar ejecutables no autorizados es bloqueado por `PermissionManager` y `RiskEngine`.
3. **Resolución de Coordenadas Frescas:** Antes de hacer clic en cualquier elemento, el controlador consulta en tiempo real `GetWindowRect` del HWND para evitar clics desalineados si la ventana se movió o redimensionó.
4. **Parada de Emergencia Failsafe:** Detiene de inmediato cualquier interacción gráfica activa y libera los mutexes de hardware.
