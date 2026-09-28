# JESSYCA PC — ANYDOC FASE 2
# REPORTE DE IDEMPOTENCIA Y SEGURIDAD DEL CACHÉ

**Módulo:** AnyDoc Idempotency Guard & Cache Security  
**Fase:** Fase 2 — Controlled Integration  
**Fecha:** 2026-09-27  

---

## 1. HUELLA CANÓNICA DE IDEMPOTENCIA (FINGERPRINTING)

Para evitar trabajo duplicado, colisiones entre contratos distintos y efectos colaterales innecesarios, AnyDoc calcula una huella SHA-256 canónica:

$$\text{Fingerprint} = \text{SHA-256}(\text{JSON\_SORTED}(\text{input\_hash}, \text{operation}, \text{allowed\_actions}, \text{anydoc\_version}, \text{input\_format}, \text{output\_path}, \text{requires\_review}))$$

Propiedades garantizadas:
1. **Determinismo:** Mismos parámetros y mismo contenido del archivo generan exactamente la misma huella.
2. **Sensibilidad a Cambios:** Modificar un solo byte del archivo de entrada altera `input_hash` y produce una huella totalmente nueva, forzando una re-ejecución limpia.
3. **Diferenciación Operacional:** Contratos con distinta operación (por ejemplo `convert` vs `extract_assets`) sobre el mismo archivo tienen huellas distintas, impidiendo colisiones entre conversiones y extracciones.

---

## 2. COMPORTAMIENTO IDEMPOTENTE DEMOSTRADO

* **Primera Invocación (`EXECUTE`):**
  * Se lee el documento, se realiza la conversión/inspección completa.
  * Se verifican las condiciones físicas del output.
  * El resultado verificado se almacena en el caché de idempotencia.
* **Invocaciones Subsiguientes (`CACHE_HIT`):**
  * La búsqueda por huella encuentra el resultado previo verificado.
  * Se devuelve el resultado de inmediato sin invocar al motor AnyDoc (`duplicate work = 0`).
  * No se re-escribe el archivo de salida (`duplicate side effects = 0`).
  * Latencia de respuesta: reducida a menos de 1 ms.

---

## 3. SEGURIDAD DEL CACHÉ

* **Confinamiento:** Todo artefacto de caché se encuentra restringido a `data/anydoc/cache/`.
* **Anti-Poisoning:** Solo se almacenan en caché resultados que hayan obtenido el estado `VERIFIED_SUCCESS`. Las operaciones fallidas, denegadas o bloqueadas por seguridad jamás ingresan al caché.
* **Aislamiento Multi-Ruta:** Rutas distintas para la salida generan fingerprints distintos, impidiendo colisiones accidentales o intencionadas entre salidas de usuario.
