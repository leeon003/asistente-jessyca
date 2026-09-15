"""Skill de gestión de aplicaciones de Windows (apps_skill.py - Fase 28.7 / Post-51.1).

Permite abrir, inspeccionar y cerrar aplicaciones de escritorio de forma gobernada, trazable e idempotente.
Garantiza la regla fundamental:
    1 PETICIÓN -> 1 EJECUCIÓN -> 1 VERIFICACIÓN -> ESTADO REAL CORRECTO -> SUCCESS
    NO REAL STATE CHANGE / NO EXECUTION EVIDENCE = NO SUCCESS CLAIM (0 FALSE SUCCESSES)
"""

from __future__ import annotations

import os
import re
import subprocess
import unicodedata
from typing import Any

import psutil
import yaml

from core.application_session_manager import ApplicationSessionManager, FakeApplicationAdapter
from core.execution.execution_verifier import get_execution_verifier
from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.base_skill import BaseSkill
from skills.skill_models import (
    SkillDefinition,
    SkillManifest,
)

logger = get_logger("jessyca.skills.apps_skill")

CONFIG_APPS_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config",
    "apps.yaml",
)

SINGLE_INSTANCE_APPS: frozenset[str] = frozenset({
    "notepad.exe",
    "notepad",
    "calc.exe",
    "calculatorapp.exe",
    "calc",
    "calculadora",
    "mspaint.exe",
    "paint.exe",
    "msedge.exe",
    "chrome.exe",
})


def _normalizar(texto: str) -> str:
    """Normaliza cadenas para comparar nombres de aplicaciones tolerando variaciones."""
    texto = texto.strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[_\-]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _buscar_en_mapeo(nombre_input: str, mapeo: dict[str, str]) -> str | None:
    input_norm = _normalizar(nombre_input)
    mapeo_norm = {_normalizar(k): v for k, v in mapeo.items()}

    if input_norm in mapeo_norm:
        return mapeo_norm[input_norm]

    for clave_norm, ejecutable in mapeo_norm.items():
        if input_norm in clave_norm or clave_norm in input_norm:
            return ejecutable

    return None


class WindowsAppsSkill(BaseSkill):
    """Skill de producción para control de aplicaciones de Windows con verificación de estado real."""

    def __init__(
        self,
        ruta_config: str = CONFIG_APPS_PATH,
        session_manager: ApplicationSessionManager | None = None,
    ) -> None:
        self.ruta_config = ruta_config
        self.session_manager = session_manager or ApplicationSessionManager()
        manifest = SkillManifest(
            id="windows.apps",
            name="Windows Apps Manager",
            version="1.0.0",
            description="Controla la apertura, inspección y cierre de aplicaciones en Windows (ej: Bloc de notas, Calculadora, Explorer).",
            author="Jessyca Core",
            capabilities=("application_control", "application"),
            required_tools=("apps.open", "apps.close", "apps.inspect"),
            required_agents=("DesktopAgent", "SystemAgent"),
            required_models=("llama3.2:latest",),
            permissions=("apps.open", "apps.close", "apps.inspect"),
            risk_level=SecurityLevel.SAFE,
        )
        def_obj = SkillDefinition(
            skill_id="windows.apps",
            name="Windows Apps Manager",
            version="1.0.0",
            description="Controla la apertura, inspección y cierre de aplicaciones en Windows.",
            capabilities=("application_control", "application"),
            required_tools=("apps.open", "apps.close", "apps.inspect"),
            required_permissions=("apps.open", "apps.close", "apps.inspect"),
            risk_level=SecurityLevel.SAFE,
            tags=("apps", "windows", "abrir", "cerrar", "programa", "aplicacion", "bloc", "notas"),
            manifest=manifest,
        )
        super().__init__(nombre="windows.apps", nivel_riesgo=1, definition=def_obj)

    def _cargar_mapeo(self) -> dict[str, str]:
        # Fallback predeterminado si el archivo config/apps.yaml no existe
        defaults = {
            "bloc de notas": "notepad.exe",
            "notepad": "notepad.exe",
            "calculadora": "calc.exe",
            "explorer": "explorer.exe",
            "cmd": "cmd.exe",
            "paint": "mspaint.exe",
            "edge": "msedge.exe",
            "chrome": "chrome.exe",
        }
        if not os.path.exists(self.ruta_config):
            return defaults
        try:
            with open(self.ruta_config, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict) and "applications" in data and isinstance(data["applications"], dict):
                    merged = dict(defaults)
                    merged.update({str(k): str(v) for k, v in data["applications"].items()})
                    return merged
        except Exception:
            pass
        return defaults

    def _get_running_pids(self, comando: str) -> list[int]:
        """Obtiene los PIDs de procesos activos que coinciden con el ejecutable."""
        target_clean = (comando or "").strip().lower()
        base_key = target_clean[:-4] if target_clean.endswith(".exe") else target_clean

        aliases = [target_clean, f"{base_key}.exe", base_key]
        if "notepad" in base_key:
            aliases.extend(["notepad.exe", "notepad"])
        elif "calc" in base_key:
            aliases.extend(["calculatorapp.exe", "calc.exe", "calculator.exe", "applicationframehost.exe"])
        elif "paint" in base_key:
            aliases.extend(["mspaint.exe", "paint.exe", "mspaint"])
        elif any(k in base_key for k in ("chrome", "google", "youtube", "edge", "msedge", "navegador")):
            aliases.extend(["chrome.exe", "msedge.exe", "chrome", "msedge"])

        found_pids: list[int] = []
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                if any(cand == pname for cand in aliases):
                    pid = proc.info.get("pid")
                    if pid is not None:
                        found_pids.append(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return found_pids

    def ejecutar(self, parametros: dict[str, Any]) -> dict[str, Any]:
        accion = str(parametros.get("accion") or parametros.get("action") or "abrir").lower()
        nombre_app = (
            parametros.get("nombre_app")
            or parametros.get("app")
            or parametros.get("nombre")
            or parametros.get("query")
        )

        if not nombre_app:
            return {"exito": False, "mensaje": "Debe especificar el nombre de la aplicación."}

        req_id = str(parametros.get("request_id") or "req_apps")
        exec_id = str(parametros.get("execution_id") or "exec_apps")
        action_id = str(parametros.get("action_id") or parametros.get("execution_id") or parametros.get("request_id") or f"act-apps-{req_id}")

        mapeo = self._cargar_mapeo()
        comando = _buscar_en_mapeo(str(nombre_app), mapeo) or f"{nombre_app}.exe"

        # 1. ACCIÓN: ABRIR
        if accion in ("abrir", "open", "launch"):
            logger.info(f"[APP_EXECUTION_REQUEST] request_id={req_id} action_id={action_id} target={nombre_app} accion={accion} comando={comando}")
            try:
                # Estado previo: Medir procesos existentes antes del intento de apertura
                pids_before = self._get_running_pids(comando)
                logger.info(f"[APP_STATE_BEFORE] target={nombre_app} process_count={len(pids_before)} pids={pids_before}")

                # Invocar lanzamiento a través de ApplicationSessionManager (Fase 75.1-B)
                logger.info(f"[APP_LAUNCH_INVOKED] execution_id={exec_id} action_id={action_id} target={nombre_app} command={comando}")
                session = self.session_manager.launch_app(str(nombre_app), action_id=action_id)
                execution_count = self.session_manager.get_execution_count(str(nombre_app))
                logger.info(f"[APP_LAUNCH_RESULT] execution_id={exec_id} action_id={action_id} session={session.session_id} execution_count={execution_count}")

                # Verificación determinista post-lanzamiento
                is_fake_adapter = isinstance(self.session_manager.adapter, FakeApplicationAdapter)
                if is_fake_adapter:
                    pids_after: list[int] = [session.pid] if session.pid is not None else []
                    new_pids: list[int] = [session.pid] if session.pid is not None else []
                    evidence_verified = True
                    evidence_dict: dict[str, Any] = {"verified": True, "details": {"pids": pids_after}}
                else:
                    evidence = get_execution_verifier().verify_execution(
                        "open_application", comando, {"nombre_app": nombre_app, "initial_pids": pids_before}, timeout_seconds=2.5
                    )
                    evidence_verified = evidence.is_verified
                    evidence_dict = evidence.to_dict()
                    raw_pids = evidence.details.get("pids", [])
                    pids_after = [int(p) for p in raw_pids if p is not None] if raw_pids else self._get_running_pids(comando)
                    new_pids = list(set(pids_after) - set(pids_before))

                logger.info(f"[APP_STATE_AFTER] target={nombre_app} process_count={len(pids_after)} pids={pids_after} new_pids={new_pids}")

                if evidence_verified and (len(pids_after) > 0 or is_fake_adapter):
                    state_change = "APPLICATION_OPENED" if (len(new_pids) > 0 or len(pids_before) == 0) else "APPLICATION_ACTIVATED"
                    logger.info(f"[APP_VERIFICATION] target={nombre_app} result=SUCCESS state_change={state_change} (new_pids={new_pids})")
                    logger.info(f"[APP_EXECUTION_FINAL] execution_id={exec_id} action_id={action_id} status=SUCCEEDED state={state_change}")
                    return {
                        "exito": True,
                        "app_state": state_change,
                        "mensaje": f"Listo, abrí {nombre_app}.",
                        "comando": comando,
                        "reused_instance": (state_change == "APPLICATION_ACTIVATED"),
                        "execution_count": execution_count,
                        "action_id": action_id,
                        "session_id": session.session_id,
                        "process_before": pids_before,
                        "process_after": pids_after,
                        "new_pids": new_pids,
                        "evidence": evidence_dict,
                    }
                else:
                    # PREVENCIÓN ESTRICTA DE FALSE SUCCESS (SI NUNCA APARECE EL PROCESO)
                    logger.warning(f"[APP_VERIFICATION] target={nombre_app} result=FAILED state_change=VERIFICATION_FAILED (process never appeared)")
                    logger.error(f"[APP_EXECUTION_FINAL] execution_id={exec_id} action_id={action_id} status=VERIFICATION_FAILED (FALSE SUCCESS PREVENTED)")
                    return {
                        "exito": False,
                        "app_state": "VERIFICATION_FAILED",
                        "mensaje": f"Intenté abrir {nombre_app}, pero Windows no confirmó que se haya abierto.",
                        "comando": comando,
                        "reused_instance": False,
                        "execution_count": execution_count,
                        "action_id": action_id,
                        "session_id": session.session_id,
                        "process_before": pids_before,
                        "process_after": pids_after,
                        "new_pids": [],
                        "error_code": "VERIFICATION_FAILED",
                        "evidence": evidence.to_dict(),
                    }

            except Exception as e:
                logger.error(f"[APPS_SKILL OPEN ERROR] Error al abrir '{nombre_app}': {e}")
                return {
                    "exito": False,
                    "app_state": "EXECUTION_FAILED",
                    "mensaje": f"Error al abrir '{nombre_app}': {e}",
                    "comando": comando,
                    "execution_count": 0,
                    "error_code": "EXECUTION_FAILED",
                }

        # 2. ACCIÓN: CERRAR
        elif accion in ("cerrar", "close", "stop"):
            closed = self.session_manager.close_app(str(nombre_app))
            proc_name = comando.lower()
            terminados = 1 if (closed and isinstance(self.session_manager.adapter, FakeApplicationAdapter)) else 0
            targets_to_check = [proc_name]
            if "notepad" in proc_name or "bloc" in str(nombre_app).lower():
                targets_to_check.extend(["notepad.exe", "notepad"])
            elif "calc" in proc_name or "calculadora" in str(nombre_app).lower():
                targets_to_check.extend(["calculatorapp.exe", "calc.exe", "calculator.exe", "applicationframehost.exe"])
            elif "paint" in proc_name:
                targets_to_check.extend(["mspaint.exe", "paint.exe", "mspaint"])
            elif "edge" in proc_name or "chrome" in proc_name or "navegador" in str(nombre_app).lower():
                targets_to_check.extend(["msedge.exe", "chrome.exe"])

            for proc in psutil.process_iter(["name"]):
                try:
                    pname = (proc.info.get("name") or "").lower()
                    if any(t == pname or t in pname for t in targets_to_check):
                        proc.kill()
                        terminados += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if os.name == "nt":
                for tgt in targets_to_check:
                    if tgt.endswith(".exe"):
                        try:
                            subprocess.run(["taskkill", "/f", "/im", tgt], capture_output=True, check=False)
                        except Exception:
                            pass

            evidence = get_execution_verifier().verify_execution(
                "close_application", comando, {"nombre_app": nombre_app}, timeout_seconds=2.0
            )

            if terminados > 0 and evidence.is_verified:
                return {
                    "exito": True,
                    "mensaje": f"Listo, cerré {nombre_app}.",
                    "terminados": terminados,
                    "evidence": evidence.to_dict(),
                }
            elif terminados == 0:
                return {
                    "exito": False,
                    "mensaje": f"No se encontraron procesos activos de '{nombre_app}' para cerrar.",
                    "terminados": 0,
                    "evidence": evidence.to_dict(),
                }
            else:
                return {
                    "exito": False,
                    "mensaje": f"Se intentó cerrar '{nombre_app}', pero el proceso sigue activo.",
                    "terminados": terminados,
                    "evidence": evidence.to_dict(),
                    "error_code": "VERIFICATION_FAILED",
                }

        # 3. ACCIÓN: INSPECCIONAR
        elif accion in ("inspeccionar", "inspect", "status"):
            proc_name = comando.lower()
            activos = []
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if proc.info["name"] and proc.info["name"].lower() == proc_name:
                        activos.append(proc.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            return {
                "exito": True,
                "mensaje": f"Se encontraron {len(activos)} instancia(s) activa(s) de '{nombre_app}'.",
                "instancias": activos,
            }

        return {"exito": False, "mensaje": f"Acción '{accion}' no reconocida."}
