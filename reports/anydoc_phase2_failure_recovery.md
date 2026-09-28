# JESSYCA PC — ANYDOC FASE 2
# REPORTE DE RESILIENCIA, LÍMITES DE RECURSOS Y RECUPERACIÓN DE FALLOS

**Módulo:** AnyDoc Resource Guard & Fault Tolerance  
**Fase:** Fase 2 — Controlled Integration  
**Fecha:** 2026-09-27  

---

## 1. CONTROL DE LÍMITES DE RECURSOS

AnyDoc integra protecciones a nivel de motor y a nivel de adaptador para mitigar ataques de denegación de servicio (DoS) basados en archivos maliciosos:

* **Tamaño Máximo de Entrada:** Límite estándar de 50 MB por archivo. Intentos de procesar archivos mayores son rechazados de inmediato con `RESOURCE_LIMIT`.
* **Protección contra Zip Bombs (`zipbomb.docx`):** Contenida por los límites de descompresión nativos del motor Rust de AnyDoc, respondiendo de forma segura con `RESOURCE_LIMIT` o `MALFORMED` sin saturar la memoria RAM.
* **Protección contra XML Profundo / Entidades (`deepxml.docx`):** Manejada con fallo seguro (`RESOURCE_LIMIT` / `MALFORMED`) evitando desbordamientos de pila (stack overflow) o recursión infinita.
* **Archivos Incompletos o Truncados (`truncated.docx`):** Detectados y reportados como `MALFORMED` / `IO_ERROR` sin generar excepciones no controladas.
* **Archivos Cifrados / Protegidos por Contraseña (`encrypted.odt`):** Devuelve `ENCRYPTED` sin causar cuelgues ni intentos de fuerza bruta.

---

## 2. MANEJO ESTRICTO DE TIMEOUT

* Cada contrato estipula un umbral de tiempo máximo (`timeout_seconds`, por defecto 30.0 s).
* Ante un evento de timeout (simulado o real):
  * La operación finaliza de inmediato con estado `TIMEOUT`.
  * No se generan outputs parciales ni se confía en archivos a medio escribir.
  * No se dejan procesos huérfanos en segundo plano.
  * El incidente se registra en el historial de auditoría con `verified = False` y `side_effects = 0`.

---

## 3. RESILIENCIA OPERACIONAL

Todos los fallos provocados fueron recuperados de manera determinista: el orquestador nunca cayó en un estado corrupto, el estado global de JESSYCA permaneció estable y las operaciones subsiguientes continuaron procesándose con total normalidad.
