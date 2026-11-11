"""Authentication for inbound SMS/USSD gateway callbacks.

Africa's Talking does not document a signature on USSD or incoming-SMS
callbacks (unverified as of this commit), so FundBridge requires a shared secret
in the callback URL (``?token=...``) or the ``X-FundBridge-Callback-Token``
header, compared in constant time, plus an optional source-IP allowlist.
If no secret is configured the endpoints fail closed.
"""

from __future__ import annotations

import hmac
import ipaddress


def token_matches(expected: str | None, supplied: str | None) -> bool:
    if not expected or not supplied:
        return False
    return hmac.compare_digest(expected.encode(), supplied.encode())


def ip_allowed(remote_addr: str | None, allowlist: str | None) -> bool:
    if not allowlist or not allowlist.strip():
        return True
    if not remote_addr:
        return False
    try:
        address = ipaddress.ip_address(remote_addr)
    except ValueError:
        return False
    for entry in allowlist.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            if address in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            continue
    return False
