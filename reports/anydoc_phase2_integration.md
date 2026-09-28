# JESSYCA PC — ANYDOC FASE 2
# REPORTE DE INTEGRACIÓN CONTROLADA Y PROCESAMIENTO DOCUMENTAL GOBERNADO

**Módulo:** AnyDoc Integration & Capability Provider  
**Fase:** Fase 2 — Controlled Integration  
**Modo Certificado:** `ANYDOC_MODE=CONTROLLED`  
**Autoridad:** JESSYCA Decision Engine (JDE)  
**Fecha:** 2026-09-27  

---

## 1. RESUMEN EJECUTIVO

Se completó de forma exitosa y exhaustiva la **Fase 2 (Controlled Integration)** de **Firecrawl AnyDoc** en JESSYCA PC.
AnyDoc ha sido configurado estrictamente bajo el principio inviolable de **Autoridad Única del JDE**. AnyDoc opera exclusivamente como un motor de procesamiento documental subordinado, sin capacidad de auto-autorización ni de emisión de órdenes al sistema.

Todas las operaciones se ejecutan mediante contratos inmutables `AnyDocTaskContract` sellados criptográficamente (SHA-256 seal) tras la decisión del JDE, confinados al sandbox de salida `data/anydoc/{input,output,cache,quarantine}`, y verificados físicamente mediante `ExecutionVerifier` con cero tolerancia a falsos éxitos.

---

## 2. ARQUITECTURA DE INTEGRACIÓN Y GOBERNANZA

El flujo estricto e inviolable implementado es:

```text
USER
 ↓
JESSYCA CORE
 ↓
JDE (Autoridad Única)
 ↓
RISK ENGINE
 ↓
PERMISSION MANAGER
 ↓
IDEMPOTENCY GUARD
 ↓
ANYDOC ADAPTER
 ↓
ANYDOC ENGINE (Rust Core)
 ↓
OUTPUT SANDBOX (data/anydoc/)
 ↓
EXECUTION VERIFIER
 ↓
JDE RECEIPT
 ↓
JESSYCA
```

---

## 3. CAPACIDADES CERTIFICADAS

Se certificaron 5 capacidades documentales bajo gobernanza del JDE:

| Capability | Risk Level | Permisos Requeridos | Estado |
|---|---|---|---|
| `document_processing.convert` | `SAFE` | `fs:read`, `fs:write` | **CERTIFICADA** |
| `document_processing.inspect` | `READ_ONLY` | `fs:read` | **CERTIFICADA** |
| `document_processing.extract_structure` | `READ_ONLY` | `fs:read` | **CERTIFICADA** |
| `document_processing.extract_assets` | `SAFE` | `fs:read`, `fs:write` | **CERTIFICADA** |
| `document_processing.detect_format` | `READ_ONLY` | `fs:read` | **CERTIFICADA** |

### Capacidades Prohibidas y Deshabilitadas
* `document_processing.ocr_external` -> **DISABLED / STRICTLY FORBIDDEN**
* `document_processing.external_upload` -> **DISABLED / STRICTLY FORBIDDEN**
* `document_processing.document_write` -> **DISABLED / STRICTLY FORBIDDEN**
* `document_processing.arbitrary` -> **DISABLED / STRICTLY FORBIDDEN**

---

## 4. CONTRATOS INMUTABLES Y PREVENCIÓN DE MANIPULACIÓN (ANTI-TAMPERING)

Cada tarea genera un `AnyDocTaskContract` con los siguientes campos obligatorios:
* `task_id`, `decision_id`, `operation_id`
* `input_path`, `input_format`, `output_path`
* `operation`, `allowed_actions`, `forbidden_actions`
* `max_input_size`, `max_output_size`, `timeout_seconds`
* `network_policy`, `requires_review`, `risk_level`

El contrato genera un sello criptográfico inmutable mediante `compute_seal()`:
$$\text{Seal} = \text{SHA-256}(\text{task\_id} : \text{decision\_id} : \text{input} : \text{output} : \text{op} : \text{risk} : \text{net} : \text{allowed} : \text{forbidden})$$

Cualquier intento de alteración posterior a la decisión del JDE (por ejemplo modificar `risk_level` o rutas de salida) invalida el sello y produce un rechazo inmediato `DENIED` con cero efectos colaterales.

---

## 5. REGLAS DE SANDBOX Y SEGURIDAD FÍSICA

* Directorios confinados:
  * `data/anydoc/input/`: Depósito de documentos de entrada.
  * `data/anydoc/output/`: Único destino permitido para salidas Markdown y assets.
  * `data/anydoc/cache/`: Caché de idempotencia aislado.
  * `data/anydoc/quarantine/`: Aislamiento de documentos malformados o sospechosos.
* AnyDoc tiene bloqueada la escritura fuera del sandbox autorizado. Ataques de path traversal (`../`, `..\`, `%2e%2e`), rutas absolutas del sistema operativo (`C:\Windows`, `/etc/passwd`), rutas UNC de red (`\\server\share`) y byte nulo son neutralizados con estado `SECURITY_BLOCKED`.
* Integridad de Entrada: AnyDoc calcula el SHA-256 del archivo antes de procesarlo y verifica que sea idéntico después del procesamiento. El input jamás es mutado.

---

## 6. CONCLUSIÓN

La integración controlada de AnyDoc en Fase 2 opera con estabilidad determinista, estricta gobernanza bajo el JDE y aislamiento completo del sistema operativo y de la red. AnyDoc queda certificado en modo `CONTROLLED` y **LISTO PARA FASE 3**.
