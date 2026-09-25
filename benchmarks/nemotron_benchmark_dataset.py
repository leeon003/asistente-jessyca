"""Dataset formal para el benchmark A/B comparativo de Nemotron 3 Ultra vs Gemma 4 e4b vs Qwen3 8B.

Contiene 25 casos de prueba deterministas divididos en:
- Categoría A: Conversación (5 pruebas)
- Categoría B: Razonamiento y Lógica (5 pruebas)
- Categoría C: Programación e Ingeniería de Software (5 pruebas)
- Categoría D: Agentes y Herramientas (5 pruebas)
- Categoría JESSYCA: Pruebas específicas de arquitectura JESSYCA (10 pruebas)

REGLA CRÍTICA DE JESSYCA:
En ningún caso se deben ejecutar acciones reales del sistema operativo.
Toda prueba evalúa la capacidad cognitiva: REASONING -> PLAN -> VERIFICATION.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class BenchmarkCategory(StrEnum):
    CONVERSATION = "conversation"
    REASONING = "reasoning"
    CODING = "coding"
    AGENTIC_TOOLS = "agentic_tools"
    JESSYCA_ARCHITECTURE = "jessyca_architecture"


@dataclass(frozen=True)
class NemotronBenchmarkCase:
    """Caso de prueba unitario y formal para benchmarking comparativo entre modelos."""

    test_id: str
    category: BenchmarkCategory
    title: str
    prompt: str
    system_prompt: str | None = None
    expected_keywords: tuple[str, ...] = ()
    forbidden_keywords: tuple[str, ...] = ()
    expected_structure_sections: tuple[str, ...] = ()
    requires_structured_plan: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


NEMOTRON_BENCHMARK_CASES: tuple[NemotronBenchmarkCase, ...] = (
    # ── CATEGORÍA A: CONVERSACIÓN (5 pruebas) ──────────────────────────────────
    NemotronBenchmarkCase(
        test_id="A01_saludo_conciso",
        category=BenchmarkCategory.CONVERSATION,
        title="Saludo natural, conciso y contextual para voz",
        prompt="Hola Jessyca, buenos días. ¿Qué tal estás hoy?",
        system_prompt="Eres Jessyca, un asistente de voz para Windows 10/11. Responde de forma muy natural, educada, cercana y en no más de 2 oraciones para no saturar el sintetizador de voz.",
        expected_keywords=("Jessyca", "días"),
        forbidden_keywords=("error", "indeterminado"),
    ),
    NemotronBenchmarkCase(
        test_id="A02_seguimiento_contexto",
        category=BenchmarkCategory.CONVERSATION,
        title="Seguimiento de contexto con referencia anafórica",
        prompt="Ayer estaba leyendo sobre la misión Artemis II a la Luna. ¿Quiénes son los astronautas asignados y cuándo despegará?",
        expected_keywords=("Artemis", "Luna"),
    ),
    NemotronBenchmarkCase(
        test_id="A03_instrucciones_negativas",
        category=BenchmarkCategory.CONVERSATION,
        title="Cumplimiento estricto de restricciones negativas",
        prompt="Explícame qué es una API REST en un solo párrafo. No utilices la palabra 'servidor', ni 'HTTP', ni 'cliente'.",
        forbidden_keywords=("servidor", "http", "cliente"),
    ),
    NemotronBenchmarkCase(
        test_id="A04_empatia_y_claridad",
        category=BenchmarkCategory.CONVERSATION,
        title="Respuesta empática ante frustración del usuario",
        prompt="Llevo dos horas intentando arreglar un error en Windows y nada me funciona, estoy agotado.",
        expected_keywords=("ayudar", "tranquil", "paso"),
    ),
    NemotronBenchmarkCase(
        test_id="A05_sintesis_concisa",
        category=BenchmarkCategory.CONVERSATION,
        title="Síntesis ultra-concisa de información densa",
        prompt="Resume en exactamente tres puntos numerados por qué la latencia es crítica en un asistente de voz.",
        expected_keywords=("1", "2", "3", "latencia"),
    ),

    # ── CATEGORÍA B: RAZONAMIENTO (5 pruebas) ───────────────────────────────────
    NemotronBenchmarkCase(
        test_id="B01_condicionales_multiples",
        category=BenchmarkCategory.REASONING,
        title="Análisis de múltiples condiciones excluyentes",
        prompt=(
            "Tenemos 3 servidores: Alfa, Beta y Gamma. "
            "Alfa solo opera si Beta está inactivo. "
            "Gamma nunca opera si Alfa está activo. "
            "Si Beta está activo, ¿cuál es el estado exacto de Alfa y Gamma? Razona paso a paso."
        ),
        expected_keywords=("inactivo", "Beta", "Alfa"),
        expected_structure_sections=("Paso", "Conclusión"),
    ),
    NemotronBenchmarkCase(
        test_id="B02_deteccion_contradiccion",
        category=BenchmarkCategory.REASONING,
        title="Detección de contradicción lógica en requisitos",
        prompt=(
            "Un cliente especifica: 'El software debe funcionar 100% offline sin conexión de red, "
            "pero debe sincronizar en tiempo real cada segundo los datos con nuestra base de datos central en la nube'. "
            "Identifica el conflicto y propone una solución arquitectónica."
        ),
        expected_keywords=("contradicción", "offline", "sincronizar", "nube"),
    ),
    NemotronBenchmarkCase(
        test_id="B03_analisis_temporal",
        category=BenchmarkCategory.REASONING,
        title="Deducción de secuencia temporal con dependencias cruzadas",
        prompt=(
            "La tarea C depende de que finalice B. B depende de que inicie A. "
            "D solo puede ejecutarse mientras B está en progreso. "
            "Si A tarda 5 minutos, B tarda 10 minutos y C tarda 2 minutos, ¿cuándo es el momento más temprano para iniciar y finalizar D?"
        ),
        expected_keywords=("minuto", "B", "A"),
    ),
    NemotronBenchmarkCase(
        test_id="B04_diagnostico_recursos",
        category=BenchmarkCategory.REASONING,
        title="Diagnóstico de cuello de botella de recursos en GPU",
        prompt=(
            "En una GPU NVIDIA RTX 3060 de 12 GB, un modelo LLM local A requiere 5.5 GB de VRAM, "
            "un modelo B requiere 6.0 GB y el sistema operativo Windows reserva 1.5 GB. "
            "¿Pueden cargarse ambos modelos simultáneamente en VRAM? Explica el cálculo exacto y el riesgo de OOM."
        ),
        expected_keywords=("13", "12", "OOM", "VRAM"),
    ),
    NemotronBenchmarkCase(
        test_id="B05_falacia_probabilistica",
        category=BenchmarkCategory.REASONING,
        title="Análisis contra-intuitivo de probabilidad y falsos positivos",
        prompt=(
            "Una prueba diagnóstica tiene un 99% de sensibilidad y 99% de especificidad. "
            "Una condición afecta a 1 de cada 10,000 personas. "
            "Si una persona da positivo, ¿la probabilidad real de padecer la condición es cercana al 99% o cercana al 1%? Explica el Teorema de Bayes."
        ),
        expected_keywords=("Bayes", "falsos positivos", "1%"),
    ),

    # ── CATEGORÍA C: PROGRAMACIÓN (5 pruebas) ───────────────────────────────────
    NemotronBenchmarkCase(
        test_id="C01_debugging_thread_safety",
        category=BenchmarkCategory.CODING,
        title="Detección de Race Condition en singleton de Python",
        prompt=(
            "Analiza el siguiente código en Python y explica el bug crítico de concurrencia:\n"
            "class Singleton:\n"
            "    _inst = None\n"
            "    @classmethod\n"
            "    def get_instance(cls):\n"
            "        if cls._inst is None:\n"
            "            cls._inst = cls()\n"
            "        return cls._inst\n"
            "¿Cómo se soluciona formalmente con threading.RLock() y double-checked locking?"
        ),
        expected_keywords=("lock", "race condition", "hilos", "concurrencia"),
    ),
    NemotronBenchmarkCase(
        test_id="C02_refactor_inyeccion_dependencias",
        category=BenchmarkCategory.CODING,
        title="Refactorización para desacoplar transporte HTTP en LLMProvider",
        prompt=(
            "Dado un cliente que llama directamente a `requests.post('http://localhost:11434/api/generate', json=d)` dentro de su lógica de negocio, "
            "diseña una interfaz o Protocolo tipado `LLMProvider` que permita inyectar un proveedor simulado en tests unitarios sin tocar la red."
        ),
        expected_keywords=("Protocol", "generate", "InferenceRequest", "InferenceResponse"),
    ),
    NemotronBenchmarkCase(
        test_id="C03_manejo_seguro_recursos",
        category=BenchmarkCategory.CODING,
        title="Detección de resource leak y context manager seguro",
        prompt=(
            "¿Cuál es el peligro de hacer `f = open('data.txt', 'w'); f.write(payload); f.close()` si `f.write()` lanza una excepción? "
            "Muestra la forma idiomática en Python y explica cómo opera el dunder `__exit__`."
        ),
        expected_keywords=("with", "__exit__", "close", "recursos", "excepción"),
    ),
    NemotronBenchmarkCase(
        test_id="C04_algoritmo_eviccion_lru",
        category=BenchmarkCategory.CODING,
        title="Diseño de política de desalojo LRU para VRAM",
        prompt=(
            "Diseña en Python una función determinista `calcular_desalojos(modelos_cargados, vram_requerida_mb, limite_max_mb)` "
            "que desaloje los modelos menos usados recientemente (LRU) priorizando no desalojar modelos con prioridad alta."
        ),
        expected_keywords=("LRU", "prioridad", "timestamp", "desaloj"),
    ),
    NemotronBenchmarkCase(
        test_id="C05_parsing_json_robusto",
        category=BenchmarkCategory.CODING,
        title="Parsing de JSON con bloques markdown y texto circundante",
        prompt=(
            "Escribe una función en Python `extraer_json_limpio(texto: str) -> dict | None` que sea capaz de extraer un objeto JSON válido "
            "incluso si el LLM envolvió el texto en bloques ```json ... ``` o añadió texto conversacional antes y después."
        ),
        expected_keywords=("re.search", "json.loads", "JSONDecodeError"),
    ),

    # ── CATEGORÍA D: AGENTES Y HERRAMIENTAS (5 pruebas) ─────────────────────────
    NemotronBenchmarkCase(
        test_id="D01_plan_multistep_herramientas",
        category=BenchmarkCategory.AGENTIC_TOOLS,
        title="Plan multi-step para crear archivo y comprimir",
        prompt="Necesito crear un reporte en D:\\reportes\\mayo.txt, escribir 'Ventas OK' y después comprimirlo en mayo.zip. Diseña el plan estructurado.",
        requires_structured_plan=True,
        expected_structure_sections=("REASONING", "PLAN", "VERIFICATION"),
        expected_keywords=("REASONING", "PLAN", "VERIFICATION", "mayo.txt"),
    ),
    NemotronBenchmarkCase(
        test_id="D02_deteccion_precondiciones",
        category=BenchmarkCategory.AGENTIC_TOOLS,
        title="Identificación de precondiciones críticas antes de invocar herramienta",
        prompt="El usuario ordena: 'Envía por correo el archivo presupuesto.pdf a compras@empresa.com'. ¿Qué precondiciones deben validarse antes de ejecutar?",
        expected_keywords=("existe", "correo", "presupuesto.pdf", "conexión"),
    ),
    NemotronBenchmarkCase(
        test_id="D03_recuperacion_ante_fallo",
        category=BenchmarkCategory.AGENTIC_TOOLS,
        title="Estrategia de fallback ante fallo de herramienta primaria",
        prompt="El agente intentó tomar una captura de pantalla mediante Desktop API pero falló con 'AccessDenied'. ¿Cuál debe ser el flujo de rescate?",
        expected_keywords=("fallback", "permisos", "error", "alternativa"),
    ),
    NemotronBenchmarkCase(
        test_id="D04_idempotencia_en_agentes",
        category=BenchmarkCategory.AGENTIC_TOOLS,
        title="Garantía de idempotencia en acciones repetidas del usuario",
        prompt="El usuario dice 'Abre Word' dos veces consecutivas en menos de 5 segundos. ¿Cómo debe razonar el agente para no duplicar procesos?",
        expected_keywords=("proceso", "idempotencia", "abierto", "PID"),
    ),
    NemotronBenchmarkCase(
        test_id="D05_verificacion_posterior_accion",
        category=BenchmarkCategory.AGENTIC_TOOLS,
        title="Regla de oro: Separar ejecución de confirmación de éxito",
        prompt="Explica por qué un agente NUNCA debe decir 'He creado el archivo' inmediatamente después de llamar a la función sin verificar previamente en el disco.",
        expected_keywords=("verificar", "éxito", "disco", "falso positivo"),
    ),

    # ── PRUEBAS ESPECÍFICAS DE ARQUITECTURA JESSYCA (10 pruebas) ───────────────
    NemotronBenchmarkCase(
        test_id="J01_clasificacion_intencion",
        category=BenchmarkCategory.JESSYCA_ARCHITECTURE,
        title="TEST 01: Clasificación entre respuesta normal, Windows o navegador",
        prompt=(
            "Analiza las siguientes tres solicitudes del usuario y clasifícalas como [NORMAL, WINDOWS_EXECUTION, BROWSER_USE]:\n"
            "1. '¿A cuántos kilómetros está el Sol de la Tierra?'\n"
            "2. 'Abre el Bloc de notas y maximízalo.'\n"
            "3. 'Busca en YouTube música para estudiar y dale al primer resultado.'\n"
            "Explica tu criterio de clasificación."
        ),
        expected_keywords=("NORMAL", "WINDOWS_EXECUTION", "BROWSER_USE"),
    ),
    NemotronBenchmarkCase(
        test_id="J02_youtube_play_verification",
        category=BenchmarkCategory.JESSYCA_ARCHITECTURE,
        title="TEST 02: Plan para abrir YouTube y reproducir canción con verificaciones",
        prompt=(
            "El usuario pide abrir YouTube y reproducir una canción. "
            "Diseña un plan de ejecución estructurado y especifica exactamente qué verificaciones deben hacerse antes de informar éxito al usuario."
        ),
        requires_structured_plan=True,
        expected_structure_sections=("REASONING", "PLAN", "VERIFICATION"),
        expected_keywords=("REASONING", "PLAN", "VERIFICATION", "YouTube", "reproducción"),
    ),
    NemotronBenchmarkCase(
        test_id="J03_notepad_anti_duplicacion",
        category=BenchmarkCategory.JESSYCA_ARCHITECTURE,
        title="TEST 03: Bloc de notas, escribir texto y guardar evitando duplicar ventanas",
        prompt=(
            "El usuario pide abrir Bloc de notas, escribir un texto y guardar el archivo. "
            "Diseña el flujo paso a paso y especifica la técnica para verificar si notepad.exe ya está en ejecución antes de lanzar un nuevo proceso."
        ),
        requires_structured_plan=True,
        expected_structure_sections=("REASONING", "PLAN", "VERIFICATION"),
        expected_keywords=("notepad.exe", "proceso", "guardar", "duplicar"),
    ),
    NemotronBenchmarkCase(
        test_id="J04_falso_exito_herramienta",
        category=BenchmarkCategory.JESSYCA_ARCHITECTURE,
        title="TEST 04: Herramienta devuelve éxito pero la aplicación no se abrió",
        prompt=(
            "Una herramienta de Windows devuelve código de salida 0 (éxito), pero el monitor de procesos confirma que la aplicación no se abrió. "
            "¿Cómo debería reaccionar el agente y qué debe informar al usuario según la regla de oro de JESSYCA?"
        ),
        expected_keywords=("falso éxito", "verificación", "no se abrió", "error"),
    ),
    NemotronBenchmarkCase(
        test_id="J05_fallo_parcial_recuperacion",
        category=BenchmarkCategory.JESSYCA_ARCHITECTURE,
        title="TEST 05: Acción de Windows falla parcialmente y estrategia de recuperación",
        prompt=(
            "En una tarea multi-step: 1) Crear carpeta (éxito), 2) Mover 5 archivos (3 movidos, 2 con PermissionError), 3) Eliminar originales. "
            "Diseña la estrategia de recuperación inmediata y cómo evitar la pérdida de los archivos no movidos."
        ),
        expected_keywords=("rollback", "PermissionError", "no eliminar", "recuperación"),
    ),
    NemotronBenchmarkCase(
        test_id="J06_criterio_escalado_gemma_vs_razonamiento",
        category=BenchmarkCategory.JESSYCA_ARCHITECTURE,
        title="TEST 06: Criterio de cuándo quedarse en Gemma/Qwen y cuándo escalar a Nemotron",
        prompt=(
            "Establece una matriz de decisión técnica clara: ¿en qué casos exactos una petición del usuario debe resolverse localmente "
            "con Gemma 4 e4b (baja latencia para voz) y cuándo debe escalarse a un modelo de razonamiento avanzado y planificación multi-step?"
        ),
        expected_keywords=("Gemma", "latencia", "voz", "complejidad", "multi-step"),
    ),
    NemotronBenchmarkCase(
        test_id="J07_solicitud_ambigua_clarificacion",
        category=BenchmarkCategory.JESSYCA_ARCHITECTURE,
        title="TEST 07: Análisis de solicitud ambigua y parámetros faltantes",
        prompt=(
            "El usuario dice: 'Envíalo al grupo ahora'. "
            "Analiza la ambigüedad, identifica exactamente qué parámetros faltan (sujeto, destino, canal) y formula una pregunta de aclaración concisa."
        ),
        expected_keywords=("ambigüedad", "parámetro", "archivo", "grupo", "aclaración"),
    ),
    NemotronBenchmarkCase(
        test_id="J08_separacion_plan_exec_verif",
        category=BenchmarkCategory.JESSYCA_ARCHITECTURE,
        title="TEST 08: Separación estricta de Planificación, Ejecución y Verificación",
        prompt=(
            "Diseña un plan para la tarea de Windows: 'Organizar los archivos de la carpeta Descargas en subcarpetas por extensión'. "
            "Estructura obligatoriamente la respuesta separando formalmente: "
            "[1. RAZONAMIENTO] -> [2. PLAN DE ACCIONES ATÓMICAS] -> [3. CRITERIOS DE VERIFICACIÓN]."
        ),
        requires_structured_plan=True,
        expected_structure_sections=("RAZONAMIENTO", "PLAN", "VERIFICACIÓN"),
        expected_keywords=("RAZONAMIENTO", "PLAN", "VERIFICACIÓN", "extensión"),
    ),
    NemotronBenchmarkCase(
        test_id="J09_deteccion_falsos_positivos_cadena",
        category=BenchmarkCategory.JESSYCA_ARCHITECTURE,
        title="TEST 09: Detección de falsos positivos en una cadena de herramientas",
        prompt=(
            "Una cadena de 3 herramientas (Descargar -> Convertir -> Imprimir) reporta éxito global porque el script final retornó True, "
            "pero el spooler de impresión no tiene ningún trabajo en cola y la impresora está apagada. "
            "¿Dónde falló la arquitectura y cómo se diseñan probes de verificación realistas?"
        ),
        expected_keywords=("spooler", "verificación", "falso positivo", "impresora"),
    ),
    NemotronBenchmarkCase(
        test_id="J10_bloqueo_timeout_fallback",
        category=BenchmarkCategory.JESSYCA_ARCHITECTURE,
        title="TEST 10: Flujo de agente bloqueado y estrategia de timeout/retry/fallback",
        prompt=(
            "El modelo remoto de razonamiento tarda más de 25 segundos en responder debido a congestión de la API. "
            "¿Cuál debe ser el comportamiento exacto del loop del asistente de voz de JESSYCA para no dejar al usuario en silencio absoluto?"
        ),
        expected_keywords=("timeout", "fallback", "Gemma", "silencio", "feedback"),
    ),
)
