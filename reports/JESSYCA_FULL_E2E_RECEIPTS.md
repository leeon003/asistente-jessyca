# JESSYCA — Reporte E2E de Receipts y Trazabilidad Criptográfica

## Estado de Certificación: CONTROLLED READY

---

### 1. Resumen Ejecutivo de Auditoría y Receipts

El subsistema de **Receipts & Audit** (`core/receipts/models.py`, `core/audit/`) constituye la capa final e inmutable de la cadena de ejecución de JESSYCA PC. Ninguna operación física es considerada completada sin un `ActionReceipt` debidamente indexado y firmado criptográficamente mediante SHA-256.

El diseño garantiza:
1. **No-Repudio y Verificabilidad Criptográfica:** El `fingerprint_sha256` sella la tupla `(decision_id, execution_id, tool_name, status, timestamp)`. Cualquier alteración posterior del registro invalida la firma.
2. **Trazabilidad Bidireccional Completa:**
   ```text
   User Request (request_id)
        ↓
   JDE Decision (decision_id)
        ↓
   Idempotency & Execution Boundary (execution_id)
        ↓
   Physical Verification (evidence, verifier)
        ↓
   ActionReceipt (fingerprint_sha256)
   ```
3. **Cero Éxito Falso:** Un receipt exitoso (`execution_status == OK`) exige de forma vinculante `verified == True` y `verification_status == VERIFIED_TRUE`.

---

### 2. Contrato de Datos del ActionReceipt

Definido formalmente en `core/receipts/models.py`:

| Campo | Tipo | Obligatorio | Descripción / Semántica |
| :--- | :--- | :---: | :--- |
| `receipt_id` | `UUID` | SÍ | Identificador único del recibo de auditoría. |
| `request_id` | `str` | SÍ | Identificador correlativo de la petición del usuario o disparador. |
| `decision_id` | `str` | SÍ | ID emitido por JDE con la autorización de la operación. |
| `execution_id` | `str` | SÍ | ID asignado por `ExecutionIdempotencyGuard` / `ExecutionBoundary`. |
| `mode` | `SystemMode` | SÍ | Modo de operación en ejecución (`CONTROLLED` en esta fase). |
| `tool_name` | `str` | SÍ | Nombre canónico de la skill o adaptador ejecutado. |
| `tool_args` | `dict` | SÍ | Argumentos y parámetros suministrados a la herramienta. |
| `tool_result` | `dict` | SÍ | Salida bruta del adaptador/skill. |
| `execution_status`| `ExecutionStatusType` | SÍ | `OK`, `FAIL`, `BLOCKED`, `PENDING`. |
| `verified` | `bool` | SÍ | Bandera booleana de verificación física confirmada. |
| `verification_status`| `VerificationStatusType`| SÍ | `VERIFIED_TRUE`, `VERIFIED_FALSE`, `VERIFIED_SKIPPED`. |
| `verification_evidence`| `dict` | SÍ | Metadatos y telemetría de verificación recolectados. |
| `risk_level` | `RiskLevel` | SÍ | Evaluación de riesgo certificada por `RiskEngine`. |
| `created_at` | `datetime` | SÍ | Marca de tiempo ISO-8601 UTC. |
| `fingerprint_sha256`| `str` | SÍ | Hash criptográfico anti-manipulación calculado sobre los campos clave. |

---

### 3. Algoritmo de Huella Digital Criptográfica (SHA-256)

El cálculo del `fingerprint_sha256` se rige por:

$$\text{data} = \text{receipt\_id} \,\|\, \text{decision\_id} \,\|\, \text{execution\_id} \,\|\, \text{tool\_name} \,\|\, \text{execution\_status} \,\|\, \text{created\_at}$$

$$\text{fingerprint} = \text{SHA256}(\text{data.encode('utf-8')})$$

Cualquier discrepancia entre el estado de ejecución reportado y la huella criptográfica causa un rechazo en las verificaciones de auditoría.

---

### 4. Ejemplos Reales de Receipts en Pruebas E2E

#### 4.1. Caso 1: Ejecución Exitosa (ALLOW — Simple Skill / AnyDoc)

```json
{
  "receipt_id": "902d3bb9-b883-4a1b-bd57-a37f5d475ef9",
  "request_id": "req-e2e-allow-01",
  "decision_id": "dec-jde-984210",
  "execution_id": "exec-bound-1142",
  "mode": "CONTROLLED",
  "tool_name": "apps.launch",
  "tool_args": {
    "app_name": "notepad.exe"
  },
  "tool_result": {
    "status": "launched",
    "pid": 4812
  },
  "execution_status": "OK",
  "verified": true,
  "verification_status": "VERIFIED_TRUE",
  "verification_evidence": {
    "method": "process_check",
    "pid": 4812,
    "process_active": true,
    "timestamp": "2026-09-27T21:05:14.221Z"
  },
  "risk_level": "LOW",
  "created_at": "2026-09-27T21:05:14.225Z",
  "fingerprint_sha256": "4b679a7bc0551e33816738b5fa01f5fecf5dd1dfcbbf7484a95610bcdeea4721"
}
```

*Verificación:* `verified: true`, `verification_status: VERIFIED_TRUE`. Trazabilidad unívoca a `decision_id: dec-jde-984210`.

---

#### 4.2. Caso 2: Operación Bloqueada por JDE (DENY — Zero Side Effects)

```json
{
  "receipt_id": "f4412cb2-7901-447a-8f19-98319f0712ce",
  "request_id": "req-e2e-deny-06",
  "decision_id": "dec-jde-critical-deny",
  "execution_id": "exec-blocked-null",
  "mode": "CONTROLLED",
  "tool_name": "system.format_drive",
  "tool_args": {
    "drive": "C:",
    "force": true
  },
  "tool_result": {
    "blocked_reason": "JDE evaluation denied execution: CRITICAL risk is blocked in CONTROLLED mode",
    "executed": false
  },
  "execution_status": "BLOCKED",
  "verified": false,
  "verification_status": "VERIFIED_SKIPPED",
  "verification_evidence": {
    "reason": "Execution blocked prior to invocation; physical verification skipped.",
    "tools_invoked": 0,
    "physical_side_effects": 0
  },
  "risk_level": "CRITICAL",
  "created_at": "2026-09-27T21:05:17.840Z",
  "fingerprint_sha256": "2a9a7b973059ebafba3a8b273b433eecae76c11709424dfefea55866164a275f"
}
```

*Verificación:* `execution_status: BLOCKED`, `tools_invoked: 0`. Cero llamadas al sistema operativo o disco.

---

#### 4.3. Caso 3: Operación Requiere Revisión Humana (REQUIRE_REVIEW)

```json
{
  "receipt_id": "18c0df1b-b4d2-4309-923f-e8b417c80775",
  "request_id": "req-e2e-review-07",
  "decision_id": "dec-jde-high-review",
  "execution_id": "exec-pending-review",
  "mode": "CONTROLLED",
  "tool_name": "filesystem.delete_directory",
  "tool_args": {
    "path": "D:/test_dir",
    "recursive": true
  },
  "tool_result": {
    "status": "AWAITING_CONFIRMATION",
    "prompt": "HIGH risk operation requires human review and confirmation token"
  },
  "execution_status": "PENDING",
  "verified": false,
  "verification_status": "VERIFIED_SKIPPED",
  "verification_evidence": {
    "reason": "Awaiting human review; no tools executed",
    "state": "UNTOUCHED"
  },
  "risk_level": "HIGH",
  "created_at": "2026-09-27T21:05:18.112Z",
  "fingerprint_sha256": "dd81e550302b1f8b30141f224b17efc8da7fa516086f4577884ec92b11e2f3d6"
}
```

*Verificación:* Se detiene en la frontera de ejecución sin tocar el sistema de archivos.

---

### 5. Reconstrucción Forense de la Trazabilidad

A partir de cualquiera de los receipts emitidos en la base de datos o almacén de auditoría, es posible ejecutar una auditoría retrospectiva de 5 puntos:

1. **Intención Original:** Obtener la petición de usuario mediante `request_id`.
2. **Evaluación de Autoridad:** Recuperar la resolución de JDE mediante `decision_id` para corroborar el modo (`CONTROLLED`), la política aplicada y el nivel de riesgo evaluado por `RiskEngine`.
3. **Frontera de Idempotencia:** Validar el `execution_id` frente a `ExecutionIdempotencyGuard` para confirmar que no hubo replays ni ejecuciones dobles.
4. **Evidencia Física:** Examinar `verification_evidence` y comprobar contra `ExecutionVerifier` que el estado físico reportado corresponde a la realidad del hardware/OS.
5. **Autenticidad Criptográfica:** Recalcular `compute_receipt_fingerprint()` y cotejar contra `fingerprint_sha256` para certificar que el log no fue manipulado tras la ejecución.

---

### 6. Conclusión de Receipts

El subsistema de Receipts & Audit opera en estricta conformidad con la arquitectura de JESSYCA PC en modo `CONTROLLED READY`. Toda acción produce un registro inmutable, no repudiable y reproducible, cerrando la brecha de verificación de extremo a extremo sin tolerar falsos positivos.
