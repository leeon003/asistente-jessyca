# System Routing Table & DNS Cache Inspector — Jessyca Windows MCP (Subetapa 09.3)

## Visión General

La **Subetapa 09.3** amplia la **ETAPA 09 — SECURE NETWORK & SYSTEM DIAGNOSTICS** implementando la inspección de diagnóstico en modo solo lectura de la tabla de ruteo IP del sistema (`get_routing_table`) y de la caché DNS local (`get_dns_cache`) bajo la capability `windows.network`.

---

## GARANTÍAS ABSOLUTA DE SEGURIDAD Y PRIVACIDAD

1. **READ-ONLY DIAGNOSTIC INSPECTION**: Operación puramente lectora de diagnóstico de rutas IP y registros DNS. CERO modificación de rutas, CERO cambios en interfaces, CERO alteración de DNS o firewall.
2. **UNTRUSTED INPUT & FAIL-SAFE DENY**: Solicitudes y filtros son validados por `NetworkRoutingSecurityManager`. Se rechazan prefijos CIDR inválidos, métricas negativas, hostnames malformados con caracteres de control o null bytes, NaN, Infinity y valores de tipos incorrectos.
3. **GRACEFUL BACKEND DEGRADATION**: Manejo de degradación limpia cuando las APIs nativas de Windows no están disponibles. El backend retorna `backend_unavailable` / `inspection_failed` de forma segura.
4. **INVARIANTE DE PRIVACIDAD EN AUDITORÍA**: El `AuditLogger` y el `EventBus` registran **ÚNICAMENTE METADATOS** (`total_found`, `returned_count`, `truncated`, `processing_time_ms`, `backend_name`). **NUNCA** almacenan rutas individuales, destinos IP, pasarelas, hostnames ni valores DNS en logs de auditoría.
5. **CERO SUBPROCESS / SHELL**: La inspección utiliza C-APIs nativas de Windows vía `ctypes` o un `FakeRoutingTableInspectionBackend` / `FakeDNSCacheInspectionBackend` sintético desacoplado en memoria. **CERO `subprocess`**, **CERO `os.system`**, **CERO `shell=True`**, **CERO `cmd.exe`**, **CERO `powershell.exe`**, **CERO `route print`**, **CERO `netsh`**, **CERO `ipconfig /displaydns`**, **CERO `Get-DnsClientCache`**.

---

## Componentes Principales

### 1. `NetworkRoutingSecurityManager` (`core/network_routing_security.py`)
- Valida prefijos CIDR, métricas, hostnames y valores DNS.
- Sanitiza hostnames y valores removiendo null bytes (`\x00`) y caracteres de control no imprimibles (`\x00-\x1f`).

### 2. Backends de Ruteo y DNS Desacoplados (`tools/network/routing_backend.py` & `dns_cache_backend.py`)
- `IRoutingTableInspectionBackend` & `IDNSCacheInspectionBackend`: Protocolos abstractos para la inspección de ruteo IP y caché DNS.
- `WindowsRoutingTableInspectionBackend` & `WindowsDNSCacheInspectionBackend`: Backends nativos desacoplados sin shell.
- `FakeRoutingTableInspectionBackend` & `FakeDNSCacheInspectionBackend`: Backends sintéticos seguros en memoria para pruebas unitarias deterministas.

### 3. Servicios y Ejecutor (`tools/network/routing_service.py`, `dns_cache_service.py` & `executor.py`)
- `RoutingTableInspectionService` & `DNSCacheInspectionService`: Orquestan la validación de seguridad, consulta del backend, filtrado y auditoría con metadatos exclusivos.
- `WindowsNetworkToolExecutor`: Ejecutor integrado en `SecureExecutionPipeline` para las operaciones `get_routing_table` y `get_dns_cache`.
