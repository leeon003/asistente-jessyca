# Secure Desktop Automation Boundary & Fail-Safe — Jessyca Windows MCP (Subetapa 08.4)

## Visión General

La **Subetapa 08.4** consolida la **ETAPA 08 — DESKTOP AUTOMATION, VISION & OCR SYSTEM** implementando la frontera de ejecución de acciones interactivas (`windows.desktop`) protegida por el subsistema independiente de **Parada de Emergencia / Fail-Safe** (`EmergencyStopManager`).

---

## GARANTÍAS ABSOLUTAS DE SEGURIDAD Y FAIL-SAFE

1. **LAYER DE CONTROL INDEPENDIENTE DEL AGENTE**: El subsistema de Parada de Emergencia opera de forma autónoma a la capa de razonamiento del LLM. No depende de respuestas del agente para interrumpir acciones.
2. **ESTADOS EXPLÍCITOS THREAD-SAFE**: `EmergencyStopState` (`RUNNING`, `STOP_REQUESTED`, `STOPPED`, `FAULTED`) protegido con `threading.RLock`.
3. **CANCELLATION TOKEN & ESPERAS NO BLOQUEANTES**: Uso de `CancellationToken` y `threading.Event`. Las esperas y retardos entre pulsaciones o clics utilizan `cancellation_event.wait(timeout)` para salir instantáneamente (0ms) al activarse la Parada de Emergencia.
4. **INSPECCIÓN POR FASES (PHASE-BY-PHASE CHECKING)**:
   - **Fase de Validación**: Cancela antes de iniciar la evaluación.
   - **Fase de Ejecución**: Cancela antes de invocar los backends.
   - **Fase de Espera**: Interrupción inmediata del temporizador.
   - **Fase de Verificación**: Marca la acción como abortada si la parada se activa durante la re-inspección.
5. **IDEMPOTENCIA ANTE DOBLE STOP**: Múltiples solicitudes concurrentes de `trigger_stop` son procesadas de forma segura y sin race conditions.
6. **INVARIANTE DE PRIVACIDAD EN AUDITORÍA**: El `AuditLogger` y el `EventBus` registran **ÚNICAMENTE METADATOS** (`reason`, `source`, `state`, `activation_count`). CERO payloads crudos en auditoría.
7. **ABSTRACCIÓN Y PRUEBAS SINTÉTICAS**: Protocolo `IEmergencyStopController` e implementación `FakeEmergencyStopController` para pruebas sintéticas deterministas.

---

## Componentes Principales

### 1. Estados y Excepciones (`core/emergency_stop.py`)
- `EmergencyStopState`: Estados explícitos (`RUNNING`, `STOP_REQUESTED`, `STOPPED`, `FAULTED`).
- `EmergencyStopTriggeredError`: Excepción lanzada cuando una acción es abortada por la activación del Fail-Safe.
- `CancellationToken`: Wrapper sobre `threading.Event` para espera no bloqueante.

## RUTA DE EJECUCIÓN OBLIGATORIA DE ACCIONES
```text
Agent/Workflow → DesktopAction → ActionGuard → Validation → Safety Check → Executor → Verification → Audit
```

### Capa de Mapeo de Coordenadas y DPI Awareness `CoordinateMapper` (`core/coordinate_mapping.py`)
Modelos e infraestructura de conversión de espacios de coordenadas y DPI:
- `CoordinateSpace`: Espacios de coordenadas (`PHYSICAL_PIXELS`, `LOGICAL_DIP`, `CLIENT_RELATIVE`, `WINDOW_RELATIVE`).
- `DPIInfo`: Información de resolución y escalado (`100%`, `125%`, `150%`, `200%`).
- `MonitorInfo`: Disposición inmutable de monitores e identidades de pantalla.
- `CoordinateMapper`: Conversión de puntos y validación estricta de 6 pasos pre-ejecución:
  1. Identificación del monitor.
  2. Obtención de DPI por monitor.
  3. Validación de resolución.
  4. Validación de espacio de coordenadas.
  5. Recálculo del target.
  6. Rechazo ante cambio incompatible de contexto (`DisplayContextChangedError` / `OffScreenCoordinateError`).
- **Reloj y Pantallas Sintéticas (`FakeScreenMetricsProvider`)**: Pruebas deterministas de escalado y multi-monitor sin requerir hardware físico variado.
