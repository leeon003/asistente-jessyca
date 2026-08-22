"""Abstracciones e implementaciones del Repositorio de Skills (skill_repository.py - Fase 34).

Proporciona:
- BaseSkillRepository (ABC)
- LocalDirectorySkillRepository (Almacén local / air-gapped)
- MockNetworkSkillRepository (Simulación de repositorio remoto con fallos de red / timeouts)
- CachingSkillRepository (Caché local con verificación estricta de integridad SHA-256 y soporte offline)

INVARIANTES DE SEGURIDAD:
- El repositorio NO ejecuta código.
- Los paquetes en caché son verificados criptográficamente mediante SHA-256 antes de su consumo.
- Ante fallo o desconexión del repositorio, el sistema degrada de forma graceful al modo offline.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from core.logger import get_logger
from core.security_architecture import SecurityLevel
from skills.skill_package import SkillPackage
from skills.skill_repository_models import (
    RepositorySkillEntry,
    SkillReputation,
    TrustStatus,
)

logger = get_logger("jessyca.skills.repository")


class RepositoryError(Exception):
    """Excepción base para errores relacionados con el repositorio de Skills."""


class RepositoryUnavailableError(RepositoryError):
    """El repositorio no se encuentra accesible o la red está desconectada."""


class RepositoryTimeoutError(RepositoryError):
    """La solicitud al repositorio ha excedido el tiempo de espera configurado."""


class PackageNotFoundError(RepositoryError):
    """La Skill o versión solicitada no existe en el repositorio."""


class CorruptedDownloadError(RepositoryError):
    """El paquete descargado está corrupto o su hash SHA-256 no coincide."""


class BaseSkillRepository(ABC):
    """Interfaz conceptual base para repositorios de Skills."""

    @abstractmethod
    def search(
        self,
        query: str = "",
        category: str | None = None,
        tags: tuple[str, ...] | None = None,
        limit: int = 20,
    ) -> list[RepositorySkillEntry]:
        """Busca Skills en el catálogo del repositorio."""
        pass

    @abstractmethod
    def get_metadata(self, skill_id: str, version: str | None = None) -> RepositorySkillEntry | None:
        """Obtiene los metadatos completos de una Skill o versión específica."""
        pass

    @abstractmethod
    def get_versions(self, skill_id: str) -> list[str]:
        """Obtiene la lista de versiones disponibles para una Skill."""
        pass

    @abstractmethod
    def download_package(
        self,
        skill_id: str,
        version: str | None = None,
        destination_dir: str | Path | None = None,
    ) -> SkillPackage:
        """Descarga o localiza el paquete .skpkg de una Skill."""
        pass

    @abstractmethod
    def get_signature(self, skill_id: str, version: str | None = None) -> dict[str, Any] | None:
        """Obtiene la firma digital publicada para la Skill."""
        pass

    @abstractmethod
    def get_dependencies(self, skill_id: str, version: str | None = None) -> dict[str, str]:
        """Obtiene las dependencias declaradas para la Skill."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Indica si el repositorio se encuentra disponible y accesible."""
        pass


class LocalDirectorySkillRepository(BaseSkillRepository):
    """Implementación de repositorio basada en un directorio local (air-gapped / testing)."""

    def __init__(self, repo_dir: str | Path) -> None:
        self.repo_dir = Path(repo_dir).resolve()
        self.repo_dir.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, dict[str, RepositorySkillEntry]] = {}  # {skill_id: {version: entry}}
        self._package_paths: dict[str, dict[str, Path]] = {}  # {skill_id: {version: path}}
        self._is_online: bool = True
        self._load_index()

    def set_online_status(self, is_online: bool) -> None:
        """Modifica el estado de conectividad simulado."""
        self._is_online = is_online

    def is_available(self) -> bool:
        return self._is_online

    def _load_index(self) -> None:
        index_file = self.repo_dir / "index.json"
        if not index_file.exists():
            return

        try:
            with open(index_file, encoding="utf-8") as f:
                data = json.load(f)
                skills_list = data.get("skills", [])
                for item in skills_list:
                    entry = self._dict_to_entry(item)
                    if entry.id not in self._entries:
                        self._entries[entry.id] = {}
                    self._entries[entry.id][entry.version] = entry
        except Exception as e:
            logger.error(f"[REPO INDEX ERROR] Error cargando 'index.json': {e}")

    def _dict_to_entry(self, d: dict[str, Any]) -> RepositorySkillEntry:
        rep_dict = d.get("reputation", {})
        reputation = SkillReputation(
            downloads=int(rep_dict.get("downloads", 0)),
            rating=float(rep_dict.get("rating", 0.0)),
            review_count=int(rep_dict.get("review_count", 0)),
            reports_count=int(rep_dict.get("reports_count", 0)),
        )

        risk_str = d.get("risk_level", "SAFE")
        try:
            risk_level = SecurityLevel(risk_str)
        except ValueError:
            risk_level = SecurityLevel.SAFE

        trust_str = d.get("trust_status", "UNKNOWN")
        try:
            trust_status = TrustStatus(trust_str)
        except ValueError:
            trust_status = TrustStatus.UNKNOWN

        return RepositorySkillEntry(
            id=d["id"],
            name=d.get("name", d["id"]),
            version=d.get("version", "1.0.0"),
            description=d.get("description", ""),
            author=d.get("author", "Unknown"),
            category=d.get("category", "general"),
            capabilities=tuple(d.get("capabilities", ())),
            required_tools=tuple(d.get("required_tools", ())),
            required_agents=tuple(d.get("required_agents", ())),
            required_models=tuple(d.get("required_models", ())),
            permissions=tuple(d.get("permissions", ())),
            risk_level=risk_level,
            dependencies=dict(d.get("dependencies", {})),
            framework_version=d.get("framework_version", "1.0.0"),
            min_system_version=d.get("min_system_version", "3.0.0"),
            max_system_version=d.get("max_system_version"),
            min_framework_version=d.get("min_framework_version", "1.0.0"),
            max_framework_version=d.get("max_framework_version"),
            signer_id=d.get("signer_id"),
            signature_hex=d.get("signature_hex"),
            package_sha256=d.get("package_sha256", ""),
            download_url=d.get("download_url", ""),
            release_date=d.get("release_date", ""),
            changelog=d.get("changelog", ""),
            trust_status=trust_status,
            reputation=reputation,
            tags=tuple(d.get("tags", ())),
        )

    def publish_skill_package(
        self,
        package: SkillPackage,
        trust_status: TrustStatus = TrustStatus.UNKNOWN,
        category: str = "general",
        tags: tuple[str, ...] = (),
        reputation: SkillReputation | None = None,
        release_date: str = "",
        changelog: str = "",
    ) -> RepositorySkillEntry:
        """Publica un paquete .skpkg en el repositorio local."""
        m = package.manifest
        pkg_file = Path(package.package_path)

        # Calcular hash SHA-256 del paquete bundle
        with open(pkg_file, "rb") as pf:
            pkg_bytes = pf.read()
            pkg_sha256 = hashlib.sha256(pkg_bytes).hexdigest()

        # Copiar paquete al repositorio
        dest_filename = f"{m.id}_{m.version.replace('.', '_')}.skpkg"
        repo_pkg_path = self.repo_dir / dest_filename
        if pkg_file != repo_pkg_path:
            shutil.copy2(pkg_file, repo_pkg_path)

        entry = RepositorySkillEntry(
            id=m.id,
            name=m.name,
            version=m.version,
            description=m.description,
            author=m.author,
            category=category,
            capabilities=m.capabilities,
            required_tools=m.required_tools,
            required_agents=m.required_agents,
            required_models=m.required_models,
            permissions=m.permissions,
            risk_level=m.risk_level,
            dependencies=m.dependencies,
            framework_version=m.framework_version,
            min_system_version=m.min_system_version,
            max_system_version=m.max_system_version,
            min_framework_version=m.min_framework_version,
            max_framework_version=m.max_framework_version,
            signer_id=package.signer_id,
            signature_hex=package.signature_bytes.hex() if package.signature_bytes else None,
            package_sha256=pkg_sha256,
            download_url=f"local://{dest_filename}",
            release_date=release_date,
            changelog=changelog,
            trust_status=trust_status,
            reputation=reputation or SkillReputation(),
            tags=tags,
        )

        if m.id not in self._entries:
            self._entries[m.id] = {}
            self._package_paths[m.id] = {}

        self._entries[m.id][m.version] = entry
        self._package_paths[m.id][m.version] = repo_pkg_path
        self._save_index()
        logger.info(f"[REPO PUBLISH] Skill '{m.id}@{m.version}' publicada en repositorio local.")
        return entry

    def _save_index(self) -> None:
        index_file = self.repo_dir / "index.json"
        all_skills: list[dict[str, Any]] = []
        for id_map in self._entries.values():
            for entry in id_map.values():
                all_skills.append(entry.to_dict())

        with open(index_file, "w", encoding="utf-8") as f:
            json.dump({"skills": all_skills}, f, indent=2)

    def search(
        self,
        query: str = "",
        category: str | None = None,
        tags: tuple[str, ...] | None = None,
        limit: int = 20,
    ) -> list[RepositorySkillEntry]:
        if not self.is_available():
            raise RepositoryUnavailableError("El repositorio local no se encuentra accesible (offline).")

        results: list[RepositorySkillEntry] = []
        q = query.lower()

        for id_map in self._entries.values():
            # Obtener la versión más reciente publicada
            sorted_entries = sorted(id_map.values(), key=lambda e: e.version, reverse=True)
            for entry in sorted_entries:
                if category and entry.category.lower() != category.lower():
                    continue

                if tags and not any(t.lower() in [tag.lower() for tag in entry.tags] for t in tags):
                    continue

                if q and (q not in entry.id.lower() and q not in entry.name.lower() and q not in entry.description.lower()):
                    continue

                results.append(entry)
                if len(results) >= limit:
                    return results

        return results

    def get_metadata(self, skill_id: str, version: str | None = None) -> RepositorySkillEntry | None:
        if not self.is_available():
            raise RepositoryUnavailableError("El repositorio no se encuentra accesible (offline).")

        if skill_id not in self._entries:
            return None

        id_map = self._entries[skill_id]
        if version:
            return id_map.get(version)

        # Si no se especifica versión, retornar la más alta
        sorted_versions = sorted(id_map.keys(), reverse=True)
        if sorted_versions:
            return id_map[sorted_versions[0]]
        return None

    def get_versions(self, skill_id: str) -> list[str]:
        if not self.is_available():
            raise RepositoryUnavailableError("El repositorio no se encuentra accesible (offline).")

        if skill_id not in self._entries:
            return []
        return sorted(self._entries[skill_id].keys(), reverse=True)

    def download_package(
        self,
        skill_id: str,
        version: str | None = None,
        destination_dir: str | Path | None = None,
    ) -> SkillPackage:
        if not self.is_available():
            raise RepositoryUnavailableError("El repositorio no se encuentra accesible (offline).")

        meta = self.get_metadata(skill_id, version)
        if not meta:
            raise PackageNotFoundError(f"Skill '{skill_id}' (versión {version or 'latest'}) no encontrada en repositorio.")

        effective_version = meta.version
        pkg_path = self._package_paths.get(skill_id, {}).get(effective_version)
        if not pkg_path or not pkg_path.exists():
            # Buscar en el directorio por convención de nombre
            expected_name = f"{skill_id}_{effective_version.replace('.', '_')}.skpkg"
            expected_path = self.repo_dir / expected_name
            if expected_path.exists():
                pkg_path = expected_path
            else:
                raise PackageNotFoundError(f"Archivo .skpkg para '{skill_id}@{effective_version}' no encontrado en disco.")

        # Copiar al directorio destino si se solicita
        target_path = pkg_path
        if destination_dir:
            dest_dir_path = Path(destination_dir).resolve()
            dest_dir_path.mkdir(parents=True, exist_ok=True)
            target_path = dest_dir_path / pkg_path.name
            shutil.copy2(pkg_path, target_path)

        return SkillPackage.load_bundle(target_path)

    def get_signature(self, skill_id: str, version: str | None = None) -> dict[str, Any] | None:
        meta = self.get_metadata(skill_id, version)
        if not meta or not meta.signature_hex or not meta.signer_id:
            return None
        return {
            "signer_id": meta.signer_id,
            "signature_hex": meta.signature_hex,
            "algorithm": "HMAC-SHA256",
        }

    def get_dependencies(self, skill_id: str, version: str | None = None) -> dict[str, str]:
        meta = self.get_metadata(skill_id, version)
        if not meta:
            return {}
        return dict(meta.dependencies)


class MockNetworkSkillRepository(BaseSkillRepository):
    """Simulador de Repositorio Remoto vía Red con inyección controlada de anomalías.

    Permite testear:
    - Timeouts de conexión.
    - Caídas de red / Offline.
    - Paquetes con bytes corruptos o alterados.
    - Descargas interrumpidas.
    """

    def __init__(
        self,
        underlying_repo: BaseSkillRepository,
        simulate_timeout: bool = False,
        simulate_offline: bool = False,
        simulate_corrupted_stream: bool = False,
        simulate_interrupted_stream: bool = False,
        timeout_seconds: float = 2.0,
    ) -> None:
        self.underlying = underlying_repo
        self.simulate_timeout = simulate_timeout
        self.simulate_offline = simulate_offline
        self.simulate_corrupted_stream = simulate_corrupted_stream
        self.simulate_interrupted_stream = simulate_interrupted_stream
        self.timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        if self.simulate_offline:
            return False
        return self.underlying.is_available()

    def _check_network(self) -> None:
        if self.simulate_offline:
            raise RepositoryUnavailableError("[NETWORK] Repositorio remoto no accesible (Red desconectada).")
        if self.simulate_timeout:
            raise RepositoryTimeoutError(f"[NETWORK TIMEOUT] Conexión al repositorio excedió {self.timeout_seconds}s.")

    def search(
        self,
        query: str = "",
        category: str | None = None,
        tags: tuple[str, ...] | None = None,
        limit: int = 20,
    ) -> list[RepositorySkillEntry]:
        self._check_network()
        return self.underlying.search(query, category, tags, limit)

    def get_metadata(self, skill_id: str, version: str | None = None) -> RepositorySkillEntry | None:
        self._check_network()
        return self.underlying.get_metadata(skill_id, version)

    def get_versions(self, skill_id: str) -> list[str]:
        self._check_network()
        return self.underlying.get_versions(skill_id)

    def download_package(
        self,
        skill_id: str,
        version: str | None = None,
        destination_dir: str | Path | None = None,
    ) -> SkillPackage:
        self._check_network()
        pkg = self.underlying.download_package(skill_id, version, destination_dir)

        # 1. Simulación de descarga interrumpida (archivo truncado a cero o incompleto)
        if self.simulate_interrupted_stream:
            with open(pkg.package_path, "wb") as pf:
                pf.write(b"INTERRUPTED_STREAM_INCOMPLETE_ZIP")
            logger.warning(f"[NETWORK STREAM] Descarga interrumpida simulada en '{pkg.package_path}'.")
            try:
                return SkillPackage.load_bundle(pkg.package_path)
            except Exception as exc:
                raise CorruptedDownloadError(f"Descarga interrumpida: {exc}") from exc

        # 2. Simulación de datos corruptos en tránsito
        if self.simulate_corrupted_stream:
            with open(pkg.package_path, "ab") as pf:
                pf.write(b"\x00\xFF_CORRUPTED_BYTES")
            logger.warning(f"[NETWORK STREAM] Bytes corruptos inyectados en '{pkg.package_path}'.")

        return pkg

    def get_signature(self, skill_id: str, version: str | None = None) -> dict[str, Any] | None:
        self._check_network()
        return self.underlying.get_signature(skill_id, version)

    def get_dependencies(self, skill_id: str, version: str | None = None) -> dict[str, str]:
        self._check_network()
        return self.underlying.get_dependencies(skill_id, version)


class CachingSkillRepository(BaseSkillRepository):
    """Capa de Caché Segura con validación obligatoria de SHA-256 y soporte offline.

    INVARIANTES DE SEGURIDAD:
    - Antes de entregar un paquete .skpkg desde la caché, calcula su SHA-256 y lo compara
      con el package_sha256 del registro.
    - Si el archivo en caché está corrupto o manipulado, lo purga inmediatamente y lanza CorruptedDownloadError.
    - Si el repositorio upstream está caído, sirve metadatos y paquetes válidos desde caché.
    """

    def __init__(
        self,
        upstream_repo: BaseSkillRepository,
        cache_dir: str | Path,
        ttl_seconds: float = 3600.0,
    ) -> None:
        self.upstream = upstream_repo
        self.cache_dir = Path(cache_dir).resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds

        self._metadata_cache: dict[str, dict[str, tuple[RepositorySkillEntry, float]]] = {}  # {id: {ver: (entry, ts)}}
        self._search_cache: dict[str, tuple[list[RepositorySkillEntry], float]] = {}

    def is_available(self) -> bool:
        return self.upstream.is_available()

    def search(
        self,
        query: str = "",
        category: str | None = None,
        tags: tuple[str, ...] | None = None,
        limit: int = 20,
    ) -> list[RepositorySkillEntry]:
        cache_key = f"{query}|{category}|{tags}|{limit}"
        now = time.time()

        try:
            results = self.upstream.search(query, category, tags, limit)
            self._search_cache[cache_key] = (results, now)
            # Actualizar metadatos individuales
            for r in results:
                if r.id not in self._metadata_cache:
                    self._metadata_cache[r.id] = {}
                self._metadata_cache[r.id][r.version] = (r, now)
            return results
        except (RepositoryUnavailableError, RepositoryTimeoutError):
            logger.info("[CACHE FALLBACK] Upstream offline. Buscando en caché de búsqueda/metadatos.")
            # 1. Intentar desde search_cache
            if cache_key in self._search_cache:
                cached_res, _ = self._search_cache[cache_key]
                return cached_res

            # 2. Si no hay clave exacta, filtrar entre las entradas cacheadas
            results_offline: list[RepositorySkillEntry] = []
            q = query.lower()
            for id_map in self._metadata_cache.values():
                for entry, _ in id_map.values():
                    if category and entry.category.lower() != category.lower():
                        continue
                    if q and (q not in entry.id.lower() and q not in entry.name.lower()):
                        continue
                    results_offline.append(entry)
                    if len(results_offline) >= limit:
                        return results_offline
            return results_offline

    def get_metadata(self, skill_id: str, version: str | None = None) -> RepositorySkillEntry | None:
        now = time.time()

        try:
            meta = self.upstream.get_metadata(skill_id, version)
            if meta:
                if skill_id not in self._metadata_cache:
                    self._metadata_cache[skill_id] = {}
                self._metadata_cache[skill_id][meta.version] = (meta, now)
            return meta
        except (RepositoryUnavailableError, RepositoryTimeoutError):
            logger.info(f"[CACHE FALLBACK] Upstream offline. Recuperando metadatos de '{skill_id}' desde caché.")
            id_map = self._metadata_cache.get(skill_id, {})
            if version:
                cached_tuple = id_map.get(version)
                return cached_tuple[0] if cached_tuple else None
            # Versión más alta disponible en caché
            sorted_versions = sorted(id_map.keys(), reverse=True)
            if sorted_versions:
                return id_map[sorted_versions[0]][0]
            return None

    def get_versions(self, skill_id: str) -> list[str]:
        try:
            return self.upstream.get_versions(skill_id)
        except (RepositoryUnavailableError, RepositoryTimeoutError):
            logger.info(f"[CACHE FALLBACK] Upstream offline. Listando versiones en caché de '{skill_id}'.")
            return sorted(self._metadata_cache.get(skill_id, {}).keys(), reverse=True)

    def download_package(
        self,
        skill_id: str,
        version: str | None = None,
        destination_dir: str | Path | None = None,
    ) -> SkillPackage:
        # 1. Obtener metadatos esperados para conocer el hash SHA-256
        meta = self.get_metadata(skill_id, version)
        if not meta:
            raise PackageNotFoundError(f"No se encontraron metadatos para '{skill_id}@{version or 'latest'}'.")

        effective_version = meta.version
        cache_filename = f"{skill_id}_{effective_version.replace('.', '_')}.skpkg"
        cached_pkg_file = self.cache_dir / cache_filename

        # 2. Si el archivo existe en caché, VALIDAR SU HASH SHA-256 antes de usarlo
        if cached_pkg_file.exists():
            with open(cached_pkg_file, "rb") as cf:
                actual_hash = hashlib.sha256(cf.read()).hexdigest()

            if meta.package_sha256 and actual_hash.lower() == meta.package_sha256.lower():
                logger.info(f"[CACHE HIT] Paquete '{cache_filename}' válido en caché local.")
                target_path = cached_pkg_file
                if destination_dir:
                    dest_dir_path = Path(destination_dir).resolve()
                    dest_dir_path.mkdir(parents=True, exist_ok=True)
                    dest_path = dest_dir_path / cache_filename
                    shutil.copy2(cached_pkg_file, dest_path)
                    target_path = dest_path
                return SkillPackage.load_bundle(target_path)
            else:
                # Caché corrupta o manipulada: eliminarla de inmediato
                logger.warning(
                    f"[CACHE CORRUPTED] Hash de caché no coincide para '{cache_filename}' "
                    f"(Esperado={meta.package_sha256}, Actual={actual_hash}). Eliminando de caché..."
                )
                cached_pkg_file.unlink(missing_ok=True)

        # 3. Si no está en caché o estaba corrupto, descargar desde upstream
        pkg = self.upstream.download_package(skill_id, effective_version, destination_dir=self.cache_dir)

        # 4. Validar el paquete descargado contra el hash esperado
        with open(pkg.package_path, "rb") as pf:
            download_hash = hashlib.sha256(pf.read()).hexdigest()

        if meta.package_sha256 and download_hash.lower() != meta.package_sha256.lower():
            Path(pkg.package_path).unlink(missing_ok=True)
            raise CorruptedDownloadError(
                f"El paquete descargado de '{skill_id}@{effective_version}' no coincide con el hash SHA-256 publicado. "
                f"Esperado={meta.package_sha256}, Calculado={download_hash}."
            )

        # Copiar a destination_dir si fue provisto
        target_path = Path(pkg.package_path)
        if destination_dir:
            dest_dir_path = Path(destination_dir).resolve()
            dest_dir_path.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir_path / target_path.name
            shutil.copy2(target_path, dest_path)
            target_path = dest_path

        return SkillPackage.load_bundle(target_path)

    def get_signature(self, skill_id: str, version: str | None = None) -> dict[str, Any] | None:
        try:
            return self.upstream.get_signature(skill_id, version)
        except (RepositoryUnavailableError, RepositoryTimeoutError):
            meta = self.get_metadata(skill_id, version)
            if meta and meta.signature_hex and meta.signer_id:
                return {
                    "signer_id": meta.signer_id,
                    "signature_hex": meta.signature_hex,
                    "algorithm": "HMAC-SHA256",
                }
            return None

    def get_dependencies(self, skill_id: str, version: str | None = None) -> dict[str, str]:
        meta = self.get_metadata(skill_id, version)
        if not meta:
            return {}
        return dict(meta.dependencies)
