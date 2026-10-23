# Auditoría integral del checkout y preparación aislada de Harness²

Fecha: 2026-10-21. Continuación del PR #1, sobre
`f10dbcbad76556822330ad15e7251edac06fe2fc`, rama
`audit/harness2-consolidation-20261021`. No se modifica ni fusiona `main`.
JESSYCA CRM, RAMY y WhatsApp quedan fuera del alcance y sin cambios.

> Informe histórico de la primera pasada. Empaquetado, dependencias y pruebas posteriores se actualizan en [ACTUALIZACION_PENDIENTES.md](ACTUALIZACION_PENDIENTES.md).

## Alcance y conclusión

Se obtuvo el checkout completo: **1.359 archivos versionados, 1.112 archivos Python**,
sin errores sintácticos AST. Se revisaron manifiestos, importaciones, cargas dinámicas,
puntos de entrada, configuración, colisiones y pruebas. El inventario por módulo y
sus importaciones internas está en `reports/harness2_audit/modules-before.csv`;
los candidatos de dependencias externas, con todos sus consumidores, en `static-before.json`.
`python scripts/audit_repository.py` reproduce el grafo completo sin importar JESSYCA.

Esto es una auditoría estática global y ejecución de pruebas en Linux/Python 3.12.14,
no una certificación funcional de Windows, audio, Ollama ni control físico del PC.
La alcanzabilidad estática incluye imports condicionales y no demuestra activación.
Los módulos sin caminos estáticos NO se consideran obsoletos automáticamente.

No hay `.gitmodules` ni submódulos Git registrados en el checkout. Las integraciones
son código/adaptadores dentro del proyecto; no corresponde borrar repositorios
externos basándose en sus nombres. Tampoco hay pares de archivos Python idénticos
no triviales (>100 bytes) en la línea base.

## Hallazgos y cambios aplicados

| Evidencia | Acción | Verificación |
|---|---|---|
| `tools/registry.py` colisiona con `tools/registry/__init__.py`; `PathFinder` elige el paquete. Este reexporta `tools.tool_registry`. El descubridor excluye `registry.py`; no hay carga explícita de su ruta en el código revisado. | Retirar solo `tools/registry.py` y corregir enlace de documentación. | Identidad de clase y singleton público/canónico; pruebas de integración del registro. |
| `AppSettings` declara dos veces `MODEL_ROUTER_ENABLED`, `MODEL_ROUTER_MODE`, `ROUTER_CONFIDENCE_THRESHOLD`, `ROUTER_SHADOW_LOG_FILE` y `NEMOTRON_ENABLED`. | Retirar las primeras declaraciones, ya sobrescritas al construir la clase. Conservar las últimas, incluidos sus metadatos. | Valores efectivos conservados: false, shadow, 0.8, logs/router_shadow.jsonl, false. AST sin campos repetidos. |
| Constructor de `ComputerUseAdapter` cambia globalmente `pyautogui.FAILSAFE=False`; el registro crea el adaptador incluso si su configuración lo deshabilita. | Eliminar la importación y mutación del constructor. No imponer un nuevo valor global. | Regresión con módulo simulado: antes falla; después conserva `FAILSAFE=True`. |
| `core/llm/inference.py` importa `requests` incondicionalmente, pero el manifiesto no lo declara; bloqueó incluso `conftest.py`. | Añadir `requests>=2.31.0` a dependencias base. | Suite logra colección tras instalarlo. |
| El README raíz declarado en `pyproject.toml` no existe. | Apuntar a `Documentos/README.md`, que sí está versionado. | Comprobación de ruta; persiste otro bloqueo de empaquetado detallado abajo. |

El archivo retirado es recuperable desde el commit base. No se eliminan memorias,
datos de usuario, suites, buses, planificadores, adaptadores opcionales ni historial.

## Matriz de componentes

| Componente | Evidencia de uso / estado | Decisión |
|---|---|---|
| `main.py`, `server/`, `interfaces/modo_voz.py`, `core/local_agent/local_agent.py` | Entradas explícitas; modo demo crea agente y servidor e inicia voz. Importar `core` provoca muchas importaciones y registros. | Conservar; revisar efectos de importación en una fase separada. |
| `tools/tool_registry.py`, `tools/registry/` | Registro canónico y paquete de herramientas del Registro Windows; alias público comprobado. | Conservar ambos. |
| `server.py` y `server/` | Segunda colisión. Archivo descrito como compatibilidad y referenciado por documentación de desarrollo; paquete es la resolución normal. | Conservar: no se demostró ausencia de consumidores externos. |
| `core/event_bus.py` y `core/bus.py` | Contratos diferentes: eventos por nombre/prioridad frente a eventos tipados/awaitables. Consumidores reales en servidor y orquestador/integraciones. | Conservar; no son intercambiables. |
| `core/planner.py`, `core/tool_planner/`, `core/dialogue/action_planner.py` | Plan general, plan declarativo controlado y planificación conversacional; consumidores y pruebas separados. | Conservar; semejanza funcional no demuestra duplicación eliminable. |
| `core/memory/`, `core/memory_retriever.py`, `core/memory_consolidation.py` | Persistencia, control de acceso, recuperación y consolidación tienen responsabilidades diferentes. | Conservar sin migrar datos. |
| `core/jde/`, `core/execution/`, `core/security*` | Decisión, ejecución/verificación y seguridad no equivalen a optimización de harness. JDE por defecto CONTROLLED. | Conservar; Harness² no los sustituye. |
| `core/integration/adapters/{jarvis,are,computer_use}_adapter.py` | Configuración de adapters deshabilitada por defecto. Hub disponible; no se encontraron llamadas a `get_integration_hub` desde main/interfaces/local_agent. | Disponibles, no afirmar activos en producción; no borrar. |
| `core/anydoc/`, `core/archify/`, `core/orca_ade/` | Integraciones con suites propias. AnyDoc requiere importación externa ausente. | Conservar; reparar instalación/aislamiento por separado. |
| `core/action_execution_bridge.py` | Reexportación explícita de compatibilidad. | Conservar. |
| `lab/harness2/` | Nuevo laboratorio independiente, sin imports del runtime ni registro en el hub. | Desactivado, solo demo sintético y revisión de contadores. |

La configuración en código no revela las variables `.env` del PC del usuario.
No se confirma que estos valores sean los efectivos en su Windows.

## Dependencias, empaquetado y riesgos pendientes

- `pyproject.toml` es el manifiesto de aplicación; `Documentos/requirements.txt`
  contiene una lista menor y no es una instalación completa. No se elimina porque
  es documentación, no una dependencia obsoleta demostrada.
- No hay lockfile. Se preservan las versiones exactas del entorno de pruebas en
  `reports/harness2_audit/test-environment.txt`; no representan un lock soportado
  para Windows ni una receta de producción.
- Faltan dependencias/capas opcionales: `anydoc`, `speech_recognition`, `pyautogui`,
  `fastmcp`, TTS y otras. El inventario recoge 34 raíces externas (candidatos, no
  necesariamente 34 distribuciones PyPI; p. ej. `PIL` corresponde a Pillow).
- `anydoc` se importa incondicionalmente en `core/anydoc/adapter.py`. Bloquea cuatro
  archivos de prueba aunque la integración no se esté usando. No se instala un
  paquete homónimo sin verificar procedencia/API del binding Rust esperado.
- `fastmcp` falta: `server/app.py` permite que la aplicación siga sin instancia real
  de FastMCP, y las pruebas que la requieren fallan. El paquete `mcp` instalado
  durante el diagnóstico no sustituye `fastmcp`.
- `pip check` del venv: sin dependencias instaladas incompatibles. Esto NO acredita
  que estén presentes todas las dependencias opcionales de la aplicación.
- La construcción de wheel sigue fallando por descubrimiento automático de múltiples
  paquetes raíz (`core`, `server`, `services`, etc.). Se requiere definir explícitamente
  el contenido distribuible y probar recursos de voz/configuración antes de publicarlo.
- Hay pruebas no herméticas: acceden a hardware, procesos reales y archivos de datos
  del checkout; modificaron resultados de benchmarks, reportes, sesiones y tareas.
  Esas modificaciones generadas se descartan de este PR; no son cambios de producto.
- Las pruebas de rutas absolutas Windows y PID 4 no son portables a Linux. También
  quedan fallos de apertura de aplicaciones, contratos/estados de verificación y
  reproducción/voz. No se atribuyen todos a dependencias sin una revisión específica.
- No se realizó un escaneo CVE de todos los extras ni se validaron sus licencias
  transitivas. El informe no certifica ausencia de vulnerabilidades.

## Validación

| Ejecución | Pasan | Fallan | Errores de colección |
|---|---:|---:|---:|
| Antes | 3311 | 56 | 5 |
| Después, repetición del mismo comando | 3314 | 56 | 5 |
| Pruebas centradas en los cambios, después | 22 | 0 | 0 |
| Contrato aislado Harness² (unittest) | 4 | 0 | 0 |

La primera pasada posterior produjo 7 fallos adicionales de consulta de PID en psutil.
La repetición del comando original volvió al conjunto exacto de fallos de la línea
base. Se conservan ambas mediciones; no se oculta la variabilidad del entorno.

Resultados detallados y nombres de fallos en `reports/harness2_audit/test-results.json`.
Los comandos equivalentes usan el mismo venv y los mismos paquetes antes/después:

```sh
python -m pytest
python -m pytest --continue-on-collection-errors
python -m pytest tests/test_audit_regressions.py tests/test_config.py \
  tests/test_integration_hub.py tests/test_server_registry_integration.py \
  tests/server/test_registry_integration.py
python -m unittest discover -s lab/harness2 -p 'test_*.py'
```

La primera ejecución normal queda detenida con 5 errores de colección. Se utiliza
`--continue-on-collection-errors` para medir las pruebas que sí pueden recopilarse,
sin ocultar ni marcar como omitidos los errores. Las regresiones nuevas se probaron
contra el código original: 2 fallaron y 1 pasó; después pasan las 3.

## Harness²: límite de esta entrega

Upstream verificado: https://github.com/google-research/harness2, commit
`1cfe254e8d25b15f37048c3730134686abe60335`, Apache-2.0. Su Python >=3.12,<3.14/POSIX
requiere separar entorno y proceso del asistente Windows >=3.11. No se importó en
JESSYCA ni se instaló en su venv. No se presupone compatibilidad con Ollama/Qwen/Gemma.

Demo oficial determinista ejecutado en venv/directorio independientes, sin credenciales:
2 tareas, 0 fallidas, 14 ejecuciones y 16 llamadas a editor local, ambos modos de
recursión con k=1. No demuestra mejora en tareas JESSYCA ni usa un LLM.
`lab/harness2/review.py` valida solamente métricas; nunca aplica scripts, prompts,
guardrails ni memorias. Requiere opt-in y mantiene `production_ready=false`.

Se preparó Dockerfile y comando de ejecución sin red, sin mounts, sin privilegios,
con límites de memoria/CPU/PIDs. Docker no está disponible aquí: esa barrera queda
pendiente de prueba. Un venv separa dependencias, pero no es un sandbox de seguridad.

Para habilitar tareas reales faltan: fixtures sintéticos representativos de JESSYCA,
comparación objetiva contra la línea base, adaptador de evaluación de propuestas,
aprobación de cambios individuales y validación Windows. No activar aprendizaje
sobre datos reales ni retirar otros módulos hasta completar esas pruebas.
