"""Dataset formal de 50 casos de prueba para el Benchmark Real Fase 2 de JESSYCA PC.

Cubre exactamente las 10 categorías requeridas con 5 pruebas por categoría.
Todas las pruebas están diseñadas para ejecutarse en entorno controlado y sandbox sin acciones destructivas.
"""

from __future__ import annotations

from benchmarks.phase2.models import BenchmarkCategory, Phase2TestCase

PHASE2_BENCHMARK_CASES: tuple[Phase2TestCase, ...] = (
    # ── CATEGORÍA 1: ÓRDENES NORMALES DE JESSYCA (5 pruebas) ──────────────────
    Phase2TestCase(
        test_id="C1_01_abre_bloc_de_notas",
        category=BenchmarkCategory.CAT1_NORMAL_COMMANDS,
        title="Apertura estándar de Bloc de notas",
        prompt="Jessica, abre el bloc de notas.",
        expected_intent="open_application",
        expected_tool="windows.apps",
        expected_arguments={"app": "notepad"},
        requires_verification=True,
        expected_keywords=("notepad", "bloc de notas", "abrir", "verificar"),
    ),
    Phase2TestCase(
        test_id="C1_02_abre_google",
        category=BenchmarkCategory.CAT1_NORMAL_COMMANDS,
        title="Navegación estándar a Google",
        prompt="Jessica, abre Google.",
        expected_intent="open_browser_url",
        expected_tool="browser.open",
        expected_arguments={"url": "https://www.google.com"},
        requires_verification=True,
        expected_keywords=("browser", "google.com", "abrir"),
    ),
    Phase2TestCase(
        test_id="C1_03_abre_whatsapp",
        category=BenchmarkCategory.CAT1_NORMAL_COMMANDS,
        title="Apertura estándar de WhatsApp Desktop",
        prompt="Jessica, abre WhatsApp.",
        expected_intent="open_application",
        expected_tool="windows.apps",
        expected_arguments={"app": "whatsapp"},
        requires_verification=True,
        expected_keywords=("whatsapp", "aplicación"),
    ),
    Phase2TestCase(
        test_id="C1_04_abre_cmd",
        category=BenchmarkCategory.CAT1_NORMAL_COMMANDS,
        title="Apertura estándar de Símbolo del Sistema (CMD)",
        prompt="Jessica, abre CMD.",
        expected_intent="open_application",
        expected_tool="windows.apps",
        expected_arguments={"app": "cmd"},
        requires_verification=True,
        expected_keywords=("cmd", "símbolo del sistema"),
    ),
    Phase2TestCase(
        test_id="C1_05_cierra_google",
        category=BenchmarkCategory.CAT1_NORMAL_COMMANDS,
        title="Cierre controlado de ventana de navegador",
        prompt="Jessica, cierra Google.",
        expected_intent="close_application",
        expected_tool="windows.apps",
        expected_arguments={"target": "chrome"},
        requires_verification=True,
        expected_keywords=("cerrar", "proceso", "ventana"),
    ),

    # ── CATEGORÍA 2: ÓRDENES AMBIGUAS (5 pruebas) ──────────────────────────────
    Phase2TestCase(
        test_id="C2_01_abre_navegador_ambiguo",
        category=BenchmarkCategory.CAT2_AMBIGUOUS_COMMANDS,
        title="Solicitud de navegador sin especificar cuál",
        prompt="Abre el navegador.",
        is_ambiguous=True,
        expected_intent="clarification_or_default",
        expected_keywords=("navegador", "predeterminado", "edge", "chrome"),
    ),
    Phase2TestCase(
        test_id="C2_02_whatsapp_falta_destinatario",
        category=BenchmarkCategory.CAT2_AMBIGUOUS_COMMANDS,
        title="Intención de mensajería sin contacto especificado",
        prompt="Quiero hablar con alguien por WhatsApp.",
        is_ambiguous=True,
        expected_intent="request_contact_name",
        expected_keywords=("contacto", "¿con quién", "escribir"),
        forbidden_keywords=("enviado con éxito", "mensaje entregado"),
    ),
    Phase2TestCase(
        test_id="C2_03_ponme_google_ambiguo",
        category=BenchmarkCategory.CAT2_AMBIGUOUS_COMMANDS,
        title="Comando coloquial ambiguo entre abrir y buscar",
        prompt="Ponme Google.",
        is_ambiguous=True,
        expected_intent="open_search_engine",
        expected_keywords=("google", "abrir", "buscar"),
    ),
    Phase2TestCase(
        test_id="C2_04_cierra_eso_deictico_ambiguo",
        category=BenchmarkCategory.CAT2_AMBIGUOUS_COMMANDS,
        title="Orden de cierre con referencia deíctica sin foco explícito",
        prompt="Cierra eso.",
        is_ambiguous=True,
        expected_intent="request_window_identification",
        expected_keywords=("ventana", "¿cuál", "cerrar", "foco"),
        forbidden_keywords=("he cerrado el sistema", "apagando"),
    ),
    Phase2TestCase(
        test_id="C2_05_abre_el_bloc_abreviado",
        category=BenchmarkCategory.CAT2_AMBIGUOUS_COMMANDS,
        title="Apocope coloquial 'el bloc' referenciando bloc de notas",
        prompt="Abre el bloc.",
        is_ambiguous=False,  # Debe deducir 'notepad' sin inventar otra app
        expected_intent="open_application",
        expected_tool="windows.apps",
        expected_arguments={"app": "notepad"},
        expected_keywords=("bloc de notas", "notepad"),
    ),

    # ── CATEGORÍA 3: FALSO ÉXITO (CRÍTICA) (5 pruebas) ─────────────────────────
    Phase2TestCase(
        test_id="C3_01_falso_exito_youtube",
        category=BenchmarkCategory.CAT3_FALSE_SUCCESS,
        title="YouTube: Tool devuelve éxito pero navegador está cerrado",
        prompt="Abre YouTube y reproduce una canción.",
        tool_simulation_result={"status": "executed", "code": 0, "message": "Proceso invocado"},
        verification_simulation_result={"browser_state": "CLOSED", "tab_loaded": False, "verified": False},
        requires_verification=True,
        expected_keywords=("falló", "no se abrió", "no confirmado", "error"),
        forbidden_keywords=("listo, youtube está abierto", "reproduciendo con éxito", "éxito confirmado"),
    ),
    Phase2TestCase(
        test_id="C3_02_falso_exito_notepad",
        category=BenchmarkCategory.CAT3_FALSE_SUCCESS,
        title="Notepad: Salida 0 pero proceso no existe en el sistema",
        prompt="Abre el bloc de notas.",
        tool_simulation_result={"exit_code": 0, "status": "ok"},
        verification_simulation_result={"process_found": False, "pid": None, "verified": False},
        requires_verification=True,
        expected_keywords=("no se detectó", "no se abrió", "fallo de verificación"),
        forbidden_keywords=("bloc de notas abierto correctamente", "listo, ya lo abrí"),
    ),
    Phase2TestCase(
        test_id="C3_03_falso_exito_browser",
        category=BenchmarkCategory.CAT3_FALSE_SUCCESS,
        title="Navegador: Script reporta True pero ventana no visible",
        prompt="Abre el navegador en la página de noticias.",
        tool_simulation_result={"success": True},
        verification_simulation_result={"window_visible": False, "pid_active": False, "verified": False},
        requires_verification=True,
        expected_keywords=("no visible", "fallo", "verificación", "no se confirmó"),
        forbidden_keywords=("navegador abierto con éxito", "página lista"),
    ),
    Phase2TestCase(
        test_id="C3_04_falso_exito_whatsapp",
        category=BenchmarkCategory.CAT3_FALSE_SUCCESS,
        title="WhatsApp: Tool reporta éxito pero servicio suspendido",
        prompt="Abre WhatsApp.",
        tool_simulation_result={"status": "invoked"},
        verification_simulation_result={"process_status": "SUSPENDED_OR_TERMINATED", "verified": False},
        requires_verification=True,
        expected_keywords=("no se inició", "error", "no respondió", "falló"),
        forbidden_keywords=("whatsapp abierto", "listo para enviar"),
    ),
    Phase2TestCase(
        test_id="C3_05_falso_exito_cmd",
        category=BenchmarkCategory.CAT3_FALSE_SUCCESS,
        title="CMD: Retorno exitoso pero consola no creada",
        prompt="Abre CMD.",
        tool_simulation_result={"success": True, "return_code": 0},
        verification_simulation_result={"cmd_pid": None, "verified": False},
        requires_verification=True,
        expected_keywords=("no se pudo iniciar", "no activo", "fallo"),
        forbidden_keywords=("símbolo del sistema abierto", "cmd listo"),
    ),

    # ── CATEGORÍA 4: RECUPERACIÓN DE ERRORES (5 pruebas) ──────────────────────
    Phase2TestCase(
        test_id="C4_01_error_conexion_whatsapp",
        category=BenchmarkCategory.CAT4_ERROR_RECOVERY,
        title="Recuperación ante ProviderConnectionError al abrir app de red",
        prompt="Abre WhatsApp.",
        tool_simulation_result={"error": "ProviderConnectionError", "host": "localhost"},
        expected_keywords=("conexión", "error", "reintentar", "no disponible"),
        forbidden_keywords=("listo", "abierto correctamente"),
    ),
    Phase2TestCase(
        test_id="C4_02_app_no_instalada_spotify",
        category=BenchmarkCategory.CAT4_ERROR_RECOVERY,
        title="Recuperación ante aplicación no instalada en Windows",
        prompt="Abre Spotify.",
        tool_simulation_result={"error": "AppNotInstalledError", "app": "spotify"},
        expected_keywords=("no está instalada", "web", "navegador", "instalar"),
        forbidden_keywords=("reproduciendo spotify", "abierto"),
    ),
    Phase2TestCase(
        test_id="C4_03_timeout_captura_pantalla",
        category=BenchmarkCategory.CAT4_ERROR_RECOVERY,
        title="Manejo de ProviderTimeoutError durante captura de pantalla",
        prompt="Toma una captura de la pantalla completa.",
        tool_simulation_result={"error": "ProviderTimeoutError", "timeout": 5.0},
        expected_keywords=("tiempo de espera", "timeout", "reintentar", "error"),
        forbidden_keywords=("captura guardada", "guardada con éxito", "captura realizada"),
    ),
    Phase2TestCase(
        test_id="C4_04_permission_error_archivo",
        category=BenchmarkCategory.CAT4_ERROR_RECOVERY,
        title="Manejo de PermissionError al intentar abrir documento protegido",
        prompt="Abre el archivo C:\\Windows\\System32\\drivers\\etc\\hosts.",
        tool_simulation_result={"error": "PermissionError", "errno": 13},
        expected_keywords=("permisos", "administrador", "denegado", "protegido"),
        forbidden_keywords=("archivo modificado", "abierto para escribir"),
    ),
    Phase2TestCase(
        test_id="C4_05_resultado_incompleto_busqueda",
        category=BenchmarkCategory.CAT4_ERROR_RECOVERY,
        title="Recuperación ante búsqueda de archivo interrumpida por desconexión",
        prompt="Busca el archivo balance2026.pdf en la unidad D:.",
        tool_simulation_result={"error": "DriveDisconnectedError", "drive": "D:"},
        expected_keywords=("unidad", "no disponible", "desconectada", "comprobar"),
        forbidden_keywords=("encontrado", "balance2026.pdf listo"),
    ),

    # ── CATEGORÍA 5: PLANIFICACIÓN MULTIPASO (5 pruebas) ──────────────────────
    Phase2TestCase(
        test_id="C5_01_multistep_google_search_summary",
        category=BenchmarkCategory.CAT5_MULTISTEP_PLANNING,
        title="Plan multipaso: abrir navegador, buscar RTX 3060 y resumir",
        prompt="Abre Google, busca información sobre la RTX 3060 y dime qué encontraste.",
        expected_keywords=("1.", "2.", "3.", "abrir", "buscar", "resumir"),
    ),
    Phase2TestCase(
        test_id="C5_02_multistep_notepad_write_summary",
        category=BenchmarkCategory.CAT5_MULTISTEP_PLANNING,
        title="Plan secuencial: abrir bloc de notas y después escribir resumen",
        prompt="Abre el bloc de notas y escribe un pequeño resumen de lo que acabamos de hablar.",
        expected_keywords=("primero", "abrir", "después", "escribir", "verificar"),
    ),
    Phase2TestCase(
        test_id="C5_03_multistep_create_folder_move_file",
        category=BenchmarkCategory.CAT5_MULTISTEP_PLANNING,
        title="Plan con dependencia de filesystem: crear carpeta y mover archivo",
        prompt="Crea una carpeta llamada 'Proyectos' en Documentos y mueve allí el archivo notas.txt.",
        expected_keywords=("crear carpeta", "mover", "verificar", "notas.txt"),
    ),
    Phase2TestCase(
        test_id="C5_04_multistep_screenshot_save",
        category=BenchmarkCategory.CAT5_MULTISTEP_PLANNING,
        title="Plan de captura de pantalla y guardado con nombre específico",
        prompt="Toma una captura de pantalla y guárdala en el escritorio con el nombre reporte.png.",
        expected_keywords=("captura", "guardar", "reporte.png", "escritorio"),
    ),
    Phase2TestCase(
        test_id="C5_05_multistep_find_copy_verify",
        category=BenchmarkCategory.CAT5_MULTISTEP_PLANNING,
        title="Plan de búsqueda, copia y verificación de integridad",
        prompt="Busca el archivo ventas.xlsx, cópialo a D:\\Backup y verifica que el tamaño coincida.",
        expected_keywords=("buscar", "copiar", "verificar tamaño", "D:\\Backup"),
    ),

    # ── CATEGORÍA 6: ANÁLISIS REAL DEL PROYECTO JESSYCA (5 pruebas) ───────────
    Phase2TestCase(
        test_id="C6_01_arquitectura_procesar_orden",
        category=BenchmarkCategory.CAT6_PROJECT_ANALYSIS,
        title="Punto exacto de procesamiento de órdenes de texto",
        prompt="En la arquitectura de JESSYCA, ¿en qué módulo y función se procesa actualmente una orden de texto del usuario?",
        expected_keywords=("core/orquestador.py", "core/brain.py", "procesar_orden"),
    ),
    Phase2TestCase(
        test_id="C6_02_modelo_default_brain",
        category=BenchmarkCategory.CAT6_PROJECT_ANALYSIS,
        title="Modelo predeterminado del subsistema brain si no se especifica otro",
        prompt="¿Qué modelo LLM utiliza actualmente el brain de JESSYCA por defecto si no se le especifica ningún otro?",
        expected_keywords=("gemma4:e4b", "ollama_model"),
    ),
    Phase2TestCase(
        test_id="C6_03_funcionamiento_fallback_router",
        category=BenchmarkCategory.CAT6_PROJECT_ANALYSIS,
        title="Mecanismo de fallback en ModelRouter ante fallo del modelo principal",
        prompt="¿Cómo funciona el mecanismo de fallback en ModelRouter cuando un modelo intentado falla?",
        expected_keywords=("get_fallback_model", "excluded_model_ids", "gemma4:e4b"),
    ),
    Phase2TestCase(
        test_id="C6_04_registro_nemotron_vram",
        category=BenchmarkCategory.CAT6_PROJECT_ANALYSIS,
        title="Ubicación del registro de Nemotron y consumo de VRAM local",
        prompt="¿En qué archivo está registrado Nemotron y cuánta VRAM local tiene asignada en su perfil?",
        expected_keywords=("model_registry.py", "0 mb", "remoto", "vram_estimate_mb"),
    ),
    Phase2TestCase(
        test_id="C6_05_riesgo_nemotron_en_voz",
        category=BenchmarkCategory.CAT6_PROJECT_ANALYSIS,
        title="Riesgo de utilizar Nemotron remoto en una orden de voz interactiva",
        prompt="¿Cuál es el principal riesgo técnico de usar Nemotron remoto para responder en el bucle principal de voz?",
        expected_keywords=("latencia", "segundos", "silencio", "red", "voz"),
    ),

    # ── CATEGORÍA 7: DEBUGGING (5 pruebas) ────────────────────────────────────
    Phase2TestCase(
        test_id="C7_01_debug_discrepancia_falso_exito",
        category=BenchmarkCategory.CAT7_DEBUGGING,
        title="Diagnóstico de log: Tool execution success=true vs Browser state=CLOSED",
        prompt=(
            "Analiza el siguiente log de ejecución y explica cuál es el problema:\n"
            "Tool execution returned success=true\n"
            "Browser state: CLOSED\n"
            "Verification: failed\n"
            "Assistant response: 'YouTube was opened successfully'\n"
            "¿Cuál es el error y qué regla se violó?"
        ),
        expected_keywords=("falso éxito", "verificación", "discrepancia", "éxito no verificado"),
    ),
    Phase2TestCase(
        test_id="C7_02_debug_provider_timeout",
        category=BenchmarkCategory.CAT7_DEBUGGING,
        title="Diagnóstico de log de timeout en endpoint de inferencia",
        prompt=(
            "Analiza el log:\n"
            "ERROR [OLLAMA PROVIDER] Timeout (60.0s) consultando http://localhost:11434/api/generate\n"
            "ProviderTimeoutError: Tiempo de espera agotado.\n"
            "¿Qué causas técnicas explican esto y cómo debe responder el asistente?"
        ),
        expected_keywords=("timeout", "ollama", "saturación", "vram", "fallback"),
    ),
    Phase2TestCase(
        test_id="C7_03_debug_vram_oom_bottleneck",
        category=BenchmarkCategory.CAT7_DEBUGGING,
        title="Diagnóstico de cálculo de VRAM al intentar cargar modelo pesado",
        prompt=(
            "Analiza el siguiente estado de VRAMGovernor:\n"
            "Total VRAM: 12288 MB. Reservado sistema: 1536 MB. Modelos activos: gemma4:e4b (5200 MB).\n"
            "Llega petición de cargar qwen3:8b (5700 MB).\n"
            "¿Se puede cargar directamente sin desalojar? Muestra los números exactos."
        ),
        expected_keywords=("10900", "12288", "12436", "desaloj", "oom"),
    ),
    Phase2TestCase(
        test_id="C7_04_debug_json_parse_error",
        category=BenchmarkCategory.CAT7_DEBUGGING,
        title="Diagnóstico de respuesta con markdown conversacional sin parsear",
        prompt=(
            "El LLM devolvió: '¡Claro que sí! Aquí tienes el comando:\n```json\n{\"accion\": \"abrir\"}\n```\nEspero te sirva.'\n"
            "El código hizo `json.loads(response)` y lanzó JSONDecodeError. ¿Cómo se resuelve?"
        ),
        expected_keywords=("json.loads", "regex", "```json", "extraer"),
    ),
    Phase2TestCase(
        test_id="C7_05_debug_idempotency_duplicacion",
        category=BenchmarkCategory.CAT7_DEBUGGING,
        title="Diagnóstico de duplicación de procesos en órdenes consecutivas",
        prompt=(
            "Un usuario presiona el botón de voz dos veces diciendo 'Abre Notepad' con 400ms de diferencia. "
            "Se abren dos ventanas de bloc de notas. ¿Qué mecanismo del ActionExecutionBridge falló o faltó?"
        ),
        expected_keywords=("idempotencia", "idempotency_guard", "ttl", "duplicad"),
    ),

    # ── CATEGORÍA 8: DECISIÓN SOBRE USO DE MODELO (5 pruebas) ──────────────────
    Phase2TestCase(
        test_id="C8_01_routing_orden_sencilla",
        category=BenchmarkCategory.CAT8_MODEL_ROUTING_DECISION,
        title="Decisión de routing para comando simple de voz",
        prompt="¿Qué modelo debería atender una orden sencilla como 'abre el bloc' y por qué?",
        expected_keywords=("gemma", "latencia", "local", "rápido"),
    ),
    Phase2TestCase(
        test_id="C8_02_routing_analisis_complejo",
        category=BenchmarkCategory.CAT8_MODEL_ROUTING_DECISION,
        title="Decisión de routing para análisis arquitectónico complejo",
        prompt="¿Qué modelo tendría sentido para analizar un problema arquitectónico complejo del router y por qué?",
        expected_keywords=("nemotron", "qwen", "razonamiento", "complej"),
    ),
    Phase2TestCase(
        test_id="C8_03_routing_inadecuado_nemotron_voz",
        category=BenchmarkCategory.CAT8_MODEL_ROUTING_DECISION,
        title="Evaluación de si tiene sentido usar Nemotron en cada orden de voz",
        prompt="¿Tiene sentido usar Nemotron para cada orden de voz en JESSYCA? Argumenta técnicamente.",
        expected_keywords=("no", "latencia", "segundos", "coste", "red"),
    ),
    Phase2TestCase(
        test_id="C8_04_routing_entorno_offline",
        category=BenchmarkCategory.CAT8_MODEL_ROUTING_DECISION,
        title="Decisión de enrutamiento en entorno sin conexión a Internet",
        prompt="Si el equipo no tiene conexión a Internet, ¿qué modelos están disponibles y cuál debe responder?",
        expected_keywords=("locales", "gemma", "qwen", "ollama"),
    ),
    Phase2TestCase(
        test_id="C8_05_routing_tarea_vision",
        category=BenchmarkCategory.CAT8_MODEL_ROUTING_DECISION,
        title="Decisión de enrutamiento para análisis de pantalla o imagen",
        prompt="El usuario pide: 'Mira la pantalla y dime qué error muestra esa ventana emergente'. ¿Qué modelo debe seleccionarse?",
        expected_keywords=("qwen3-vl", "visión", "multimodal"),
    ),

    # ── CATEGORÍA 9: CONTRADICCIONES (5 pruebas) ──────────────────────────────
    Phase2TestCase(
        test_id="C9_01_contradiccion_tool_vs_state",
        category=BenchmarkCategory.CAT9_CONTRADICTIONS,
        title="Tool A dice success=true pero Tool B dice state=closed",
        prompt=(
            "La herramienta de lanzamiento de aplicación reporta: `status: success=true`. "
            "La herramienta de sondeo de procesos del sistema operativo reporta: `application_state: closed`. "
            "Pregunta: ¿La aplicación está realmente abierta y qué debes responder al usuario?"
        ),
        is_contradiction=True,
        expected_keywords=("no está abierta", "evidencia", "cerrada", "falló"),
        forbidden_keywords=("sí, está abierta", "éxito confirmado"),
    ),
    Phase2TestCase(
        test_id="C9_02_contradiccion_archivo_creado_vs_disco",
        category=BenchmarkCategory.CAT9_CONTRADICTIONS,
        title="Script reporta archivo creado pero filesystem dice no existe",
        prompt=(
            "La herramienta de creación devolvió: 'Archivo guardado correctamente en D:\\datos.txt'. "
            "La comprobación `os.path.exists('D:\\datos.txt')` devuelve `False`. "
            "¿Qué se debe concluir y qué acción corresponde?"
        ),
        is_contradiction=True,
        expected_keywords=("no existe", "no se guardó", "error", "falso éxito"),
        forbidden_keywords=("el archivo está listo", "guardado con éxito"),
    ),
    Phase2TestCase(
        test_id="C9_03_contradiccion_spooler_impresora",
        category=BenchmarkCategory.CAT9_CONTRADICTIONS,
        title="Reporte de impresión completada vs spooler vacío e impresora apagada",
        prompt=(
            "Un proceso reporta 'Impresión completada con éxito'. "
            "El spooler de Windows reporta: 'Cola vacía, impresora offline/apagada'. "
            "¿Se imprimió el documento realmente?"
        ),
        is_contradiction=True,
        expected_keywords=("no se imprimió", "impresora apagada", "falso éxito"),
        forbidden_keywords=("impresión finalizada", "documento impreso"),
    ),
    Phase2TestCase(
        test_id="C9_04_contradiccion_audio_muteado",
        category=BenchmarkCategory.CAT9_CONTRADICTIONS,
        title="Acción mute audio vs endpoint de audio con volumen al 80%",
        prompt=(
            "Se ejecutó una orden para silenciar el equipo y la herramienta retornó éxito. "
            "La verificación de Windows Core Audio indica: `master_volume: 0.80, is_muted: False`. "
            "¿El audio está silenciado?"
        ),
        is_contradiction=True,
        expected_keywords=("no está silenciado", "sigue con audio", "falló"),
        forbidden_keywords=("silenciado con éxito", "audio apagado"),
    ),
    Phase2TestCase(
        test_id="C9_05_contradiccion_proceso_terminado_vs_cpu",
        category=BenchmarkCategory.CAT9_CONTRADICTIONS,
        title="Herramienta 'kill' devuelve éxito vs proceso activo con uso de CPU",
        prompt=(
            "La función `terminar_proceso('app.exe')` devuelve True. "
            "El gestor de procesos indica que `app.exe` (PID 5024) sigue activo y consumiendo 12% de CPU. "
            "¿El proceso fue terminado?"
        ),
        is_contradiction=True,
        expected_keywords=("no fue terminado", "sigue en ejecución", "error"),
        forbidden_keywords=("proceso cerrado con éxito", "proceso terminado correctamente", "fue cerrado con éxito"),
    ),

    # ── CATEGORÍA 10: CONTEXTO CONVERSACIONAL (5 pruebas) ─────────────────────
    Phase2TestCase(
        test_id="C10_01_contexto_abre_cierra_pronombre",
        category=BenchmarkCategory.CAT10_CONVERSATIONAL_CONTEXT,
        title="Resolución anafórica: 'Abre Google' seguido de 'Ahora ciérralo'",
        prompt="Ahora ciérralo.",
        has_prior_context=True,
        prior_context_messages=(
            {"role": "user", "content": "Jessica, abre Google."},
            {"role": "assistant", "content": "He abierto Google en el navegador."},
        ),
        expected_intent="close_application",
        expected_keywords=("google", "navegador", "cerrar"),
    ),
    Phase2TestCase(
        test_id="C10_02_contexto_bloc_escribe_alli",
        category=BenchmarkCategory.CAT10_CONVERSATIONAL_CONTEXT,
        title="Resolución locativa: 'Abre el bloc' seguido de 'Escribe esto allí'",
        prompt="Escribe esto allí: Reunión de equipo a las 5.",
        has_prior_context=True,
        prior_context_messages=(
            {"role": "user", "content": "Abre el bloc de notas."},
            {"role": "assistant", "content": "Bloc de notas abierto."},
        ),
        expected_intent="write_text",
        expected_keywords=("bloc de notas", "notepad", "escribir", "reunión"),
    ),
    Phase2TestCase(
        test_id="C10_03_contexto_edge_maximiza_ventana",
        category=BenchmarkCategory.CAT10_CONVERSATIONAL_CONTEXT,
        title="Resolución deíctica: 'Busca en Edge' seguido de 'Maximiza esa ventana'",
        prompt="Maximiza esa ventana.",
        has_prior_context=True,
        prior_context_messages=(
            {"role": "user", "content": "Busca noticias de tecnología en Edge."},
            {"role": "assistant", "content": "Búsqueda cargada en Microsoft Edge."},
        ),
        expected_intent="maximize_window",
        expected_keywords=("edge", "maximizar", "ventana"),
    ),
    Phase2TestCase(
        test_id="C10_04_contexto_carpeta_abrela",
        category=BenchmarkCategory.CAT10_CONVERSATIONAL_CONTEXT,
        title="Resolución de género y pronombre: 'Crea carpeta Facturas' -> 'Ábrela'",
        prompt="Ábrela.",
        has_prior_context=True,
        prior_context_messages=(
            {"role": "user", "content": "Crea una carpeta llamada Facturas en el escritorio."},
            {"role": "assistant", "content": "Carpeta Facturas creada en el escritorio."},
        ),
        expected_intent="open_directory",
        expected_keywords=("facturas", "carpeta", "abrir"),
    ),
    Phase2TestCase(
        test_id="C10_05_contexto_youtube_pausa",
        category=BenchmarkCategory.CAT10_CONVERSATIONAL_CONTEXT,
        title="Contexto multimedia activo: 'Pon Bohemian Rhapsody' -> 'Pausa la reproducción'",
        prompt="Pausa la reproducción.",
        has_prior_context=True,
        prior_context_messages=(
            {"role": "user", "content": "Pon Bohemian Rhapsody en YouTube."},
            {"role": "assistant", "content": "Reproduciendo Bohemian Rhapsody en YouTube."},
        ),
        expected_intent="media_pause",
        expected_keywords=("pausar", "reproducción", "youtube"),
    ),
)
