# JESSYCA PC — ORCA + ADE FASE 3 IDEMPOTENCY REPORT

## CERTIFICACIÓN DE IDEMPOTENCIA CRIPTOGRÁFICA

### 1. Cálculo Canónico del Fingerprint
Cada contrato de tarea `OrcaTaskContract` genera una huella criptográfica SHA-256 única computada sobre:
* `objective`: Objetivo de la tarea normalizado
* `workspace`: Ruta canónica del espacio de trabajo
* `allowed_actions`: Lista ordenada y canónica de acciones permitidas
* `forbidden_actions`: Lista ordenada y canónica de acciones prohibidas
* `timeout_seconds`: Tiempo límite de ejecución
* `requires_review`: Bandera de revisión

### 2. Comportamiento en Reejecución
* **Primer Despacho:** La tarea se procesa y ejecuta formalmente; el resultado se almacena en la caché de idempotencia.
* **Segundo Despacho Idéntico:** El orquestador detecta la coincidencia exacta de huella SHA-256 y emite inmediatamente `CACHE_HIT` con metadatos de idempotencia, sin generar procesos adicionales, sin crear worktrees duplicados y sin efectos colaterales.
* **Mutación de Parámetros:** Si se modifica cualquier parámetro (incluso un solo caracter del objetivo), el fingerprint varía y se genera una nueva ejecución independiente.
