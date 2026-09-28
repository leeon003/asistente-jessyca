# JESSYCA PC — ANYDOC FASE 2
# REPORTE DE CONCURRENCIA Y CARGA PARALELA

**Módulo:** AnyDoc Concurrency & Resource Isolation  
**Fase:** Fase 2 — Controlled Integration  
**Fecha:** 2026-09-27  

---

## 1. NIVELES DE CONCURRENCIA EVALUADOS

Se ejecutaron baterías de procesamiento concurrente mediante hilos de trabajo independientes (`ThreadPoolExecutor`):

* **1 Documento:** Línea base secuencial.
* **2 Documentos simultáneos:** Concurrencia dual.
* **5 Documentos simultáneos:** Carga media concurrente.
* **10 Documentos simultáneos:** Carga pesada concurrente.

---

## 2. RESULTADOS Y COMPORTAMIENTO MEDIDO

| Nivel de Concurrencia | Tareas Despachadas | Tareas Exitosas | Colisiones de Output | Colisiones de Caché | Procesos Huérfanos |
|---|---|---|---|---|---|
| **1 doc** | 1 | 1 (100%) | 0 | 0 | 0 |
| **2 docs** | 2 | 2 (100%) | 0 | 0 | 0 |
| **5 docs** | 5 | 5 (100%) | 0 | 0 | 0 |
| **10 docs** | 10 | 10 (100%) | 0 | 0 | 0 |

---

## 3. MONITOREO DE RECURSOS

* **CPU & RAM:** Carga distribuida eficientemente en subprocesos aislados sin picos anómalos.
* **VRAM (GPU):** 0 MB consumidos en la tarjeta gráfica RTX 3060 12GB (AnyDoc opera íntegramente en CPU y memoria del sistema).
* **Integridad de Salidas:** Cada hilo operó sobre su propia ruta aislada dentro de `data/anydoc/output/` sin sobrescrituras cruzadas.
* **Condiciones de Carrera (Race Conditions):** Ausencia total de deadlocks o bloqueos mutuos.
