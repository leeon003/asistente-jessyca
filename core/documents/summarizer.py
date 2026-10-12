"""Motor común de resumen extractivo estructurado para documentos (core/documents/summarizer.py).

Implementa un extractor de reglas gobernado, honestamente identificado como resumen extractivo,
que garantiza:
1. Exclusión de líneas vacías, separadores decorativos y encabezados duplicados.
2. Priorización de decisiones, negaciones, restricciones y conclusiones por encima o a la par
   de datos numéricos secundarios, evitando que textos sin cifras se pierdan.
3. Distribución estratificada a lo largo de todo el documento.
4. Preservación de hechos y referencias documentales auditables (Línea X).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Separadores decorativos típicos en documentos de texto / Markdown / Word
_SEPARATOR_REGEX = re.compile(r"^[\—\-\=\_\*\.\s]{2,}$")
_EXPLICIT_SEPARATORS = frozenset({"—", "--", "---", "===", "___", "***", "• • •", "- - -", "* * *", "==="})

# Marcadores de decisiones, acuerdos, conclusiones y determinaciones
_DECISION_WORDS = re.compile(
    r"\b(acord[oó]|decidi[oó]|determin[oó]|resolvi[oó]|aprob[oó]|rechaz[oó]|desestim[oó]|autoriz[oó]|"
    r"prohibi[oó]|dictamin[oó]|conclusi[oó]n|concluye|decisi[oó]n|resoluci[oó]n|acuerdo|acordado|"
    r"dictamen|postura|veredicto)\b",
    re.IGNORECASE,
)

# Marcadores de negación, prohibición, cancelación y restricciones críticas
_NEGATION_WORDS = re.compile(
    r"\b(no se autoriza|se proh[ií]be|queda cancelado|sin efecto|denegado|no procede|se descarta|"
    r"no se admiten|queda sin validez|rechazado|no se acepta|no se aprob[oó]|no se realizar[aá]|"
    r"no continuar|se suspende|vetado|inadmisible)\b",
    re.IGNORECASE,
)

# Marcadores numéricos y métricas operativas
_METRICS_REGEX = re.compile(
    r"\d+[\.,]?\d*|\$|€|%|USD|EUR|KB|MB|GB|TB|ms|segundos|minutos|horas|d[ií]as|usuarios|servidores",
    re.IGNORECASE,
)


def resolve_effective_authorized_root(
    requested_root: str | Path | None = None,
    trusted_root: str | Path | None = None,
    allow_unrestricted_policy: bool = False,
) -> Path | None:
    """Resuelve la política efectiva de confinamiento documental a partir de una fuente confiable.

    REGLAS DE SEGURIDAD Y PROCEDENCIA:
    1. El alcance efectivo DEBE proceder de una autorización o configuración confiable (trusted_root).
       Los parámetros de solicitud (requested_root) son UNTRUSTED INPUT y NUNCA pueden
       otorgar o ampliar autorización por sí mismos.
    2. Si falta el alcance confiable requerido (trusted_root es None, vacío o solo espacios en blanco):
       - Se RECHAZA la operación con un PermissionError explícito.
       - No se acepta requested_root como sustituto ni se asume None como acceso libre.
    3. Si existe un modo de acceso amplio legítimo, DEBE proceder de una política confiable explícita
       (allow_unrestricted_policy=True o trusted_root == "*"), no de requested_root ni de None.
    4. Con trusted_root válido:
       - Si requested_root se omite o está vacío: se conserva la política efectiva concedida (trusted_root).
       - Si requested_root se especifica: debe residir estrictamente DENTRO del alcance concedido
         (sub-alcance menor). Si intenta escapar o ubicarse fuera de trusted_root, se RECHAZA con PermissionError.
    """
    from pathlib import Path

    # 1. Modo de acceso amplio legítimo solo mediante política confiable explícita
    if allow_unrestricted_policy or (isinstance(trusted_root, str) and trusted_root.strip() == "*"):
        return None

    # 2. Normalización de trusted_root (autorización o configuración confiable)
    clean_trusted = str(trusted_root).strip() if trusted_root is not None else ""
    if not clean_trusted:
        raise PermissionError(
            "Acceso denegado: No se ha especificado un alcance confiable autorizado (trusted_root). "
            "La lectura requiere autorización o configuración confiable explícita."
        )

    base_trusted = Path(clean_trusted).resolve()

    # 3. Normalización de requested_root (parámetro de herramienta no confiable)
    clean_requested = str(requested_root).strip() if requested_root is not None else ""
    if not clean_requested:
        # Omitido o vacío: conserva la política efectiva concedida
        return base_trusted

    p_req = Path(clean_requested).resolve()
    try:
        p_req.relative_to(base_trusted)
        return p_req
    except ValueError:
        raise PermissionError(
            f"Acceso denegado: El alcance solicitado '{clean_requested}' no puede ampliar "
            f"el alcance concedido '{base_trusted}'."
        )


def check_document_authorization(
    file_path: str | Path,
    authorized_root: str | Path | None = None,
    trusted_root: str | Path | None = None,
    allow_unrestricted_policy: bool = False,
) -> tuple[bool, str]:
    """Evalúa deterministamente la política efectiva de autorización documental.

    Reutiliza el mecanismo de autorización existente:
    1. Bloqueo de rutas críticas de Windows (_is_path_critical).
    2. Bloqueo de extensiones ejecutables (FORBIDDEN_EXECUTABLE_EXTENSIONS).
    3. Procedencia de authorized_root y confinamiento:
       - El alcance confiable es obligatorio (salvo política amplia explícita).
       - Los parámetros no confiables pueden reducir el alcance, pero nunca otorgar o ampliar.
       - La omisión de parámetros conserva la política efectiva concedida.
    """
    p_file = Path(file_path).resolve()

    from skills.files_skills import FORBIDDEN_EXECUTABLE_EXTENSIONS, _is_path_critical
    from core.logger import get_logger
    logger = get_logger("jessyca.core.documents.authorization")

    # 1. Rutas críticas de Windows
    if _is_path_critical(str(p_file)):
        logger.warning(f"[AUTH POLICY DENIED] Archivo en ruta crítica: {p_file}")
        return False, f"Acceso denegado: Intento de lectura en ruta crítica de Windows ({p_file.name})."

    # 2. Extensiones ejecutables prohibidas
    if p_file.suffix.lower() in FORBIDDEN_EXECUTABLE_EXTENSIONS:
        logger.warning(f"[AUTH POLICY DENIED] Extensión ejecutable prohibida: {p_file.suffix}")
        return False, f"Acceso denegado: Las extensiones ejecutables ({p_file.suffix}) están prohibidas."

    # 3. Procedencia de authorized_root y confinamiento al alcance autorizado
    try:
        effective_root = resolve_effective_authorized_root(
            requested_root=authorized_root,
            trusted_root=trusted_root,
            allow_unrestricted_policy=allow_unrestricted_policy,
        )
    except PermissionError as err:
        logger.warning(f"[AUTH POLICY DENIED] Intento de ampliación o falta de alcance confiable: {err}")
        return False, str(err)

    if effective_root:
        from tools.filesystem.path_security import PathSecurityManager
        from tools.filesystem.errors import PathSecurityError, SandboxViolationError
        try:
            sec_mgr = PathSecurityManager(sandbox_root=effective_root)
            sec_mgr.validate_and_canonicalize(str(p_file))
            logger.info(f"[AUTH POLICY ALLOWED] '{p_file}' autorizado dentro del alcance '{sec_mgr.canonical_sandbox_str}'.")
        except (SandboxViolationError, PathSecurityError) as err:
            logger.warning(f"[AUTH POLICY DENIED] '{p_file}' fuera del alcance autorizado '{effective_root}': {err}")
            return False, f"Acceso denegado: El archivo '{p_file.name}' está fuera del alcance autorizado."

    return True, "Autorizado"


def extractive_summarize(
    content: str = "",
    file_path: str = "",
    max_points: int = 5,
    authorized_root: str | Path | None = None,
    trusted_root: str | Path | None = None,
    allow_unrestricted_policy: bool = False,
) -> dict[str, Any]:
    """Genera un resumen extractivo auditable sobre un texto o archivo documental."""
    # 1. Recuperar contenido desde archivo si no se suministró en memoria
    if not content and file_path:
        p_file = Path(file_path).resolve()

        # Validación estricta y trazabilidad de la política efectiva de autorización ANTES de leer
        is_auth, auth_reason = check_document_authorization(
            p_file,
            authorized_root=authorized_root,
            trusted_root=trusted_root,
            allow_unrestricted_policy=allow_unrestricted_policy,
        )
        if not is_auth:
            raise PermissionError(auth_reason)

        if not p_file.exists():
            raise FileNotFoundError(f"Documento no encontrado o no disponible: {file_path}")

        if p_file.suffix.lower() == ".docx":
            try:
                import docx
                doc = docx.Document(p_file)
                content = "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
            except Exception:
                with open(p_file, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(50000)
        else:
            with open(p_file, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(50000)

    if not content or not str(content).strip():
        return {
            "exito": False,
            "mensaje": "El documento no contiene texto para resumir.",
            "summary": "Sin contenido textual para resumir.",
            "resumen": "Sin contenido textual para resumir.",
            "key_points": [],
            "puntos_clave": [],
            "references": [],
            "referencias": [],
            "mode": "extractive",
            "verified": False,
        }

    raw_lines = str(content).splitlines()
    candidates: list[dict[str, Any]] = []
    seen_normalized: set[str] = set()

    for idx, raw in enumerate(raw_lines, start=1):
        clean = raw.strip()
        if not clean:
            continue

        # A. Excluir separadores decorativos
        if clean in _EXPLICIT_SEPARATORS or _SEPARATOR_REGEX.match(clean):
            continue

        # B. Excluir títulos repetidos y líneas duplicadas normalizadas
        norm = re.sub(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ]", "", clean.lower())
        if not norm or norm in seen_normalized:
            continue
        seen_normalized.add(norm)

        # C. Ponderación sustantiva:
        # - Negaciones y restricciones: +4 (evita que decisiones negativas se pierdan)
        # - Decisiones y acuerdos: +4 (conserva decisiones no numéricas)
        # - Métricas y cifras: +2 (datos cuantificables)
        # - Viñetas y directivas: +1
        weight = 0
        if _NEGATION_WORDS.search(clean):
            weight += 4
        if _DECISION_WORDS.search(clean):
            weight += 4
        if _METRICS_REGEX.search(clean):
            weight += 2
        if clean.startswith(("-", "*", "•", "1.", "2.", "3.", "4.", "5.")):
            weight += 1
        if clean.startswith("#") or (len(clean) < 60 and not clean.endswith(".")):
            weight += 1

        candidates.append({"line": idx, "text": clean, "weight": weight})

    if not candidates:
        return {
            "exito": False,
            "mensaje": "El documento no contiene líneas sustantivas para resumir.",
            "summary": "Documento sin líneas sustantivas para extraer.",
            "resumen": "Documento sin líneas sustantivas para extraer.",
            "key_points": [],
            "puntos_clave": [],
            "references": [],
            "referencias": [],
            "mode": "extractive",
            "verified": False,
        }

    # D. Selección estratificada a lo largo de todo el documento (inicio, medio y final)
    if len(candidates) > max_points:
        chunk_size = len(candidates) / float(max_points)
        selected: list[dict[str, Any]] = []
        for i in range(max_points):
            start_i = int(i * chunk_size)
            end_i = int((i + 1) * chunk_size) if i < max_points - 1 else len(candidates)
            stratum = candidates[start_i:end_i]
            if stratum:
                # Elige el mejor candidato del estrato según peso y relevancia
                best = max(stratum, key=lambda c: (c["weight"], len(c["text"])))
                selected.append(best)
        selected.sort(key=lambda x: x["line"])
    else:
        selected = candidates

    puntos_clave = [s["text"] for s in selected]
    referencias = [f"Línea {s['line']}: {s['text'][:70]}..." for s in selected]

    resumen_text = (
        f"Resumen extractivo ({len(puntos_clave)} puntos clave):\n"
        + "\n".join(f"• {pt}" for pt in puntos_clave)
        + "\n\nReferencias Documentales:\n"
        + "\n".join(f"[{ref}]" for ref in referencias)
    )

    return {
        "exito": True,
        "mensaje": "Resumen extractivo generado con éxito.",
        "resumen": resumen_text,
        "summary": resumen_text,
        "puntos_clave": puntos_clave,
        "key_points": puntos_clave,
        "referencias": referencias,
        "references": referencias,
        "mode": "extractive",
        "source_ref": str(file_path) if file_path else "en_memoria",
        "verified": len(puntos_clave) > 0 and len(referencias) > 0,
    }
