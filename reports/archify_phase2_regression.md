# INFORME DE REGRESIÓN GLOBAL — ARCHIFY FASE 2

**Sistema:** JESSYCA PC  
**Módulo:** Suite Global de Regresión (JDE + Archify)  
**Fecha:** 2026-09-27  
**Estado:** **PASS — ZERO REGRESSIONS**  

---

## 1. COMPARATIVA CONTRA EL BASELINE DE FASE 1

| Métrica | Baseline Fase 1 | Resultado Fase 2 | Variación |
| :--- | :---: | :---: | :---: |
| **Tests de Archify** | 11 passed | 34 passed | +23 tests |
| **Tests de JDE** | 227 passed | 227 passed | 0 (Estabilidad 100%) |
| **Total Tests Combinados** | **238 passed** | **261 passed** | **+23 tests (100% PASS)** |
| **Fallos (Failures)** | 0 | 0 | 0 |
| **Errores (Errors)** | 0 | 0 | 0 |
| **Regresiones Detectadas** | 0 | 0 | 0 |

---

## 2. DESGLOSE DETALLADO POR MÓDULOS DE PRUEBA

### A. Módulos de Archify (34 Tests)
* `tests/archify/test_archify_integration.py`: 11 passed (Suite fundacional de Fase 1).
* `tests/archify/test_archify_phase2_controlled.py`: 23 passed (Suite de activación controlada, límites, seguridad, idempotencia, verificación y concurrencia).

### B. Módulos de JDE (227 Tests)
* `tests/jde/test_decision_engine.py`: 10 passed
* `tests/jde/test_false_success_regressions.py`: 7 passed
* `tests/jde/test_phase3a_false_success_fixes.py`: 7 passed
* `tests/jde/test_phase3b_critical_verification.py`: 12 passed
* `tests/jde/test_phase3c_consolidation.py`: 18 passed
* `tests/jde/test_phase4_authority.py`: 31 passed
* `tests/jde/test_phase5_canary.py`: 35 passed
* `tests/jde/test_phase6_limited.py`: 38 passed
* `tests/jde/test_phase7_progressive.py`: 37 passed
* `tests/jde/test_phase8_full_authority.py`: 18 passed
* `tests/jde/test_shadow_integration.py`: 10 passed
* `tests/jde/test_shadow_mode.py`: 4 passed

---

## 3. CONFIRMACIÓN DE INVARIANTES Y CONTRATOS

1. **Anti-False Success:** Ninguna modificación alteró la regla `No evidence = No success claim`.
2. **Autoridad de Decisión:** JDE continúa siendo la única autoridad de decisión; Archify se mantiene como proveedor pasivo de compilación visual.
3. **Contención y Aislamiento:** La incorporación de capacidades en `CapabilityRegistry` respeta el nivel de autoridad `LIMITED`, sin conceder privilegios destructivos ni de modificación del sistema.
4. **Retrocompatibilidad:** La tupla de retorno de `render_diagram` mantiene total compatibilidad con las firmas anteriores `(success, msg, path)`.

---

## 4. CONCLUSIÓN FINAL

La Fase 2 de Archify se consolida sin introducir ninguna regresión técnica ni de seguridad en el ecosistema JESSYCA PC.
