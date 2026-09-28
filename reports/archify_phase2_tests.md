# INFORME DE PRUEBAS — ARCHIFY FASE 2

**Sistema:** JESSYCA PC  
**Módulo:** Suite de Pruebas Archify (Fase 2 Controlled)  
**Fecha:** 2026-09-27  
**Resultado:** **34/34 PASSED (100% SUCCESS)**  
**Tiempo Total:** 0.58s  

---

## 1. RESUMEN DE EJECUCIÓN

La suite de pruebas de Archify fue ejecutada sobre la versión controlada del adaptador y de la skill, integrando las 11 pruebas de la Fase 1 y las 23 nuevas pruebas exhaustivas de la Fase 2:

```bash
pytest tests/archify/ -v
```

```text
tests/archify/test_archify_integration.py::test_01_health_check_detects_node_runtime PASSED [  2%]
tests/archify/test_archify_integration.py::test_02_validation_rejects_unsupported_diagram_type PASSED [  5%]
tests/archify/test_archify_integration.py::test_03_validation_accepts_valid_architecture_spec PASSED [  8%]
tests/archify/test_archify_integration.py::test_04_shadow_mode_observes_without_writing_file PASSED [ 11%]
tests/archify/test_archify_integration.py::test_05_active_mode_renders_valid_standalone_html PASSED [ 14%]
tests/archify/test_archify_integration.py::test_06_failure_injection_path_traversal_blocked PASSED [ 17%]
tests/archify/test_archify_integration.py::test_07_failure_injection_xss_sanitization PASSED [ 20%]
tests/archify/test_archify_integration.py::test_08_failure_injection_dos_limits_enforced PASSED [ 23%]
tests/archify/test_archify_integration.py::test_09_failure_injection_secrets_redacted PASSED [ 26%]
tests/archify/test_archify_integration.py::test_10_archify_lab_battery PASSED [ 29%]
tests/archify/test_archify_integration.py::test_11_archify_skill_execution_in_shadow_mode PASSED [ 32%]
tests/archify/test_archify_phase2_controlled.py::test_01_archify_modes_and_default PASSED [ 35%]
tests/archify/test_archify_phase2_controlled.py::test_02_certified_capabilities_render_html[architecture-Arquitectura JESSYCA Core] PASSED [ 38%]
tests/archify/test_archify_phase2_controlled.py::test_02_certified_capabilities_render_html[workflow-Flujo de Venta E-commerce] PASSED [ 41%]
tests/archify/test_archify_phase2_controlled.py::test_02_certified_capabilities_render_html[sequence-Secuencia Usuario \u2192 JDE \u2192 Verifier] PASSED [ 44%]
tests/archify/test_archify_phase2_controlled.py::test_02_certified_capabilities_render_html[dataflow-Flujo de Datos Open WebUI a Core] PASSED [ 47%]
tests/archify/test_archify_phase2_controlled.py::test_02_certified_capabilities_render_html[lifecycle-Ciclo de Vida de una Acci\u00f3n en JDE] PASSED [ 50%]
tests/archify/test_archify_phase2_controlled.py::test_03_unsupported_capability_rejected PASSED [ 52%]
tests/archify/test_archify_phase2_controlled.py::test_04_jde_capability_registry_integration PASSED [ 55%]
tests/archify/test_archify_phase2_controlled.py::test_05_ir_duplicate_node_ids_rejected PASSED [ 58%]
tests/archify/test_archify_phase2_controlled.py::test_06_ir_dangling_edge_references_rejected PASSED [ 61%]
tests/archify/test_archify_phase2_controlled.py::test_07_complexity_limits_nodes PASSED [ 64%]
tests/archify/test_archify_phase2_controlled.py::test_08_complexity_limits_edges PASSED [ 67%]
tests/archify/test_archify_phase2_controlled.py::test_09_security_xss_and_injection_sanitized PASSED [ 70%]
tests/archify/test_archify_phase2_controlled.py::test_10_security_path_traversal_blocked PASSED [ 73%]
tests/archify/test_archify_phase2_controlled.py::test_11_security_secrets_redacted_in_artifact PASSED [ 76%]
tests/archify/test_archify_phase2_controlled.py::test_12_idempotency_cache_reuse PASSED [ 79%]
tests/archify/test_archify_phase2_controlled.py::test_13_execution_verifier_validates_real_artifact PASSED [ 82%]
tests/archify/test_archify_phase2_controlled.py::test_14_execution_verifier_detects_tampered_or_empty_file PASSED [ 85%]
tests/archify/test_archify_phase2_controlled.py::test_15_archify_skill_controlled_execution PASSED [ 88%]
tests/archify/test_archify_phase2_controlled.py::test_16_archify_skill_fallback_to_mermaid_when_disabled PASSED [ 91%]
tests/archify/test_archify_phase2_controlled.py::test_17_mermaid_generation_action PASSED [ 94%]
tests/archify/test_archify_phase2_controlled.py::test_18_concurrency_multi_threaded_renders PASSED [ 97%]
tests/archify/test_archify_phase2_controlled.py::test_19_operational_rollback PASSED [100%]

============================= 34 passed in 0.58s ==============================
```

---

## 2. DETALLE POR CATEGORÍAS DE PRUEBA

### Categoría 1: Modos Operacionales y Gobernanza
* **Test 01:** Comprobó que el adaptador inicializa en `CONTROLLED` por omisión y permite la transición determinista entre `OFF`, `SHADOW`, `CONTROLLED` y `ACTIVE`.
* **Test 04:** Verificó el registro formal de las 5 capacidades en el `CapabilityRegistry` central de JDE, comprobando que se autorizan bajo el modo de autoridad `LIMITED`.

### Categoría 2: Capacidades Certificadas
* **Test 02 (x5):** Validó la compilación real de artefactos HTML independientes para:
  * `architecture`: Arquitectura JESSYCA Core.
  * `workflow`: Flujo de Venta E-commerce.
  * `sequence`: Secuencia Usuario → JDE → Verifier.
  * `dataflow`: Flujo de Datos Open WebUI a Core.
  * `lifecycle`: Ciclo de Vida de una Acción en JDE.
* **Test 03:** Comprobó que cualquier tipo desconocido o inventado (ej: `quantum_simulation`) es rechazado formalmente con `INVALID_DIAGRAM_SPEC`.

### Categoría 3: Validación Estructural de IR y Límites Anti-DoS
* **Test 05:** Comprobó que nodos con identificadores duplicados son invalidados de inmediato.
* **Test 06:** Comprobó que aristas con origen o destino hacia nodos no declarados son invalidadas de inmediato.
* **Test 07 (Límites de Nodos):**
  * 99 nodos: `VALID`
  * 100 nodos: `VALID`
  * 101 nodos: `REJECTED`
* **Test 08 (Límites de Aristas):**
  * 199 aristas: `VALID`
  * 200 aristas: `VALID`
  * 201 aristas: `REJECTED`

### Categoría 4: Seguridad y Sanitización
* **Test 09:** Inyección de payloads XSS (`<script>`, `<img onerror>`, `<iframe>`) verificando que quedan 100% neutralizados como entidades HTML.
* **Test 10:** Inyección de secuencias de Path Traversal (`../../`, `..\..\`, `C:\`, `/etc/`) verificando su bloqueo absoluto.
* **Test 11:** Presencia de credenciales y tokens en el JSON de entrada, verificando su redacción automática a `***REDACTED_SECRET***`.

### Categoría 5: Idempotencia y Reutilización de Artefactos
* **Test 12:** Verificó que dos solicitudes con la misma especificación normalizada retornan el mismo archivo físico, registrando `NEW_ARTIFACT` en la primera y `CACHE_HIT` en la segunda, incrementando la métrica `archify_cache_hits`.

### Categoría 6: Verificación Determinista Post-Ejecución
* **Test 13:** Comprobó que `ExecutionVerifier` inspecciona el archivo HTML en disco, validando `<!DOCTYPE html>`, `<svg id="archify-svg"`, tamaño > 0 y ausencia de secretos.
* **Test 14:** Comprobó que archivos vacíos (0 bytes) o corruptos (sin estructura SVG) son calificados como `VERIFICATION_FAILED` sin declarar falso éxito.

### Categoría 7: Skill y Fallback
* **Test 15:** Comprobó la ejecución de `ArchifySkill` en modo `CONTROLLED`, obteniendo el `ActionReceipt` y metadatos de verificación.
* **Test 16:** Comprobó que con Archify en `OFF`, la skill conmuta limpiamente a Mermaid (`fallback_provider = "mermaid"`).
* **Test 17:** Comprobó la generación directa de sintaxis Mermaid para secuencias (`sequenceDiagram`) y grafos (`graph TD`).

### Categoría 8: Concurrencia y Resiliencia
* **Test 18:** Ejecución concurrente mediante 10 hilos simultáneos (`ThreadPoolExecutor(max_workers=10)`), comprobando 0 colisiones de nombres de archivo y 100% de artefactos íntegros.
* **Test 19:** Verificación del mecanismo de Rollback: `CONTROLLED` (escribe) -> `SHADOW` (observa) -> `OFF` (bloquea) -> `CONTROLLED` (restaura operación).

---

## 3. CONCLUSIÓN

La batería de pruebas de Archify Fase 2 alcanza una cobertura total sobre todos los requisitos de integración controlada, seguridad y verificación física.
