# ETAPA 7: PLAN DE INTEGRACIÓN ARQUITECTÓNICA (PROPUESTA — NO EJECUTAR)

**Fecha de evaluación:** 2026-10-14  
**Rama:** `eval/gui-agents`  
**Estado:** **SOLO DISEÑO / PENDIENTE DE APROBACIÓN EXPLÍCITA DEL USUARIO**. Ninguna acción de este plan ha sido ejecutada en producción.

---

## 1. RESUMEN DE CAMBIOS NECESARIOS EN EL REPOSITORIO

Para adoptar la arquitectura complementaria ganadora (Opción C: Agent-S como cerebro de planificación semántica + CUA como sandbox headless en VPS + Gobernanza de Jessyca), se requieren los siguientes cambios modulares:

### A. Capa de Seguridad y Regla de Dos Modos (Canal WhatsApp)
1. **Creación de `core/security/channel_authority_guard.py`:**
   - Intercepta el origen del mensaje antes del despachador de habilidades (`SkillRouter`).
   - Si `channel == "whatsapp"` y el remitente **NO** cuenta con identidad verificada de dueño:
     - Bloquea incondicionalmente el catálogo de agentes de pantalla (`ScreenAgentSkill`, `ComputerUseAdapter`).
     - Habilita exclusivamente las herramientas seguras del CRM (APIs de consulta de stock, catálogo de productos, registro de leads).
   - Si el remitente es el **Dueño Verificado** (autenticado por número + firma/token de sesión):
     - Desbloquea la activación del agente de pantalla bajo confirmación de nivel 3 (`RiskLevel.HIGH`).

### B. Capa Cognitiva: Integración de Agent-S en `BaseSkill`
1. **Creación de `skills/screen_agent_skill.py` (`ScreenAgentSkill`):**
   - Implementa el contrato `BaseSkill` con identificador `screen.agent`.
   - Integra los principios de *Proactive Hierarchical Planning (PHP)* y *Mixture of Grounding (MoG)* del framework Apache 2.0 de `Agent-S` (`gui-agents` v0.3.2).
   - Descompone la meta del usuario en submetas atómicas guiadas por identificadores semánticos de accesibilidad (`AutomationId`, nombres de control, clases DOM).
   - Conecta cada submeta con `RiskEngine` antes de emitir cualquier acción física.

### C. Capa de Infraestructura: Adaptador CUA Headless para VPS
1. **Corrección de bugs en `skills/computer_use_skill.py`:**
   - Corregir la firma de llamada a `PermissionManager.check_permission(tool_name="windows.computer_use", operation=accion, parameters=params, risk_level=risk)`.
   - Evaluar correctamente la decisión de permiso comparando `perm_decision == PermissionDecision.ALLOW` en lugar del booleano crudo del enum.
2. **Evolución de `core/integration/adapters/computer_use_adapter.py` a Sandbox Remoto:**
   - Añadir soporte para backend de ejecución `CuaSandboxDriver` (vía `cua` SDK v0.4.1).
   - En el VPS, las órdenes de mouse y teclado no se inyectan en el host con `pyautogui`, sino que se despachan al contenedor Docker con display virtual `Xvfb`.
   - **Regla estricta de licencias:** Se prohíbe terminantemente la instalación del paquete `cua-perception` (para evitar la licencia restrictiva AGPL-3.0 de OmniParser). Toda la visión se resuelve con el modelo local limpio `qwen3-vl:4b` vía Ollama.

---

## 2. MATRIZ DE RIESGOS Y PLAN DE MITIGACIÓN

| Riesgo Técnico Identificado | Nivel de Impacto | Probabilidad | Plan de Mitigación Implementado |
| :--- | :---: | :---: | :--- |
| **Fuga de comandos del cliente al escritorio** | Catastrófico | Baja | Bloqueo a nivel de arquitectura en `ChannelAuthorityGuard` antes del router. El cliente no tiene la herramienta de pantalla en su catálogo. |
| **Alucinación o bucle ciego de clics** | Alto | Media | Límite máximo de pasos por tarea (`max_steps = 10`), detección de ambigüedad previa (`AWAITING_CLARIFICATION`) y política *Anti-False Success* de Jessyca. |
| **Consumo excesivo de recursos en VPS** | Medio | Baja | Driver en Rust (`cua-driver`) ultra-ligero (< 50 MB RAM); uso de árboles semánticos accesibles (UIA/DOM) para el 95% de tareas sin saturar la VRAM. |
| **Contaminación de licencia Copyleft (AGPL)** | Alto | Nula | Rechazo explícito de `cua-perception`. Solo se utilizan dependencias Apache 2.0 (`gui-agents`) y MIT (`cua` core). |
| **Pérdida de sesión gráfica en VPS headless** | Alto | Media | Uso de contenedor Docker con servidor X virtual (`Xvfb :99`) preconfigurado; no depende de sesiones interactivas de usuario ni de RDP activo. |

---

## 3. PLAN DE REVERSIÓN (ROLLBACK STRATEGY)

En caso de presentarse inestabilidad, excepciones no controladas o sobrecosto computacional tras la integración:

1. **Feature Flag de Desactivación Inmediata:**
   - En `config/settings.yaml`, definir:
     ```yaml
     gui_agent:
       enabled: false
       backend: "native_fallback"
     ```
   - Al establecer `enabled: false`, el orquestador degrada de inmediato a las habilidades deterministas nativas (`windows.apps`, `browser.*`), desactivando Agent-S y CUA sin requerir redeploys.
2. **Aislamiento en Git:**
   - La integración se realizará en una rama específica `feature/hybrid-gui-agent` y solo se fusionará a `main` tras una auditoría exhaustiva.
   - Tag de respaldo previo: `git tag backup-pre-gui-integration-v3.0`.
   - Rollback instantáneo: `git checkout main && git reset --hard backup-pre-gui-integration-v3.0`.

---

## 4. GUÍA DE DESPLIEGUE EN VPS (HEADLESS UBUNTU SERVER)

Pasos estructurados para configurar a Jessyca en el VPS sin pantalla:

### Paso 1: Configuración del Contenedor Sandbox (CUA Headless)
Crear un contenedor Docker aislado para ejecutar el navegador y aplicaciones de prueba:
```dockerfile
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    xvfb x11vnc fluxbox chromium-browser python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*
ENV DISPLAY=:99
CMD Xvfb :99 -screen 0 1920x1080x24 & fluxbox
```

### Paso 2: Instalación de Dependencias Python Limpias (Cero AGPL)
Instalar exclusivamente las librerías con licencias permisivas:
```bash
pip install gui-agents cua psutil
```

### Paso 3: Configuración de Modelos Locales en Ollama
En el VPS (o conectado al servidor de inferencia):
```bash
ollama pull gemma4:e4b
ollama pull qwen3-vl:4b
```

### Paso 4: Enrutador de Modos de WhatsApp
Configurar el webhook de mensajería para que verifique la firma criptográfica antes de despachar eventos a la capa `ChannelAuthorityGuard`.
