# JESSYCA PC — ORCA + ADE FASE 3 ROLLBACK & KILL SWITCH REPORT

## PROCEDIMIENTOS DE ROLLBACK Y KILL SWITCH OPERACIONAL

### 1. Jerarquía de Rollback
La transición descendente de modos se encuentra plenamente validada y garantizada por `OrcaAdeAdapter`:
* `ACTIVE` -> `CONTROLLED` (Desactiva activación productiva, retorna a integración gobernada de pruebas)
* `CONTROLLED` -> `SHADOW` (Desactiva mutación de worktrees, solo evaluación pasiva sin efectos laterales)
* `SHADOW` -> `LAB` (Retorno a entorno de laboratorio aislado)
* `LAB` -> `OFF` (Desactivación total del subsistema)

### 2. Kill Switch Operacional Inmediato
* La invocación de `adapter.kill_switch()` establece inmediatamente `mode = OFF` y `status = DISABLED`.
* Limpia de forma síncrona la caché de tareas y aborta nuevas asignaciones.
* Garantiza la ausencia de procesos huérfanos o hilos colgados.
