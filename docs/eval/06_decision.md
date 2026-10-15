# ETAPA 6: DECISIÓN Y MATRIZ PONDERADA (CUA vs AGENT-S)

**Fecha de evaluación:** 2026-10-14  
**Rama:** `eval/gui-agents`  
**Entregable:** Matriz ponderada de decisión y veredicto arquitectónico fundamentado en evidencia empírica.

---

## 1. MATRIZ PONDERADA DE DECISIÓN

Escala de evaluación: **1 (Muy Deficiente) a 5 (Excelente)**.  
Ponderación total: **100%**.

| Criterio | Peso | Opción A: Solo CUA | Opción B: Solo Agent-S | Opción C: Ambos con Roles Definidos | Justificación del Puntaje |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **1. Seguridad e Integración con RiskEngine / PermissionManager / AutonomyPolicy** | **30%** | **3.8** (1.14) | **4.2** (1.26) | **4.9** (1.47) | **CUA** provee sandbox fuerte pero en host corre con `FAILSAFE=False`. **Agent-S** se adapta mejor al modelo de metas semánticas de `AutonomyPolicy` pero carece de sandbox propio. **Opción C** combina el aislamiento de contenedor de CUA con la gobernanza semántica de Agent-S y la compuerta de dos modos de Jessyca. |
| **2. Tasa de Éxito y Eficiencia en Pruebas** | **25%** | **4.2** (1.05) | **4.8** (1.20) | **4.9** (1.22) | Ambos lograron 100% de éxito en sandbox gobernado, pero **Agent-S completó las tareas con un 25% menos de pasos** (54 vs 72 pasos) gracias a su Mixture of Grounding (MoG) y resolución semántica por IDs. |
| **3. Facilidad de Integración con BaseSkill / Orchestrator** | **15%** | **4.4** (0.66) | **4.0** (0.60) | **4.5** (0.68) | CUA ya tiene adaptador base en el repo (`ComputerUseAdapter`); Agent-S requiere integrar su bucle PHP en Python. La combinación desacopla la habilidad en un pipeline limpio: Cerebro (BaseSkill Agent-S) -> Compuerta de Seguridad -> Ejecutor (Sandbox CUA). |
| **4. Recursos y Viabilidad en VPS sin Pantalla (Headless)** | **15%** | **4.8** (0.72) | **3.5** (0.53) | **4.7** (0.71) | **CUA es el estándar de la industria para VPS headless** (Docker con virtual displays Xvfb preconfigurados y driver en Rust). Agent-S por sí solo no provee display virtual ni sandbox en VPS. |
| **5. Costo y Eficiencia de Tokens** | **10%** | **4.5** (0.45) | **4.0** (0.40) | **4.3** (0.43) | En modelos locales de Ollama (`gemma4:e4b`) el costo financiero es **$0.00 USD**. En tokens, CUA es más económico (7,695 vs 13,860 tokens), mientras que Agent-S invierte más tokens en planificar para ahorrar pasos físicos. |
| **6. Mantenimiento, Licencias y Comunidad** | **5%** | **4.4** (0.22) | **4.6** (0.23) | **4.6** (0.23) | CUA tiene 29.7k estrellas (MIT/Rust), pero riesgo copyleft en submódulo legacy `cua-perception` (AGPL). Agent-S tiene 12.6k estrellas y licencia **Apache 2.0 limpia y permisiva**. |
| **PUNTAJE PONDERADO TOTAL** | **100%** | **4.24 / 5.00** | **4.22 / 5.00** | **4.74 / 5.00** | **GANADOR: OPCIÓN C (AMBOS CON ROLES DEFINIDOS)** |

---

## 2. VEREDICTO ARQUITECTÓNICO FINAL

### **VEREDICTO: OPCIÓN C — USAR AMBOS CON ROLES DEFINIDOS**

La evidencia técnica y los benchmarks empíricos demuestran que elegir exclusivamente CUA o exclusivamente Agent-S generaría un desbalance arquitectónico crítico:
1. **Quedarse solo con CUA (Opción A):** Mantendría a Jessyca con un ejecutor ciego de bajo nivel. En modelos locales compactos (4B–8B), CUA sufre alucinaciones de puntería en formularios dinámicos y carece de planificación jerárquica para resolver problemas de múltiples pasos sin intervención humana continua.
2. **Cambiar solo a Agent-S (Opción B):** Dotaría a Jessyca de un cerebro SOTA de navegación GUI, pero **dejaría el sistema completamente desprotegido en el VPS**, ya que Agent-S carece de virtualización, no tiene sandbox nativo y no puede operar de forma aislada sin poner en riesgo los archivos y la sesión del host.
3. **La Solución Superior (Opción C):** Integrar una arquitectura complementaria desacoplada donde cada proyecto cumple exactamente la función para la que fue diseñado.

---

## 3. DEFINICIÓN DE ROLES EN LA ARQUITECTURA HÍBRIDA

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        ROL 1: AGENT-S (CEREBRO)                        │
│   Ubicación: skills/screen_agent_skill.py                              │
│   Responsabilidad:                                                     │
│   - Descomposición de metas en submetas (Proactive Hierarchical Plan)  │
│   - Inspección semántica de elementos (Mixture of Grounding / MoG)     │
│   - Detección de ambigüedad previa y recuperación ante popups          │
│   - Emite intenciones de acción normalizadas (Click ID, Type, Navigate)│
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               ROL 2: JESSYCA SECURITY LAYER (GOBERNANZA)               │
│   Ubicación: core/risk_engine.py / core/permission_manager.py          │
│   Responsabilidad:                                                     │
│   - Autenticación criptográfica de identidad (WhatsApp)               │
│   - REGLA DE DOS MODOS:                                                │
│     * Modo Cliente WhatsApp -> BLOQUEO TOTAL DE PANTALLA (DENY)        │
│     * Modo Dueño Verificado -> AUTORIZADO (Nivel 3 con confirmación)   │
│   - Intercepción de inyecciones y rutas críticas (SystemPathRiskRule)  │
│   - Parada de Emergencia (EmergencyStopManager < 100 ms)               │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   ROL 3: CUA (INFRAESTRUCTURA & SANDBOX)               │
│   Ubicación: core/integration/adapters/cua_sandbox_adapter.py          │
│   Responsabilidad:                                                     │
│   - Despliegue de Sandbox efímero en VPS (Docker con display Xvfb)    │
│   - Driver en segundo plano (cua-driver UniFFI) sin robar foco         │
│   - Aislamiento absoluto de red y sistema de archivos del host         │
│   - Despacho de clics y capturas de pantalla de telemetría             │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 4. VERIFICACIÓN DE LA REGLA DE LOS DOS MODOS

La Opción C garantiza el cumplimiento estricto de la regla de diseño para el VPS y WhatsApp:

1. **Modo Cliente (Ventas por WhatsApp):**
   - El canal de mensajería identifica que el remitente es un cliente externo (`user_identity != "verified_owner"` o `is_client_mode = True`).
   - El orquestador de Jessyca **únicamente carga y despacha herramientas del CRM por API** (ej. consultas de stock, cotizaciones, registro de pedidos).
   - Cualquier intento de invocar la skill de pantalla (`eval.agent_s` o `eval.cua`) es rechazado en la primera línea de código con `AuditEventType.EXECUTION_DENIED` y veredicto `DENY`, sin instanciar el sandbox ni consumir GPU/VRAM.

2. **Modo Dueño (Control Remoto desde WhatsApp):**
   - Requiere autenticación de identidad verificada del dueño (número telefónico verificado + token/firma criptográfica o palabra clave de pase).
   - Únicamente tras superar la compuerta de autenticación, el orquestador permite la activación de la habilidad de pantalla.
   - Las acciones de pantalla se ejecutan **dentro del sandbox aislado de CUA en el VPS**, garantizando que incluso ante una alucinación o error de navegación, los archivos del servidor y la máquina física permanezcan 100% protegidos.
