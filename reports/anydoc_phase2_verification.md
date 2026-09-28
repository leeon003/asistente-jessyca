# JESSYCA PC — ANYDOC FASE 2
# REPORTE DE VERIFICACIÓN FÍSICA Y PROTECCIÓN ANTI-FALSE SUCCESS

**Módulo:** AnyDoc Execution Verifier & False-Success Protection  
**Fase:** Fase 2 — Controlled Integration  
**Fecha:** 2026-09-27  

---

## 1. PRINCIPIO DE VERIFICACIÓN FÍSICA

Bajo la arquitectura de JESSYCA PC, nunca se confía en la simple afirmación `"conversion completed"`. El sistema separa taxativamente:
1. `CLAIMED_SUCCESS`: Estado preliminar donde el motor técnico finalizó su cómputo.
2. `VERIFIED_SUCCESS`: Estado alcanzado únicamente tras la verificación determinista e independiente de la evidencia física en disco.
3. `VERIFICATION_FAILED`: Estado final si cualquiera de las condiciones físicas requeridas falla.

---

## 2. CONDICIONES OBLIGATORIAS DE VERIFICACIÓN

Para que una operación sea declarada `VERIFIED_SUCCESS`, el `ExecutionVerifier` comprueba:
* **Inmutabilidad de Entrada:** El hash SHA-256 del archivo de entrada debe ser exactamente idéntico antes y después del procesamiento.
* **Existencia del Output:** El archivo generado debe existir físicamente en el disco.
* **Archivo Regular:** Debe ser un archivo estándar, no un enlace simbólico, junction o directorio.
* **Confinamiento al Sandbox:** El path resuelto del output debe residir estrictamente en `data/anydoc/output/`.
* **No Vacío:** El tamaño en bytes del output debe ser mayor a cero (`size > 0`).
* **Validez del Formato:** La salida Markdown debe ser legible y estructurada.
* **Registro de Hashes:** El SHA-256 del output se calcula y se registra formalmente.

---

## 3. CASOS DE PRUEBA DE FALSO ÉXITO (FALSE-SUCCESS CASES)

| Escenario Adversarial | Simulación / Causa | Resultado Obtenido | Estado del Verifier |
|---|---|---|---|
| Salida no generada | Archivo ausente tras declarar éxito | `VERIFICATION_FAILED` | **PASS (Bloqueado)** |
| Salida vacía (0 bytes) | Fixture `empty.docx` | `MALFORMED` / `VERIFICATION_FAILED` | **PASS (Bloqueado)** |
| Salida fuera del sandbox | Intento de escritura en `../` | `SECURITY_BLOCKED` | **PASS (Bloqueado)** |
| Manipulación de entrada | Hash alterado durante el proceso | `VERIFICATION_FAILED` | **PASS (Bloqueado)** |
| Simulación forzada de fallo | Flag `simulate_verification_failure` | `VERIFICATION_FAILED` | **PASS (Bloqueado)** |

En todos los casos de falla de verificación, la emisión de recibos queda bloqueada y el orquestador no almacena el resultado en el caché de idempotencia.
