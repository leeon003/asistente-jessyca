# BROWSER AGENT — JESSYCA 3.0 (FASE 14)

## 1. Arquitectura del Agente de Navegación

El `BrowserAgent` (`core/agents/browser_agent.py`) evoluciona la frontera `BrowserSessionManager` hacia un agente especializado autónomo gobernado estrictamente por `ControlledAgentLoop` sobre el navegador **Microsoft Edge** (`msedge.exe`):

```text
┌─────────────────────────────────────────────────────────────┐
│                      Intención Usuario                      │
│             ("abre YouTube", "busca información")           │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                        AgentRouter                          │
│                   (Enruta a BrowserAgent)                   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                        BrowserAgent                         │
│                 (BaseSpecializedAgent)                      │
│  Capabilities: NAVIGATE, READ, CLICK, TYPE, SUBMIT, SCROLL │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                       BrowserPolicy                         │
│  • Whitelist URLs (Deny-by-Default)                         │
│  • Session Secrets Redaction (Cero tokens/cookies al LLM)   │
│  • Download Control (Prohibido auto-ejecutar binarios)      │
│  • Purchase / Checkout Escalation                           │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                    ControlledAgentLoop                      │
│   (OBSERVE -> INTERPRET -> PLAN -> SECURITY CHECK -> ACT)   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                       Microsoft Edge                        │
│             (Selenium WebDriver / CDP Adapter)              │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Garantías y Políticas de Seguridad (`BrowserPolicy`)

1. **Navegador Exclusivo**: Microsoft Edge (`msedge.exe`). NO se utiliza Chrome ni navegadores no autorizados.
2. **`URL != TRUSTED DATA`**:
   - Deny-by-Default: Solo dominios autorizados en `URLAllowlistPolicy` (`youtube.com`, `google.com`, `wikipedia.org`, etc.).
   - Bloqueo estricto de esquemas peligrosos: `javascript:`, `file:`, `data:`, `about:`, `chrome:`.
   - NUNCA se confía en el LLM para decidir si una URL es segura.
3. **Session Security (Anti-Leakage)**:
   - Sanitización y redacción automática de contraseñas (`[REDACTED_PASSWORD]`), tokens Bearer (`[REDACTED_TOKEN]`), cookies y secretos de sesión antes de que el texto del DOM sea expuesto al LLM.
4. **Control de Descargas**:
   - Bloqueo de extensiones ejecutables peligrosas (`.exe`, `.bat`, `.cmd`, `.ps1`, `.vbs`, `.msi`, `.dll`).
   - Cero auto-ejecución de archivos descargados.
5. **Barrera contra Compras y Transacciones**:
   - `NAVEGACIÓN != AUTORIZACIÓN DE COMPRA`.
   - Intenciones transaccionales ("comprar", "checkout", "pagar", "tarjeta") detienen el ciclo de forma determinista y exigen confirmación explícita de usuario vía `SecurityPipeline`.

---

## 3. Capacidades Granulares (`core/agents/browser_capabilities.py`)

- `BROWSER_NAVIGATE`
- `BROWSER_READ`
- `BROWSER_CLICK`
- `BROWSER_TYPE`
- `BROWSER_SUBMIT`
- `BROWSER_BACK`
- `BROWSER_SCROLL`

---

## 4. Resultados de Verificación

| Métrica / Suite | Pruebas | Resultado |
|:---|:---:|:---:|
| **`pytest tests/agents/test_browser_agent.py`** | 8 pruebas (navegación Edge, esquemas bloqueados, dominios no autorizados, sanitización DOM, descargas, transacciones, emergency stop, routing) | ✅ **8 / 8 PASS** |
| **`pytest tests/agents/`** | 32 pruebas de agentes | ✅ **32 / 32 PASS** |
| **`ruff check`** | `core/agents/`, `tests/agents/` | ✅ **All checks passed!** |
| **`mypy`** | Tipado estático de agentes | ✅ **0 errores en el paquete** |
