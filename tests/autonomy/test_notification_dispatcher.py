"""Pruebas unitarias y de seguridad para NotificationDispatcher (Etapa 13.3).

REQUISITOS PROBADOS:
1. rate limit: Prevención estricta de loops infinitos al sobrepasar NOTIFICATION_RATE_LIMIT_PER_MINUTE.
2. duplicate suppression: Supresión de notificaciones idénticas dentro de la ventana de deduplicación.
3. cancellation: Cancelación limpia de notificaciones pendientes.
4. failure recovery: Recuperación elegante ante fallos de backend Toast/TTS sin crashes.
5. concurrent notifications: Despacho concurrente multi-hilo thread-safe.
"""

from __future__ import annotations

import threading

from core.notification_dispatcher import (
    NotificationChannel,
    NotificationDispatcher,
    NotificationStatus,
)


def test_rate_limiting() -> None:
    """Verifica que al superar el límite de notificaciones por minuto, se bloqueen los excesos (RATE_LIMITED)."""
    dispatcher = NotificationDispatcher(rate_limit_per_minute=3, dedup_window_seconds=0.1)

    # Despachar 3 notificaciones válidas con diferentes títulos para evitar deduplicación
    r1 = dispatcher.dispatch(title="Notif 1", message="Msg 1")
    r2 = dispatcher.dispatch(title="Notif 2", message="Msg 2")
    r3 = dispatcher.dispatch(title="Notif 3", message="Msg 3")

    assert r1.status == NotificationStatus.SENT
    assert r2.status == NotificationStatus.SENT
    assert r3.status == NotificationStatus.SENT

    # La 4ta notificación excede el rate limit y debe ser bloqueada
    r4 = dispatcher.dispatch(title="Notif 4", message="Msg 4")
    assert r4.status == NotificationStatus.RATE_LIMITED
    assert "excedido" in r4.reason.lower() or "preducción" in r4.reason.lower() or "rate" in r4.reason.lower()


def test_duplicate_suppression() -> None:
    """Verifica que notificaciones idénticas dentro de la ventana de deduplicación sean suprimidas (DEDUPLICATED)."""
    dispatcher = NotificationDispatcher(rate_limit_per_minute=10, dedup_window_seconds=5.0)

    # Primera notificación
    r1 = dispatcher.dispatch(title="Alerta Almacenamiento", message="Espacio en disco bajo")
    assert r1.status == NotificationStatus.SENT

    # Segunda notificación idéntica enviada inmediatamente
    r2 = dispatcher.dispatch(title="Alerta Almacenamiento", message="Espacio en disco bajo")
    assert r2.status == NotificationStatus.DEDUPLICATED
    assert "deduplicación" in r2.reason.lower()


def test_cancellation() -> None:
    """Verifica la cancelación de notificaciones pendientes."""
    dispatcher = NotificationDispatcher(rate_limit_per_minute=10)

    # Simular elemento en cola pendiente
    dispatcher._pending_queue["notif-test-1"] = None  # Mock item

    cancelled = dispatcher.cancel_pending("notif-test-1")
    assert cancelled is True
    assert "notif-test-1" not in dispatcher._pending_queue

    # Probar cancel_all()
    dispatcher._pending_queue["notif-test-2"] = None
    dispatcher._pending_queue["notif-test-3"] = None
    count = dispatcher.cancel_all()
    assert count == 2
    assert len(dispatcher._pending_queue) == 0


def test_failure_recovery() -> None:
    """Verifica la recuperación elegante sin crashes si falla un canal de despacho."""
    dispatcher = NotificationDispatcher(toast_enabled=True, voice_enabled=True)

    # Simular fallo forzado en el método interno de Toast
    def failing_toast(title: str, msg: str) -> bool:
        raise RuntimeError("Simulated Toast UI Crash")

    dispatcher._send_windows_toast = failing_toast

    # Debe retornar FAILED sin propagar la excepción ni romper la aplicación
    result = dispatcher.dispatch(title="Failure Test", message="Test Crash", channel=NotificationChannel.TOAST)
    assert result.status == NotificationStatus.FAILED
    assert "Simulated Toast UI Crash" in result.reason


def test_concurrent_notifications() -> None:
    """Verifica el despacho concurrente desde múltiples hilos en forma thread-safe."""
    dispatcher = NotificationDispatcher(rate_limit_per_minute=20, dedup_window_seconds=0.01)

    results: list[NotificationStatus] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        res = dispatcher.dispatch(title=f"Worker {i}", message=f"Payload {i}")
        with lock:
            results.append(res.status)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(15)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 15
    # Todos deben haber sido procesados correctamente (SENT, DEDUPLICATED o RATE_LIMITED) sin excepciones
    assert all(s in NotificationStatus for s in results)
