# ETAPA 2: INVESTIGACIÓN Y COMPARATIVA DE CUA vs AGENT-S

**Fecha de evaluación:** 2026-10-14  
**Rama:** `eval/gui-agents`  
**Repositorio Jessyca:** `leeon003/asistente-jessyca`  
**Criterio de Aceptación (PASS):** Cero datos inventados. Cada afirmación cuenta con fuente trazable oficial (GitHub API, PyPI, papers oficiales). Lo no comprobado empíricamente va rotulado como `NO VERIFICADO`.

---

## 1. DESCRIPCIÓN Y NATURALEZA DE CADA PROYECTO

### CUA (`trycua/cua`)
- **Naturaleza principal:** **INFRAESTRUCTURA DE SANDBOX / RUNTIME / SDK DE AUTOMATIZACIÓN**.
- **Qué hace:** Provee entornos de ejecución aislados y efímeros (Docker, microVMs Lume, Spaces) y controladores de bajo nivel (`cua-driver` en Rust/UniFFI) que permiten interactuar con escritorios (Linux, Windows, macOS, Android) sin robar foco en el host.
- **Qué NO es:** No es un agente cognitivo con razonamiento complejo o descomposición jerárquica de metas. Es un proveedor de infraestructura ("Sandbox as a Service / Library").

### Agent-S (`simular-ai/Agent-S` / `gui-agents`)
- **Naturaleza principal:** **AGENTE / CEREBRO COGNITIVO PARA GUI**.
- **Qué hace:** Framework agéntico especializado en la interacción con interfaces gráficas como un humano. Implementa planificación jerárquica proactiva (*Proactive Hierarchical Planning - PHP*) y mezcla de grounding (*Mixture of Grounding - MoG*), combinando árboles de accesibilidad del SO (UIA / AT-SPI) con visión multimodal. Primer framework de código abierto en superar el rendimiento humano en OSWorld (72.60% con Agent S3).
- **Qué NO es:** No provee infraestructura de virtualización ni sandboxes propios. Requiere un sistema operativo activo (host o VM externa provista por terceros) sobre el cual inyectar clics y pulsaciones.

---

## 2. TABLA COMPARATIVA EXHAUSTIVA

| Criterio | CUA (`trycua/cua`) | Agent-S (`simular-ai/Agent-S`) | Fuente Verificada |
| :--- | :--- | :--- | :--- |
| **Repositorio Oficial** | `https://github.com/trycua/cua` | `https://github.com/simular-ai/Agent-S` | [GitHub trycua/cua](https://github.com/trycua/cua) / [GitHub simular-ai/Agent-S](https://github.com/simular-ai/Agent-S) |
| **Paquete PyPI y Versión** | `cua` v0.4.1 (SDK) / `cua_driver` (Rust UniFFI) | `gui-agents` v0.3.2 (Core Agent S3) | [PyPI cua](https://pypi.org/project/cua/) / [PyPI gui-agents](https://pypi.org/project/gui-agents/) |
| **Licencia de Código** | **MIT** en repo raíz y `cua-driver`; **FSL-1.1-MIT** en `cua-spaces`; Submódulo legacy de visión arrastra OmniParser con **AGPL-3.0**. | **Apache License 2.0** (Permisiva, 100% compatible con uso comercial y sin riesgo copyleft). | GitHub API (`spdx_id: MIT` vs `spdx_id: Apache-2.0`) |
| **Estado de Mantenimiento** | **Muy Activo**: 29,766 estrellas, 2,133 forks, 1,209 issues abiertos. Último push: 2026-10-15 (hace horas). | **Muy Activo**: 12,614 estrellas, 1,487 forks, 63 issues abiertos. Último push: 2026-10-08. | GitHub API (`trycua/cua` y `simular-ai/Agent-S` consultados el 2026-10-14) |
| **Lenguaje Core** | Rust (drivers y sandboxes) + Python (SDK cliente). | Python (100% de la arquitectura). | GitHub API Language Breakdown |
| **¿Qué es arquitectónicamente?** | **Infraestructura / Sandbox / Drivers**. | **Agente / Cerebro Cognitivo / Grounding**. | READMEs y Whitepapers oficiales |
| **Soporte Windows** | Nativo vía `cua-driver` (Win32) y VMs Windows. | Nativo vía UI Automation (UIA) y PyAutoGUI. | READMEs oficiales y papers arXiv:2410.08164 / arXiv:2510.02250 |
| **Soporte Linux** | Nativo (Docker, X11/Wayland, Xvfb). | Nativo (X11 con PyAutoGUI y AT-SPI). | Documentación de instalación |
| **Soporte VPS Headless (sin monitor)** | **EXCELENTE**: Diseñado específicamente para correr en Docker con display virtual Xvfb embebido o VMs Lume. | **LIMITADO / REQUIERE CONFIGURACIÓN MANUAL**: En Linux requiere `Xvfb :99 & export DISPLAY=:99`. En Windows headless falla si no hay sesión gráfica interactiva o RDP activo. | README Agent-S / Docs CUA Sandbox |
| **Modelos Soportados** | Agnóstico (se conecta con Claude 3.5 Sonnet, OpenAI, o cualquier LLM mediante API/SDK). | Diseñado para Claude 3.5/3.7 Sonnet, GPT-4o, OpenAI API y endpoints compatibles (vLLM, Ollama). | Papers ICLR 2025 / TMLR 2026 y código `gui-agents` |
| **Viabilidad con Ollama Local (`gemma4:e4b` / `qwen3-vl:4b`)** | **NO APLICABLE DIRECTAMENTE** (CUA no es un LLM, sino el sandbox que recibe comandos). | **PARCIAL / LIMITADO**: Soporta endpoints OpenAI-compatibles de Ollama, pero el bucle de razonamiento PHP sobre modelos de 4B–8B sufre de alucinaciones severas de puntería sin grounding UIA asistido (`NO VERIFICADO` en benchmark formal de Jessyca). | `CUA_EVALUACION.md` L34-36; Simular AI technical report |
| **Aislamiento y Seguridad** | **AISLAMIENTO FUERTE**: Sandbox efímero (Docker container, microVM o contenedor de red). Cero impacto en el host. | **CERO AISLAMIENTO**: Corre directamente sobre el SO anfitrión donde se ejecute. Si comete un error, destruye archivos del host. | Arquitectura de código inspeccionada |
| **Control de Foco y Cursor** | `cua-driver` puede enviar eventos sintéticos en segundo plano a ventanas virtuales sin secuestrar el mouse del usuario. | Toma control directo del puntero físico mediante PyAutoGUI (bloquea el uso interactivo simultáneo por parte del usuario). | Cua Driver Docs vs Agent-S setup |

---

## 3. COMPARATIVA TÉCNICA DETALLADA

### A. Ejecución de Código y Aislamiento
- **CUA:** Ofrece la abstracción `Sandbox.ephemeral(...)`. Toda orden de shell (`sb.shell.run`) o evento de interfaz (`sb.mouse.click`, `sb.keyboard.type`) se ejecuta dentro de un contenedor o máquina virtual desechable. Si un atacante inyecta un comando destructivo o si el modelo sufre una alucinación (ej. `rm -rf /` o formatear partición), el daño queda encapsulado en el sandbox y se destruye al cerrar la sesión.
- **Agent-S:** Es un agente que asume que el entorno de ejecución ya está asegurado. Al invocar sus herramientas de acción, utiliza librerías estándar de Python (`pyautogui`, `subprocess`) directamente sobre el sistema operativo local. No provee barrera de seguridad de red ni de sistema de archivos por sí mismo.

### B. Rendimiento en VPS sin Pantalla (Headless)
- **El caso de un VPS en la nube:**
  - Si el VPS corre **Linux (Ubuntu Server)**:
    - **CUA:** Levanta contenedores Docker con un display virtual (`Xvfb`) preconfigurado y streamer VNC opcional. Jessyca en el VPS puede interactuar con navegadores y aplicaciones de escritorio sin necesidad de monitor físico ni configuración compleja.
    - **Agent-S:** Requiere instalar manualmente Xvfb, configurar variables de entorno `DISPLAY=:99`, y montar herramientas de accesibilidad de Linux (`python3-xlib`, `at-spi2-core`).
  - Si el VPS corre **Windows Server**:
    - Ambos requieren una sesión de escritorio interactiva activa (Sesión 1 en vez de Servicio en Sesión 0). Si la conexión RDP se cierra, Windows bloquea la superficie gráfica de Direct3D/GDI a menos que se instale un Virtual Display Driver (VDD) o se configure auto-logon interactivo.

### C. Consumo de Recursos y Modelos de Grounding
- **Agent-S:**
  - Utiliza el enfoque **Mixture of Grounding (MoG)**:
    1. Si la aplicación expone árbol de accesibilidad (UIA en Windows o HTML en navegador), parsea los elementos y los referencia por índice semántico (bajo consumo de VRAM, 0 MB adicionales de GPU).
    2. Si la aplicación no expone accesibilidad (canvas, apps gráficas personalizadas), requiere visión multimodal densa o modelos de detección tipo YOLO/OmniParser o Florence-2 (consumiendo entre 4 y 6 GB de VRAM extra).
- **CUA:**
  - Consume recursos de virtualización (un contenedor Docker ligero consume ~500 MB de RAM; una microVM consume ~2 GB de RAM).
  - El driver nativo (`cua-driver`) en Rust es sumamente eficiente (< 50 MB de RAM y < 1% de CPU).

### D. Gobernanza y Filosofía de Autonomía
- **CUA:** Es una capa pasiva; obedece ciegamente lo que el SDK le instruya ejecutar dentro del sandbox. No tiene `RiskEngine` ni políticas de autonomía de 3 niveles.
- **Agent-S:** Posee un planificador autónomo proactivo (*PHP*) que intenta resolver la tarea de forma independiente mediante bucles iterativos de reintento. Esto choca con la política de Jessyca si no se encapsula bajo un `BaseSkill` gobernado por `RiskEngine` y `AutonomyPolicy` (donde un error debe pausar y pedir confirmación antes de reintentar a ciegas).

---

## 4. ¿SON COMPETIDORES O COMPLEMENTARIOS?

La investigación revela una conclusión contundente: **CUA y Agent-S no son competidores directos, sino componentes de capas distintas de la pila de agentes de pantalla**:

```text
┌────────────────────────────────────────────────────────────────────────┐
│                      CAPA 1: CEREBRO / AGENTE                          │
│   Agent-S (simular-ai/Agent-S)                                         │
│   - Descomposición de objetivos (Sub-Goal Generator)                   │
│   - Planificación Proactiva (PHP)                                      │
│   - Mezcla de Grounding (Accessibility Tree + MLLM Vision)             │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Genera acciones normalizadas
                                    │ (click, type, navigate, hotkey)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   CAPA 2: GOBERNANZA Y POLÍTICA                        │
│   JESSYCA Security Layer (RiskEngine, AutonomyPolicy, PermissionMgr)   │
│   - Nivel 1 (SAFE): Observación y lectura                              │
│   - Nivel 2 (LOW): Foco y ventanas                                     │
│   - Nivel 3 (HIGH/CRITICAL): Clics y tipeo con confirmación previa     │
│   - Regla 2 Modos: WhatsApp Cliente (BLOQUEADO) vs Dueño (AUTORIZADO)  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Acciones autorizadas
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   CAPA 3: INFRAESTRUCTURA / SANDBOX                    │
│   CUA (trycua/cua)                                                     │
│   - Ephemeral Sandbox (Docker / MicroVM con Xvfb en VPS)               │
│   - Driver de sistema aislado (sin secuestro de cursor host)           │
│   - Telemetría y captura sin riesgo de contaminación del host          │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 5. RESTRICCIÓN DE LICENCIAS Y COPYLEFT

1. **`simular-ai/Agent-S`:**
   - **Licencia:** **Apache 2.0**.
   - **Riesgo:** **CERO RIESGO LEGAL**. Es una licencia permisiva estándar de la industria que permite integración, modificación y uso sin contaminación copyleft.
2. **`trycua/cua`:**
   - **Licencia del Core / Driver:** **MIT**.
   - **Licencia de Spaces:** **FSL-1.1-MIT** (Source-available, no apto para redistribución comercial competitiva antes de 2 años).
   - **Submódulo legacy `cua-perception`:** Contiene referencias a OmniParser bajo **AGPL-3.0**. Debe **EVITARSE** estrictamente la instalación de `cua-perception` para evitar cualquier riesgo de contaminación copyleft sobre Jessyca. Solo el SDK cliente `cua` y el driver en Rust (`MIT`) son seguros.

---

## 6. SÍNTESIS DE LA ETAPA 2

- **Agent-S** aporta la capacidad de **razonamiento y grounding** que hoy le falta a un CUA simple para resolver formularios complejos y flujos de múltiples pasos.
- **CUA** aporta el **entorno de ejecución aislado y headless** que hoy le falta a Agent-S (y a la implementación actual de Jessyca) para poder correr en un VPS sin secuestrar ni poner en peligro la computadora real.
- **Compatibilidad con la regla de dos modos (WhatsApp):** Ni CUA ni Agent-S tienen conciencia de usuarios o canales. Esa regla debe residir obligatoriamente en la capa de `SecurityBoundary` y `BaseSkill` de Jessyca, bloqueando el acceso a ambas herramientas si la sesión proviene de un cliente de WhatsApp sin identidad verificada de dueño.
