# AnyDoc Fase 3 — Auditoría de Resiliencia y Recuperación de Fallos

## 1. Vectores de Fallo Inyectados y Evaluados

| Vector de Fallo | Simulación / Causa Raíz | Estado Resultante | Efectos Secundarios |
| :--- | :--- | :--- | :--- |
| **Timeout de Ejecución** | Tiempo de conversión superior al umbral configurado | `TIMEOUT` | 0 (Fail-safe) |
| **Documento Malformado** | Archivo vacío o estructura binaria trunca (`empty.docx`) | `MALFORMED` | 0 (Sin escrituras) |
| **Documento Cifrado** | Archivo con contraseña / protección criptográfica (`encrypted.odt`) | `ENCRYPTED` | 0 (Sin escrituras) |
| **Límite de Recursos** | Zipbomb o documento anidado que excede umbral de seguridad (`zipbomb.docx`) | `RESOURCE_LIMIT` | 0 (Interrupción segura) |
| **Denegación JDE** | Política de control o decisión que rechaza la operación | `DENIED` | 0 (Sin efectos) |
| **Manipulación de Contrato** | Parámetros alterados tras el cálculo del sello criptográfico | `DENIED` | 0 (Sin efectos) |
| **Fallo de Verificador** | Archivo resultante ausente o corrupto tras la ejecución | `VERIFICATION_FAILED` | 0 (Recibo no emitido) |
| **Fallo de Red / OCR** | Documento que requiere OCR externo (`scanned.pdf`) | `NEEDS_OCR` | 0 (Sin llamadas externas) |

---

## 2. Garantías de Fail-Safe

En cada uno de los vectores evaluados, el orquestador gobernado garantiza que el sistema no presente falsos positivos, no ejecute comandos adicionales y no deje residuos fuera del sandbox controlado.
