# Network Interfaces & Adapter Inspection — Jessyca Windows MCP (Subetapa 09.1)

## Visión General

La **Subetapa 09.1** da inicio a la **ETAPA 09 — SECURE NETWORK & SYSTEM DIAGNOSTICS** implementando la inspección declarativa y segura en modo solo lectura de adaptadores de red (`get_network_interfaces`) bajo la capability `windows.network`.

---

## GARANTÍAS ABSOLUTAS DE SEGURIDAD Y PRIVACIDAD

1. **READ-ONLY DIAGNOSTIC INSPECTION**: Operación puramente lectora de diagnóstico. CERO modificación de IP, CERO cambio de DNS, CERO alteración de pasarelas/rutas, CERO habilitación/deshabilitación de adaptadores.
2. **UNTRUSTED INPUT & FAIL-SAFE DENY**: Solicitudes y filtros son validados por `NetworkSecurityManager`. Se rechazan patrones peligrosos de metacaracteres, filtrado malicioso y longitudes excesivas.
3. **VALIDACIÓN RIGUROSA DE DIRECCIONES IP Y FORMATO MAC**: Las direcciones IP son validadas y clasificadas utilizando el módulo estándar `ipaddress`. Las direcciones MAC son sanitizadas y normalizadas a formato `XX-XX-XX-XX-XX-XX`.
4. **INVARIANTE DE PRIVACIDAD EN AUDITORÍA**: El `AuditLogger` y el `EventBus` registran **ÚNICAMENTE METADATOS** (`interface_count`, `ipv4_count`, `ipv6_count`, `gateway_count`, `dns_count`, `processing_time_ms`, `backend_name`). **NUNCA** almacenan direcciones IP crudas, MACs ni la topología completa de la red en logs de auditoría.
5. **CERO SUBPROCESS / SHELL**: La inspección utiliza psutil / APIs de sockets nativas de Windows o un `FakeNetworkInspectionBackend` sintético desacoplado en memoria. **CERO `subprocess`**, **CERO `os.system`**, **CERO `shell=True`**, **CERO `cmd.exe`**, **CERO `powershell.exe`**, **CERO `ipconfig`**, **CERO `netsh`**.

---

## Componentes Principales

### 1. `NetworkSecurityManager` (`core/network_security.py`)
- Valida la longitud y caracteres del filtro de interfaces.
- Normaliza direcciones MAC y enforza los límites configurados (`NETWORK_MAX_INTERFACES=256`, `NETWORK_MAX_IP_ADDRESSES_PER_INTERFACE=64`, `NETWORK_MAX_GATEWAYS_PER_INTERFACE=16`, `NETWORK_MAX_DNS_SERVERS_PER_INTERFACE=32`, `NETWORK_MAX_NAME_LENGTH=256`, `NETWORK_MAX_DESCRIPTION_LENGTH=1024`).

### 2. Backends de Inspección Desacoplados (`tools/network/backend.py`)
- `INetworkInspectionBackend`: Protocolo abstracto para inspección de red.
- `WindowsNetworkInspectionBackend`: Backend nativo utilizando psutil y sockets con fallback limpio.
- `FakeNetworkInspectionBackend`: Backend sintético seguro en memoria para pruebas unitarias deterministas.

### 3. Servicio y Ejecutor (`tools/network/network_service.py` & `executor.py`)
- `NetworkInspectionService`: Orquesta la validación de seguridad, consulta del backend de red, sanitización y auditoría con metadatos exclusivos.
- `WindowsNetworkToolExecutor`: Ejecutor integrado en `SecureExecutionPipeline` para la operación `get_network_interfaces`.
