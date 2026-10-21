# Auditoría de consolidación: JESSYCA + Harness²

Estado: **exploratorio, sin integración ni eliminación automática**.

## Alcance

Este repositorio corresponde a JESSYCA Asistente para Windows. No incluir Tiendas RAMY, CRM, pagos ni WhatsApp.

## Evidencia inicial (21-10-2026)

- La rama principal contiene un `pyproject.toml` que declara Python >=3.11, paquete `jessyca-windows-mcp`, FastAPI y pytest como dependencia de desarrollo.
- La obtención de `README.md` en la raíz devolvió 404 a través del conector; verificar si el archivo fue movido antes de corregir `pyproject.toml`.
- No hay evidencia suficiente de conflictos de importación, procesos duplicados o módulos obsoletos: no interpretar coincidencias de nombres como prueba.
- Se incorporó `scripts/audit_harness2_overlap.py` como herramienta de inventario **de solo lectura**.

## Ejecución sugerida

```powershell
python scripts/audit_harness2_overlap.py --json > audit_harness2_inventory.json
python -m pytest -q
```

El inventario generado es información diagnóstica; revisar datos sensibles antes de publicarlo.

## Condiciones previas a retirar módulos

1. Obtener el árbol completo y el grafo de importaciones de JESSYCA.
2. Verificar qué componentes ejecutan realmente voz, archivos, navegación, planificación, memoria, control Windows y validación de acciones.
3. Identificar implementaciones equivalentes mediante contratos y pruebas funcionales, no solo nombres de archivo.
4. Mantener una única interfaz pública por capacidad; reemplazar llamadas internas gradualmente.
5. Crear pruebas de regresión para abrir/reproducir archivos locales sin redireccionamientos no solicitados, evitar eco de instrucciones y reanudar tareas desde memoria.
6. Habilitar cualquier experimentación Harness² solo en un entorno aislado, con acciones simuladas, límites de recursos, registros y revisión explícita de cambios.
7. Ejecutar pruebas después de cada sustitución; retirar módulos solamente cuando no tengan consumidores y existan alternativas verificadas.
8. Guardar copia recuperable y aplicar cambios mediante PR, sin borrar historial ni modificar `main` directamente.

## Integración propuesta

`JESSYCA Core -> interfaz ImprovementEvaluator -> Harness2Adapter (desactivado por defecto)`

El adaptador debe recibir tareas de evaluación sin credenciales y devolver recomendaciones validadas, nunca ejecutar automáticamente cambios en el sistema operativo. CUA/SAI y el controlador Windows permanecen separados. No se presupone compatibilidad directa entre Harness² y Ollama/Qwen/Gemma.

## Pendientes

- Inventario y métricas ejecutadas sobre un checkout completo (aún no ejecutados).
- Matriz de módulos: **conservar / consolidar / sustituir / retirar** con rutas y referencias verificables.
- Comprobación de compatibilidad de licencia, APIs y dependencias del upstream Harness².
- CI y pruebas Windows en un entorno controlado.
