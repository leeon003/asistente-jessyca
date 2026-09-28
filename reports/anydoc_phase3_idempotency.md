# AnyDoc Fase 3 — Auditoría de Idempotencia y Cache

## 1. Huella Criptográfica Canónica

La idempotencia en AnyDoc se garantiza calculando una huella SHA-256 única y determinista para cada tarea:

```text
Fingerprint = SHA256(
    input_hash +
    operation +
    sorted(allowed_actions) +
    anydoc_version +
    input_format +
    output_path +
    requires_review
)
```

---

## 2. Validación de Cache y Prevención de Envenenamiento

- **Ejecución Inicial**: Se procesa el documento y el resultado verificado se indexa bajo su huella canónica (`CACHE MISS`).
- **Segunda Ejecución (Mismos parámetros)**: Se detecta la huella en memoria y se retorna el resultado verificado instantáneamente con `metadata.cache_hit = true` (`CACHE HIT`).
- **Aislamiento**:
  - Un cambio en el contenido del archivo de entrada altera su `input_hash`, generando una huella diferente y forzando una nueva ejecución.
  - Una alteración en la operación (e.g. `convert` vs `inspect`) genera huellas disjuntas.
  - Un resultado con falla de verificación jamás se almacena en el cache de idempotencia.
