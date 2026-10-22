# Actualización del PR #1 — 2026-10-22

Rama: `audit/harness2-consolidation-20261021`. Continúa desde `d74bb3d16dfc920bdec19d1fca0798b7d9695c6f`. Sin fusión a main y sin cambios en JESSYCA CRM.

## Pendientes resueltos

- Empaquetado: descubrimiento explícito de paquetes, recursos de configuración y entrada `jessyca`. La wheel excluye datos, logs, tests y laboratorios; construcción y contenido comprobados.
- Dependencias: PyYAML base y extras separados `mcp`, `documents`, `voice`, `desktop`; httpx para pruebas. La distribución correcta de AnyDoc es `firecrawl-anydoc==0.2.4`.
- AnyDoc ausente: el módulo puede importarse y reporta UNAVAILABLE/UNSUPPORTED sin ejecutar ni escribir; health_check usa el contrato correcto y no declara salud incondicional.
- Seguridad de procesos: rechazo previo de PID 0, 1 y 4, sin consultar ni terminar procesos reservados.
- Rutas: las unidades Windows no se interpretan como nombres relativos en Linux.
- Lanzamiento Windows: se elimina la segunda invocación ShellExecute después de un Popen exitoso. Regresión reproducida antes y aprobada después con backend simulado; falta validación física en Windows.
- Autorización: identificadores nuevos mediante UUID evitan reutilizar la aprobación de otra acción creada en el mismo milisegundo. Los request_id explícitos conservan la idempotencia. Regresión con reloj congelado falla antes y pasa después.
- Prueba de medios: usa la misma instancia de logger que el agente, con restauración automática del mock.
- FastMCP: actualizado de 2.14.7 a 3.4.11. El escaneo inicial detectó CVE-2025-64340 y CVE-2026-27124 en FastMCP, y CVE-2025-69872 en diskcache. Se valida una instalación nueva para excluir metadatos residuales del entorno anterior.

## Validación y límites

Comandos reproducibles desde la raíz, con Python 3.12 en un entorno nuevo:

```sh
uv venv .venv
uv pip install --python .venv/bin/python '.[dev,mcp,voice,documents,desktop]'
uv pip check --python .venv/bin/python
.venv/bin/python -m pytest
python -m pip wheel --no-deps .
```

La línea base de esta continuación, con dependencias opcionales instaladas, fue 3486 aprobadas y 51 fallidas, sin errores de colección. La primera auditoría con dependencias incompletas registró 3311 aprobadas, 56 fallidas y 5 errores de colección: no son entornos equivalentes.

Resultado final en entorno nuevo: **3500 aprobadas, 45 fallidas, 0 errores de colección** (109,83 s); 36 pruebas dirigidas aprobadas. `uv pip check` pasa. `pip-audit` revisó 104 distribuciones sin vulnerabilidades conocidas; diskcache no forma parte de esta instalación nueva. La wheel se importa fuera del checkout. Una ejecución previa sin resultado completo no se contabiliza como éxito.

Resultados finales, lista completa de nodos fallidos y versiones en `reports/harness2_audit/update-results.json` y `update-environment.txt`. No se suprimen ni se convierten en skips los fallos previos. La suite aún no permite certificar el conjunto.

## Pendientes abiertos

- Resolver los fallos enumerados en el informe, distinguiendo contratos de aplicación/verificación de limitaciones del host. No se atribuyen automáticamente todos a Linux.
- Validar escritorio y sesiones interactivas Windows, GUI, audio y dispositivos reales; PortAudio no está disponible aquí.
- Ejecutar la receta Docker de Harness² en un host con Docker. Se conserva el laboratorio aislado y desactivado; un venv no equivale a sandbox.
- Diseñar y revisar un adaptador productivo de tareas JESSYCA para Harness² antes de habilitar cualquier aplicación automática de cambios. La demo determinista previa no acredita operación con modelos reales.
- El escaneo de vulnerabilidades cubre las versiones instaladas en Linux y la base consultada; no certifica extras Windows ni ausencia de vulnerabilidades desconocidas.

No se eliminan módulos adicionales por falta de alcanzabilidad estática. La eliminación obsoleta demostrada sigue siendo la documentada en la auditoría original.
