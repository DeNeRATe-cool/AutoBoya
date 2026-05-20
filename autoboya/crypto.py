from __future__ import annotations

import base64
import hashlib
import json
import secrets
import string
import time
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import hashes, padding as sym_padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

BYKC_RSA_PEM = b"""-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDlHMQ3B5GsWnCe7Nlo1YiG/YmH
dlOiKOST5aRm4iaqYSvhvWmwcigoyWTM+8bv2+sf6nQBRDWTY4KmNV7DBk1eDnTI
Qo6ENA31k5/tYCLEXgjPbEjCK9spiyB62fCT6cqOhbamJB0lcDJRO6Vo1m3dy+fD
0jbxfDVBBNtyltIsDQIDAQAB
-----END PUBLIC KEY-----
"""

KEY_ALPHABET = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkmnprstwxyz2345678"


@dataclass
class EncryptedRequest:
    body: bytes
    headers: dict[str, str]


class BykcCrypto:
    def __init__(self, key: bytes | None = None) -> None:
        self.key = key or random_aes_key()
        self.public_key = serialization.load_pem_public_key(BYKC_RSA_PEM)

    @classmethod
    def fixed_key_for_test(cls, key: str) -> "BykcCrypto":
        return cls(key.encode())

    def encrypt_plaintext(self, plaintext: bytes) -> bytes:
        padder = sym_padding.PKCS7(128).padder()
        padded = padder.update(plaintext) + padder.finalize()
        encryptor = Cipher(algorithms.AES(self.key), modes.ECB()).encryptor()
        encrypted = encryptor.update(padded) + encryptor.finalize()
        return json.dumps(base64.b64encode(encrypted).decode()).encode()

    def decrypt_response(self, body: bytes | str) -> Any:
        text = body.decode() if isinstance(body, bytes) else body
        encoded = json.loads(text)
        encrypted = base64.b64decode(encoded)
        decryptor = Cipher(algorithms.AES(self.key), modes.ECB()).decryptor()
        padded = decryptor.update(encrypted) + decryptor.finalize()
        unpadder = sym_padding.PKCS7(128).unpadder()
        plaintext = unpadder.update(padded) + unpadder.finalize()
        return json.loads(plaintext.decode())

    def encrypt_request(self, payload: dict[str, Any] | str) -> EncryptedRequest:
        if isinstance(payload, str):
            plaintext = payload.encode()
        else:
            plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        body = self.encrypt_plaintext(plaintext)
        return EncryptedRequest(
            body=body,
            headers={
                "Ak": self._rsa_b64(self.key),
                "Sk": self._rsa_b64(hashlib.sha1(plaintext).hexdigest().encode()),
                "Ts": str(int(time.time() * 1000)),
            },
        )

    def _rsa_b64(self, data: bytes) -> str:
        encrypted = self.public_key.encrypt(data, asym_padding.PKCS1v15())
        return base64.b64encode(encrypted).decode()


def random_aes_key() -> bytes:
    return "".join(secrets.choice(KEY_ALPHABET) for _ in range(16)).encode()
