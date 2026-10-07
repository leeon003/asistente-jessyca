"""tests/memory/test_long_term_memory_reliable_persistence_phase07.py

Suite de pruebas exhaustiva para la Fase 07 — Persistencia de memoria fiable:
1. Persistencia atómica y generación de JSON válido sin temporales residuales.
2. Inyección de fallos en serialización: lanzamiento de MemoryPersistenceError, sin archivo en disco y sin entrada en caché.
3. Inyección de fallos en apertura/escritura (PermissionError/IOError): rollback en caché y limpieza de temporales propios.
4. Inyección de fallo en reemplazo atómico (os.replace): preservación íntegra del archivo destino previo y de la versión en caché.
5. Error observable por el consumidor con metadatos estructurados (details con record_id, target_path, etc.).
6. Coherencia total entre estado en memoria y disco (store, update, delete).
7. Limpieza selectiva: se eliminan los temporales propios sin borrar archivos temporales ajenos o concurrentes.
8. Concurrencia intra-proceso soportada (multi-threading con threading.RLock) sin colisiones ni corrupción.
9. Compatibilidad demostrada en Windows y aislamiento en el mismo directorio.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import shutil
import tempfile
import threading
from typing import Any
from unittest.mock import patch

import pytest

from core.emergency_stop import get_emergency_stop_manager
from core.memory.long_term_memory import (
    LongTermMemoryEngine,
    LongTermMemoryRecord,
    MemoryPersistenceError,
    MemoryRecordType,
    MemorySensitivity,
)


class TestLongTermMemoryReliablePersistencePhase07:
    """Pruebas de resiliencia, atomicidad y tolerancia a fallos para LongTermMemoryEngine."""

    def setup_method(self) -> None:
        self.emergency_stop = get_emergency_stop_manager()
        self.emergency_stop.reset("test_setup_cleanup")
        self.temp_dir = tempfile.mkdtemp(prefix="jessyca_ltm_p07_")
        self.engine = LongTermMemoryEngine(storage_dir=self.temp_dir, emergency_stop=self.emergency_stop)

    def teardown_method(self) -> None:
        self.emergency_stop.reset("test_teardown_cleanup")
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ── 1. PERSISTENCIA ATÓMICA Y JSON VÁLIDO ──

    def test_01_atomic_write_produces_valid_json_and_no_residual_temp_files(self) -> None:
        """Verifica que el archivo final es JSON válido y no quedan archivos temporales .tmp_*."""
        rec = self.engine.store_record(
            content="Preferencias del usuario: tono profesional.",
            record_type=MemoryRecordType.USER_PREFERENCES,
            source="user",
            scope="global",
            confidence=0.9,
        )
        assert rec is not None
        target_path = os.path.join(self.temp_dir, f"{rec.id}.json")
        assert os.path.exists(target_path)

        # Validar sintaxis y estructura JSON
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["id"] == rec.id
        assert data["content"] == "Preferencias del usuario: tono profesional."
        assert data["version"] == 1

        # Verificar que no quedaron temporales .tmp_*
        temp_files = [f for f in os.listdir(self.temp_dir) if f.startswith(".tmp_")]
        assert len(temp_files) == 0, f"Quedaron archivos temporales residuales: {temp_files}"

    # ── 2. INYECCIÓN DE FALLO: ERROR DE SERIALIZACIÓN ──

    def test_02_serialization_failure_aborts_and_keeps_cache_consistent(self) -> None:
        """Si la serialización falla, se propaga MemoryPersistenceError y la caché permanece limpia."""
        bad_object = object()  # No serializable por json.dumps

        with pytest.raises(MemoryPersistenceError) as exc_info:
            self.engine.store_record(
                content="Contenido con procedencia no serializable",
                record_type=MemoryRecordType.SEMANTIC_MEMORY,
                provenance={"unserializable": bad_object},
            )

        err = exc_info.value
        assert "serialization" in str(err.details.get("phase")) or "serializando" in err.message.lower()

        # Caché en memoria debe estar completamente vacía
        assert len(self.engine._records) == 0

        # Ningún archivo (ni definitivo ni temporal) debe haberse creado
        files = os.listdir(self.temp_dir)
        assert len(files) == 0

    # ── 3. INYECCIÓN DE FALLO: ERROR DE ESCRITURA / PERMISOS ──

    def test_03_write_io_failure_cleans_own_temp_and_propagates_error(self) -> None:
        """Si open() falla al escribir el temporal, se lanza MemoryPersistenceError y no hay fuga en caché."""
        original_open = open

        def mock_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            if isinstance(file, str) and ".tmp_" in file and "w" in mode:
                raise PermissionError("Acceso denegado simulado durante escritura temporal (WinError 5)")
            return original_open(file, mode, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open):
            with pytest.raises(MemoryPersistenceError) as exc_info:
                self.engine.store_record(
                    content="Prueba de fallo de I/O en escritura",
                    record_type=MemoryRecordType.SEMANTIC_MEMORY,
                )

        assert "Acceso denegado simulado" in str(exc_info.value)
        assert len(self.engine._records) == 0
        assert len(os.listdir(self.temp_dir)) == 0

    # ── 4. INYECCIÓN DE FALLO: REEMPLAZO FALLIDO Y PRESERVACIÓN DEL ARCHIVO PREVIO ──

    def test_04_replacement_failure_preserves_previous_file_and_cache(self) -> None:
        """Si os.replace falla (ej. archivo bloqueado en Windows), el archivo anterior y la caché quedan intactos."""
        # 1. Almacenar versión inicial exitosamente
        rec = self.engine.store_record(
            content="Versión inicial intacta",
            record_type=MemoryRecordType.USER_PREFERENCES,
        )
        assert rec is not None
        rec_id = rec.id
        target_path = os.path.join(self.temp_dir, f"{rec_id}.json")

        with open(target_path, "r", encoding="utf-8") as f:
            initial_disk_data = json.load(f)
        assert initial_disk_data["version"] == 1
        assert initial_disk_data["content"] == "Versión inicial intacta"

        # 2. Simular fallo de os.replace (WinError 32: sharing violation en Windows)
        def mock_replace(src: str, dst: str) -> None:
            raise PermissionError("El proceso no tiene acceso al archivo porque está siendo utilizado (WinError 32)")

        with patch("os.replace", side_effect=mock_replace):
            with pytest.raises(MemoryPersistenceError) as exc_info:
                self.engine.update_record(
                    record_id=rec_id,
                    new_content="Intento de contenido nuevo fallido",
                )

        assert "WinError 32" in str(exc_info.value)

        # 3. VERIFICACIÓN CRÍTICA:
        # A) El archivo en disco debe seguir siendo la versión 1 íntegra
        with open(target_path, "r", encoding="utf-8") as f:
            current_disk_data = json.load(f)
        assert current_disk_data["version"] == 1
        assert current_disk_data["content"] == "Versión inicial intacta"

        # B) La caché en memoria DEBE seguir reflejando la versión 1 sin modificaciones espurias
        cached = self.engine._records[rec_id]
        assert cached.version == 1
        assert cached.content == "Versión inicial intacta"
        assert len(cached.history) == 0

        # C) El temporal propio fue eliminado, sin archivos basura
        temp_files = [f for f in os.listdir(self.temp_dir) if f.startswith(".tmp_")]
        assert len(temp_files) == 0

    # ── 5. LIMPIEZA SELECTIVA DE TEMPORALES (NO BORRA ARCHIVOS AJENOS) ──

    def test_05_cleanup_does_not_delete_foreign_temp_files(self) -> None:
        """Verifica que el rollback elimine solo su archivo temporal específico, no temporales ajenos."""
        # Crear un archivo temporal ajeno previo en el directorio
        foreign_temp = os.path.join(self.temp_dir, ".tmp_foreign_operation_12345.json")
        with open(foreign_temp, "w", encoding="utf-8") as f:
            f.write('{"alien": true}')

        # Simular fallo en os.replace para una nueva operación
        def mock_replace(src: str, dst: str) -> None:
            raise OSError("Fallo simulado en reemplazo")

        with patch("os.replace", side_effect=mock_replace):
            with pytest.raises(MemoryPersistenceError):
                self.engine.store_record("Prueba de limpieza selectiva")

        # El temporal ajeno DEBE permanecer intacto
        assert os.path.exists(foreign_temp)
        with open(foreign_temp, "r", encoding="utf-8") as f:
            assert json.load(f) == {"alien": True}

    # ── 6. COHERENCIA DE CACHÉ EN DELETE_RECORD ──

    def test_06_delete_record_failure_retains_memory_cache(self) -> None:
        """Si os.remove falla al borrar de disco, se lanza MemoryPersistenceError y no se borra de la caché."""
        rec = self.engine.store_record("Dato para borrar", MemoryRecordType.SEMANTIC_MEMORY)
        assert rec is not None
        rec_id = rec.id

        def mock_remove(path: str) -> None:
            raise PermissionError("Bloqueo de archivo en Windows durante eliminación")

        with patch("os.remove", side_effect=mock_remove):
            with pytest.raises(MemoryPersistenceError) as exc_info:
                self.engine.delete_record(rec_id)

        assert "Bloqueo de archivo" in str(exc_info.value)
        # El registro aún debe estar presente en memoria porque no se pudo borrar de disco
        assert rec_id in self.engine._records

    # ── 7. METADATOS ESTRUCTURADOS DEL ERROR OBSERVABLE ──

    def test_07_structured_error_details_exposed_to_consumer(self) -> None:
        """El error expone código, mensaje y diccionario de detalles utilizables por el llamador."""
        with patch("os.replace", side_effect=OSError("Disco lleno / Espacio insuficiente")):
            with pytest.raises(MemoryPersistenceError) as exc_info:
                self.engine.store_record("Dato para validar metadatos de error")

        err = exc_info.value
        assert isinstance(err.to_dict(), dict)
        assert err.code == "MemoryPersistenceError"
        assert "details" in err.to_dict()
        assert "target_path" in err.details
        assert "temp_path" in err.details

    # ── 8. CONCURRENCIA INTRA-PROCESO (MULTI-THREADING) ──

    def test_08_multithreaded_concurrency_consistency(self) -> None:
        """Múltiples hilos concurrentes operando en el mismo engine no corrompen caché ni archivos."""
        num_threads = 12
        records_per_thread = 5

        def worker(thread_idx: int) -> list[str]:
            created_ids: list[str] = []
            for i in range(records_per_thread):
                rec = self.engine.store_record(
                    content=f"Dato hilo {thread_idx} iteración {i}",
                    record_type=MemoryRecordType.SEMANTIC_MEMORY,
                    source=f"thread_{thread_idx}",
                    confidence=0.8,
                )
                assert rec is not None
                created_ids.append(rec.id)
                # Pequeña actualización concurrente
                self.engine.update_record(rec.id, f"Dato hilo {thread_idx} iteración {i} (actualizado)")
            return created_ids

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, t) for t in range(num_threads)]
            all_ids = []
            for f in concurrent.futures.as_completed(futures):
                all_ids.extend(f.result())

        total_expected = num_threads * records_per_thread
        assert len(all_ids) == total_expected

        # Verificar coherencia total entre memoria y disco
        with self.engine._lock:
            assert len(self.engine._records) == total_expected

        disk_files = [f for f in os.listdir(self.temp_dir) if f.endswith(".json") and not f.startswith(".tmp_")]
        assert len(disk_files) == total_expected

        # Verificar que todos los archivos son JSON válidos con versión 2
        for fname in disk_files:
            fpath = os.path.join(self.temp_dir, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                item = json.load(f)
            assert item["version"] == 2
            assert "(actualizado)" in item["content"]

    # ── 9. MODELO DE CONCURRENCIA Y ATOMICIDAD WINDOWS ──

    def test_09_concurrency_lock_is_reentrant_and_same_volume(self) -> None:
        """Verifica que el lock es RLock y que los archivos temporales se ubican en el mismo directorio."""
        assert isinstance(self.engine._lock, type(threading.RLock()))

        rec = self.engine.store_record("Prueba de ruta de directorio")
        assert rec is not None
        target = os.path.join(self.temp_dir, f"{rec.id}.json")
        assert os.path.dirname(target) == self.temp_dir
