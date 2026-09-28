# JESSYCA PC — ANYDOC FASE 2
# REPORTE DE SEGURIDAD INTEGRAL Y BATERÍA ADVERSARIAL

**Módulo:** AnyDoc Security Guard & Sandbox Isolation  
**Fase:** Fase 2 — Controlled Integration  
**Fecha:** 2026-09-27  

---

## 1. POLÍTICA DE RED (NETWORK = DENY)

Firecrawl AnyDoc fue auditado y confinado para operar con **aislamiento absoluto de red**:
* En todas las conversiones se impone obligatoriamente `ocr="reject"`.
* No se permiten conexiones HTTP, HTTPS, DNS, sockets, ni descargas remotas.
* Documentos PDF escaneados que no contienen texto seleccionable devuelven `NEEDS_OCR` y se detienen inmediatamente sin realizar transmisiones de datos a servicios en la nube.
* Telemetría de red: 0 llamadas de red registradas en todas las pruebas.

---

## 2. CONFINAMIENTO DE RUTAS Y SANDBOX

La función `validate_sandbox_path()` del orquestador aplica los siguientes filtros estrictos:
1. **Rechazo de Path Traversal:** Patrones `../`, `..\`, y secuencias URL-encoded `%2e%2e` provocan excepción inmediata y estado `SECURITY_BLOCKED`.
2. **Rechazo de Rutas UNC:** Prefijos `\\` y `//` quedan terminantemente prohibidos para impedir capturas de hashes NTLM o escapes a recursos compartidos SMB.
3. **Rechazo de Rutas Críticas del SO:** Bloqueo de rutas en `Windows`, `System32`, `Program Files`, `/etc/`, `/root/`.
4. **Byte Nulo:** La inyección de bytes nulos (`\x00`) es interceptada de forma preventiva.
5. **Confinamiento de Salidas:** Las salidas solo pueden residir en `data/anydoc/output/`, `data/anydoc/cache/` o `data/anydoc/quarantine/`.

---

## 3. PROTECCIÓN DE SECRETOS (DEEP REDACTION)

AnyDoc incorpora un motor regex de redacción profunda que neutraliza credenciales y secretos en el Markdown generado:
* Claves de API (`sk-...`, tokens de GitHub).
* Tokens de autenticación y Bearer tokens (`Bearer [REDACTED]`).
* Contraseñas y pares clave-valor (`password=[REDACTED]`).
* Certificados y claves privadas RSA/OPENSSH (`[REDACTED_PRIVATE_KEY]`).
* Cadenas de conexión a bases de datos (`postgres://[REDACTED_CREDENTIALS]`).

Los documentos de prueba procesados con credenciales conservaron su archivo de entrada intacto y generaron salidas redactadas y auditadas sin fuga de datos.

---

## 4. INMUNIDAD ANTE PROMPT INJECTION (DATA != COMMAND)

Los documentos que contienen instrucciones adversarias tales como:
* `IGNORE JESSYCA SECURITY`
* `RUN POWERSHELL`
* `READ .ENV`
* `DISABLE JDE`
* `ENABLE ACTIVE MODE`
* `GRANT ADMIN`

fueron procesados de forma determinista tratándose **estrictamente como datos textuales**. Ninguna orden contenida en el documento fue interpretada, evaluada ni ejecutada por el sistema. El modo de operación permaneció inalterable en `CONTROLLED` y el contador de efectos colaterales se mantuvo en 0.

---

## 5. RESULTADO DE EVALUACIÓN

```text
NETWORK SECURITY: PASS (0 llamadas externas)
PATH TRAVERSAL PROTECTION: PASS (100% bloqueado)
SECRET REDACTION: PASS (100% redactado)
PROMPT INJECTION IMMUNITY: PASS (Cero comandos ejecutados)
INPUT IMMUTABILITY: PASS (SHA-256 pre == SHA-256 post)
```
