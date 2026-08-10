# Capability System & Tool Registry Hardening — Jessyca Windows MCP (Subetapa 06.1)

## Visión General

El **Capability System** de **Jessyca Windows MCP** proporciona una capa declarativa, inmutable y fuertemente tipada que gobierna qué herramientas puede ofrecer Jessyca, qué operaciones expone cada herramienta, el riesgo intrínseco de cada operación y sus restricciones de autorización.

Garantiza que la definición de capacidades provenga **exclusivamente de fuentes autorizadas y confiables** (`SYSTEM`, `ADMINISTRATOR`, `CONFIGURATION`, `BUILTIN`) y desestima explícitamente cualquier intento de inyección o falsificación desde fuentes no confiables (`LLM`, `USER_PROMPT`, `CLIENT`, `ASSISTANT`).

---

## Arquitectura del Capability System

```text
MCP Client Request
    ↓
RequestContext (Aislamiento de Entradas No Confiables)
    ↓
ExecutionRequest
    ↓
CapabilityResolver (core/capability_resolver.py)
    └─ CapabilityRegistry (core/capability_registry.py)
         └─ CapabilityValidator (core/capability_validator.py)
    ↓
[CAPABILITY_RESOLVED Audit Event]
    ↓
SecureExecutionPipeline (05.2 Orchestrator)
    ├─ RiskEngine (04.2)
    ├─ SecurityPolicyEvaluator (04.5)
    ├─ PermissionManager (04.3)
    ├─ SecurityDecisionAggregator (Effective Decision = most_restrictive)
    └─ ConfirmationManager (04.4)
    ↓
AuthorizationEvidence (SHA-256 Cryptographic Binding)
    ↓
SecureExecutionBoundary (05.2)
    ↓
DisabledToolExecutor (05.2 - Ejecución Deshabilitada)
```

---

## Componentes Clave

### 1. `core/capabilities.py`
- **`CapabilitySource`**: Enum con fuentes autorizadas (`SYSTEM`, `ADMINISTRATOR`, `CONFIGURATION`, `BUILTIN`).
- **`CapabilityRiskLevel`**: `SAFE`, `WARNING`, `DANGEROUS`, `CRITICAL`, `UNKNOWN`.
- **`CapabilityDecision`**: `ALLOW`, `REQUIRE_CONFIRMATION`, `REQUIRE_ELEVATED_AUTHORIZATION`, `DENY`.
- **`CapabilityStatus`**: `ENABLED`, `DISABLED`, `DEPRECATED`, `BLOCKED`.
- **`CapabilityOperation`**: Modelo inmutable (`@dataclass(frozen=True)`).
- **`ToolCapability`**: Modelo inmutable (`@dataclass(frozen=True)`).
- **`compute_capability_fingerprint()`**: Hash SHA-256 determinista sobre `tool_name`, `version`, `operation_id`, `risk_level`, `decision`, `requires_confirmation`, `requires_elevation`.

### 2. `CapabilityRegistry` (`core/capability_registry.py`)
Registro thread-safe que gestiona el catálogo de `ToolCapability`. Soporta un mecanismo de sellado (`lock_registry()`) e impide la eliminación de capacidades marcadas como `is_immutable=True`.

### 3. `CapabilityValidator` (`core/capability_validator.py`)
Valida la integridad de las capacidades y enforza las invariantes de seguridad:
- Operaciones `CRITICAL` -> Jamás `ALLOW` directo.
- Operaciones `UNKNOWN` -> `DENY` obligatorio.
- Operaciones con `requires_elevation=True` -> Jamás `ALLOW` directo.
- Rechazo inmediato de capacidades originadas en `LLM`, `CLIENT` o `USER_PROMPT`.

### 4. `CapabilityResolver` (`core/capability_resolver.py`)
Resuelve las consultas `tool_name + operation` contra el `CapabilityRegistry`. Si la herramienta u operación no existe o está bloqueada, devuelve un resultado estructurado `DENY`.

---

## Distinción: `ToolRegistry` vs `CapabilityRegistry`

- **`ToolRegistry` (`tools/registry.py`)**: Maneja el descubrimiento de instancias de herramientas en tiempo de ejecución (`BaseTool`) y la interfaz de MCP.
- **`CapabilityRegistry` (`core/capability_registry.py`)**: Maneja los metadatos declarativos de seguridad, niveles de riesgo, autorizaciones e invariantes del sistema.

---

## Capabilities Integradas Declarativas (`core/builtin_capabilities.py`)

Se registran únicamente metadatos declarativos sin lógica de ejecución real:
- `windows.files` (`list_directory`, `read_file`, `write_file`, `delete_file`)
- `windows.process` (`list_processes`, `get_process_info`, `terminate_process`)
- `windows.registry` (`read_registry`, `write_registry`)
- `windows.services` (`list_services`, `get_service_status`, `restart_service`)
- `windows.shell` (`execute_command`)
- `windows.desktop` (`take_screenshot`, `get_active_window`)
