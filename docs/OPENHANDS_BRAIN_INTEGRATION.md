# OpenHands ↔ JESSYCA BRAIN: estado de integración

Rama de origen: `integration/brain-harness2-20261022`.
Se incorpora `core/cognitive_brain/openhands_provider.py` y un método explícito
`JessycaBrain.run_development_task(..., approved=...)`.

## Alcance implementado
- Contrato de tareas y resultados especializados en programación.
- Inyección de ejecutor; desactivado por defecto.
- Aprobación explícita por tarea.
- Restricción por directorio resuelto dentro de sandbox.
- Proveedor opcional para el SDK OpenHands siguiendo su API publicada.
- Tests unitarios de aislamiento y CI para Python 3.12.

## Límites importantes
- **No está activado en el arranque** y no se ha desplegado Agent Server ni Docker.
- El control de ruta en Python **no impide** que las herramientas internas
  de OpenHands accedan a otras rutas: **es imprescindible un sandbox OS/contenedor
  separado** sin secretos ni carpetas del usuario montadas.
- La API del SDK y el modelo contratado deben verificarse con instalación
  y ejecución de la versión fijada antes de habilitarse.
- La aprobación de la tarea no da permiso para fusionar cambios, instalar software,
  ejecutar operaciones en Windows anfitrión o eliminar archivos.
- El resultado del SDK no equivale a pruebas aprobadas; los cambios deben
  verificarse por tests y revisión independiente.
- No modifica la conversación, SAI, CUA, voz, memoria, CRM ni pagos.

## Validación pendiente de completar
1. Estado de los checks del PR (se añade workflow aislado).
2. Suite general de JESSYCA y pruebas funcionales de Windows 11.
3. Desplegar sandbox aislado y ejecutar una tarea de ejemplo con OpenHands instalado.
4. Contrato de estado, cancelación, logs y presupuesto de tokens.
5. Integración con PermissionManager, RiskEngine y ExecutionVerifier del flujo
   real; no se debe activar sin estas comprobaciones.
6. Benchmark de ejecución y recuperación tras cancelaciones.

Para ejecutar solo la suite del proveedor:
`python -m unittest discover -s tests -p 'test_openhands_brain_provider.py' -v`
