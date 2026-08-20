"""Pruebas de enforzamiento de límites de adaptadores e IPs de red (Subetapa 09.1)."""

from datetime import UTC, datetime

from core.network_models import (
    NetworkInterface,
    NetworkInterfaceMetadata,
    NetworkInterfacesResult,
    NetworkIPAddress,
)
from core.network_security import (
    NetworkSecurityManager,
)


def test_network_security_truncates_excessive_interfaces_and_ips() -> None:
    sec = NetworkSecurityManager()
    sec.max_interfaces = 2
    sec.max_ips = 1

    ips = (NetworkIPAddress(ip_address="10.0.0.1"), NetworkIPAddress(ip_address="10.0.0.2"))
    ifaces = tuple(
        NetworkInterface(
            interface_id=f"id-{i}",
            name=f"Eth{i}",
            description="Desc",
            adapter_type="Ethernet",
            operational_status="Up",
            administrative_status="Enabled",
            mac_address="001122334455",
            ipv4_addresses=ips,
            ipv6_addresses=(),
            gateways=(),
            dns_servers=(),
        )
        for i in range(10)
    )

    res = NetworkInterfacesResult(
        success=True,
        interfaces=ifaces,
        metadata=NetworkInterfaceMetadata(10, 20, 0, 0, 0, 1.0, "Mock", datetime.now(UTC)),
        message="OK",
    )

    sanitized = sec.validate_result(res)

    assert len(sanitized.interfaces) == 2
    assert len(sanitized.interfaces[0].ipv4_addresses) == 1
