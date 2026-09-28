# JESSYCA PC — ANÁLISIS DE BRECHAS TÉCNICAS (GAP ANALYSIS)
**Fecha:** 2026-09-27  
**Sistema:** JESSYCA PC  
**Alcance:** Detección de vacíos técnicos reales en el código base, infraestructura y gobernanza.

---

## 1. RESUMEN DE BRECHAS POR SUBSISTEMA

| Categoría | Brecha Detectada | Evidencia en Código | Impacto | Dependencia | Prioridad Técnica |
| :--- | :--- | :--- | :--- | :--- | :---: |
| **DECISION** | El bucle principal de diálogo del agente opera JDE en modo Shadow pasivo en lugar de Full Authority síncrono. | `agent.py` llama a `_observe_shadow_turn()` hacia `JDEShadowAdapter` en lugar de interceptar y bloquear con `JDEEngine.evaluate()`. | Las decisiones del agente no están forzadas síncronamente por el JDE durante el flujo conversacional estándar. | JDE Phase 8 (ya certificado) | **P0 (Crítica)** |
| **AGENT / REASONING**| ARE está implementado pero deshabilitado por configuración (`are.enabled=False`) y no está conectado al ciclo de vida del agente. | `config/settings.py` línea con flag `enabled: False`. `agent.py` no invoca `are_adapter`. | Tareas multi-paso complejas carecen de diagnóstico formal y re-planificación automática ante fallos. | `are_adapter.py` (ya existe) | **P1 (Alta)** |
| **TOOLS / DOCUMENTS**| `skills/documents_skills.py` sigue registrado como fallback y puede competir con `core/anydoc/`. | `skills/documents_skills.py` coexiste con el adaptador certificado de AnyDoc en el registro de herramientas. | Duplicidad de herramientas para procesamiento de documentos. | AnyDoc Phase 3 (ya certificado) | **P2 (Media)** |
| **MODEL ROUTING** | Model Router permanece en modo `shadow` en `.env` sin activar el enrutamiento dinámico productivo. | `.env` contiene `MODEL_ROUTER_MODE=shadow` y `MODEL_ROUTER_ENABLED=false` en defaults de `settings.py`. | No se optimiza el consumo de VRAM ni la latencia al enviar prompts pesados a modelos pequeños. | Ollama / Local Models | **P2 (Media)** |
| **COMPUTER USE** | `computer_use_adapter.py` carece de capa de visión multimodal integrada para validar visualmente la pantalla antes del clic. | `computer_use_adapter.py` solo ejecuta `pyautogui.click(x, y)` basado en coordenadas estáticas sin bounding boxes de visión. | Alto riesgo de clics erróneos si la resolución o posición de la ventana cambia. | Modelo VLM (Ollama / LLaVA) | **P3 (Baja)** |
| **MOBILE** | No existe frontend móvil en este repositorio; solo el backend REST en puerto 8765. | `interfaces/mobile_api/` tiene endpoints FastAPI, pero no hay código Flutter/React Native/Android. | El usuario móvil depende de un proyecto externo no versionado aquí. | Mobile API (ya funcional) | **P2 (Media)** |
| **WEB / UI** | Despliegue fragmentado de dos servidores ASGI independientes (`webui_bridge` en 8088 y `mobile_api` en 8765). | Dos carpetas en `interfaces/` con scripts de inicio independientes. | Mayor complejidad de supervisión de procesos y puertos de red abiertos. | Uvicorn / FastAPI | **P3 (Baja)** |
| **VOICE** | Falta integración nativa de hotword offline permanente de ultra bajo consumo para despertar al asistente. | `services/voice_service.py` depende de escucha continua con VAD o trigger manual. | Mayor consumo de CPU/GPU en reposo auditivo. | PocketSphinx / Porcupine | **P3 (Baja)** |
| **SECURITY** | Las políticas de confirmación para herramientas de alto riesgo dependen de listas estáticas en lugar de inferencia dinámica del JDE. | `core/security/confirmation_manager.py` evalúa patrones predefinidos en lugar de consultar la matriz de riesgo del JDE. | Riesgo de desalineación entre la evaluación de riesgo de JDE y el prompt de confirmación. | JDE Full Authority | **P1 (Alta)** |
| **OBSERVABILITY** | Los receipts de ejecución del JDE, logs de auditoría y trazas de ORCA se almacenan en múltiples archivos dispersos. | Logs en `logs/`, receipts en `reports/`, shadow divergence en archivos `.jsonl` independientes. | Dificultad para correlacionar una interacción de usuario con todos sus eventos en una sola vista. | Sistema de logging unificado | **P2 (Media)** |
| **TESTING** | A pesar de contar con 3,480 tests unitarios y de componentes, no hay un test E2E que ejecute en un solo turno: WebUI -> Agent -> JDE Full -> ARE -> ORCA -> AnyDoc. | Tests existentes prueban módulos individuales o pares (ej. ORCA+JDE, AnyDoc+Security), pero no la cadena completa. | Riesgo de incompatibilidad de interfaces entre subsistemas certificados de forma aislada. | Unificación de interfaces | **P1 (Alta)** |
| **DOCUMENTATION** | Persistencia de menciones históricas a componentes inexistentes (Mark-LIV, Hermes) en planes o notas informales. | Referencias verbales en prompts de usuario o especificaciones pasadas no cotejadas con el código. | Desgaste cognitivo y confusión en auditorías y roadmaps. | Auditoría Maestra | **P2 (Media)** |

---

## 2. ANÁLISIS DE PRIORIDADES PARA EL PLAN DE ACCIÓN

### Bloqueadores Críticos (P0)
1. **Elevación de JDE en el Bucle Principal del Agente:**  
   Actualmente JDE Phase 8 está certificado como subsistema independiente, pero en `agent.py` se invoca únicamente como un observador en modo `shadow`. La autoridad real sobre las herramientas en el día a día sigue en manos del enrutador de herramientas convencional. Para que la promesa de "JDE FULL AUTHORITY" sea una realidad operativa, el despacho de herramientas en `JessycaLocalAgent` debe consultar de manera obligatoria y síncrona el veredicto del JDE.

### Prioridades Altas (P1)
2. **Activación y Certificación de ARE:**  
   Dado que `core/integration/adapters/are_adapter.py` ya existe y sus 28 tests pasan al 100%, la brecha no es de desarrollo de software, sino de integración arquitectónica. Debe crearse el puente entre `JessycaLocalAgent` y `ARE` para que las tareas complejas se beneficien de su capacidad de descomposición y diagnóstico de fallos.
3. **Test E2E de Cadena Completa:**  
   Unificar en una prueba de integración end-to-end la cadena completa de subsistemas ya certificados.
