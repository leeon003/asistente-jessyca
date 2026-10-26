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

## Seguimiento del 25-10-2026
- RiskEngine ahora recibe un `SecurityRequest` tipado, no una cadena suelta.
- PermissionManager debe aprobar la solicitud antes de invocar el runner.
- Suite del proveedor ampliada a 16 comprobaciones simuladas.
- GitHub Actions ejecuta la suite en Linux y Windows hospedado (pruebas Python, **no** automatización CUA/GUI).
- El SDK real no se ha ejecutado; requiere sandbox aislado ya desplegado, proveedor LLM configurado y validación de acciones internas. No se debe activar en el anfitrión Windows.
- No se ha demostrado equivalencia con un sandbox mediante validación de rutas, ni se ha ejecutado prueba integral del agente.

## Resultados CI comprobados (26-10-2026)
- Pruebas aisladas en `ubuntu-latest` y `windows-latest`: **PASS** (GitHub Actions 40270207179).
- SDK oficial `openhands-sdk==1.58.2` y `openhands-workspace==1.58.2` instalados durante el trabajo de CI.
- Smoke real de `DockerWorkspace`: **PASS**, comando `python -c 'print(12345)'` dentro del contenedor con `exit_code=0` (GitHub Actions 40270207230).
- No se ha validado el flujo extremo a extremo con LLM, permisos por cada acción interna, límites y cancelación, ni CUA en Windows.
- **No activar o fusionar como integración terminada mientras falten esas validaciones.**
