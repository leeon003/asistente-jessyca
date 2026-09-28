# Manual de Integración y Arquitectura de Archify — JESSYCA PC

**Sistema:** JESSYCA PC  
**Módulo:** Archify Integration & Capability Provider  
**Fase:** Fase 3 — Production Certified  
**Modo Operacional:** `ARCHIFY_MODE=ACTIVE` (Gobernado por JDE)  

---

## 1. Arquitectura del Sistema
Archify es un compilador especializado de diagramas técnicos interactivos que genera artefactos visuales autocontenidos en formatos HTML y SVG. Proporciona soporte para temas oscuro/claro, renderizado interactivo, escalado y representación estructurada de flujos de sistemas.

En JESSYCA PC, Archify opera como un **Capability Provider** estrictamente subordinado al **JESSYCA Decision Engine (JDE)**. No posee autonomía, memoria propia, ni facultades de decisión.

### Cadena de Invocación Inviolable
```text
USER REQUEST
    ↓
JESSYCA CORE
    ↓
JDE DECISION ENGINE (Evalúa la intención y selecciona diagram_generation.<tipo>)
    ↓
RISK ENGINE & PERMISSION MANAGER (Verifica SAFE risk tier y permisos estrictos)
    ↓
IDEMPOTENCY GUARD (Calcula hash SHA-256 de la especificación; retorna CACHE_HIT si ya existe)
    ↓
ARCHIFY SKILL & ADAPTER (Sanitiza XSS, redacta secretos, valida complejidad)
    ↓
ARCHIFY ENGINE COMPILER (Compila HTML y SVG determinista)
    ↓
ARTIFACT (Almacenamiento exclusivo en data/archify/diagram_<id>.html)
    ↓
EXECUTION VERIFIER (Comprueba existencia física, tamaño > 0, estructura HTML/SVG, confinamiento y checksum)
    ↓
JDE RECEIPT (Emite ActionReceipt forense inmutable)
    ↓
JESSYCA RESPONSE (Entrega el mensaje y artefacto verificado al usuario)
```

Queda **totalmente bloqueado** y prevenido cualquier intento de bypass directo `USER -> ARCHIFY -> EXECUTION`.

---

## 2. Capacidades de Diagramación
Únicamente se encuentran habilitadas y certificadas las siguientes cinco (5) capacidades especializadas:

1. **`diagram_generation.architecture`:** Topologías de arquitectura de software, servicios y componentes.
2. **`diagram_generation.workflow`:** Flujos operacionales, pipelines de datos y procesos de negocio.
3. **`diagram_generation.sequence`:** Diagramas de secuencia y sincronización de mensajes temporales.
4. **`diagram_generation.dataflow`:** Flujos de datos, canales de transformación y tuberías.
5. **`diagram_generation.lifecycle`:** Máquinas de estados finitos y ciclos de vida de entidades.

### Capacidades No Certificadas
`diagram_generation.generic` y `diagram_generation.skill` han sido clasificadas como no certificadas y permanecen en estado **DISABLED** (`enabled=False`) en el CapabilityRegistry. Solicitudes dirigidas a estas capacidades son denegadas automáticamente por el JDE.

---

## 3. Modos Operacionales
El sistema admite cuatro (4) modos formales controlados por variable de entorno o API:

* **`OFF`:** Capacidad completamente desactivada. Las peticiones son rechazadas o derivadas a fallback.
* **`SHADOW`:** Modo observacional no invasivo. Evalúa y valida la especificación sin escribir archivos en disco.
* **`CONTROLLED`:** Modo de laboratorio y pruebas con límites estrictos y registro de métricas.
* **`ACTIVE`:** **Modo Producción Certificado.** Ejecución real gobernada por JDE para capacidades certificadas.

---

## 4. Gobernanza del JDE (Principio de Single Authority)
* **JDE es la única autoridad de decisión.** Archify jamás decide si debe generar un diagrama.
* Si el JDE dictamina `DENY`, Archify no se ejecuta, no genera artefactos ni produce efectos secundarios.
* Toda invocación directa sin autorización ni `decision_id` de JDE es rechazada con `DENIED / GOVERNANCE_REQUIRED`.
* Archify no puede revocar ni alterar las decisiones emitidas por el JDE.

---

## 5. Seguridad y Batería Adversarial
* **Sanitización XSS:** Todo texto (títulos, nodos, aristas) es escapado mediante entidades HTML (`<script>`, `<img>`, `<iframe>` neutralizados).
* **Escape de Script Tags en JSON:** Las secuencias `</script>` dentro de datos JSON embebidos se transforman automáticamente a `<\/script>` para prevenir script breakout.
* **Anti-DoS:** Límites duros de complejidad (≤ 100 nodos, ≤ 200 aristas, strings ≤ 4,000 caracteres, artefacto ≤ 5 MB).
* **Validación de Identidad de Nodos:** Rechazo de identificadores duplicados y aristas que referencien nodos no declarados.

---

## 6. Auditoría de Permisos
Archify posee exclusivamente permisos de escritura en su sandbox designado (`data/archify/`).
* **NO** puede leer archivos arbitrarios del sistema.
* **NO** puede escribir fuera de `data/archify/`.
* **NO** puede invocar shells (PowerShell, CMD, Bash).
* **NO** puede lanzar procesos arbitrarios.
* **NO** puede modificar código, memoria ni configuraciones del sistema.
* **NO** puede acceder a credenciales o tokens.

---

## 7. Confinamiento de Salida
Se aplica resolución canónica estricta sobre las rutas destino:
1. Decodificación de URL encoding (`urllib.parse.unquote`) para evitar dobles codificaciones (`%2e%2e%2f`).
2. Detección y bloqueo de bytes nulos (`\x00`).
3. Extracción de nombre base mediante `os.path.basename`.
4. Comprobación de contención física mediante `os.path.commonpath([target_real, output_real]) == output_real`.
5. Aseguramiento de terminación `.html`.

---

## 8. Idempotencia y Caché
* Se calcula una clave determinista SHA-256 a partir del tipo de diagrama, título normalizado, nodos ordenados y aristas ordenadas.
* Solicitudes idénticas reutilizan el archivo existente retornando `CACHE_HIT` en ~0.4 ms sin duplicar archivos en disco.
* Cualquier variación en título, nodos, aristas o tipo de diagrama genera un nuevo fingerprint y nuevo artefacto.

---

## 9. Verificación Determinista (`ExecutionVerifier`)
Ninguna operación se reporta como exitosa sin evidencia física:
1. Comprueba existencia real y tipo de archivo regular.
2. Comprueba tamaño > 0 bytes y ≤ 5 MB.
3. Comprueba extensión canónica `.html`.
4. Comprueba estructura HTML y SVG interactivo.
5. Comprueba integridad criptográfica (SHA-256) contra el `expected_checksum`.
6. Comprueba que el archivo no contenga patrones sensibles de contraseñas o tokens.

---

## 10. Fallback y Resiliencia
Si Archify se encuentra en modo `OFF`, falla en la compilación, o el `ExecutionVerifier` detecta inconsistencias:
* Si `allow_fallback=True`, se genera automáticamente un diagrama en **Mermaid** en el cuerpo del mensaje.
* Si el fallback no está autorizado, la operación falla de manera segura (`FAILED`) sin falsos éxitos.

---

## 11. Configuración de Producción
En el entorno de producción (`.env` o variables del sistema):
```bash
ARCHIFY_MODE=ACTIVE
ARCHIFY_ENFORCE_GOVERNANCE=true
```

---

## 12. Activación de Producción
Para verificar la activación operativa:
```python
from core.archify.adapter import get_archify_adapter, ArchifyMode

adapter = get_archify_adapter()
adapter.set_mode(ArchifyMode.ACTIVE)
status = adapter.health_check()
print(status["status"])  # "HEALTHY"
```

---

## 13. Procedimiento de Rollback Inmediato
Si se requiere suspender la generación real de Archify de forma instantánea sin reiniciar el servicio ni modificar código:
```bash
# 1. Rollback a modo controlado (pruebas restringidas):
set ARCHIFY_MODE=CONTROLLED

# 2. Rollback a modo observacional pasivo (sin escrituras):
set ARCHIFY_MODE=SHADOW

# 3. Desactivación total (fallback a Mermaid):
set ARCHIFY_MODE=OFF
```

---

## 14. Troubleshooting
* **`INVALID_DIAGRAM_SPEC`:** La especificación JSON no contiene campos válidos, supera 100 nodos o 200 aristas, contiene IDs duplicados o aristas hacia nodos inexistentes.
* **`Violación de seguridad: intento de Path Traversal detectado`:** El nombre de archivo solicitado contiene secuencias relativas (`..`), caracteres no permitidos o rutas absolutas de sistema.
* **`DENIED / GOVERNANCE_REQUIRED`:** Se intentó invocar el adaptador directamente sin pasar por el JDE o sin proporcionar un `decision_id`.
* **`Checksum mismatch`:** El archivo HTML fue alterado en disco tras haber sido generado.

---

## 15. Limitaciones Conocidas
* **Node.js Runtime:** Requiere que Node.js esté disponible en el PATH del sistema para validaciones auxiliares.
* **Límites de Visualización:** Gráficos con más de 100 nodos no son renderizados en Archify para evitar saturación visual y degradación de rendimiento (se recomienda subdividir en subdiagramas).
* **Entornos Texto Puro:** Clientes CLI o consolas sin navegador web deben solicitar salida en Mermaid o texto estructurado.
