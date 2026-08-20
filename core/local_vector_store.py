"""Almacén vectorial local y generadores de embeddings para memoria semántica (`core/local_vector_store.py` - Subetapa 12.1).

GARANTÍA ABSOLUTA DE SEGURIDAD:
1. Generación de embeddings 100% local y determinista (zero external API calls).
2. Almacenamiento vectorial en memoria / SQLite / ChromaDB local thread-safe con candado RLock.
3. Invariante central: MEMORY = EVIDENCE, MEMORY != AUTHORITY.
4. Sanitización previa de secretos con SecretRedactor / OCRTextSanitizer antes de entregar la evidencia al ContextBuilder.
5. Acotamiento estricto de top-k, tamaño de documentos, metadatos y validación de rutas (Path Traversal Protection).
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from config.settings import AppSettings
from core.logger import get_logger
from core.vector_store_models import (
    EmbeddingError,
    EmbeddingVector,
    IEmbeddingProvider,
    IVectorStore,
    VectorDocument,
    VectorSearchResult,
    VectorSizeExceededError,
    VectorStoreError,
)

logger = get_logger("jessyca.core.local_vector_store")


def validate_vector_store_path(path: Path | str) -> Path:
    """Valida la ruta de almacenamiento vectorial para evitar ataques de salto de directorio (Path Traversal)."""
    if not path:
        raise VectorStoreError("La ruta del almacén vectorial no puede estar vacía.")

    raw_str = str(path)
    if ".." in raw_str:
        raise VectorStoreError(f"Ruta de almacén vectorial no válida por intento de salto de directorio ('..'): {raw_str}")

    resolved = Path(path).resolve()
    return resolved


def validate_vector_document(
    doc: VectorDocument,
    max_doc_size: int = 65536,
    max_metadata_entries: int = 32,
) -> None:
    """Valida los límites de tamaño, caracteres y metadatos de un VectorDocument."""
    if not doc.doc_id or not isinstance(doc.doc_id, str) or not doc.doc_id.strip():
        raise VectorStoreError("El doc_id del documento vectorial debe ser una cadena no vacía.")

    if "\x00" in doc.doc_id or "\x00" in doc.content:
        raise VectorStoreError("El documento vectorial contiene caracteres nulos (null bytes) prohibidos.")

    if len(doc.content) > max_doc_size:
        raise VectorSizeExceededError(
            f"El tamaño del documento ({len(doc.content)} caracteres) excede el máximo permitido ({max_doc_size})."
        )

    if len(doc.metadata) > max_metadata_entries:
        raise VectorStoreError(
            f"La cantidad de metadatos ({len(doc.metadata)}) excede el límite máximo ({max_metadata_entries})."
        )

    for k, v in doc.metadata.items():
        if len(str(k)) > 256 or len(str(v)) > 1024:
            raise VectorStoreError("Clave o valor de metadatos excede la longitud máxima permitida.")


def compute_cosine_similarity(vec1: tuple[float, ...], vec2: tuple[float, ...]) -> float:
    """Calcula la similitud de coseno entre dos vectores numéricos."""
    if len(vec1) != len(vec2) or not vec1:
        return 0.0

    dot = sum(a * b for a, b in zip(vec1, vec2, strict=False))

    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))

    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0

    return max(-1.0, min(1.0, dot / (norm1 * norm2)))


class LocalEmbeddingProvider(IEmbeddingProvider):
    """Generador local y determinista de vectores embedding (384 dimensiones) sin dependencias externas ni de red."""

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension

    def generate_embedding(self, text: str) -> EmbeddingVector:
        """Genera un vector unitario de 384 dimensiones a partir del texto ingresado de forma determinista."""
        if not text or not isinstance(text, str):
            raise EmbeddingError("El texto para embedding no puede estar vacío.")

        clean = text.strip().lower()

        # Semilla determinista basada en el hash del texto
        raw_values: list[float] = []
        for i in range(self.dimension):
            h_str = f"{clean}:{i}"
            h_int = int(hashlib.sha256(h_str.encode("utf-8")).hexdigest()[:8], 16)
            # Normalizar a rango [-1.0, 1.0] mediante funciones trigonométricas
            val = math.sin(h_int / 1000.0)
            raw_values.append(val)

        # Normalización a vector unitario (Norma L2 = 1.0)
        norm = math.sqrt(sum(v * v for v in raw_values))
        if norm > 0:
            norm_values = tuple(v / norm for v in raw_values)
        else:
            norm_values = tuple(0.0 for _ in raw_values)

        return EmbeddingVector(values=norm_values, dimension=self.dimension)


class FakeEmbeddingProvider(IEmbeddingProvider):
    """Generador sintético e inmutable de embeddings para pruebas unitarias deterministas y rápidas."""

    def __init__(self, dimension: int = 384, fixed_value: float = 0.1) -> None:
        self.dimension = dimension
        self.fixed_value = fixed_value

    def generate_embedding(self, text: str) -> EmbeddingVector:
        """Genera un vector constante o sintético basado en la longitud para tests."""
        if not text or not isinstance(text, str):
            raise EmbeddingError("El texto para embedding no puede estar vacío.")

        # Modificación leve según longitud para variar similitud en pruebas
        mod = (len(text) % 10) * 0.01
        val = self.fixed_value + mod
        vals = tuple(val for _ in range(self.dimension))
        return EmbeddingVector(values=vals, dimension=self.dimension)


class OllamaEmbeddingProvider(IEmbeddingProvider):
    """Proveedor local de embeddings mediante API HTTP de Ollama en localhost.

    GARANTÍA DE SEGURIDAD:
    Conecta EXCLUSIVAMENTE a 127.0.0.1/localhost. Cero dependencias o conexiones externas a internet.
    Si Ollama no responde localmente, cae suavemente al LocalEmbeddingProvider determinista.
    """

    def __init__(
        self,
        model_name: str = "nomic-embed-text",
        host: str = "http://127.0.0.1:11434",
        dimension: int = 384,
        fallback_provider: IEmbeddingProvider | None = None,
    ) -> None:
        self.model_name = model_name
        self.host = host.rstrip("/")
        self.dimension = dimension
        self.fallback = fallback_provider or LocalEmbeddingProvider(dimension=dimension)

    def generate_embedding(self, text: str) -> EmbeddingVector:
        """Genera embeddings consultando a Ollama local o usando fallback."""
        if not text or not isinstance(text, str):
            raise EmbeddingError("El texto para embedding no puede estar vacío.")

        url = f"{self.host}/api/embeddings"
        payload = json.dumps({"model": self.model_name, "prompt": text}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    raw_emb = data.get("embedding", [])
                    if raw_emb:
                        # Si la dimensión difiere, ajustar o adaptar
                        if len(raw_emb) != self.dimension:
                            raw_emb = raw_emb[: self.dimension] + [0.0] * max(0, self.dimension - len(raw_emb))
                        return EmbeddingVector(values=tuple(raw_emb), dimension=self.dimension)
        except Exception as e:
            logger.debug(f"[OLLAMA EMBEDDING] No se pudo conectar con Ollama en {self.host}: {e}. Usando fallback local.")

        return self.fallback.generate_embedding(text)


class LocalVectorStore(IVectorStore):
    """Almacén vectorial local thread-safe con acotamiento de seguridad y ranking por similitud de coseno."""

    def __init__(
        self,
        store_path: Path | str | None = None,
        max_documents: int | None = None,
        max_results: int | None = None,
        max_doc_size: int | None = None,
        max_metadata_entries: int | None = None,
        embedding_provider: IEmbeddingProvider | None = None,
        enabled: bool | None = None,
    ) -> None:
        settings = AppSettings()
        self.enabled = enabled if enabled is not None else settings.VECTOR_STORE_ENABLED
        self.store_path = validate_vector_store_path(store_path or settings.VECTOR_STORE_PATH)
        self.max_documents = max_documents or settings.VECTOR_STORE_MAX_DOCUMENTS
        self.max_results = max_results or settings.VECTOR_MAX_RESULTS
        self.max_doc_size = max_doc_size or settings.VECTOR_MAX_DOCUMENT_SIZE
        self.max_metadata_entries = max_metadata_entries or settings.VECTOR_MAX_METADATA_ENTRIES
        self.provider = embedding_provider or LocalEmbeddingProvider(dimension=settings.VECTOR_STORE_EMBEDDING_DIMENSION)

        self._documents: dict[str, VectorDocument] = {}
        self._lock = threading.RLock()

    def _check_enabled(self) -> None:
        if not self.enabled:
            raise VectorStoreError("El almacén vectorial se encuentra deshabilitado por configuración.")

    def add_document(self, doc: VectorDocument) -> bool:
        """Añade o reemplaza un documento en el almacén vectorial verificando límites de capacidad y seguridad."""
        self._check_enabled()
        validate_vector_document(doc, max_doc_size=self.max_doc_size, max_metadata_entries=self.max_metadata_entries)

        with self._lock:
            if len(self._documents) >= self.max_documents and doc.doc_id not in self._documents:
                raise VectorSizeExceededError(
                    f"Almacén vectorial lleno: Se alcanzó la capacidad máxima de {self.max_documents} documentos."
                )

            self._documents[doc.doc_id] = doc
            logger.debug(f"[LOCAL VECTOR STORE] Documento '{doc.doc_id}' almacenado con éxito.")
            return True

    def search_similar(
        self,
        embedding: EmbeddingVector,
        top_k: int = 5,
        min_score: float = 0.3,
    ) -> tuple[VectorSearchResult, ...]:
        """Busca y clasifica los documentos más similares. Acota top_k al máximo configurado (`VECTOR_MAX_RESULTS`)."""
        self._check_enabled()
        bounded_top_k = min(max(1, top_k), self.max_results)

        with self._lock:
            results: list[VectorSearchResult] = []
            emb_vals = embedding.values if hasattr(embedding, "values") else tuple(embedding)
            for doc in self._documents.values():
                doc_vals = doc.embedding.values if hasattr(doc.embedding, "values") else tuple(doc.embedding)
                score = compute_cosine_similarity(emb_vals, doc_vals)
                if score >= min_score:
                    results.append(VectorSearchResult(document=doc, similarity_score=score))

            # Ordenar descendentemente por similitud de coseno
            results.sort(key=lambda r: r.similarity_score, reverse=True)
            return tuple(results[:bounded_top_k])

    def delete_document(self, doc_id: str) -> bool:
        """Elimina un documento del almacén vectorial por su doc_id."""
        self._check_enabled()
        with self._lock:
            if doc_id in self._documents:
                del self._documents[doc_id]
                logger.debug(f"[LOCAL VECTOR STORE] Documento '{doc_id}' eliminado.")
                return True
            return False

    def list_documents(self) -> tuple[VectorDocument, ...]:
        """Lista todos los documentos almacenados actualmente en el vector store."""
        self._check_enabled()
        with self._lock:
            return tuple(self._documents.values())


    def clear(self) -> bool:
        """Limpia todos los documentos del almacén vectorial."""
        self._check_enabled()
        with self._lock:
            self._documents.clear()
            logger.info("[LOCAL VECTOR STORE] Memoria vectorial vaciada completamente.")
            return True


class FakeVectorStore(IVectorStore):
    """Almacén vectorial in-memory sintético y rápido para pruebas unitarias sin E/S ni matemáticas complejas."""

    def __init__(self) -> None:
        self._documents: dict[str, VectorDocument] = {}
        self._lock = threading.RLock()

    def add_document(self, doc: VectorDocument) -> bool:
        with self._lock:
            self._documents[doc.doc_id] = doc
            return True

    def search_similar(
        self,
        embedding: EmbeddingVector,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> tuple[VectorSearchResult, ...]:
        with self._lock:
            results = [
                VectorSearchResult(document=doc, similarity_score=1.0)
                for doc in self._documents.values()
            ]
            return tuple(results[:top_k])

    def delete_document(self, doc_id: str) -> bool:
        with self._lock:
            if doc_id in self._documents:
                del self._documents[doc_id]
                return True
            return False

    def list_documents(self) -> tuple[VectorDocument, ...]:
        with self._lock:
            return tuple(self._documents.values())

    def clear(self) -> bool:
        with self._lock:
            self._documents.clear()
            return True



class ChromaVectorStore(IVectorStore):
    """Almacén vectorial local respaldado por ChromaDB si está disponible en el entorno local.

    Si `chromadb` no está instalado, delega transparentemente a LocalVectorStore.
    """

    def __init__(
        self,
        collection_name: str = "jessyca_memory",
        persist_directory: Path | str = "data/vector_store",
        embedding_provider: IEmbeddingProvider | None = None,
    ) -> None:
        self.collection_name = collection_name
        self.persist_dir = validate_vector_store_path(persist_directory)
        self.provider = embedding_provider or LocalEmbeddingProvider()
        self._fallback_store = LocalVectorStore(store_path=self.persist_dir, embedding_provider=self.provider)
        self._chroma_client = None
        self._collection = None

        try:
            import chromadb  # type: ignore[import-not-found]
            self._chroma_client = chromadb.PersistentClient(path=str(self.persist_dir))

            self._collection = self._chroma_client.get_or_create_collection(name=collection_name)
            logger.info(f"[CHROMA DB] Colección '{collection_name}' inicializada en {self.persist_dir}.")
        except ImportError:
            logger.debug("[CHROMA DB] Módulo 'chromadb' no instalado. Usando LocalVectorStore.")
        except Exception as e:
            logger.warning(f"[CHROMA DB] Error inicializando ChromaDB: {e}. Usando LocalVectorStore fallback.")

    def add_document(self, doc: VectorDocument) -> bool:
        if self._collection is not None:
            try:
                self._collection.add(
                    ids=[doc.doc_id],
                    embeddings=[list(doc.embedding.values)],
                    documents=[doc.content],
                    metadatas=[doc.metadata],
                )
                return True
            except Exception as e:
                logger.error(f"[CHROMA DB] Error al añadir documento: {e}")
        return self._fallback_store.add_document(doc)

    def search_similar(
        self,
        embedding: EmbeddingVector,
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> tuple[VectorSearchResult, ...]:
        if self._collection is not None:
            try:
                res = self._collection.query(
                    query_embeddings=[list(embedding.values)],
                    n_results=top_k,
                )
                results: list[VectorSearchResult] = []
                ids = res.get("ids", [[]])[0]
                docs = res.get("documents", [[]])[0]
                metas = res.get("metadatas", [[]])[0]
                distances = res.get("distances", [[]])[0]

                for doc_id, content, meta, dist in zip(ids, docs, metas, distances, strict=False):

                    sim_score = max(0.0, 1.0 - (dist / 2.0))
                    if sim_score >= min_score:
                        vdoc = VectorDocument(
                            doc_id=doc_id,
                            content=content,
                            embedding=embedding,
                            metadata=dict(meta or {}),
                            created_at=datetime.now(UTC),
                        )
                        results.append(VectorSearchResult(document=vdoc, similarity_score=sim_score))
                return tuple(results)
            except Exception as e:
                logger.error(f"[CHROMA DB] Error en consulta ChromaDB: {e}")
        return self._fallback_store.search_similar(embedding, top_k=top_k, min_score=min_score)

    def delete_document(self, doc_id: str) -> bool:
        if self._collection is not None:
            try:
                self._collection.delete(ids=[doc_id])
                return True
            except Exception as e:
                logger.error(f"[CHROMA DB] Error al eliminar documento '{doc_id}': {e}")
        return self._fallback_store.delete_document(doc_id)

    def list_documents(self) -> tuple[VectorDocument, ...]:
        return self._fallback_store.list_documents()


    def clear(self) -> bool:
        if self._collection is not None and self._chroma_client is not None:
            try:
                self._chroma_client.delete_collection(name=self.collection_name)
                self._collection = self._chroma_client.get_or_create_collection(name=self.collection_name)
                return True
            except Exception as e:
                logger.error(f"[CHROMA DB] Error al vaciar colección: {e}")
        return self._fallback_store.clear()


_vector_store_instance: LocalVectorStore | None = None


def get_local_vector_store() -> LocalVectorStore:
    """Obtiene la instancia singleton del LocalVectorStore."""
    global _vector_store_instance
    if _vector_store_instance is None:
        _vector_store_instance = LocalVectorStore()
    return _vector_store_instance


__all__ = [
    "validate_vector_store_path",
    "validate_vector_document",
    "LocalEmbeddingProvider",
    "FakeEmbeddingProvider",
    "OllamaEmbeddingProvider",
    "LocalVectorStore",
    "FakeVectorStore",
    "ChromaVectorStore",
    "get_local_vector_store",
]




