"""Pruebas dedicadas completas para Browser Control, URLAllowlistPolicy, DOMQueryEngine, PageStateWaiter y AllowedJSSnippet (Subetapa 11.2)."""

from __future__ import annotations

import pytest

from core.browser_boundary import BrowserControlBoundary
from core.browser_models import (
    AllowedJSSnippet,
    ArbitraryJSExecutionError,
    DOMElementNotFoundError,
    MediaState,
    PageStateTimeoutError,
    PageStateWaiter,
    URLAccessDeniedError,
    URLAllowlistPolicy,
)
from core.browser_session_manager import BrowserSessionManager, FakeBrowserAdapter
from core.cancellation import CancellationToken
from core.emergency_stop import EmergencyStopTriggeredError, get_emergency_stop_manager


def test_url_allowlist_allowed_domain() -> None:
    policy = URLAllowlistPolicy()
    assert policy.is_url_allowed("https://youtube.com/watch?v=123") is True
    assert policy.is_url_allowed("https://google.com") is True
    assert policy.is_url_allowed("https://github.com/leeon003") is True


def test_url_allowlist_blocked_domain() -> None:
    policy = URLAllowlistPolicy()
    assert policy.is_url_allowed("https://unauthorized-domain-xyz.com") is False

    with pytest.raises(URLAccessDeniedError):
        policy.validate_url("https://malicious-phishing-site.org")


def test_dom_selector_query_and_click() -> None:
    adapter = FakeBrowserAdapter()
    mgr = BrowserSessionManager(adapter=adapter)

    # 1. Consulta estructurada de elemento DOM sin coordenadas
    elem = mgr.query_dom_element("#play-button")
    assert elem["text"] == "Play"
    assert elem["visible"] is True

    # 2. Clic estructurado sobre elemento DOM
    clicked = mgr.click_dom_element("#play-button")
    assert clicked is True

    # 3. Selector inexistente lanza DOMElementNotFoundError
    with pytest.raises(DOMElementNotFoundError):
        mgr.query_dom_element("#non-existent-selector")


def test_page_state_timeout() -> None:
    adapter = FakeBrowserAdapter()
    mgr = BrowserSessionManager(adapter=adapter)

    def never_true() -> bool:
        return False

    with pytest.raises(PageStateTimeoutError):
        mgr.waiter.wait_until_condition(never_true, timeout_seconds=0.1)


def test_page_state_waiter_conditions() -> None:
    adapter = FakeBrowserAdapter()
    mgr = BrowserSessionManager(adapter=adapter)

    # Espera exitosa por elemento 'visible'
    ready = mgr.waiter.wait_for_element_state(mgr.dom_query_engine, "#play-button", expected_state="visible", timeout_seconds=1.0)
    assert ready is True


def test_browser_session_reuse() -> None:
    adapter = FakeBrowserAdapter()
    mgr = BrowserSessionManager(adapter=adapter)

    tab1 = mgr.open_url("https://youtube.com")
    tab2 = mgr.open_url("https://google.com")

    assert mgr.current_browser_session is not None
    # Misma sesión de navegador reutilizada
    assert tab1.tab_id == tab2.tab_id


def test_duplicate_browser_prevention() -> None:
    adapter = FakeBrowserAdapter()
    mgr = BrowserSessionManager(adapter=adapter)

    tab1 = mgr.open_url("https://youtube.com")
    tab2 = mgr.open_url("https://youtube.com")

    # BROWSER_SINGLE_INSTANCE_ENFORCED reutiliza la sesión existente sin duplicar el ejecutable de Edge/Chrome
    assert tab1.tab_id == tab2.tab_id


def test_cancellation_during_wait() -> None:
    token = CancellationToken()
    token.cancel("User cancellation test")

    em = get_emergency_stop_manager()
    em.trigger_stop("Emergency stop cancellation test", source="test")
    try:
        waiter = PageStateWaiter(emergency_stop=em)
        with pytest.raises(EmergencyStopTriggeredError):
            waiter.wait_until_condition(lambda: False, timeout_seconds=5.0)
    finally:
        em.reset("cleanup")


def test_js_allowlist_predefined_snippet() -> None:
    adapter = FakeBrowserAdapter()
    mgr = BrowserSessionManager(adapter=adapter)

    res = mgr.execute_js_snippet(AllowedJSSnippet.PLAY_MEDIA)
    assert res == "SUCCESS"
    assert len(adapter.js_execution_history) == 1
    assert adapter.js_execution_history[0]["snippet"] == "PLAY_MEDIA"


def test_arbitrary_js_rejection() -> None:
    adapter = FakeBrowserAdapter()
    mgr = BrowserSessionManager(adapter=adapter)

    # Intento de pasar código JS libre arbitrario como string -> DEBE DENEGAR
    with pytest.raises(ArbitraryJSExecutionError):
        mgr.execute_js_snippet("alert('xss')")  # type: ignore
