# JESSYCA PC — ANYDOC FASE 1 DEPENDENCY AUDIT

## 1. RUNTIMES EVALUADOS
* **Python Runtime:** Python 3.11.9 (64-bit Windows) — **SELECCIONADO COMO PRIMARIO**
  * La rueda binaria precompilada (`firecrawl_anydoc-0.2.4-cp310-abi3-win_amd64.whl`) utiliza CPython Stable ABI 3.10+, permitiendo ejecución nativa en Python 3.11 sin necesidad de toolchain Rust local instalado.
* **Node.js Runtime:** Node v24.5.0, npm 11.5.1
  * Paquete `@firecrawl/anydoc` disponible vía npm / npx con soporte binario `@firecrawl/anydoc-win32-x64-msvc`.
* **Rust Toolchain:** `cargo` y `rustc` no están instalados globalmente en la máquina, pero no son requeridos gracias a las ruedas precompiladas ABI3.

## 2. AGENT SKILL EVALUADO
* **Ubicación:** `skills/convert-documents-to-markdown/SKILL.md`
* **Instrucciones:** Especifica ejecución mediante `npx -y @firecrawl/anydoc <file>`.
* **Riesgo Identificado:** Invocar `npx -y` en runtime requiere acceso a internet si no está en caché y permite ejecución no confinada de Node.
* **Dictamen:** No se instala globalmente. En su lugar, el `AnyDocAdapter` de Python es el punto de integración auditado y seguro.
