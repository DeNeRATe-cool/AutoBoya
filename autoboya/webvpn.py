from __future__ import annotations

from urllib.parse import urlparse

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

try:
    from cryptography.hazmat.decrepit.ciphers.modes import CFB
except Exception:  # pragma: no cover - compatibility with older cryptography
    from cryptography.hazmat.primitives.ciphers.modes import CFB

WEBVPN_GATEWAY = "https://d.buaa.edu.cn"
WEBVPN_KEY = b"wrdvpnisthebest!"


def to_webvpn_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname == "d.buaa.edu.cn":
        return url
    if parsed.port is None:
        protocol = parsed.scheme
    elif parsed.scheme == "http" and parsed.port == 80:
        protocol = "http"
    elif parsed.scheme == "https" and parsed.port == 443:
        protocol = "https"
    else:
        protocol = f"{parsed.scheme}-{parsed.port}"
    query = f"?{parsed.query}" if parsed.query else ""
    fragment = f"#{parsed.fragment}" if parsed.fragment else ""
    host = encrypt_webvpn_host(parsed.hostname or "")
    return f"{WEBVPN_GATEWAY}/{protocol}/{host}{parsed.path}{query}{fragment}"


def encrypt_webvpn_host(host: str) -> str:
    plain = host.encode()
    padded = plain + b"0" * ((16 - len(plain) % 16) % 16)
    cipher = Cipher(algorithms.AES(WEBVPN_KEY), CFB(WEBVPN_KEY)).encryptor()
    encrypted = cipher.update(padded) + cipher.finalize()
    return WEBVPN_KEY.hex() + encrypted.hex()[: len(plain) * 2]
