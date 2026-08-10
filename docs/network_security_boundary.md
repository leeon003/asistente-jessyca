# Secure Network & System Diagnostics Boundary — Jessyca Windows MCP (Subetapa 09.4)

## Visión General

La **Subetapa 09.4** consolida y audita formalmente la frontera de seguridad de la **ETAPA 09 — SECURE NETWORK & SYSTEM DIAGNOSTICS**, garantizando que las 5 operaciones del dominio `windows.network`:

1. `get_network_interfaces`
2. `get_active_connections`
3. `get_listening_ports`
4. `get_routing_table`
5. `get_dns_cache`

constituyan una frontera de diagnóstico de red unificada, inmutable, en modo solo lectura (READ-ONLY) y con auditoría con metadatos exclusivos.

---

## MATRIZ DE CAPABILIDADES (`windows.network`)

| Operación              | Dominio         | Nivel de Riesgo | Mutación de Red | Ejecución Shell | Pipeline Obligatorio | Nivel de Auditoría |
| ---------------------- | --------------- | --------------- | --------------- | --------------- | -------------------- | ------------------ |
| get_network_interfaces | windows.network | SAFE            | NO              | NO              | REQUERIDO            | Metadatos Únicamente |
| get_active_connections | windows.network | SAFE            | NO              | NO              | REQUERIDO            | Metadatos Únicamente |
| get_listening_ports    | windows.network | SAFE            | NO              | NO              | REQUERIDO            | Metadatos Únicamente |
| get_routing_table      | windows.network | SAFE            | NO              | NO              | REQUERIDO            | Metadatos Únicamente |
| get_dns_cache          | windows.network | SAFE            | NO              | NO              | REQUERIDO            | Metadatos Únicamente |

---

## CONSOLIDADOR DE SEGURIDAD (`NetworkBoundaryConsolidator`)

El componente `NetworkBoundaryConsolidator` (`core/network_boundary_security.py`) centraliza la verificación de las 20 Invariantes Globales de Seguridad de la Etapa 09:

1. **UNTRUSTED INPUT**: Todo parámetro proveniente de un cliente MCP es tratado como potencialmente malicioso y pasa por sanitización estricta.
2. **FAIL-SAFE DENY**: Cualquier fallo de backend, timeout, tipo incorrecto, entrada malformada o firma criptográfica inválida produce `DENY`.
3. **READ-ONLY ABSOLUTO**: Ninguna operación de red modifica adaptadores, IP, DNS, rutas, conexiones, sockets o reglas de firewall.
4. **ZERO SHELL EXECUTION**: Auditoría de código fuente recursiva que garantiza **CERO `subprocess`**, **CERO `shell=True`**, **CERO `os.system`**, **CERO `cmd.exe`**, **CERO `powershell.exe`**, **CERO `netsh`**, **CERO `ipconfig`**, **CERO `route`**, **CERO `arp`**, **CERO `nslookup`**, **CERO `netstat`**.
5. **SECURE EXECUTION PIPELINE MANDATORY**: Toda operación atraviesa obligatoriamente la cadena `RequestContext -> ExecutionRequest -> CapabilityResolver -> SecureExecutionPipeline -> AuthorizationEvidence -> WindowsNetworkToolExecutor`.
6. **INVARIANTE DE PRIVACIDAD ABSOLUTA**: `AuditLogger` y `EventBus` registran **ÚNICAMENTE METADATOS** (`total_found`, `returned_count`, `truncated`, `processing_time_ms`, `backend_name`, `status`). CERO direcciones IP crudas, pasarelas, hostnames, registros DNS o nombres de proceso en logs de auditoría.
7. **LÍMITES Y TIMEOUTS CONSOLIDADOS**: `max_results` estrictamente acotado, timeouts finitos y no anulables desde payloads MCP, y rechazo de NaN, Infinity, números negativos o type mismatches.
