# JESSYCA BRAIN 1.0 — FASE 5: PLAN DE RETIRADA Y PROCEDIMIENTO DE ROLLBACK

**Fecha:** 16 de Octubre de 2026  
**Rama de Trabajo:** `feature/jessyca-brain-1.0`  
**Estado:** Probado y reversible sin impacto en producción

---

## 1. PRINCIPIO DE NO AFECTACIÓN EN PRODUCCIÓN

La Fase 5 fue desarrollada bajo una estricta política de **aislamiento progresivo**:
1. La bandera global `USE_JESSYCA_BRAIN` permanece en `False` en `config/settings.py`.
2. Las peticiones habituales del asistente continúan canalizándose por la arquitectura tradicional de agentes y herramientas.
3. El subsistema cognitivo y de aprendizaje reside en bases de datos y módulos desacoplados:
   - Base de datos cognitiva: `data/memory_brain.db` (aislada de `data/sessions.db`).
   - Módulos nuevos: `core/cognitive_brain/procedure_learning_engine.py`.

---

## 2. PROCEDIMIENTO DE ROLLBACK OPERATIVO (SIN REVERSIÓN DE CÓDIGO)

Si se detectara alguna anomalía en las pruebas de aprendizaje procedimental, la mitigación es inmediata:

### Paso 1: Confirmar bandera global desactivada
Verificar que en `config/settings.py`:
```python
USE_JESSYCA_BRAIN = False
```
Con este valor, ningún componente de `JessycaBrain` ni `ProcedureLearningEngine` es invocado durante el uso cotidiano de JESSYCA.

### Paso 2: Limpieza o reseteo de procedimientos aprendidos
Si un procedimiento corrupto o no deseado quedara registrado en la memoria procedimental de pruebas:
```powershell
# En PowerShell desde la raíz del proyecto:
python -c "import sqlite3; conn = sqlite3.connect('data/memory_brain.db'); conn.execute('DELETE FROM procedures WHERE state != \"VALIDATED\"'); conn.commit(); conn.close(); print('Procedimientos no validados eliminados')"
```
O bien, restablecer la base de datos de pruebas a partir del backup limpio:
```powershell
Copy-Item "data/backups/memory_brain_clean.db" "data/memory_brain.db" -Force
```

---

## 3. PROCEDIMIENTO DE ROLLBACK DE CÓDIGO (GIT)

Si fuera necesario revertir completamente los cambios introducidos en la Fase 5:

### Paso 1: Comprobar el estado del repositorio
```powershell
git status
```

### Paso 2: Revertir los commits específicos de Fase 5
```powershell
# Identificar el commit base de Fase 4:
git log -n 5 --oneline

# Si se desea descartar los cambios no confirmados:
git restore core/cognitive_brain/contracts.py core/cognitive_brain/memory_engine.py core/cognitive_brain/brain_orchestrator.py core/cognitive_brain/__init__.py
git clean -fd tests/cognitive_brain/test_procedure_learning_engine.py core/cognitive_brain/procedure_learning_engine.py
```

### Paso 3: Verificar integridad del asistente clásico
Ejecutar la suite de regresión completa de aceptación:
```powershell
pytest tests/acceptance/test_fase7_acceptance_30_scenarios.py -v
```
**Criterio de éxito:** Los 31 escenarios de aceptación deben reportar `PASSED`.

---

## 4. MATRIZ DE RIESGOS Y ACCIONES DE CONTENCIÓN

| Incidente Posible | Causa Raíz | Acción de Contención Inmediata |
| :--- | :--- | :--- |
| Procedimiento en bucle de reintentos | Error de UI no controlado | Invocar parada de emergencia (`cancel_current_task()`); restablece el token y mata el subproceso. |
| Coincidencia errónea de intención | Intención genérica asociada | Cambiar estado a `DEPRECATED` en `ProceduralMemory`; el motor volverá a planificar desde cero. |
| Incompatibilidad tras actualización de app | Cambio de interfaz de Windows | `learn_from_failure` degrada a `TESTING` tras 2 fallos consecutivos. |
