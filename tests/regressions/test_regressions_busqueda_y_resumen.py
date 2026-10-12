"""Pruebas de regresión para búsqueda gobernada, resumen extractivo y selección contextual de documentos.

Cubre:
1. Búsqueda web:
   - Distinción de estados: navegación iniciada vs lectura real vs respuesta elaborada.
   - Declaración precisa de proveedor y contenido leído.
   - NO etiquetar Wikipedia como "fuente oficial"; etiquetar como Referencia.
   - Preservación de restricciones de consulta (versiones, fechas, entidades) y exclusión de homónimos
     ajenos (ej. exclusión de taxones biológicos de serpientes ante 'Python 3.12').
   - Respeto irrestricto de políticas de red (URLAllowlistPolicy).
   - Declaración de limitación si solo funciona consulta enciclopédica estructurada.
   - Pruebas generalizables sobre tres temas distintos sin atajos ad-hoc.
2. Resumen extractivo:
   - Documento con decisiones, negaciones y conclusiones sin cifras, preservadas frente a métricas secundarias.
   - Identificación honesta del modo como 'Resumen extractivo' (extractive).
   - Reutilización de implementación común entre Skills y ARE.
3. Selección desde la interfaz habitual (LocalAgent.process_text):
   - Flujo conversacional end-to-end: solicitud ambigua -> AWAITING_CLARIFICATION -> elección -> resumen.
   - Cero inyección manual de context o session_reference; enlace gobernado por la aplicación.
   - Verificación de cero candidatos.
   - Verificación de referencias que ya no existen.
   - Principio de autorización: la existencia de una ruta no equivale a autorización para leerla.
4. Pruebas y entornos limpios:
   - Documentos generados en directorios temporales (tmp_path).
"""

import os
import subprocess
import sys
from pathlib import Path
import pytest

from core.browser_models import URLAllowlistPolicy
from core.documents.summarizer import extractive_summarize
from core.local_agent.local_agent import JessycaLocalAgent
from core.local_agent.local_agent_models import AgentExecutionState
from skills.browser_search_skill import BrowserSearchSkill
from skills.documents_skills import DocumentsSummarizeSkill


@pytest.fixture(scope="module")
def local_agent():
    return JessycaLocalAgent.get_instance()


# ══════════════════════════════════════════════════════════════════
# 1. BÚSQUEDA WEB Y POLÍTICAS DE RED
# ══════════════════════════════════════════════════════════════════

def test_busqueda_sin_resultados_declara_unicamente_apertura_interna():
    """Verifica que si no se pueden leer resultados, la skill declare únicamente la apertura."""
    skill = BrowserSearchSkill()
    res = skill.ejecutar({"query": "termino_inexistente_xyz_test", "simulate_no_results": True})

    assert res["exito"] is True
    assert res["navegacion_iniciada"] is True
    assert res["resultados_leidos"] is False
    assert res["respuesta_elaborada"] is False
    assert len(res["resultados_extraidos"]) == 0
    assert "Abrí la búsqueda para 'termino_inexistente_xyz_test' en el navegador." in res["mensaje"]


def test_busqueda_respeta_politica_de_red():
    """Verifica que todas las peticiones y navegaciones respeten URLAllowlistPolicy."""
    policy = URLAllowlistPolicy()

    # Esquemas peligrosos denegados
    assert policy.is_url_allowed("javascript:alert(1)") is False
    assert policy.is_url_allowed("data:text/html,hack") is False
    assert policy.is_url_allowed("file:///C:/Windows/System32/cmd.exe") is False

    # Dominios autorizados permitidos
    assert policy.is_url_allowed("https://duckduckgo.com/?q=test") is True
    assert policy.is_url_allowed("https://es.wikipedia.org/wiki/Python") is True
    assert policy.is_url_allowed("https://en.wikipedia.org/wiki/Python") is True
    assert policy.is_url_allowed("https://www.google.com/search?q=test") is True
    assert policy.is_url_allowed("https://www.bing.com/search?q=test") is True


def test_busqueda_generalizada_3_temas_distintos_y_exclusion_homonimos():
    """Verifica búsqueda sobre tres temas, exclusión de serpientes en Python 3.12 y no llamar fuente oficial a Wikipedia."""
    skill = BrowserSearchSkill()
    temas = ["Python 3.12", "Computación cuántica", "Telescopio James Webb"]

    for tema in temas:
        res = skill.ejecutar({"query": tema})
        assert res["exito"] is True
        assert res["navegacion_iniciada"] is True
        assert res["resultados_leidos"] is True
        assert res["respuesta_elaborada"] is True
        assert len(res["resultados_extraidos"]) >= 1

        info_txt = res["info_elaborada"]
        # 1. No debe etiquetar Wikipedia como 'fuente oficial'
        assert "Fuente oficial" not in info_txt

        # 2. Debe identificar el proveedor y contenido leído
        assert "Proveedor:" in info_txt
        assert "Contenido leído:" in info_txt
        assert "Referencia:" in info_txt

        # 3. Caso crítico: Para 'Python 3.12', no debe devolver una serpiente (Python bivittatus / Pythonidae)
        if tema == "Python 3.12":
            for item in res["resultados_extraidos"]:
                titulo_lower = item.get("titulo", "").lower()
                snip_lower = item.get("snippet", "").lower()
                assert "bivittatus" not in titulo_lower
                assert "serpiente" not in snip_lower
                assert "pythonidae" not in snip_lower


# ══════════════════════════════════════════════════════════════════
# 2. RESUMEN EXTRACTIVO Y PONDERACIÓN SIN CIFRAS
# ══════════════════════════════════════════════════════════════════

def test_resumen_documento_sin_cifras_con_decisiones_y_negaciones(tmp_path):
    """Verifica que un documento con decisiones y negaciones importantes sin cifras no las pierda frente a datos secundarios."""
    doc_path = tmp_path / "resolucion_directiva.txt"
    texto_documento = (
        "1. La junta directiva acordó rechazar categóricamente la fusión propuesta.\n"
        "2. Se prohíbe terminantemente autorizar cualquier transferencia de propiedad intelectual.\n"
        "3. Se imprimieron 3 copias del informe preliminar para constancia de mesa.\n"
        "4. El comité de auditoría determinó que el proveedor externo incumplió los protocolos.\n"
        "5. Asistieron 12 vocales a la sesión matutina.\n"
        "6. Se concluye que la licitación queda cancelada sin efecto legal alguno.\n"
    )
    doc_path.write_text(texto_documento, encoding="utf-8")

    # Prueba con la implementación común
    res = extractive_summarize(file_path=str(doc_path), max_points=4, trusted_root=str(tmp_path))

    assert res["exito"] is True
    assert res["mode"] == "extractive"
    assert "Resumen extractivo" in res["resumen"]

    puntos = res["puntos_clave"]
    # Decisiones y negaciones sustantivas sin cifras DEBEN ser extraídas
    assert any("acordó rechazar" in p for p in puntos)
    assert any("Se prohíbe" in p for p in puntos)
    assert any("determinó" in p for p in puntos)
    assert any("queda cancelada sin efecto" in p for p in puntos)
    # Datos numéricos secundarios no deben desplazar a las decisiones
    assert not any("3 copias" in p for p in puntos)
    assert not any("12 vocales" in p for p in puntos)

    # Las referencias documentales deben estar presentes con números de línea auditables
    assert len(res["referencias"]) >= 3
    assert any("Línea" in r for r in res["referencias"])


def test_resumen_reutiliza_implementacion_comun_en_skills_y_are(tmp_path):
    """Verifica que DocumentsSummarizeSkill y ARE ActionCatalog utilicen la misma lógica común."""
    from core.are.action_catalog import _handle_documents_summarize

    test_file = tmp_path / "acuerdo_marco.txt"
    test_file.write_text("La asamblea resolvió adoptar el nuevo estatuto de gobernanza.", encoding="utf-8")

    # 1. Llamada mediante Skill (con trusted_root en contexto de ejecución confiable por solicitud)
    skill = DocumentsSummarizeSkill()
    res_skill = skill.ejecutar(
        {"ruta": str(test_file), "max_points": 3},
        context={"trusted_root": str(tmp_path)},
    )

    # 2. Llamada mediante ARE ActionCatalog (con trusted_root en ctx seguro)
    res_are = _handle_documents_summarize(
        {"file_path": str(test_file), "max_points": 3},
        ctx={"trusted_root": str(tmp_path)},
    )

    assert res_skill["exito"] is True
    assert res_are["exito"] is True
    assert res_skill["mode"] == "extractive"
    assert res_are["mode"] == "extractive"
    assert res_skill["puntos_clave"] == res_are["puntos_clave"]


# ══════════════════════════════════════════════════════════════════
# 3. SELECCIÓN DE DOCUMENTOS DESDE LA INTERFAZ HABITUAL
# ══════════════════════════════════════════════════════════════════

def test_seleccion_documento_componente_con_contexto_previo(local_agent, tmp_path):
    """Prueba de componente con candidatos precargados en la sesión.

    Conserva la prueba original que verifica la resolución de aclaración y resumen
    cuando la sesión ya contiene 'candidate_documents', explicitando que es una
    prueba a nivel de componente.
    """
    doc1 = tmp_path / "acta_comite_a.txt"
    doc2 = tmp_path / "informe_financiero_b.txt"

    doc1.write_text("La junta acordó suspender el despliegue tras detectar riesgos en auditoría.", encoding="utf-8")
    doc2.write_text("El balance trimestral registró ingresos por $450000 y utilidades de $80000.", encoding="utf-8")

    session_id = "sesion-componente-contexto-test"
    sess = local_agent.context_manager.get_or_create_session(session_id)
    # Prueba de componente: actualización del contexto de sesión con candidatos y alcance autorizado
    sess.update_context("candidate_documents", [str(doc1), str(doc2)])
    sess.grant_scope(tmp_path)

    # TURNO 1: Petición ambigua
    res_t1 = local_agent.process_text("resume un documento", session_id=session_id)

    assert res_t1.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert res_t1.requires_clarification is True
    assert "acta_comite_a.txt" in res_t1.response_text
    assert "informe_financiero_b.txt" in res_t1.response_text

    # TURNO 2: Elección de candidato ("1")
    res_t2 = local_agent.process_text("1", session_id=session_id)

    assert res_t2.success is True
    assert res_t2.status == AgentExecutionState.COMPLETED
    assert "Resumen extractivo" in res_t2.response_text
    assert "acordó suspender" in res_t2.response_text


def test_seleccion_documento_flujo_habitual_completo_sin_inyeccion_manual(local_agent, tmp_path):
    """Recorrido completo desde la interfaz habitual (process_text) SIN inyección manual:
    
    1. La sesión cuenta con un alcance de acceso legítimo concedido mediante la política de sesión (grant_scope).
    2. Pedir buscar documentos en una carpeta temporal autorizada -> la aplicación descubre
       los archivos y los registra de manera natural en la sesión.
    3. Pedir un resumen cuando hay múltiples candidatos -> la aplicación detecta la ambigüedad
       y emite AWAITING_CLARIFICATION con la lista de candidatos.
    4. Elegir uno ('1') en la misma sesión -> la aplicación resuelve el slot pendiente y
       devuelve el resumen extractivo.
    """
    auth_dir = tmp_path / "carpeta_autorizada"
    auth_dir.mkdir(parents=True, exist_ok=True)

    doc_a = auth_dir / "acta_estrategica_2026.txt"
    doc_b = auth_dir / "plan_operativo_2026.txt"

    doc_a.write_text("La junta directiva decidió aprobar el plan de contingencia sin objeciones.", encoding="utf-8")
    doc_b.write_text("El equipo completó la auditoría de seguridad el pasado viernes con éxito.", encoding="utf-8")

    session_id = "sesion-flujo-habitual-e2e-sin-inyeccion"
    sess = local_agent.context_manager.get_or_create_session(session_id)
    # Flujo legítimo: concesión explícita del alcance confiable de la sesión
    sess.grant_scope(auth_dir)
    
    # TURNO 1: Búsqueda desde la interfaz habitual
    prompt_buscar = f"busca documentos en {auth_dir}"
    res_t1 = local_agent.process_text(prompt_buscar, session_id=session_id)

    assert res_t1.success is True
    assert res_t1.status == AgentExecutionState.COMPLETED
    assert "acta_estrategica_2026.txt" in res_t1.response_text
    assert "plan_operativo_2026.txt" in res_t1.response_text

    # Comprobar que la sesión adquirió los candidatos por el flujo normal de la app
    sess = local_agent.context_manager.get_or_create_session(session_id)
    candidatos_obtenidos = sess.get_context("candidate_documents")
    assert candidatos_obtenidos is not None
    assert len(candidatos_obtenidos) >= 2
    assert str(doc_a) in candidatos_obtenidos
    assert str(doc_b) in candidatos_obtenidos

    # TURNO 2: Solicitud de resumen ante múltiples candidatos
    res_t2 = local_agent.process_text("resume un documento", session_id=session_id)

    assert res_t2.status == AgentExecutionState.AWAITING_CLARIFICATION
    assert res_t2.requires_clarification is True
    assert "acta_estrategica_2026.txt" in res_t2.response_text
    assert "plan_operativo_2026.txt" in res_t2.response_text

    # TURNO 3: Selección ordinal '1' en la misma sesión
    res_t3 = local_agent.process_text("1", session_id=session_id)

    assert res_t3.success is True
    assert res_t3.status == AgentExecutionState.COMPLETED
    assert "Resumen extractivo" in res_t3.response_text
    assert "decidió aprobar el plan de contingencia" in res_t3.response_text


def test_busqueda_web_href_real_y_declaracion_de_fragmentos():
    """Verifica:
    1. Extracción exacta de (título, href real, fragmento) desde el MISMO contenedor DOM
       utilizando una página local controlada con:
       - enlace de logotipo/dominio antes del título (debe ser ignorado);
       - enlace de título con ruta completa;
       - enlace auxiliar de acción (debe ser ignorado);
       - fragmento propio del contenedor;
       - dos resultados del mismo dominio con rutas distintas;
       - contenedor espurio sin título legítimo (debe ser omitido sin inventar enlaces).
    2. Comprobación real del buscador general en Microsoft Edge sin respuestas ni URLs fijas.
    3. Declaración honesta de fragmentos leídos sin afirmar haber navegado a la página de destino.
    """
    from skills.browser_search_skill import parse_search_results_from_html

    # ── 1. PÁGINA LOCAL CONTROLADA AMPLIADA CON LOGO, ACCIONES Y DOS RUTAS DISTINTAS ──
    html_controlado = """
    <!DOCTYPE html>
    <html lang="es">
    <head><title>Resultados de Prueba Controlada</title></head>
    <body>
      <main class="results-container">
        <!-- Resultado 1 -->
        <article class="result" data-testid="result">
          <!-- Enlace de logotipo/dominio antes del título (href a raíz) -->
          <div class="result__badge">
            <a class="badge-link" href="https://ejemplo-controlado.org/">
              <img src="/logo.png" alt="Logo" />
              <span class="domain-text">ejemplo-controlado.org</span>
            </a>
          </div>
          <!-- Enlace de título con ruta completa -->
          <h2 class="result-title">
            <a data-testid="result-title-a" class="result__a" href="https://ejemplo-controlado.org/articulos/guia-arquitectura">
              Guía de Arquitectura de Sistemas
            </a>
          </h2>
          <!-- Enlace auxiliar (no debe confundirse con el título) -->
          <div class="result__extras">
            <a class="aux-share" href="https://ejemplo-controlado.org/compartir?id=101">Compartir</a>
            <a class="aux-cache" href="https://ejemplo-controlado.org/cache?id=101">Caché</a>
          </div>
          <!-- Fragmento propio -->
          <div data-testid="result-snippet" class="result__snippet">
            Explicación detallada de los patrones modulares y fronteras de seguridad del sistema.
          </div>
        </article>

        <!-- Resultado 2: Mismo dominio, ruta distinta -->
        <article class="result" data-testid="result">
          <!-- Enlace de logotipo/dominio antes del título -->
          <div class="result__badge">
            <a class="badge-link" href="https://ejemplo-controlado.org/">
              <span class="domain-text">ejemplo-controlado.org</span>
            </a>
          </div>
          <!-- Enlace de título con ruta completa -->
          <h2 class="result-title">
            <a data-testid="result-title-a" class="result__a" href="https://ejemplo-controlado.org/manuales/referencia-api">
              Manual de Referencia de la API
            </a>
          </h2>
          <!-- Enlace auxiliar -->
          <div class="result__extras">
            <a class="aux-share" href="https://ejemplo-controlado.org/compartir?id=202">Compartir</a>
          </div>
          <!-- Fragmento propio -->
          <div data-testid="result-snippet" class="result__snippet">
            Especificación técnica de endpoints y parámetros de autorización verificables.
          </div>
        </article>

        <!-- Contenedor espurio / sin enlace de título válido (debe ser omitido) -->
        <article class="result" data-testid="result">
          <div class="result__badge">
            <a class="arbitrary-link" href="https://ejemplo-controlado.org/anuncio">Publicidad</a>
          </div>
          <p>Texto sin encabezado ni título legítimo.</p>
        </article>
      </main>
    </body>
    </html>
    """

    resultados_controlados = parse_search_results_from_html(html_controlado, base_url="https://ejemplo-controlado.org")

    # Debe extraer exactamente los 2 resultados legítimos, omitiendo el contenedor espurio
    assert len(resultados_controlados) == 2

    # Comprobación exacta del Resultado 1 (título, URL completa y fragmento)
    res_1 = resultados_controlados[0]
    assert res_1["titulo"] == "Guía de Arquitectura de Sistemas"
    assert res_1["url"] == "https://ejemplo-controlado.org/articulos/guia-arquitectura"
    assert res_1["snippet"] == "Explicación detallada de los patrones modulares y fronteras de seguridad del sistema."

    # Comprobación exacta del Resultado 2 (título, URL completa y fragmento)
    res_2 = resultados_controlados[1]
    assert res_2["titulo"] == "Manual de Referencia de la API"
    assert res_2["url"] == "https://ejemplo-controlado.org/manuales/referencia-api"
    assert res_2["snippet"] == "Especificación técnica de endpoints y parámetros de autorización verificables."

    # Ambos comparten el mismo dominio pero conservan rutas completas distintas y fragmentos no truncados
    assert res_1["url"] != res_2["url"]
    assert res_1["url"].split("/")[2] == res_2["url"].split("/")[2] == "ejemplo-controlado.org"
    # Ninguno tomó el enlace del logo (raíz) ni el auxiliar
    assert all(r["url"] != "https://ejemplo-controlado.org/" for r in resultados_controlados)
    assert all("compartir" not in r["url"] and "cache" not in r["url"] for r in resultados_controlados)

    # ── 2. COMPROBACIÓN REAL DEL BUSCADOR (SIN RESPUESTAS NI URLS FIJAS) ──
    skill = BrowserSearchSkill()
    res_real = skill.ejecutar({"query": "Telescopio Espacial James Webb astronomia"})

    assert res_real["exito"] is True
    assert res_real["resultados_leidos"] is True
    assert res_real["respuesta_elaborada"] is True
    assert len(res_real["resultados_extraidos"]) >= 1

    info_txt = res_real["info_elaborada"]

    # Declaración honesta: no afirmar haber consultado la página externa de destino si solo se leyeron fragmentos
    assert (
        "no se consultó la página de destino directamente" in info_txt
        or "no se consultó la página externa de destino" in info_txt
    )

    # Cada resultado extraído en vivo conserva correspondencia título, URL real con ruta y fragmento
    for item in res_real["resultados_extraidos"]:
        url = item.get("url", "")
        titulo = item.get("titulo", "")
        snippet = item.get("snippet", "")
        assert url.startswith("http://") or url.startswith("https://")
        assert len(url.split("/")) >= 3
        assert len(titulo.strip()) > 0
        assert len(snippet.strip()) > 0


def test_procedencia_authorized_root_no_permite_ampliar_alcance(tmp_path):
    """Verifica rigurosamente desde Skills y ARE:
    1. trusted_root válido y requested_root omitido -> Permite archivos concedidos, deniega externos.
    2. requested_root dentro del alcance -> Permite subcarpeta menor, deniega archivos fuera de ella.
    3. requested_root fuera del alcance -> Denegación de ampliación con PermissionError.
    4. trusted_root ausente con requested_root externo -> Denegado con error explícito de falta de autorización.
    5. Ambos ausentes -> Denegado con error explícito de falta de autorización confiable.
    6. Valores vacíos -> Denegado con error explícito.
    7. Las denegaciones ocurren antes de leer contenido (sin abrir el archivo).
    """
    from core.are.action_catalog import _handle_documents_summarize
    from core.documents.summarizer import (
        check_document_authorization,
        resolve_effective_authorized_root,
    )
    from unittest.mock import patch

    alcance_concedido = tmp_path / "alcance_concedido"
    alcance_concedido.mkdir()
    sub_alcance = alcance_concedido / "subcarpeta"
    sub_alcance.mkdir()
    alcance_externo = tmp_path / "alcance_externo"
    alcance_externo.mkdir()

    doc_concedido = alcance_concedido / "autorizado_base.txt"
    doc_concedido.write_text("Acuerdo marco general aprobado por la junta.", encoding="utf-8")

    doc_sub = sub_alcance / "autorizado_sub.txt"
    doc_sub.write_text("Acta técnica específica de la subcarpeta.", encoding="utf-8")

    doc_externo = alcance_externo / "archivo_externo.txt"
    doc_externo.write_text("Documento confidencial fuera de la frontera autorizada.", encoding="utf-8")

    # ── 1. COMPROBACIÓN DIRECTA DE LA FUNCIÓN DE POLÍTICA EFECTIVA ──
    # A. Parámetro solicita menor alcance -> Válido
    eff_sub = resolve_effective_authorized_root(
        requested_root=str(sub_alcance),
        trusted_root=str(alcance_concedido),
    )
    assert eff_sub == sub_alcance.resolve()

    # B. Parámetro solicita alcance externo -> Error explícito
    try:
        resolve_effective_authorized_root(
            requested_root=str(alcance_externo),
            trusted_root=str(alcance_concedido),
        )
        assert False, "Debió rechazar ampliación de alcance"
    except PermissionError as e:
        assert "no puede ampliar el alcance concedido" in str(e)

    # C. trusted_root ausente con requested_root -> Error explícito (no confía en requested_root)
    try:
        resolve_effective_authorized_root(
            requested_root=str(alcance_externo),
            trusted_root=None,
        )
        assert False, "Debió rechazar falta de trusted_root"
    except PermissionError as e:
        assert "No se ha especificado un alcance confiable autorizado" in str(e)

    # D. Ambos ausentes o vacíos -> Error explícito
    for t_val, r_val in [(None, None), ("", ""), ("   ", "   ")]:
        try:
            resolve_effective_authorized_root(requested_root=r_val, trusted_root=t_val)
            assert False, f"Debió rechazar t={t_val}, r={r_val}"
        except PermissionError as e:
            assert "No se ha especificado un alcance confiable autorizado" in str(e)

    # ── 2. COMPROBACIÓN DESDE SKILLS ──
    skill = DocumentsSummarizeSkill()
    ctx_trusted = {"trusted_root": str(alcance_concedido)}

    # 2.1 trusted_root válido y requested_root omitido
    res_s_1_ok = skill.ejecutar({"ruta": str(doc_concedido)}, context=ctx_trusted)
    assert res_s_1_ok["exito"] is True
    assert "Acuerdo marco general" in res_s_1_ok["puntos_clave"][0]

    res_s_1_fail = skill.ejecutar({"ruta": str(doc_externo)}, context=ctx_trusted)
    assert res_s_1_fail["exito"] is False
    assert "fuera del alcance autorizado" in res_s_1_fail["error"]

    # 2.2 requested_root dentro del alcance (subcarpeta)
    res_s_2_ok = skill.ejecutar(
        {"ruta": str(doc_sub), "authorized_root": str(sub_alcance)},
        context=ctx_trusted,
    )
    assert res_s_2_ok["exito"] is True

    res_s_2_fuera = skill.ejecutar(
        {"ruta": str(doc_concedido), "authorized_root": str(sub_alcance)},
        context=ctx_trusted,
    )
    assert res_s_2_fuera["exito"] is False
    assert "fuera del alcance autorizado" in res_s_2_fuera["error"]

    # 2.3 requested_root fuera del alcance (intento de ampliación)
    res_s_3_fail = skill.ejecutar(
        {"ruta": str(doc_externo), "authorized_root": str(alcance_externo)},
        context=ctx_trusted,
    )
    assert res_s_3_fail["exito"] is False
    assert "no puede ampliar el alcance concedido" in res_s_3_fail["error"]

    # 2.4 trusted_root ausente con requested_root externo
    skill_sin_trust = DocumentsSummarizeSkill()
    res_s_4_fail = skill_sin_trust.ejecutar(
        {"ruta": str(doc_externo), "authorized_root": str(alcance_externo)},
        context={},
    )
    assert res_s_4_fail["exito"] is False
    assert "No se ha especificado un alcance confiable autorizado" in res_s_4_fail["error"]

    # 2.5 Ambos ausentes
    res_s_5_fail = skill_sin_trust.ejecutar({"ruta": str(doc_concedido)}, context={})
    assert res_s_5_fail["exito"] is False
    assert "No se ha especificado un alcance confiable autorizado" in res_s_5_fail["error"]

    # 2.6 Valores vacíos
    res_s_6_fail = skill_sin_trust.ejecutar(
        {"ruta": str(doc_concedido), "authorized_root": ""},
        context={"trusted_root": "   "},
    )
    assert res_s_6_fail["exito"] is False
    assert "No se ha especificado un alcance confiable autorizado" in res_s_6_fail["error"]

    # ── 3. COMPROBACIÓN DESDE ARE ACTION CATALOG ──
    # 3.1 trusted_root válido y requested_root omitido
    res_are_1_ok = _handle_documents_summarize(
        {"file_path": str(doc_concedido)},
        ctx={"trusted_root": str(alcance_concedido)},
    )
    assert res_are_1_ok["exito"] is True

    res_are_1_fail = _handle_documents_summarize(
        {"file_path": str(doc_externo)},
        ctx={"trusted_root": str(alcance_concedido)},
    )
    assert res_are_1_fail["exito"] is False
    assert "fuera del alcance autorizado" in res_are_1_fail["error"]

    # 3.2 requested_root dentro del alcance (subcarpeta)
    res_are_2_ok = _handle_documents_summarize(
        {"file_path": str(doc_sub), "authorized_root": str(sub_alcance)},
        ctx={"trusted_root": str(alcance_concedido)},
    )
    assert res_are_2_ok["exito"] is True

    # 3.3 requested_root fuera del alcance (intento de ampliación)
    res_are_3_fail = _handle_documents_summarize(
        {"file_path": str(doc_externo), "authorized_root": str(alcance_externo)},
        ctx={"trusted_root": str(alcance_concedido)},
    )
    assert res_are_3_fail["exito"] is False
    assert "no puede ampliar el alcance concedido" in res_are_3_fail["error"]

    # 3.4 trusted_root ausente con requested_root externo
    res_are_4_fail = _handle_documents_summarize(
        {"file_path": str(doc_externo), "authorized_root": str(alcance_externo)},
        ctx={},
    )
    assert res_are_4_fail["exito"] is False
    assert "No se ha especificado un alcance confiable autorizado" in res_are_4_fail["error"]

    # 3.5 Ambos ausentes
    res_are_5_fail = _handle_documents_summarize(
        {"file_path": str(doc_concedido)},
        ctx={},
    )
    assert res_are_5_fail["exito"] is False
    assert "No se ha especificado un alcance confiable autorizado" in res_are_5_fail["error"]

    # 3.6 Valores vacíos
    res_are_6_fail = _handle_documents_summarize(
        {"file_path": str(doc_concedido), "authorized_root": ""},
        ctx={"trusted_root": "   "},
    )
    assert res_are_6_fail["exito"] is False
    assert "No se ha especificado un alcance confiable autorizado" in res_are_6_fail["error"]

    # ── 4. VERIFICACIÓN DE QUE LAS DENEGACIONES OCURREN ANTES DE LEER CONTENIDO ──
    # Mockeamos builtins.open para demostrar que un acceso denegado NUNCA abre el archivo en disco
    import builtins
    original_open = builtins.open
    open_called_on_target = False

    def tracked_open(file, *args, **kwargs):
        nonlocal open_called_on_target
        if str(file) == str(doc_externo) or str(file) == str(doc_concedido):
            open_called_on_target = True
        return original_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=tracked_open):
        open_called_on_target = False
        res_denegado = skill.ejecutar(
            {"ruta": str(doc_externo), "authorized_root": str(alcance_externo)},
            context=ctx_trusted,
        )
        assert res_denegado["exito"] is False
        assert open_called_on_target is False, "El archivo NUNCA debe ser abierto si la autorización es denegada."


def test_autorizacion_documental_skills_y_are_txt_dentro_y_fuera(tmp_path):
    """Verifica que un archivo .txt inofensivo fuera del alcance autorizado sea bloqueado por política en Skills y ARE."""
    from core.are.action_catalog import _handle_documents_summarize

    scope_dir = tmp_path / "alcance_autorizado"
    scope_dir.mkdir()
    fuera_dir = tmp_path / "fuera_de_alcance"
    fuera_dir.mkdir()

    doc_autorizado = scope_dir / "documento_valido.txt"
    doc_autorizado.write_text("Acuerdo comercial suscrito con vigencia de 12 meses.", encoding="utf-8")

    doc_no_autorizado = fuera_dir / "archivo_fuera.txt"
    doc_no_autorizado.write_text("Documento inofensivo pero no perteneciente al alcance.", encoding="utf-8")

    # ── 1. SKILLS ──
    skill = DocumentsSummarizeSkill()
    ctx_scope = {"trusted_root": str(scope_dir)}

    # Archivo dentro del alcance -> Éxito
    res_skill_ok = skill.ejecutar({"ruta": str(doc_autorizado)}, context=ctx_scope)
    assert res_skill_ok["exito"] is True
    assert "Acuerdo comercial suscrito" in res_skill_ok["puntos_clave"][0]

    # Archivo fuera del alcance -> Denegación de seguridad
    res_skill_fail = skill.ejecutar({"ruta": str(doc_no_autorizado)}, context=ctx_scope)
    assert res_skill_fail["exito"] is False
    assert "fuera del alcance autorizado" in res_skill_fail["error"]

    # ── 2. ARE ACTION CATALOG ──
    # Archivo dentro del alcance -> Éxito
    res_are_ok = _handle_documents_summarize(
        {"file_path": str(doc_autorizado)},
        ctx={"trusted_root": str(scope_dir)},
    )
    assert res_are_ok["exito"] is True
    assert "Acuerdo comercial suscrito" in res_are_ok["puntos_clave"][0]

    # Archivo fuera del alcance -> Denegación de seguridad
    res_are_fail = _handle_documents_summarize(
        {"file_path": str(doc_no_autorizado)},
        ctx={"trusted_root": str(scope_dir)},
    )
    assert res_are_fail["exito"] is False
    assert "fuera del alcance autorizado" in res_are_fail["error"]


def test_seleccion_cero_candidatos(local_agent):
    """Verifica que ante cero candidatos se responda con mensaje limpio sin inventar."""
    session_id = "sesion-cero-candidatos-test"
    sess = local_agent.context_manager.get_or_create_session(session_id)
    sess.active_context.clear()
    sess.context_items.clear()
    sess.clear_pending()

    # Ejecutar en una sesión sin documentos
    res = local_agent.process_text("resume un documento", session_id=session_id)

    assert "No se encontraron documentos candidatos" in res.response_text


def test_seleccion_referencia_inexistente(local_agent):
    """Verifica el manejo de una referencia a un documento que no existe o fue eliminado."""
    session_id = "sesion-referencia-inexistente-test"
    res = local_agent.process_text("resume el documento archivo_inexistente_999.docx", session_id=session_id)

    assert "no existe o ya no está disponible" in res.response_text


def test_existencia_de_ruta_no_equivale_a_autorizacion(local_agent):
    """Verifica que la existencia de una ruta en disco no autorice su lectura (bloqueo de seguridad)."""
    session_id = "sesion-seguridad-autorizacion-test"
    # C:\Windows\System32\cmd.exe existe en Windows, pero debe ser denegado terminantemente
    res = local_agent.process_text("resume el documento C:\\Windows\\System32\\cmd.exe", session_id=session_id)

    assert "Acceso denegado" in res.response_text or "No tienes autorización" in res.response_text




def test_aislamiento_sesiones_y_concurrencia_skill_sin_estado(local_agent, tmp_path):
    """Regresiones exhaustivas de aislamiento, concurrencia y no-mutabilidad de la Skill compartida:
    
    1. Demuestra que registry.get_skill devuelve una instancia compartida (singleton).
    2. Sesión A autorizada seguida de Sesión B sin autorización -> B denegada, no hereda permisos.
    3. Sesión A y B autorizadas a carpetas distintas -> A no lee de B, B no lee de A.
    4. Peticiones concurrentes multi-hilo con alcances diferentes -> Aislamiento estricto sin filtración.
    5. Excepción durante una petición en Sesión A seguida de Sesión B -> B denegada, sin estado residual.
    """
    import concurrent.futures

    dir_a = tmp_path / "carpeta_a"
    dir_a.mkdir()
    doc_a = dir_a / "acta_a.txt"
    doc_a.write_text("La asamblea de A resolvió aprobar el presupuesto operativo 2026.", encoding="utf-8")

    dir_b = tmp_path / "carpeta_b"
    dir_b.mkdir()
    doc_b = dir_b / "acta_b.txt"
    doc_b.write_text("El consejo de B determinó rechazar la adquisición por riesgos legales.", encoding="utf-8")

    # 1. Comprobar que registry devuelve la misma instancia compartida
    skill_inst_1 = local_agent.skill_manager.registry.get_skill("documents.summarize")
    skill_inst_2 = local_agent.skill_manager.registry.lookup("documents.summarize")
    assert skill_inst_1 is skill_inst_2, "El registro de skills DEBE devolver una instancia compartida."

    # 2. Regresión 1: Sesión A autorizada seguida de B sin autorización
    sess_a_id = "sesion-regresion-a"
    sess_a = local_agent.context_manager.get_or_create_session(sess_a_id)
    sess_a.grant_scope(dir_a)

    sess_b_id = "sesion-regresion-b"
    sess_b = local_agent.context_manager.get_or_create_session(sess_b_id)
    # Sesión B explícitamente sin autorización (granted_scope es None)
    sess_b.grant_scope(None)

    # Sesión A resume su propio documento con éxito
    res_a = local_agent.process_text(f"resume el documento {doc_a}", session_id=sess_a_id)
    assert res_a.success is True
    assert "Resumen extractivo" in res_a.response_text
    assert "aprobó el presupuesto" in res_a.response_text or "aprobado" in res_a.response_text or "resolvió aprobar" in res_a.response_text

    # Comprobar que la skill compartida NO retuvo ningún atributo de autorización mutable
    assert not hasattr(skill_inst_1, "trusted_root") or getattr(skill_inst_1, "trusted_root") is None

    # Sesión B intenta leer doc_a -> DENEGADO terminantemente
    res_b = local_agent.process_text(f"resume el documento {doc_a}", session_id=sess_b_id)
    assert res_b.success is False or "Acceso denegado" in res_b.response_text or "No se ha especificado un alcance confiable" in res_b.response_text
    assert "Resumen extractivo" not in res_b.response_text

    # 3. Regresión 2: A y B autorizadas a carpetas distintas
    sess_b.grant_scope(dir_b)

    # Sesión A intenta leer documento de B -> DENEGADO
    res_a_into_b = local_agent.process_text(f"resume el documento {doc_b}", session_id=sess_a_id)
    assert res_a_into_b.success is False or "Acceso denegado" in res_a_into_b.response_text or "fuera del alcance" in res_a_into_b.response_text

    # Sesión B intenta leer documento de A -> DENEGADO
    res_b_into_a = local_agent.process_text(f"resume el documento {doc_a}", session_id=sess_b_id)
    assert res_b_into_a.success is False or "Acceso denegado" in res_b_into_a.response_text or "fuera del alcance" in res_b_into_a.response_text

    # Sesión B lee su propio documento -> ÉXITO
    res_b_own = local_agent.process_text(f"resume el documento {doc_b}", session_id=sess_b_id)
    assert res_b_own.success is True
    assert "Resumen extractivo" in res_b_own.response_text
    assert "determinó rechazar" in res_b_own.response_text or "rechazar la adquisición" in res_b_own.response_text

    # 4. Regresión 3: Peticiones concurrentes con alcances diferentes
    def worker_request(task_tuple):
        s_id, prompt_text = task_tuple
        return local_agent.process_text(prompt_text, session_id=s_id)

    # Preparar 20 tareas concurrentes alternadas
    tasks = []
    for i in range(10):
        # Solicitudes legítimas en hilos concurrentes
        tasks.append((sess_a_id, f"resume el documento {doc_a}"))
        tasks.append((sess_b_id, f"resume el documento {doc_b}"))
        # Solicitudes cruzadas no autorizadas que deben ser bloqueadas
        tasks.append((sess_a_id, f"resume el documento {doc_b}"))
        tasks.append((sess_b_id, f"resume el documento {doc_a}"))

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(worker_request, tasks))

    for idx, r in enumerate(results):
        kind = idx % 4
        if kind == 0:
            # Sesión A -> doc_a (legítimo)
            assert r.success is True
            assert "Resumen extractivo" in r.response_text
        elif kind == 1:
            # Sesión B -> doc_b (legítimo)
            assert r.success is True
            assert "Resumen extractivo" in r.response_text
        elif kind == 2:
            # Sesión A -> doc_b (cruzado no autorizado)
            assert r.success is False or "Acceso denegado" in r.response_text or "fuera del alcance" in r.response_text
        elif kind == 3:
            # Sesión B -> doc_a (cruzado no autorizado)
            assert r.success is False or "Acceso denegado" in r.response_text or "fuera del alcance" in r.response_text

    # 5. Regresión 4: Excepción durante una petición en Sesión A seguida de Sesión B
    from unittest.mock import patch
    sess_c_id = "sesion-regresion-c-sin-autorizacion"
    sess_c = local_agent.context_manager.get_or_create_session(sess_c_id)
    sess_c.grant_scope(None)

    # Forzar excepción en Session A simulando un fallo inesperado durante la ejecución
    with patch("core.documents.summarizer.extractive_summarize", side_effect=RuntimeError("Fallo inducido para prueba de excepción")):
        res_exc = local_agent.process_text(f"resume el documento {doc_a}", session_id=sess_a_id)
        assert res_exc.success is False or "Fallo inducido" in res_exc.response_text

    # Comprobar que tras la excepción, Sesión C (sin autorización) sigue terminantemente bloqueada
    res_c = local_agent.process_text(f"resume el documento {doc_a}", session_id=sess_c_id)
    assert res_c.success is False or "Acceso denegado" in res_c.response_text or "No se ha especificado un alcance confiable" in res_c.response_text
    assert "Resumen extractivo" not in res_c.response_text


def test_busqueda_en_carpeta_no_concede_autorizacion_de_lectura(local_agent, tmp_path):
    """Demuestra que realizar una búsqueda exitosa o solicitar una ruta en 'busca documentos en ...'
    NO concede automáticamente autorización de lectura para esa carpeta:
    
    1. La sesión cuenta con alcance legítimo concedido únicamente para 'carpeta_autorizada'.
    2. El usuario o modelo ejecuta 'busca documentos en <carpeta_no_autorizada>'.
    3. La búsqueda descubre los candidatos pero NO altera session.trusted_root ni concede lectura.
    4. El usuario solicita resumir el documento descubierto fuera de alcance -> Denegado con política de seguridad.
    5. El usuario solicita resumir un documento dentro del alcance concedido -> Éxito.
    """
    dir_autorizado = tmp_path / "carpeta_autorizada"
    dir_autorizado.mkdir()
    doc_autorizado = dir_autorizado / "informe_legitimo.txt"
    doc_autorizado.write_text("La comisión determinó aprobar las partidas presupuestarias.", encoding="utf-8")

    dir_no_autorizado = tmp_path / "carpeta_no_autorizada"
    dir_no_autorizado.mkdir()
    doc_secreto = dir_no_autorizado / "datos_confidenciales.txt"
    doc_secreto.write_text("Acuerdo restringido fuera de los alcances operativos autorizados.", encoding="utf-8")

    session_id = "sesion-no-auto-autorizacion-busqueda"
    sess = local_agent.context_manager.get_or_create_session(session_id)
    # Concesión legítima restringida únicamente a dir_autorizado
    sess.grant_scope(dir_autorizado)

    # Verificar alcance inicial concedido
    assert sess.trusted_root == str(dir_autorizado.resolve())

    # TURNO 1: Búsqueda sobre la carpeta no autorizada
    prompt_buscar = f"busca documentos en {dir_no_autorizado}"
    res_busqueda = local_agent.process_text(prompt_buscar, session_id=session_id)

    assert res_busqueda.success is True
    assert "datos_confidenciales.txt" in res_busqueda.response_text

    # INVARIANTE CRÍTICO: La búsqueda NO debe haber modificado session.trusted_root ni granted_scope
    assert sess.trusted_root == str(dir_autorizado.resolve())
    assert sess.trusted_root != str(dir_no_autorizado.resolve())

    # TURNO 2: Intento de resumir el documento descubierto fuera de alcance
    prompt_resumen_externo = f"resume el documento {doc_secreto}"
    res_externo = local_agent.process_text(prompt_resumen_externo, session_id=session_id)

    # Debe ser denegado por política de autorización antes de leer el contenido
    assert res_externo.success is False or "Acceso denegado" in res_externo.response_text or "fuera del alcance autorizado" in res_externo.response_text
    assert "Resumen extractivo" not in res_externo.response_text

    # TURNO 3: Resumir el documento legítimo dentro del alcance concedido en la misma sesión
    prompt_resumen_propio = f"resume el documento {doc_autorizado}"
    res_propio = local_agent.process_text(prompt_resumen_propio, session_id=session_id)

    assert res_propio.success is True
    assert "Resumen extractivo" in res_propio.response_text
    assert "aprobó las partidas presupuestarias" in res_propio.response_text or "determinó aprobar" in res_propio.response_text


# ══════════════════════════════════════════════════════════════════
# 4. CLI REAL
# ══════════════════════════════════════════════════════════════════

def test_cli_busqueda_sin_resultados_real():
    """Verifica desde la CLI real que una búsqueda sin lectura declare únicamente apertura."""
    cmd = [sys.executable, "main.py", "run", "busca informacion sobre termino_inexistente_sin_lectura_12345"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, errors="replace")

    assert result.returncode == 0
    output = result.stdout
    assert "squeda para" in output
    assert "en el navegador" in output
    assert "termino_inexistente_sin_lectura_12345" in output
