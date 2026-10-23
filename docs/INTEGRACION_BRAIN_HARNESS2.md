# Integración de Brain/Aurora con la auditoría Harness²

Fecha: 2026-10-22. Base Brain `2513456`, auditoría `ad1b7bf`.

La rama de auditoría parte de un historial anterior a Brain/Aurora. Esta integración conserva ambos historiales; no reemplaza Brain por la rama del PR #1.

## Resolución de conflictos

- Configuración: se conserva íntegra la versión de Brain; ya había eliminado los campos duplicados.
- AnyDoc: se conservan confinamiento de rutas y backend Docling. La ausencia de firecrawl-anydoc no bloquea Docling disponible; el fallo de Docling se conserva si no existe motor alternativo. Importaciones internas rotas no se ocultan como dependencia ausente. Estado de salud condicionado al backend y al ciclo de vida.
- Orquestador: conserva el confinamiento estricto y admite importación sin AnyDoc.
- ComputerUseAdapter: constructor sin mutación global de FAILSAFE; mantiene el resto de mejoras de Brain.
- Dependencias: unión de extras, conservando faster-whisper, PyAudio y bibliotecas Office; FastMCP 3.4.11. Se elimina la segunda declaración redundante de requests.
- Empaquetado: conserva los recursos estáticos de Aurora además de configuración.
- tools/registry.py: se conserva el shim modificado por Brain. La eliminación demostrada en la base antigua no se aplica automáticamente a esta variante. El registro canónico sigue siendo tools.tool_registry.

## Evidencia

En Linux, pruebas dirigidas antes: 153 aprobadas y 1 omitida; después con regresiones nuevas: 163 aprobadas y 1 omitida. Otras 3 regresiones de auditoría pasan. Brain/Aurora: 70 aprobadas y 14 fallidas antes y después, exactamente los mismos nodos fallidos. Wheel construida con index.html y continuous_voice.js de Aurora presentes.

El usuario informó 7 pruebas de aceptación aprobadas en Windows antes de integrar. La suite Windows completa no terminó: quedan incidencias Office y detección intermitente de Calculadora. No se certifica operación completa ni se ocultan estos pendientes.

Resultados: `reports/harness2_audit/brain-integration-results.json`.

## Aplicación local

Las modificaciones sin commit del Windows del usuario no están en esta rama. Deben guardarse en un stash adicional antes del avance fast-forward y reaplicarse conservando el stash. Si aparece un conflicto, se revisa sin descartar ninguna versión. Después se valida instalación y pruebas en su venv de Python 3.11.

La rama principal, JESSYCA CRM y los servicios comerciales no se modifican. Harness² sigue en lab/harness2, experimental y separado del runtime.
