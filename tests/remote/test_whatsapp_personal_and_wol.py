"""Suite exhaustiva de pruebas para WhatsApp Personal y Wake-on-LAN (Fase 6).

Cubre:
1. Mensajes permitidos (Ping, Estado, Investigación, Tareas, Apertura de apps).
2. Remitentes desconocidos y dispositivos no autorizados.
3. Rechazo estricto de comandos prohibidos (cmd, powershell, del, install, etc.).
4. Cancelación inmediata y activación de Parada de Emergencia.
5. Reconexión, empaquetado y verificación de integridad en el túnel seguro.
6. Manejo honesto de PC desconectada (Offline).
7. Ataques de repetición (Replay attacks con nonces duplicados).
8. Expiración de mensajes por timestamp fuera de ventana.
9. Construcción y despacho de Magic Packet Wake-on-LAN (102 bytes).
10. Prohibición de falsos éxitos al despertar (no afirmar éxito sin confirmación real).
11. Desafíos de confirmación adicional (OTP 6 dígitos) para operaciones sensibles.
12. Apertura con lista blanca estricta y detección de pantalla bloqueada.
"""

from __future__ import annotations

import time
import pytest

from core.emergency_stop import EmergencyStopManager
from core.remote.auth import OwnerAuthManager
from core.remote.models import (
    ALLOWED_REMOTE_APPS,
    FORBIDDEN_COMMAND_PATTERNS,
    RemoteCommandType,
    RemoteExecutionResult,
    RemoteExecutionStatus,
    RemoteMessage,
)
from core.remote.task_router import RemoteTaskRouter
from core.remote.tunnel_protocol import PacketType, TunnelProtocol
from core.remote.wol_controller import WakeOnLanController
from interfaces.whatsapp_personal.gateway import WhatsAppPersonalGateway


@pytest.fixture
def auth_manager():
    return OwnerAuthManager(
        owner_phone_jid="51999888777@s.whatsapp.net",
        authorized_device_ids={"owner-phone-s23", "owner-tablet"},
        shared_secret="secret-key-test-fase6",
        max_age_seconds=60.0,
        rate_limit_per_minute=10,
    )


@pytest.fixture
def task_router():
    return RemoteTaskRouter()


@pytest.fixture
def wol_controller():
    return WakeOnLanController(
        target_mac="04-7C-16-6E-B4-70",
        broadcast_ip="127.0.0.1",
        wol_port=9999,
        agent_host="127.0.0.1",
        agent_port=8088,
    )


@pytest.fixture
def gateway(auth_manager, task_router, wol_controller):
    gw = WhatsAppPersonalGateway(
        auth_manager=auth_manager,
        task_router=task_router,
        wol_controller=wol_controller,
        is_pc_online_override=True,
    )
    return gw


# ── TEST 1: AUTENTICACIÓN - REMITENTE Y DISPOSITIVO AUTORIZADO ───────────────────

def test_auth_authorized_sender_and_device(auth_manager):
    ok, msg = auth_manager.verify_sender("51999888777@s.whatsapp.net", "owner-phone-s23")
    assert ok is True
    assert "verificados" in msg.lower()


def test_auth_unknown_sender_rejected(auth_manager):
    ok, msg = auth_manager.verify_sender("51900000000@s.whatsapp.net", "owner-phone-s23")
    assert ok is False
    assert "no autorizado" in msg.lower()


def test_auth_unauthorized_device_rejected(auth_manager):
    ok, msg = auth_manager.verify_sender("51999888777@s.whatsapp.net", "untrusted-device-xyz")
    assert ok is False
    assert "no reconocido" in msg.lower()


# ── TEST 2: PROTECCIÓN CONTRA ATAQUES DE REPETICIÓN (ANTI-REPLAY) ────────────────

def test_anti_replay_blocks_duplicate_nonce(auth_manager):
    now = time.time()
    nonce = "unique_nonce_abc123"

    ok1, _ = auth_manager.verify_anti_replay(nonce, now)
    assert ok1 is True

    # Segundo intento con el mismo nonce debe ser rechazado
    ok2, err = auth_manager.verify_anti_replay(nonce, now)
    assert ok2 is False
    assert "repetición" in err.lower() or "ya utilizado" in err.lower()


def test_anti_replay_blocks_expired_timestamp(auth_manager):
    old_time = time.time() - 120.0  # 2 minutos en el pasado
    ok, err = auth_manager.verify_anti_replay("new_nonce_456", old_time)
    assert ok is False
    assert "expirado" in err.lower()


# ── TEST 3: INTEGRIDAD CRIPTOGRÁFICA (FIRMA HMAC-SHA256) ─────────────────────────

def test_hmac_signature_verification(auth_manager):
    msg = RemoteMessage(
        message_id="msg_001",
        sender_phone_jid="51999888777@s.whatsapp.net",
        device_id="owner-phone-s23",
        command_type=RemoteCommandType.PING_STATUS,
        nonce="nonce_sig_123",
        timestamp=time.time(),
    )
    sig = auth_manager.sign_message(msg)
    msg.signature = sig

    ok, _ = auth_manager.verify_signature(msg)
    assert ok is True

    # Alterar el mensaje invalida la firma
    msg.payload = {"tampered": True}
    ok_tampered, err = auth_manager.verify_signature(msg)
    assert ok_tampered is False
    assert "inválida" in err.lower()


# ── TEST 4: RATE LIMITING POR VENTANA DESLIZANTE ─────────────────────────────────

def test_rate_limiting_enforcement(auth_manager):
    jid = "51999888777@s.whatsapp.net"
    # El límite es 10 por minuto
    for _ in range(10):
        ok, _ = auth_manager.check_rate_limit(jid)
        assert ok is True

    # La solicitud 11 debe ser rechazada
    ok11, err = auth_manager.check_rate_limit(jid)
    assert ok11 is False
    assert "límite de solicitudes" in err.lower()


# ── TEST 5: RECHAZO DE COMANDOS PROHIBIDOS (CONSOLA REMOTA / SCRIPTS) ────────────

def test_forbidden_command_patterns_rejected(task_router):
    prohibited_samples = [
        "ejecuta cmd.exe /c whoami",
        "powershell Get-Process",
        "del C:\\secret.txt",
        "format D:",
        "net user hacker Pass123 /add",
        "install software malware.exe",
    ]

    for sample in prohibited_samples:
        msg = RemoteMessage(
            message_id="test_forbid",
            sender_phone_jid="51999888777@s.whatsapp.net",
            device_id="owner-phone-s23",
            command_type="arbitrary_exec",
            payload={"query": sample},
            nonce="nonce_forbid",
        )
        res = task_router.route_command(msg)
        assert res.success is False
        assert res.status == RemoteExecutionStatus.REJECTED_FORBIDDEN
        assert "denegada por seguridad" in res.message.lower()


# ── TEST 6: COMANDOS REMOTOS PERMITIDOS EN WHATSAPP ──────────────────────────────

def test_gateway_ping_command(gateway):
    resp = gateway.process_inbound_whatsapp(
        sender_phone_jid="51999888777@s.whatsapp.net",
        device_id="owner-phone-s23",
        text="¿Estás ahí, JESSYCA?",
    )
    assert "tu pc está encendida" in resp.lower()
    assert "jessyca se encuentra lista" in resp.lower()


def test_gateway_status_command(gateway):
    resp = gateway.process_inbound_whatsapp(
        sender_phone_jid="51999888777@s.whatsapp.net",
        device_id="owner-phone-s23",
        text="Dame el estado de jessyca y recursos",
    )
    assert "estado del sistema jessyca" in resp.lower()
    assert "llama3.2" in resp.lower()
    assert "memoria ram" in resp.lower()


def test_gateway_research_command(gateway):
    resp = gateway.process_inbound_whatsapp(
        sender_phone_jid="51999888777@s.whatsapp.net",
        device_id="owner-phone-s23",
        text="Investiga sobre computación cuántica",
    )
    assert "resultado de la investigación" in resp.lower()
    assert "computación cuántica" in resp.lower()


# ── TEST 7: CANCELACIÓN Y PARADA DE EMERGENCIA REMOTA ────────────────────────────

def test_gateway_cancel_triggers_emergency_stop(gateway):
    resp = gateway.process_inbound_whatsapp(
        sender_phone_jid="51999888777@s.whatsapp.net",
        device_id="owner-phone-s23",
        text="JESSYCA, detente de inmediato",
    )
    assert "detenido" in resp.lower()
    assert "parada de emergencia" in resp.lower()
    assert EmergencyStopManager.get_instance().is_stopped() is True

    # Restablecer para no afectar tests posteriores
    EmergencyStopManager.get_instance().reset(caller_id="test_suite")


# ── TEST 8: APERTURA DE APLICACIONES CON LISTA BLANCA ESTRICTA ───────────────────

def test_open_app_whitelisted(task_router, monkeypatch):
    class FakeProc:
        pid = 12345

    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr(task_router, "is_windows_session_locked", lambda: False)

    msg = RemoteMessage(
        message_id="app_ok",
        sender_phone_jid="51999888777@s.whatsapp.net",
        device_id="owner-phone-s23",
        command_type=RemoteCommandType.OPEN_APP,
        payload={"app_name": "notepad"},
        nonce="nonce_app",
    )
    res = task_router.route_command(msg)
    assert res.success is True
    assert res.status == RemoteExecutionStatus.COMPLETED
    assert "12345" in res.message


def test_open_app_non_whitelisted_rejected(task_router):
    msg = RemoteMessage(
        message_id="app_bad",
        sender_phone_jid="51999888777@s.whatsapp.net",
        device_id="owner-phone-s23",
        command_type=RemoteCommandType.OPEN_APP,
        payload={"app_name": "spotify"},
        nonce="nonce_bad_app",
    )
    res = task_router.route_command(msg)
    assert res.success is False
    assert res.status == RemoteExecutionStatus.REJECTED_FORBIDDEN
    assert "no se encuentra en la lista blanca" in res.message.lower()


def test_open_app_blocked_when_session_is_locked(task_router, monkeypatch):
    monkeypatch.setattr(task_router, "is_windows_session_locked", lambda: True)

    msg = RemoteMessage(
        message_id="app_locked",
        sender_phone_jid="51999888777@s.whatsapp.net",
        device_id="owner-phone-s23",
        command_type=RemoteCommandType.OPEN_APP,
        payload={"app_name": "notepad"},
        nonce="nonce_locked",
    )
    res = task_router.route_command(msg)
    assert res.success is False
    assert res.status == RemoteExecutionStatus.LOCKED_STATION
    assert "pantalla de tu pc está bloqueada" in res.message.lower()


# ── TEST 9: MANEJO HONESTO DE PC DESCONECTADA (OFFLINE) ──────────────────────────

def test_gateway_handles_offline_pc_honestly(gateway):
    gateway.set_pc_online_override(False)

    resp = gateway.process_inbound_whatsapp(
        sender_phone_jid="51999888777@s.whatsapp.net",
        device_id="owner-phone-s23",
        text="Abre el bloc de notas",
    )
    assert "apagada o suspendida (offline)" in resp.lower()
    assert "despierta la pc" in resp.lower()


# ── TEST 10: WAKE-ON-LAN - MAGIC PACKET Y CERO FALSOS ÉXITOS ─────────────────────

def test_wol_magic_packet_structure():
    mac = "04-7C-16-6E-B4-70"
    packet = WakeOnLanController.create_magic_packet(mac)
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    # 16 repeticiones de la MAC (6 bytes cada una)
    mac_bytes = bytes.fromhex("047C166EB470")
    for i in range(16):
        start = 6 + (i * 6)
        assert packet[start : start + 6] == mac_bytes


def test_wol_send_packet_acknowledgment(gateway):
    gateway.set_pc_online_override(False)

    resp = gateway.process_inbound_whatsapp(
        sender_phone_jid="51999888777@s.whatsapp.net",
        device_id="owner-phone-s23",
        text="Despierta la PC por favor",
    )
    # Debe ser honesto: confirma envío de señal pero NO afirma que ya despertó
    assert "transmitido el paquete de reactivación" in resp.lower()
    assert "esperando confirmación real" in resp.lower()


def test_wol_does_not_claim_awake_on_timeout(wol_controller):
    # Simulamos que la PC nunca responde al probe
    ok, msg = wol_controller.trigger_wake_and_poll(
        max_wait_seconds=0.1,
        poll_interval=0.05,
        probe_fn=lambda: False,
    )
    assert ok is False
    assert "aún no responde" in msg.lower()


def test_wol_confirms_awake_only_when_probe_succeeds(wol_controller):
    # Simulamos que en el segundo intento la PC responde
    calls = [False, True]

    def mock_probe():
        return calls.pop(0) if calls else True

    ok, msg = wol_controller.trigger_wake_and_poll(
        max_wait_seconds=1.0,
        poll_interval=0.05,
        probe_fn=mock_probe,
    )
    assert ok is True
    assert "se ha reactivado" in msg.lower()


# ── TEST 11: CONFIRMACIÓN ADICIONAL PARA OPERACIONES SENSIBLES (OTP) ─────────────

def test_sensitive_operation_confirmation_flow(auth_manager, gateway):
    # Generar un desafío para una acción sensible
    cmd_id = "cmd_sensitive_01"
    code, prompt = auth_manager.create_confirmation_challenge(cmd_id, "FORMAT_DISK_SIMULATION")
    assert len(code) == 6
    assert code.isdigit()

    # Intentar confirmar con código erróneo
    wrong_resp = gateway.process_inbound_whatsapp(
        sender_phone_jid="51999888777@s.whatsapp.net",
        device_id="owner-phone-s23",
        text="CONFIRMAR 000000",
    )
    assert "incorrecto" in wrong_resp.lower()

    # Confirmar con el código correcto
    valid_resp = gateway.process_inbound_whatsapp(
        sender_phone_jid="51999888777@s.whatsapp.net",
        device_id="owner-phone-s23",
        text=f"CONFIRMAR {code}",
    )
    assert "operación confirmada" in valid_resp.lower()


# ── TEST 12: TÚNEL CIFRADO VPS <-> WINDOWS (RECONEXIÓN Y EMPAQUETADO) ────────────

def test_tunnel_protocol_packing_and_unpacking():
    tunnel = TunnelProtocol(shared_secret="test_secret_tunnel")
    payload = {"status": "heartbeat_ok", "vram_free": 10240}

    packed = tunnel.pack(PacketType.HEARTBEAT_PING, payload)
    assert isinstance(packed, str)

    ok, pkt, reason = tunnel.unpack(packed)
    assert ok is True
    assert pkt is not None
    assert pkt.packet_type == PacketType.HEARTBEAT_PING
    assert pkt.payload["vram_free"] == 10240
    assert pkt.signature != ""


def test_tunnel_rejects_tampered_packet():
    tunnel = TunnelProtocol(shared_secret="test_secret_tunnel")
    packed = tunnel.pack(PacketType.COMMAND_RESULT, {"data": 123})

    # Modificar el contenido JSON
    tampered = packed.replace("123", "999")
    ok, pkt, reason = tunnel.unpack(tampered)
    assert ok is False
    assert "inválida" in reason.lower()
