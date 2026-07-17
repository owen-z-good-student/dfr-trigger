import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class ValueCipher:
    def __init__(self, encoded_key: str):
        try:
            key = base64.urlsafe_b64decode(encoded_key.encode())
        except Exception as exc:
            raise ValueError("DFR_CONFIG_KEY must be URL-safe base64") from exc
        if len(key) != 32:
            raise ValueError("DFR_CONFIG_KEY must decode to 32 bytes")
        self._cipher = AESGCM(key)

    def encrypt(self, value: str) -> str:
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(
            nonce, value.encode(), b"dfr-trigger-config-v1"
        )
        return base64.urlsafe_b64encode(nonce + ciphertext).decode()

    def decrypt(self, value: str) -> str:
        raw = base64.urlsafe_b64decode(value.encode())
        try:
            return self._cipher.decrypt(
                raw[:12], raw[12:], b"dfr-trigger-config-v1"
            ).decode()
        except (InvalidTag, ValueError) as exc:
            raise ValueError("configuration decryption failed") from exc
