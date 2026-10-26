# OpenHands para JESSYCA Asistente — fase 1

## Estado
Bridge de descubrimiento seguro implementado, desactivado por defecto.
**NO constituye una integración funcional de ejecución de tareas de OpenHands.**
No se modifica JESSYCA BRAIN, controlador Windows, voz, CRM ni pagos.

## Arquitectura objetivo
JESSYCA (orquestador existente) → aprobaciones → interfaz de tareas de programación → OpenHands Agent Server en sandbox → resultados verificados → revisión humana.

La interfaz Python `integrations.openhands_bridge.OpenHandsBridge` solo comprueba conectividad con un servidor de API OpenHands mediante `/openapi.json` en loopback. No invoca tareas, no ejecuta comandos ni obtiene acceso al disco. Requiere configuración `enabled=True` explícita y no se conecta al arranque.

## Verificaciones
`python -m unittest -v tests.test_openhands_bridge`
La suite aislada contiene 6 pruebas: desactivación, rechazo de redes externas y credenciales en URL, timeout, disponibilidad, offline e incompatibilidad de API. Estas pruebas se ejecutaron en un entorno Python aislado antes de publicar la propuesta; la suite general del repositorio y las pruebas en Windows están pendientes.

## Siguiente fase antes de activar acciones
1. Auditar de forma completa imports, controladores y rutas de tareas existentes para descartar agentes duplicados.
2. Ejecutar OpenHands en sandbox Docker independiente con volumen restringido a una copia de trabajo sin secretos.
3. Integrar cliente autenticado para la versión *exacta* de Agent Server instalada. Probar endpoints contra OpenAPI real, sin asumir rutas.
4. Agregar límites de tiempo/costo/recursos, aprobación para escritura/comandos, pruebas de regresión y rollback.
5. Integrar con orquestador JESSYCA mediante feature flag y confirmar que no afecta STT/TTS ni rutas locales de usuario.
6. Validar en Windows 11, después abrir PR para habilitación; no integrar la fuente completa del upstream dentro del monorepo.

## Beneficios potenciales (no confirmados)
Edición de código, análisis de errores, pruebas de software y refactorizaciones asistidas. No mejora por sí solo la velocidad del diálogo, el modelo LLM, la voz o la memoria persistente.

Upstream: https://github.com/OpenHands/software-agent-sdk
Documentación: https://docs.openhands.dev/sdk
